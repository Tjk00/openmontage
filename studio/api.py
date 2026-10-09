"""OpenMontage AI Studio — FastAPI web application.

Mobile-first dashboard + lightweight JSON API + background worker.
Serves the static SPA, validates input, enforces auth/throttling, and exposes
the production job manager. Long rendering work always happens in the worker
thread — never inside a request handler.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pydantic import ValidationError

from studio.config import StudioConfig, load_config
from studio.db import Database, new_id
from studio.ffmpeg_env import ensure_tools, find_ffmpeg, find_ffprobe
from studio.jobs import JobManager
from studio.models import DeleteProjectRequest, ProviderToggle, ResearchRequest, VideoRequest
from studio.pipeline import providers as providers_mod
from studio.pipeline import research as research_mod
from studio.pipeline import storage as storage_mod
from studio.security import (RateLimiter, ensure_session_secret, generate_session_token,
                             mask_secret, safe_error, safe_join, verify_session_token)
from studio.worker import PipelineWorker

SESSION_COOKIE = "om_studio_session"
STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(cfg: Optional[StudioConfig] = None) -> FastAPI:
    cfg = cfg or load_config()
    cfg.ensure_dirs()
    tools_info = ensure_tools(cfg)

    db = Database(cfg.db_path)
    jobs = JobManager(db, dedupe_window_seconds=cfg.dedupe_window_seconds,
                      max_retries=cfg.max_retries)
    worker = PipelineWorker(cfg, db, jobs)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        worker.start()
        yield
        worker.stop()

    app = FastAPI(title="OpenMontage AI Studio", version="1.0.0", docs_url=None, redoc_url=None,
                  lifespan=lifespan)
    app.state.cfg = cfg
    app.state.db = db
    app.state.jobs = jobs
    app.state.worker = worker
    app.state.tools = tools_info
    app.state.session_secret = ensure_session_secret(cfg.session_secret)
    app.state.limiter = RateLimiter(cfg.rate_limit_per_minute)
    app.state.job_limiter = RateLimiter(cfg.job_create_rate_per_minute)
    app.state.started_at = time.time()

    auth_enabled = bool(cfg.admin_token)

    # ---------------- middleware ----------------
    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        ip = request.client.host if request.client else "unknown"
        if not app.state.limiter.allow(ip):
            return JSONResponse({"error": "rate limit exceeded — slow down"}, status_code=429)
        path = request.url.path
        needs_auth = auth_enabled and path.startswith("/api/") and path not in (
            "/api/health", "/api/auth/login", "/api/auth/status",
        )
        if needs_auth:
            token = request.cookies.get(SESSION_COOKIE) or request.headers.get("X-Studio-Token", "")
            if not verify_session_token(app.state.session_secret, token):
                return JSONResponse({"error": "authentication required"}, status_code=401)
            if request.method in ("POST", "PUT", "PATCH", "DELETE"):
                # CSRF: mutating requests must come with the custom header too.
                if not request.headers.get("X-Requested-With") and not request.headers.get("X-Studio-Token"):
                    return JSONResponse({"error": "missing CSRF header (X-Requested-With)"}, status_code=403)
        try:
            response = await call_next(request)
        except Exception as exc:  # never leak internals
            return JSONResponse({"error": safe_error(exc)}, status_code=500)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def client_ip(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def ok(data: Any, status: int = 200) -> JSONResponse:
        return JSONResponse(data, status_code=status)

    # ---------------- auth ----------------
    @app.get("/api/auth/status")
    def auth_status():
        return {"auth_enabled": auth_enabled,
                "open_local_mode": not auth_enabled,
                "warning": (None if auth_enabled else
                            "No OM_STUDIO_TOKEN configured: instance is OPEN. Only use on localhost or behind your own auth.")}

    @app.post("/api/auth/login")
    async def auth_login(request: Request):
        body = await request.json()
        token = str(body.get("token", ""))
        if not auth_enabled:
            return ok({"authenticated": True, "note": "auth is disabled (open local mode)"})
        if token != cfg.admin_token:
            time.sleep(0.5)  # slow down brute force
            return JSONResponse({"error": "invalid token"}, status_code=401)
        session = generate_session_token(app.state.session_secret, cfg.session_ttl_seconds)
        resp = ok({"authenticated": True})
        resp.set_cookie(SESSION_COOKIE, session, httponly=True, samesite="lax",
                        secure=False, max_age=cfg.session_ttl_seconds)
        return resp

    @app.post("/api/auth/logout")
    def auth_logout():
        resp = ok({"authenticated": False})
        resp.delete_cookie(SESSION_COOKIE)
        return resp

    # ---------------- jobs ----------------
    @app.post("/api/jobs")
    async def create_job(request: Request):
        if not app.state.job_limiter.allow(client_ip(request)):
            return JSONResponse({"error": "job creation rate limit exceeded"}, status_code=429)
        body = await request.json()
        try:
            vr = VideoRequest(**body)
        except ValidationError as exc:
            return JSONResponse({"error": "invalid request", "details": json.loads(exc.json())},
                                status_code=422)
        data = vr.model_dump()
        result = jobs.create_job(data)
        return ok({"job_id": result["job"]["id"], "project_id": result["job"]["project_id"],
                   "deduplicated": result["deduplicated"],
                   "status": result["job"]["status"], "stage": result["job"]["stage"]},
                  status=200 if result["deduplicated"] else 201)

    @app.get("/api/jobs")
    def list_jobs(status: Optional[str] = None, project_id: Optional[str] = None, limit: int = 100):
        rows = jobs.list_jobs(status=status or None, project_id=project_id or None,
                              limit=max(1, min(limit, 500)))
        out = []
        for r in rows:
            r["request"] = json.loads(r["request_json"])
            del r["request_json"]
            out.append(r)
        return {"jobs": out}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        job = jobs.get_job(job_id)
        if not job:
            return JSONResponse({"error": "job not found"}, status_code=404)
        job.pop("request_json", None)
        job.pop("qc_json", None)
        job.pop("warnings_json", None)
        return job

    @app.get("/api/jobs/{job_id}/logs")
    def job_logs(job_id: str, after_id: int = 0):
        return {"logs": jobs.get_logs(job_id, after_id=after_id)}

    @app.post("/api/jobs/{job_id}/retry")
    def retry_job(job_id: str):
        res = jobs.retry(job_id)
        return ok(res, status=200 if res.get("ok") else 400)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        res = jobs.request_cancel(job_id)
        return ok(res, status=200 if res.get("cancelled") else 400)

    # ---------------- research ----------------
    @app.post("/api/research")
    async def run_research_ep(request: Request):
        if not app.state.job_limiter.allow(client_ip(request), max_per_minute=10):
            return JSONResponse({"error": "research rate limit exceeded"}, status_code=429)
        body = await request.json()
        try:
            rr = ResearchRequest(**body)
        except ValidationError as exc:
            return JSONResponse({"error": "invalid request", "details": json.loads(exc.json())},
                                status_code=422)
        try:
            result = research_mod.run_research(
                rr.query, depth=rr.depth, timeout=cfg.research_timeout_seconds,
                max_sources=cfg.research_max_sources, cache=db,
                cache_hours=cfg.research_cache_hours,
            )
            run_id = new_id("res")
            db.save_research(run_id, rr.query, result.status, result.to_dict(),
                             f"api_{rr.query.lower().strip()}_{rr.depth}")
            return ok({"id": run_id, "result": result.to_dict()})
        except ValueError as exc:
            return JSONResponse({"error": safe_error(exc)}, status_code=422)
        except Exception as exc:
            return JSONResponse({"error": safe_error(exc)}, status_code=502)

    @app.get("/api/research/recent")
    def recent_research(limit: int = 20):
        rows = db.query("SELECT id, query, created_at, status FROM research_runs "
                        "ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 100)),))
        return {"runs": rows}

    # ---------------- projects / downloads ----------------
    @app.get("/api/projects")
    def list_projects():
        rows = db.list_projects()
        for r in rows:
            r["meta"] = json.loads(r.pop("meta_json") or "{}")
            r["attribution"] = json.loads(r.pop("attribution_json") or "[]")
            r.pop("script_json", None)
        return {"projects": rows}

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str):
        row = db.get_project(project_id)
        if not row:
            return JSONResponse({"error": "project not found"}, status_code=404)
        row["meta"] = json.loads(row.pop("meta_json") or "{}")
        row["attribution"] = json.loads(row.pop("attribution_json") or "[]")
        script_raw = row.pop("script_json")
        row["script"] = json.loads(script_raw) if script_raw else None
        pdir = storage_mod.project_dir(cfg, project_id)
        files = []
        if pdir.exists():
            for p in sorted(pdir.rglob("*")):
                if p.is_file():
                    files.append({"name": str(p.relative_to(pdir)), "size": p.stat().st_size})
        row["files"] = files
        return row

    @app.delete("/api/projects/{project_id}")
    async def delete_project(project_id: str, request: Request):
        body = await request.json() if (request.headers.get("content-length")) else {}
        req = DeleteProjectRequest(**(body or {}))
        res = storage_mod.delete_project(cfg, project_id, db, confirm=req.confirm)
        return ok(res, status=200 if res.get("deleted") else 400)

    @app.get("/api/projects/{project_id}/download/{file_name:path}")
    def download_file(project_id: str, file_name: str, request: Request):
        try:
            pdir = storage_mod.project_dir(cfg, project_id)
            # allow subdirectories in file_name via safe_join
            parts = file_name.split("/")
            target = safe_join(pdir, *parts)
        except ValueError:
            return JSONResponse({"error": "invalid file path"}, status_code=400)
        if not target.exists() or not target.is_file():
            return JSONResponse({"error": "file not found"}, status_code=404)
        if not target.is_relative_to(pdir):
            return JSONResponse({"error": "invalid file path"}, status_code=400)
        return FileResponse(target, filename=target.name,
                            media_type=_guess_media(target))

    # ---------------- uploads ----------------
    @app.post("/api/uploads/audio")
    async def upload_audio(request: Request):
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "filename"):
            return JSONResponse({"error": "missing file field"}, status_code=422)
        name = Path(str(upload.filename)).name
        if not name.lower().endswith((".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac")):
            return JSONResponse({"error": "audio files only (.wav .mp3 .m4a .aac .ogg .flac)"},
                                status_code=422)
        data = await upload.read()
        max_bytes = cfg.max_upload_mb * 1024 * 1024
        if len(data) > max_bytes:
            return JSONResponse({"error": f"file exceeds {cfg.max_upload_mb} MB limit"}, status_code=413)
        if not data:
            return JSONResponse({"error": "empty file"}, status_code=422)
        upload_id = new_id("up")
        dest = cfg.data_dir / "uploads" / upload_id / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        db.add_upload(upload_id, "narration", name, str(dest), len(data))
        return ok({"upload_id": upload_id, "filename": name, "size": len(data)}, status=201)

    # ---------------- providers ----------------
    @app.get("/api/providers")
    def list_providers():
        catalog = providers_mod.build_provider_catalog(cfg, db)
        return {"providers": [p.to_dict() for p in catalog]}

    @app.post("/api/providers/{provider_id}/check")
    def provider_check(provider_id: str):
        res = providers_mod.check_provider(provider_id, cfg, db)
        return ok(res, status=200 if res.get("ok") is not None else 404)

    @app.post("/api/providers/{provider_id}/toggle")
    async def provider_toggle(provider_id: str, request: Request):
        body = await request.json()
        try:
            pt = ProviderToggle(**body)
        except ValidationError as exc:
            return JSONResponse({"error": "invalid request", "details": json.loads(exc.json())},
                                status_code=422)
        known = {p.id for p in providers_mod.build_provider_catalog(cfg, db)}
        if provider_id not in known:
            return JSONResponse({"error": "unknown provider"}, status_code=404)
        if pt.enabled and provider_id in ("elevenlabs", "openai-sora", "fal-ai"):
            # Enabling a paid provider is allowed but explicitly acknowledged.
            db.set_provider_state(provider_id, enabled=True)
            return ok({"id": provider_id, "enabled": True,
                       "warning": "Paid provider enabled — usage may incur charges. "
                                  "The free workflow will still prefer free/local providers."})
        db.set_provider_state(provider_id, enabled=pt.enabled)
        return ok({"id": provider_id, "enabled": pt.enabled})

    # ---------------- storage / settings ----------------
    @app.get("/api/storage")
    def storage_info():
        usage = storage_mod.storage_usage(cfg)
        usage["retention_days"] = cfg.retention_days
        usage["max_upload_mb"] = cfg.max_upload_mb
        usage["persistence_warning"] = _persistence_warning(cfg)
        return usage

    @app.post("/api/storage/cleanup")
    def storage_cleanup():
        res = storage_mod.cleanup_expired(cfg, db)
        return ok(res)

    # ---------------- health / diagnostics ----------------
    @app.get("/api/health")
    def health():
        return {"status": "ok", "service": "openmontage-ai-studio",
                "worker_alive": any(t.is_alive() for t in worker._threads),
                "uptime_seconds": round(time.time() - app.state.started_at, 1)}

    @app.get("/api/stats")
    def stats():
        s = db.stats()
        s["worker_alive"] = any(t.is_alive() for t in worker._threads)
        s["active_job_id"] = worker.active_job_id
        s["auth_enabled"] = auth_enabled
        return s

    @app.get("/api/diagnostics")
    def diagnostics():
        ffmpeg = find_ffmpeg(cfg)
        ffprobe = find_ffprobe(cfg)
        disk = shutil.disk_usage(str(cfg.data_dir))
        checks = []

        def add(name, ok_, detail):
            checks.append({"name": name, "ok": bool(ok_), "detail": detail})

        add("ffmpeg", ffmpeg, tools_info.get("ffmpeg_version") or "missing")
        add("ffprobe", ffprobe, tools_info.get("ffprobe_version") or
            "missing (QC falls back to ffmpeg parse)")
        try:
            from studio.pipeline.tts import EspeakEngine

            add("tts_espeak", EspeakEngine.available(),
                "offline narration available" if EspeakEngine.available() else "not installed")
        except Exception as exc:
            add("tts_espeak", False, str(exc))
        add("worker", any(t.is_alive() for t in worker._threads),
            "background worker running" if any(t.is_alive() for t in worker._threads) else "worker not running")
        add("database", cfg.db_path.exists(), str(cfg.db_path))
        add("storage_writable", os.access(str(cfg.data_dir), os.W_OK), str(cfg.data_dir))
        add("disk_space", disk.free > 100 * 1024 * 1024,
            f"{disk.free // (1024*1024)} MB free")
        add("auth", auth_enabled,
            "admin token configured" if auth_enabled else
            "OPEN MODE — configure OM_STUDIO_TOKEN before exposing publicly")
        add("persistence", not _persistence_warning(cfg),
            _persistence_warning(cfg) or "data dir looks persistent")

        return {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "checks": checks,
            "data_dir": str(cfg.data_dir),
            "env_tips": [
                "Set OM_STUDIO_TOKEN to protect the instance.",
                "PEXELS_API_KEY / PIXABAY_API_KEY are optional free keys for real stock footage.",
                "OM_LLM_BASE_URL enables an optional LLM script assistant (e.g. local Ollama).",
            ],
        }

    # ---------------- static SPA ----------------
    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app


def _guess_media(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".mp4": "video/mp4", ".srt": "text/plain", ".json": "application/json",
        ".txt": "text/plain", ".log": "text/plain", ".wav": "audio/wav",
        ".mp3": "audio/mpeg", ".png": "image/png",
    }.get(ext, "application/octet-stream")


def _persistence_warning(cfg: StudioConfig) -> Optional[str]:
    p = str(cfg.data_dir)
    if p.startswith("/tmp") or p.startswith("/var/tmp") or "/ephemeral" in p:
        return ("Data directory is on ephemeral storage — projects will NOT survive "
                "container restarts. Download finished videos promptly or set "
                "OM_STUDIO_DATA_DIR to a persistent path.")
    return None
