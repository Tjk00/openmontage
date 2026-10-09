"""SQLite persistence for OpenMontage AI Studio.

Durable job/project state for the production manager. Uses only the standard
library (sqlite3). All timestamps are UTC ISO-8601 strings.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    request_json TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    error TEXT,
    error_stage TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    output_path TEXT,
    qc_json TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    angle TEXT,
    warnings_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project_id);
CREATE INDEX IF NOT EXISTS idx_jobs_hash ON jobs(request_hash);

CREATE TABLE IF NOT EXISTS job_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    level TEXT NOT NULL,
    stage TEXT,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_logs_job ON job_logs(id);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    topic TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    meta_json TEXT NOT NULL DEFAULT '{}',
    output_path TEXT,
    attribution_json TEXT NOT NULL DEFAULT '[]',
    script_json TEXT,
    deleted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS research_runs (
    id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT NOT NULL,
    cache_key TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_research_cache ON research_runs(cache_key, created_at);

CREATE TABLE IF NOT EXISTS provider_state (
    id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    config_json TEXT NOT NULL DEFAULT '{}',
    last_check_at TEXT,
    last_check_ok INTEGER,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS uploads (
    id TEXT PRIMARY KEY,
    job_id TEXT,
    kind TEXT NOT NULL,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Database:
    """Thread-safe thin wrapper around sqlite3 with a lock per connection."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ---- generic helpers -------------------------------------------------
    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cur

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            return [dict(r) for r in cur.fetchall()]

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> Optional[dict]:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    # ---- jobs ------------------------------------------------------------
    def create_job(self, *, job_id: str, project_id: str, request_hash: str, request: dict, stage: str) -> None:
        now = utcnow()
        self.execute(
            """INSERT INTO jobs (id, project_id, request_hash, request_json, stage, status,
                                 progress, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (job_id, project_id, request_hash, json.dumps(request), stage, "QUEUED", 0, now, now),
        )

    def update_job(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields.setdefault("updated_at", utcnow())
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))

    def get_job(self, job_id: str) -> Optional[dict]:
        return self.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))

    def list_jobs(self, *, status: Optional[str] = None, project_id: Optional[str] = None,
                  limit: int = 100) -> list[dict]:
        sql = "SELECT * FROM jobs"
        conds, params = [], []
        if status:
            conds.append("status = ?")
            params.append(status)
        if project_id:
            conds.append("project_id = ?")
            params.append(project_id)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return self.query(sql, params)

    def find_active_by_hash(self, request_hash: str, statuses: tuple[str, ...]) -> Optional[dict]:
        ph = ",".join("?" for _ in statuses)
        rows = self.query(
            f"SELECT * FROM jobs WHERE request_hash = ? AND status IN ({ph}) ORDER BY created_at DESC",
            (request_hash, *statuses),
        )
        return rows[0] if rows else None

    def claim_next_queued(self) -> Optional[dict]:
        """Atomically claim one QUEUED job and mark it RUNNING (stage set by worker)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE status = 'QUEUED' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            self._conn.execute(
                "UPDATE jobs SET status = 'RUNNING', started_at = ?, updated_at = ? WHERE id = ? AND status = 'QUEUED'",
                (utcnow(), utcnow(), row["id"]),
            )
            self._conn.commit()
            return dict(self._conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone())

    def add_log(self, job_id: str, level: str, message: str, stage: Optional[str] = None) -> None:
        self.execute(
            "INSERT INTO job_logs (job_id, ts, level, stage, message) VALUES (?,?,?,?,?)",
            (job_id, utcnow(), level, stage, message),
        )

    def get_logs(self, job_id: str, after_id: int = 0, limit: int = 500) -> list[dict]:
        return self.query(
            "SELECT * FROM job_logs WHERE job_id = ? AND id > ? ORDER BY id LIMIT ?",
            (job_id, after_id, limit),
        )

    # ---- projects --------------------------------------------------------
    def upsert_project(self, project_id: str, *, title: str, topic: str, status: str,
                       meta: Optional[dict] = None, output_path: Optional[str] = None,
                       attribution: Optional[list] = None, script: Optional[dict] = None) -> None:
        now = utcnow()
        existing = self.query_one("SELECT id FROM projects WHERE id = ?", (project_id,))
        if existing:
            sets, params = ["updated_at = ?", "status = ?", "title = ?"], [now, status, title]
            if meta is not None:
                sets.append("meta_json = ?")
                params.append(json.dumps(meta))
            if output_path is not None:
                sets.append("output_path = ?")
                params.append(output_path)
            if attribution is not None:
                sets.append("attribution_json = ?")
                params.append(json.dumps(attribution))
            if script is not None:
                sets.append("script_json = ?")
                params.append(json.dumps(script))
            params.append(project_id)
            self.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id = ?", params)
        else:
            self.execute(
                """INSERT INTO projects (id, title, topic, status, created_at, updated_at,
                       meta_json, output_path, attribution_json, script_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (project_id, title, topic, status, now, now,
                 json.dumps(meta or {}), output_path,
                 json.dumps(attribution or []), json.dumps(script) if script else None),
            )

    def get_project(self, project_id: str) -> Optional[dict]:
        row = self.query_one("SELECT * FROM projects WHERE id = ? AND deleted = 0", (project_id,))
        return row

    def list_projects(self, limit: int = 200) -> list[dict]:
        return self.query(
            "SELECT * FROM projects WHERE deleted = 0 ORDER BY created_at DESC LIMIT ?", (limit,)
        )

    def soft_delete_project(self, project_id: str) -> None:
        self.execute("UPDATE projects SET deleted = 1, updated_at = ? WHERE id = ?", (utcnow(), project_id))

    # ---- research --------------------------------------------------------
    def save_research(self, run_id: str, query: str, status: str, result: dict, cache_key: str) -> None:
        self.execute(
            "INSERT INTO research_runs (id, query, created_at, status, result_json, cache_key) VALUES (?,?,?,?,?,?)",
            (run_id, query, utcnow(), status, json.dumps(result), cache_key),
        )

    def cached_research(self, cache_key: str, max_age_hours: int) -> Optional[dict]:
        row = self.query_one(
            "SELECT * FROM research_runs WHERE cache_key = ? ORDER BY created_at DESC LIMIT 1", (cache_key,)
        )
        if not row:
            return None
        created = datetime.fromisoformat(row["created_at"])
        age_h = (datetime.now(timezone.utc) - created).total_seconds() / 3600.0
        if age_h > max_age_hours:
            return None
        return json.loads(row["result_json"])

    # ---- providers -------------------------------------------------------
    def get_provider_state(self, provider_id: str) -> Optional[dict]:
        return self.query_one("SELECT * FROM provider_state WHERE id = ?", (provider_id,))

    def set_provider_state(self, provider_id: str, *, enabled: Optional[bool] = None,
                           config: Optional[dict] = None, check_ok: Optional[bool] = None,
                           error: Optional[str] = None) -> None:
        existing = self.get_provider_state(provider_id)
        if not existing:
            self.execute(
                "INSERT INTO provider_state (id, enabled, config_json, last_check_at, last_check_ok, last_error) VALUES (?,?,?,?,?,?)",
                (provider_id, int(enabled if enabled is not None else 1),
                 json.dumps(config or {}), utcnow() if check_ok is not None else None,
                 None if check_ok is None else int(check_ok), error),
            )
            return
        sets, params = [], []
        if enabled is not None:
            sets.append("enabled = ?")
            params.append(int(enabled))
        if config is not None:
            sets.append("config_json = ?")
            params.append(json.dumps(config))
        if check_ok is not None:
            sets.extend(["last_check_at = ?", "last_check_ok = ?", "last_error = ?"])
            params.extend([utcnow(), int(check_ok), error])
        if sets:
            params.append(provider_id)
            self.execute(f"UPDATE provider_state SET {', '.join(sets)} WHERE id = ?", params)

    # ---- uploads ---------------------------------------------------------
    def add_upload(self, upload_id: str, kind: str, filename: str, path: str, size: int,
                   job_id: Optional[str] = None) -> None:
        self.execute(
            "INSERT INTO uploads (id, job_id, kind, filename, path, size, created_at) VALUES (?,?,?,?,?,?,?)",
            (upload_id, job_id, kind, filename, path, size, utcnow()),
        )

    def stats(self) -> dict:
        by_status = {r["status"]: r["n"] for r in self.query("SELECT status, COUNT(*) n FROM jobs GROUP BY status")}
        projects = self.query_one("SELECT COUNT(*) n FROM projects WHERE deleted = 0")["n"]
        return {"jobs_by_status": by_status, "projects": projects}
