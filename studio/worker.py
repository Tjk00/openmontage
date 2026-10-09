"""Background production worker.

Runs the real pipeline stages for queued jobs, outside any request handler.
One worker thread per configured slot (default 1). Cancellation is cooperative
between stages. Every stage logs progress; failures are recorded with the
stage name so the dashboard can show exactly what broke.
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Optional

from studio.config import StudioConfig
from studio.db import Database, new_id
from studio.jobs import JobManager
from studio.pipeline import assets as assets_mod
from studio.pipeline import captions as captions_mod
from studio.pipeline import music as music_mod
from studio.pipeline import qc as qc_mod
from studio.pipeline import render as render_mod
from studio.pipeline import research as research_mod
from studio.pipeline import scriptgen as scriptgen_mod
from studio.pipeline import storage as storage_mod
from studio.pipeline import tts as tts_mod
from studio.security import safe_error


class CancelledError(Exception):
    pass


class PipelineWorker:
    def __init__(self, cfg: StudioConfig, db: Database, jobs: JobManager):
        self.cfg = cfg
        self.db = db
        self.jobs = jobs
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.active_job_id: Optional[str] = None

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> None:
        for i in range(self.cfg.max_concurrent_jobs):
            t = threading.Thread(target=self._loop, name=f"studio-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = self.db.claim_next_queued()
                if job is None:
                    self._stop.wait(self.cfg.worker_poll_seconds)
                    continue
                self.active_job_id = job["id"]
                self._run_job(job)
            except Exception:
                traceback.print_exc()
            finally:
                self.active_job_id = None

    # ---- pipeline --------------------------------------------------------
    def _check_cancel(self, job_id: str) -> None:
        if self.jobs.is_cancel_requested(job_id):
            raise CancelledError("cancel requested by user")

    def _run_job(self, job: dict) -> None:
        job_id = job["id"]
        project_id = job["project_id"]
        request = json.loads(job["request_json"])
        try:
            result = self._execute_pipeline(job_id, project_id, request)
            if result.get("cancelled"):
                self.db.update_job(job_id, status="CANCELLED", finished_at=_now(),
                                   stage=result.get("stage", job["stage"]))
                self.jobs.log(job_id, "Job cancelled.", level="INFO")
                self.db.upsert_project(project_id, title=request["topic"][:80],
                                       topic=request["topic"], status="CANCELLED")
                return
            self.jobs.complete(job_id, project_id=project_id,
                               output_path=result["output_path"], qc=result["qc"])
            self.db.upsert_project(
                project_id, title=request["topic"][:80], topic=request["topic"],
                status="COMPLETED", output_path=result["output_path"],
                attribution=result.get("attribution", []), script=result.get("script"),
                meta={"request": request, "research": result.get("research_summary"),
                      "warnings": result.get("warnings", [])},
            )
            storage_mod.write_project_files(
                self.cfg, project_id, request=request, script=result.get("script"),
                research=result.get("research"), assets=result.get("assets"),
                qc=result.get("qc"), logs=self._logs_text(job_id),
                output_path=result["output_path"], attribution=result.get("attribution", []),
            )
        except CancelledError:
            self.db.update_job(job_id, status="CANCELLED", finished_at=_now())
            self.jobs.log(job_id, "Job cancelled at a safe point.", level="INFO")
            self.db.upsert_project(project_id, title=request["topic"][:80],
                                   topic=request["topic"], status="CANCELLED")
        except Exception as exc:
            stage = self.db.get_job(job_id).get("stage") or "UNKNOWN"
            self.jobs.fail(job_id, error=safe_error(exc), stage=stage)
            self.jobs.log(job_id, f"Traceback: {traceback.format_exc()[-1500:]}", level="ERROR")
            self.db.upsert_project(project_id, title=request["topic"][:80],
                                   topic=request["topic"], status="FAILED")
            storage_mod.write_project_files(
                self.cfg, project_id, request=request, script=None, research=None,
                assets=None, qc=None, logs=self._logs_text(job_id),
                output_path=None, attribution=[],
            )

    def _logs_text(self, job_id: str) -> str:
        rows = self.db.get_logs(job_id)
        return "\n".join(f"{r['ts']} [{r['level']}] {r.get('stage') or '-'}: {r['message']}" for r in rows)

    def _execute_pipeline(self, job_id: str, project_id: str, request: dict) -> dict:
        warnings: list[str] = []
        cfg, jobs = self.cfg, self.jobs

        # ---------- 1. RESEARCHING ----------
        self._check_cancel(job_id)
        jobs.set_stage(job_id, "RESEARCHING", f"Researching: {request['topic']}")
        research_result = research_mod.run_research(
            request.get("selected_angle") or request["topic"],
            depth=request.get("research_depth", "standard"),
            feeds=_feeds_from_references(request.get("reference_urls") or []),
            timeout=cfg.research_timeout_seconds,
            max_sources=cfg.research_max_sources,
            cache=self.db, cache_hours=cfg.research_cache_hours,
        )
        research_dict = research_result.to_dict()
        jobs.log(job_id, f"Research status: {research_result.status} "
                         f"({len(research_result.sources)} sources, verified={research_result.verified})",
                 stage="RESEARCHING")
        if research_result.status != "ok":
            warnings.append("Research was unavailable or partial — treat topic claims as unverified.")
        if research_result.cached:
            jobs.log(job_id, "Research cache hit.", stage="RESEARCHING")

        # ---------- 2. SCRIPTING ----------
        self._check_cancel(job_id)
        jobs.set_stage(job_id, "SCRIPTING", "Generating script + storyboard")
        doc = scriptgen_mod.generate_script_llm(cfg, request, research_dict) \
            or scriptgen_mod.generate_script(request, research_dict)
        script = doc.to_dict()
        warnings.extend(script.get("warnings", []))
        jobs.log(job_id, f"Script generated by {script['generated_by']}: "
                         f"{len(script['scenes'])} scenes, "
                         f"{len(script['voiceover_text'].split())} narration words.",
                 stage="SCRIPTING")

        # ---------- 3. COLLECTING_ASSETS ----------
        self._check_cancel(job_id)
        jobs.set_stage(job_id, "COLLECTING_ASSETS", "Discovering / generating footage")
        workdir = storage_mod.project_dir(cfg, project_id)
        workdir.mkdir(parents=True, exist_ok=True)
        manifest = assets_mod.collect_assets(cfg, request, script["scenes"], workdir)
        assets_dict = manifest.to_dict()
        warnings.extend(manifest.warnings)
        jobs.log(job_id, f"Asset strategy: {manifest.strategy}; "
                         f"{len(manifest.clips)} clips collected.", stage="COLLECTING_ASSETS")
        if not manifest.clips:
            raise RuntimeError("No footage could be collected or generated — cannot render.")

        # ---------- 4. GENERATING_VOICE ----------
        self._check_cancel(job_id)
        jobs.set_stage(job_id, "GENERATING_VOICE", "Synthesizing narration")
        uploaded = None
        if request.get("narration_upload_id"):
            row = self.db.query_one("SELECT path FROM uploads WHERE id = ?", (request["narration_upload_id"],))
            if row:
                uploaded = Path(row["path"])
        tts_result = tts_mod.synthesize(
            cfg, script["voiceover_text"], workdir / "narration.wav",
            voice=request.get("voice", "en-us"),
            uploaded_audio=uploaded,
        )
        narration_required = True  # default expectation: the pipeline produces narration
        if tts_result.ok:
            jobs.log(job_id, f"Narration ready via {tts_result.engine}: "
                             f"{tts_result.duration_seconds:.2f}s.", stage="GENERATING_VOICE")
        else:
            # Explicit failure handling: no pretending.
            if uploaded:
                raise RuntimeError(f"Narration failed: {tts_result.error}")
            warnings.append(f"Narration FAILED ({tts_result.error}). "
                            f"{tts_result.diagnostics} Continuing WITHOUT narration — "
                            "the video will not contain spoken audio.")
            jobs.log(job_id, f"Narration failed: {tts_result.error}", level="ERROR",
                     stage="GENERATING_VOICE")
            narration_required = False

        # ---------- 5. CREATING_CAPTIONS ----------
        self._check_cancel(job_id)
        jobs.set_stage(job_id, "CREATING_CAPTIONS", "Building timed captions")
        caption_cards = []
        captions_dict = {}
        want_captions = request.get("caption_preference", "burned") in ("burned", "srt-only")
        if want_captions and script.get("voiceover_text"):
            audio_dur = tts_result.duration_seconds if tts_result.ok else float(request["duration_seconds"])
            cap = captions_mod.build_captions(script["voiceover_text"], audio_dur, workdir)
            captions_dict = cap.to_dict()
            warnings.extend(cap.warnings)
            jobs.log(job_id, f"Captions: {len(cap.cues)} cues "
                             f"(timing: {cap.timing_source}).", stage="CREATING_CAPTIONS")
            if request.get("caption_preference") == "burned" and cap.cues:
                w, h = render_mod.target_size(request.get("aspect", "9:16"),
                                              scale=cfg.render_scale)
                caption_cards = captions_mod.render_caption_cards(
                    cap.cues, workdir, width=w, height=h,
                    position="bottom",
                )
        elif want_captions:
            warnings.append("No narration text — captions skipped.")

        # ---------- 6. RENDERING ----------
        self._check_cancel(job_id)
        jobs.set_stage(job_id, "RENDERING", "Rendering final MP4")
        music_path = None
        if request.get("music_preference") == "ambient":
            try:
                music_path = music_mod.generate_ambient_bed(
                    workdir / "music_bed.wav", float(request["duration_seconds"]) + 1.0)
                jobs.log(job_id, "Ambient music bed synthesized locally.", stage="RENDERING")
            except Exception as exc:
                warnings.append(f"Music bed generation failed ({safe_error(exc)}) — rendering without music.")
        elif request.get("music_preference") == "upload":
            warnings.append("Music upload preference: no uploaded track found — rendering without music.")

        clip_specs = [
            {"path": c.path, "duration": float(s["duration"])}
            for c, s in zip(manifest.clips, script["scenes"])
        ]
        output_path = workdir / "renders" / "final.mp4"
        render_result = render_mod.render_video(
            cfg, clips=clip_specs, aspect=request.get("aspect", "9:16"),
            output_path=output_path,
            narration=Path(tts_result.audio_path) if tts_result.ok else None,
            music=music_path,
            caption_cards=caption_cards if request.get("caption_preference") == "burned" else None,
            scale=cfg.render_scale,
        )
        if not render_result.ok:
            raise RuntimeError(f"Rendering failed: {render_result.error}")
        warnings.extend(render_result.warnings)
        jobs.log(job_id, f"Render complete ({render_result.width}x{render_result.height}) "
                         f"using: {', '.join(render_result.used_tools)}.", stage="RENDERING")

        # ---------- 7. QUALITY_CHECK ----------
        self._check_cancel(job_id)
        jobs.set_stage(job_id, "QUALITY_CHECK", "Validating output")
        report = qc_mod.run_qc(
            cfg, output_path=Path(render_result.output_path),
            requested_duration=float(request["duration_seconds"]),
            aspect=request.get("aspect", "9:16"),
            narration_required=narration_required and tts_result.ok,
            captions_requested=request.get("caption_preference", "burned") == "burned",
            captions_produced=bool(caption_cards),
            log_text=self._logs_text(job_id),
        )
        qc_dict = report.to_dict()
        if not report.passed:
            failed = [c["name"] for c in qc_dict["checks"] if not c["passed"]]
            raise RuntimeError(f"Quality check failed: {', '.join(failed)}")
        jobs.log(job_id, "Quality check PASSED — all output validations succeeded.",
                 stage="QUALITY_CHECK")

        return {
            "output_path": render_result.output_path,
            "qc": qc_dict,
            "script": script,
            "research": research_dict,
            "research_summary": {"status": research_dict["status"], "verified": research_dict["verified"]},
            "assets": assets_dict,
            "attribution": manifest.attribution,
            "warnings": warnings,
        }


def _now() -> str:
    from studio.db import utcnow

    return utcnow()


def _feeds_from_references(urls: list[str]) -> Optional[list[str]]:
    """Use user reference URLs as extra RSS sources only when they look like feeds."""
    feeds = [u for u in urls if any(tok in u.lower() for tok in ("rss", "feed", ".xml", "atom"))]
    return feeds or None
