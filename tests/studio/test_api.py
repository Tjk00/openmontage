"""API endpoint tests: validation, auth, throttling, secret masking, downloads."""
from __future__ import annotations

import json


def test_health_and_stats(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    r2 = client.get("/api/stats")
    assert r2.status_code == 200
    assert "jobs_by_status" in r2.json()


def test_spa_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "OpenMontage" in r.text


def test_job_creation_and_validation(client, sample_request):
    r = client.post("/api/jobs", json=sample_request)
    assert r.status_code == 201
    body = r.json()
    assert body["job_id"].startswith("job_")

    # duplicate → deduplicated
    r2 = client.post("/api/jobs", json=sample_request)
    assert r2.status_code == 200
    assert r2.json()["deduplicated"] is True

    # invalid duration
    bad = dict(sample_request, duration_seconds=17)
    r3 = client.post("/api/jobs", json=bad)
    assert r3.status_code == 422

    # invalid aspect
    r4 = client.post("/api/jobs", json=dict(sample_request, aspect="4:3"))
    assert r4.status_code == 422

    # missing topic
    r5 = client.post("/api/jobs", json={})
    assert r5.status_code == 422

    # SSRF-unsafe reference URL rejected
    r6 = client.post("/api/jobs", json=dict(sample_request, reference_urls=["http://169.254.169.254/"]))
    assert r6.status_code == 422

    # job fetch + logs
    j = client.get(f"/api/jobs/{body['job_id']}").json()
    assert j["status"] == "QUEUED"
    logs = client.get(f"/api/jobs/{body['job_id']}/logs").json()["logs"]
    assert logs


def test_cancel_retry_endpoints(client, sample_request):
    job_id = client.post("/api/jobs", json=dict(sample_request, topic="cancel me please now")).json()["job_id"]
    r = client.post(f"/api/jobs/{job_id}/cancel", json={})
    assert r.status_code == 200
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "CANCELLED"

    job2 = client.post("/api/jobs", json=dict(sample_request, topic="retry me please now")).json()["job_id"]
    r2 = client.post(f"/api/jobs/{job2}/retry", json={})
    assert r2.status_code == 400  # not FAILED yet


def test_providers_mask_secrets(client):
    r = client.get("/api/providers")
    assert r.status_code == 200
    providers = r.json()["providers"]
    ids = {p["id"] for p in providers}
    assert {"ffmpeg", "espeak-ng", "local-motion", "pexels", "pixabay", "piper", "llm",
            "elevenlabs", "openai-sora", "fal-ai"} <= ids
    # paid providers disabled by default
    for p in providers:
        if p["cost_status"] == "paid":
            assert p["enabled"] is False
        # no raw secrets anywhere
        blob = json.dumps(p)
        assert "sk-" not in blob
    # core free providers present
    ffmpeg = next(p for p in providers if p["id"] == "ffmpeg")
    assert ffmpeg["required_for_free_workflow"] is True


def test_provider_toggle_and_check(client):
    r = client.post("/api/providers/pexels/toggle", json={"enabled": True})
    assert r.status_code == 200
    r2 = client.post("/api/providers/does-not-exist/toggle", json={"enabled": True})
    assert r2.status_code == 404
    r3 = client.post("/api/providers/ffmpeg/check", json={})
    assert r3.status_code == 200
    assert r3.json()["ok"] is True


def test_diagnostics(client):
    r = client.get("/api/diagnostics")
    assert r.status_code == 200
    d = r.json()
    names = {c["name"] for c in d["checks"]}
    assert {"ffmpeg", "ffprobe", "worker", "auth", "storage_writable"} <= names
    ffmpeg = next(c for c in d["checks"] if c["name"] == "ffmpeg")
    assert ffmpeg["ok"] is True


def test_storage_endpoint(client):
    r = client.get("/api/storage")
    assert r.status_code == 200
    assert "used_bytes" in r.json()


def test_upload_audio_validates(client):
    r = client.post("/api/uploads/audio", files={"file": ("evil.sh", b"#!/bin/sh\n", "text/plain")})
    assert r.status_code == 422
    r2 = client.post("/api/uploads/audio", files={"file": ("voice.wav", b"RIFF0000WAVEfake", "audio/wav")})
    assert r2.status_code == 201
    assert r2.json()["upload_id"].startswith("up_")


def test_download_path_traversal_blocked(client):
    r = client.get("/api/projects/proj_x/download/..%2F..%2Fstudio.db")
    assert r.status_code in (400, 404)
    r2 = client.get("/api/projects/proj_x/download/renders/final.mp4")
    assert r2.status_code == 404


def test_auth_enforcement(studio_env, monkeypatch):
    monkeypatch.setenv("OM_STUDIO_TOKEN", "super-secret-token")
    from fastapi.testclient import TestClient

    from studio.api import create_app
    from studio.config import load_config

    cfg = load_config()
    app = create_app(cfg)
    csrf = {"X-Requested-With": "pytest"}
    with TestClient(app) as c:
        assert c.get("/api/auth/status").json()["auth_enabled"] is True
        assert c.get("/api/jobs").status_code == 401
        assert c.get("/api/health").status_code == 200  # health is public
        bad = c.post("/api/auth/login", json={"token": "wrong"})
        assert bad.status_code == 401
        good = c.post("/api/auth/login", json={"token": "super-secret-token"})
        assert good.status_code == 200
        # cookie now authorises
        assert c.get("/api/jobs").status_code == 200
        r = c.post("/api/jobs", json={"topic": "auth test topic here", "duration_seconds": 15},
                   headers=csrf)
        assert r.status_code == 201
        # mutating without CSRF header is rejected (defense in depth)
        r2 = c.post("/api/jobs", json={"topic": "auth test topic here 2", "duration_seconds": 15})
        assert r2.status_code == 403


def test_secret_not_in_error_messages(client):
    r = client.post("/api/jobs", json={"topic": "x"})
    assert r.status_code == 422
    assert "PEXELS" not in r.text and "API_KEY" not in r.text
