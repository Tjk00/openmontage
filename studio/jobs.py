"""Production job manager.

Job lifecycle (per request):
  QUEUED -> RUNNING (stages: RESEARCHING -> SCRIPTING -> COLLECTING_ASSETS ->
  GENERATING_VOICE -> CREATING_CAPTIONS -> RENDERING -> QUALITY_CHECK) ->
  COMPLETED | FAILED | CANCELLED

Durable state in SQLite. Duplicate-submission protection via request hashing.
Retry re-queues a failed job (bounded by OM_MAX_RETRIES). Cancellation is
cooperative: checked between stages and inside long loops.
"""
from __future__ import annotations

import hashlib
import json
import threading
from typing import Any, Optional

from studio.db import Database, new_id, utcnow

ACTIVE_STATUSES = ("QUEUED", "RUNNING")
TERMINAL_STATUSES = ("COMPLETED", "FAILED", "CANCELLED")

STAGES = [
    "RESEARCHING",
    "SCRIPTING",
    "COLLECTING_ASSETS",
    "GENERATING_VOICE",
    "CREATING_CAPTIONS",
    "RENDERING",
    "QUALITY_CHECK",
]

# Progress percentages at the start of each stage.
STAGE_PROGRESS = {
    "QUEUED": 0,
    "RESEARCHING": 5,
    "SCRIPTING": 20,
    "COLLECTING_ASSETS": 35,
    "GENERATING_VOICE": 55,
    "CREATING_CAPTIONS": 65,
    "RENDERING": 75,
    "QUALITY_CHECK": 92,
    "COMPLETED": 100,
}


def request_hash(request: dict) -> str:
    canonical = json.dumps({k: request[k] for k in sorted(request)}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


class JobManager:
    """Thread-safe job operations on top of the SQLite store."""

    def __init__(self, db: Database, *, dedupe_window_seconds: int = 300, max_retries: int = 2):
        self.db = db
        self.dedupe_window_seconds = dedupe_window_seconds
        self.max_retries = max_retries
        self._lock = threading.RLock()
        self._cancel_flags: set[str] = set()

    # ---- creation / dedupe ----------------------------------------------
    def create_job(self, request: dict) -> dict:
        """Create a production job. Identical in-flight requests return the
        existing job instead of starting a duplicate."""
        h = request_hash(request)
        with self._lock:
            existing = self.db.find_active_by_hash(h, ACTIVE_STATUSES)
            if existing:
                return {"job": existing, "deduplicated": True}
            job_id = new_id("job")
            project_id = new_id("proj")
            self.db.create_job(job_id=job_id, project_id=project_id, request_hash=h,
                               request=request, stage="QUEUED")
            self.db.upsert_project(project_id, title=request["topic"][:80], topic=request["topic"],
                                   status="QUEUED", meta={"request": request})
            self.db.add_log(job_id, "INFO", "Job created and queued.", stage="QUEUED")
            job = self.db.get_job(job_id)
            return {"job": job, "deduplicated": False}

    # ---- state transitions ----------------------------------------------
    def set_stage(self, job_id: str, stage: str, log: str = "") -> None:
        self.db.update_job(job_id, stage=stage, status="RUNNING",
                           progress=STAGE_PROGRESS.get(stage, 0))
        if log:
            self.db.add_log(job_id, "INFO", log, stage=stage)

    def log(self, job_id: str, message: str, level: str = "INFO", stage: Optional[str] = None) -> None:
        self.db.add_log(job_id, level, message, stage=stage)

    def complete(self, job_id: str, *, project_id: str, output_path: str, qc: dict) -> None:
        job = self.db.get_job(job_id) or {}
        topic = json.loads(job.get("request_json") or "{}").get("topic", "video")
        self.db.update_job(job_id, status="COMPLETED", stage="QUALITY_CHECK", progress=100,
                           finished_at=utcnow(), output_path=output_path,
                           qc_json=json.dumps(qc))
        self.db.add_log(job_id, "INFO", f"Job completed. Output: {output_path}", stage="QUALITY_CHECK")
        self.db.upsert_project(project_id, title=topic[:80], topic=topic,
                               status="COMPLETED", output_path=output_path)

    def fail(self, job_id: str, *, error: str, stage: str) -> None:
        self.db.update_job(job_id, status="FAILED", error=error, error_stage=stage,
                           finished_at=utcnow())
        self.db.add_log(job_id, "ERROR", f"Job failed at {stage}: {error}", stage=stage)
        job = self.db.get_job(job_id)
        if job:
            self.db.upsert_project(job["project_id"],
                                   title=json.loads(job["request_json"])["topic"][:80],
                                   topic=json.loads(job["request_json"])["topic"], status="FAILED")

    def request_cancel(self, job_id: str) -> dict:
        job = self.db.get_job(job_id)
        if not job:
            return {"cancelled": False, "error": "job not found"}
        if job["status"] in TERMINAL_STATUSES:
            return {"cancelled": False, "error": f"job already {job['status']}"}
        with self._lock:
            self._cancel_flags.add(job_id)
        self.db.update_job(job_id, cancel_requested=1)
        if job["status"] == "QUEUED":
            self.db.update_job(job_id, status="CANCELLED", finished_at=utcnow())
            self.db.add_log(job_id, "INFO", "Job cancelled while queued.", stage=job["stage"])
        else:
            self.db.add_log(job_id, "INFO", "Cancellation requested — stopping at next safe point.",
                            stage=job["stage"])
        return {"cancelled": True, "job_id": job_id}

    def is_cancel_requested(self, job_id: str) -> bool:
        if job_id in self._cancel_flags:
            return True
        job = self.db.get_job(job_id)
        return bool(job and job.get("cancel_requested"))

    def retry(self, job_id: str) -> dict:
        job = self.db.get_job(job_id)
        if not job:
            return {"ok": False, "error": "job not found"}
        if job["status"] != "FAILED":
            return {"ok": False, "error": f"only FAILED jobs can be retried (status={job['status']})"}
        if job["retry_count"] >= self.max_retries:
            return {"ok": False, "error": f"retry limit reached ({self.max_retries})"}
        with self._lock:
            self._cancel_flags.discard(job_id)
        self.db.update_job(job_id, status="QUEUED", stage="QUEUED", progress=0,
                           error=None, error_stage=None, cancel_requested=0,
                           retry_count=job["retry_count"] + 1, finished_at=None)
        self.db.add_log(job_id, "INFO",
                        f"Retry {job['retry_count'] + 1}/{self.max_retries} queued.", stage="QUEUED")
        return {"ok": True, "job_id": job_id, "retry_count": job["retry_count"] + 1}

    # ---- queries ---------------------------------------------------------
    def get_job(self, job_id: str) -> Optional[dict]:
        job = self.db.get_job(job_id)
        if not job:
            return None
        job["warnings"] = json.loads(job.get("warnings_json") or "[]")
        job["request"] = json.loads(job["request_json"])
        job["qc"] = json.loads(job["qc_json"]) if job.get("qc_json") else None
        return job

    def list_jobs(self, **kw: Any) -> list[dict]:
        return self.db.list_jobs(**kw)

    def get_logs(self, job_id: str, after_id: int = 0) -> list[dict]:
        return self.db.get_logs(job_id, after_id=after_id)
