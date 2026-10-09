"""End-to-end production test — REAL pipeline, REAL video output.

Creates a job through the public API, lets the background worker run every
stage (research → script → assets → voice → captions → render → QC), and
verifies a valid MP4 with moving footage, narration audio, and burned-in
captions is produced. Uses local-motion footage (no network required) and
the espeak-ng engine. Nothing here is mocked.
"""
from __future__ import annotations

import subprocess
import time

from studio.ffmpeg_env import find_ffprobe


def test_full_pipeline_produces_valid_mp4(client, studio_env):
    request = {
        "topic": "How honeybees communicate with dance",
        "audience": "curious adults",
        "platform": "tiktok",
        "duration_seconds": 15,
        "language": "en",
        "voice": "en-us",
        "style": "documentary",
        "aspect": "1:1",
        "research_depth": "quick",
        "footage_preference": "local",       # real moving footage, generated locally
        "caption_preference": "burned",      # burned-in captions + SRT
        "music_preference": "ambient",
        "reference_urls": [],
        "restrictions": "",
        "call_to_action": "auto",
    }
    r = client.post("/api/jobs", json=request)
    assert r.status_code == 201, r.text
    job_id = r.json()["job_id"]
    project_id = r.json()["project_id"]

    # Wait for the background worker to finish (real stages run).
    deadline = time.time() + 240
    job = None
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
            break
        time.sleep(1.0)

    assert job is not None
    logs = client.get(f"/api/jobs/{job_id}/logs").json()["logs"]
    log_text = "\n".join(l["message"] for l in logs)
    assert job["status"] == "COMPLETED", f"job did not complete: {job.get('error')}\nLOGS:\n{log_text}"

    # Stages all reached
    stages_seen = {l.get("stage") for l in logs}
    for expected in ("RESEARCHING", "SCRIPTING", "COLLECTING_ASSETS", "GENERATING_VOICE",
                     "CREATING_CAPTIONS", "RENDERING", "QUALITY_CHECK"):
        assert expected in stages_seen, f"missing stage {expected} in logs"

    # QC passed and is recorded
    assert job["qc"] is not None and job["qc"]["passed"] is True

    # Download the MP4 through the API (like an iPhone would)
    dl = client.get(f"/api/projects/{project_id}/download/renders/final.mp4")
    assert dl.status_code == 200
    assert len(dl.content) > 20_000

    out_path = studio_env.projects_dir / project_id / "renders" / "final.mp4"
    assert out_path.exists()

    # Independent ffprobe verification
    ffprobe = find_ffprobe(studio_env)
    probe = subprocess.run([ffprobe, "-v", "error", "-print_format", "json",
                            "-show_format", "-show_streams", str(out_path)],
                           capture_output=True, text=True, timeout=60)
    import json

    info = json.loads(probe.stdout)
    duration = float(info["format"]["duration"])
    assert abs(duration - 15.0) <= studio_env.duration_tolerance_seconds + 1.0
    v = [s for s in info["streams"] if s["codec_type"] == "video"][0]
    a = [s for s in info["streams"] if s["codec_type"] == "audio"]
    assert int(v["width"]) == int(v["height"])  # 1:1
    assert a, "narration audio stream missing"

    # Frames actually change over time (moving footage, not a still)
    from studio.ffmpeg_env import find_ffmpeg

    ffmpeg = find_ffmpeg(studio_env)
    frames = []
    for t in (2.0, 11.0):
        fr = subprocess.run([ffmpeg, "-y", "-ss", str(t), "-i", str(out_path),
                             "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                            capture_output=True, timeout=60)
        frames.append(fr.stdout)
    assert frames[0] != frames[1], "video frames identical — output is not moving footage"

    # Captions burned in: caption cards exist and SRT downloads
    proj = client.get(f"/api/projects/{project_id}").json()
    names = {f["name"] for f in proj["files"]}
    assert any(n.endswith(".png") for n in names), "no caption cards rendered"
    srt = client.get(f"/api/projects/{project_id}/download/captions.srt")
    assert srt.status_code == 200
    assert b"-->" in srt.content

    # Narration is real audio (non-silent)
    nar = studio_env.projects_dir / project_id / "narration.wav"
    assert nar.exists() and nar.stat().st_size > 10_000

    # Attribution + script saved
    assert proj["script"] is not None
    assert proj["attribution"] is not None


def test_invalid_request_never_starts_production(client):
    r = client.post("/api/jobs", json={"topic": "x", "duration_seconds": 15, "style": "nope"})
    assert r.status_code == 422
    jobs = client.get("/api/jobs").json()["jobs"]
    assert all(j["request"].get("style") != "nope" for j in jobs)


def test_failure_path_reports_explicit_error(client, monkeypatch):
    """If rendering breaks, the job must FAIL loudly — never fake success."""
    from studio.pipeline import render as RD

    monkeypatch.setattr(RD, "render_video", lambda *a, **kw: RD.RenderResult(
        ok=False, error="simulated renderer crash"))
    request = {
        "topic": "Failure handling verification topic",
        "duration_seconds": 15, "style": "custom", "aspect": "9:16",
        "footage_preference": "local", "caption_preference": "none",
        "music_preference": "none", "research_depth": "quick",
        "voice": "en-us", "language": "en", "platform": "tiktok",
    }
    r = client.post("/api/jobs", json=request)
    assert r.status_code == 201
    job_id = r.json()["job_id"]
    deadline = time.time() + 120
    job = None
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
            break
        time.sleep(0.5)
    assert job["status"] == "FAILED"
    assert "simulated renderer crash" in (job.get("error") or "")
    assert job["error_stage"] == "RENDERING"
