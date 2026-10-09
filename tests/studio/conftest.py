"""Shared fixtures for OpenMontage AI Studio tests."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture()
def studio_env(tmp_path, monkeypatch):
    """Isolated studio config pointed at a temp data dir."""
    data = tmp_path / "studio_data"
    monkeypatch.setenv("OM_STUDIO_DATA_DIR", str(data))
    monkeypatch.setenv("OM_RENDER_SCALE", "0.15")
    monkeypatch.setenv("OM_TTS_ENGINE", "espeak")
    monkeypatch.setenv("OM_RESEARCH_TIMEOUT_SECONDS", "2")
    monkeypatch.setenv("OM_RATE_LIMIT_PER_MINUTE", "10000")
    monkeypatch.setenv("OM_JOB_CREATE_RATE_PER_MINUTE", "10000")
    monkeypatch.setenv("OM_WORKER_POLL_SECONDS", "0.2")
    monkeypatch.setenv("OM_STAGE_TIMEOUT_SECONDS", "300")
    # No optional keys in tests
    for key in ("PEXELS_API_KEY", "PIXABAY_API_KEY", "OM_LLM_BASE_URL", "OM_LLM_API_KEY",
                "OM_PIPER_MODEL", "OM_STUDIO_TOKEN", "OM_STUDIO_SESSION_SECRET"):
        monkeypatch.delenv(key, raising=False)
    from studio.config import load_config

    cfg = load_config()
    return cfg


@pytest.fixture()
def db(studio_env):
    from studio.db import Database

    return Database(studio_env.db_path)


@pytest.fixture()
def jobs(db):
    from studio.jobs import JobManager

    return JobManager(db, dedupe_window_seconds=300, max_retries=2)


@pytest.fixture()
def sample_request():
    return {
        "topic": "How honeybees communicate with dance",
        "audience": "curious adults",
        "platform": "tiktok",
        "duration_seconds": 15,
        "language": "en",
        "voice": "en-us",
        "style": "documentary",
        "aspect": "1:1",
        "research_depth": "quick",
        "footage_preference": "local",
        "caption_preference": "burned",
        "music_preference": "ambient",
        "reference_urls": [],
        "restrictions": "",
        "call_to_action": "auto",
    }


@pytest.fixture()
def client(studio_env):
    from fastapi.testclient import TestClient

    from studio.api import create_app

    app = create_app(studio_env)
    with TestClient(app) as c:
        yield c
