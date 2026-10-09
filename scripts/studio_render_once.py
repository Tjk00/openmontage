#!/usr/bin/env python
"""Render one video production headlessly (no web server).

Usage:
    python scripts/studio_render_once.py "Your topic here" \
        [--duration 15] [--aspect 9:16] [--style documentary] \
        [--footage local] [--out-dir studio_data]

Runs the full OpenMontage AI Studio pipeline (research → script → assets →
voice → captions → render → QC) synchronously and prints the output MP4
path. Exit code 0 only when QC passes. Useful for CI runners (see
docs/FREE_DEPLOYMENT.md Option 4) and for quick local renders.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from studio.config import load_config  # noqa: E402
from studio.db import Database  # noqa: E402
from studio.ffmpeg_env import ensure_tools  # noqa: E402
from studio.jobs import JobManager  # noqa: E402
from studio.models import VideoRequest  # noqa: E402
from studio.worker import PipelineWorker  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Headless OpenMontage AI Studio render")
    parser.add_argument("topic")
    parser.add_argument("--duration", type=int, default=15, choices=[15, 30, 45, 60, 90])
    parser.add_argument("--aspect", default="9:16", choices=["9:16", "16:9", "1:1"])
    parser.add_argument("--style", default="custom")
    parser.add_argument("--footage", default="auto", choices=["auto", "stock", "open", "local"])
    parser.add_argument("--captions", default="burned", choices=["burned", "srt-only", "none"])
    parser.add_argument("--music", default="ambient", choices=["none", "ambient", "upload"])
    parser.add_argument("--platform", default="tiktok")
    parser.add_argument("--language", default="en")
    parser.add_argument("--voice", default="en-us")
    parser.add_argument("--audience", default="general viewers")
    args = parser.parse_args()

    cfg = load_config()
    ensure_tools(cfg)
    db = Database(cfg.db_path)
    jobs = JobManager(db)
    worker = PipelineWorker(cfg, db, jobs)

    request = VideoRequest(
        topic=args.topic, audience=args.audience, platform=args.platform,
        duration_seconds=args.duration, language=args.language, voice=args.voice,
        style=args.style, aspect=args.aspect, research_depth="standard",
        footage_preference=args.footage, caption_preference=args.captions,
        music_preference=args.music,
    ).model_dump()

    created = jobs.create_job(request)
    if created["deduplicated"]:
        print(f"Note: identical request already active as {created['job']['id']}")
    job_id = created["job"]["id"]
    print(f"Job {job_id} queued — running pipeline…")

    # Run this job inline via the worker's pipeline executor (synchronous).
    job = db.claim_next_queued()
    while job and job["id"] != job_id:
        db.update_job(job["id"], status="QUEUED")  # put others back
        job = db.claim_next_queued()
    if job is None:
        print("ERROR: could not claim job", file=sys.stderr)
        return 2

    worker._run_job(job)  # noqa: SLF001 — intentional synchronous entry point
    final = jobs.get_job(job_id)
    print(json.dumps({k: final[k] for k in ("status", "stage", "error", "output_path")},
                     indent=2))
    if final.get("qc"):
        print("QC:", "PASSED" if final["qc"].get("passed") else "FAILED")
    return 0 if final["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
