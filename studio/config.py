"""OpenMontage AI Studio — configuration.

All settings come from environment variables (optionally via a local ``.env``).
No secrets are ever committed; see ``.env.example`` for placeholders.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Load repo-root .env (placeholders only in git; real values stay local)."""
    env_path = REPO_ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name, "").lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


@dataclass
class StudioConfig:
    """Runtime configuration for the studio web app + pipeline worker."""

    data_dir: Path = field(default_factory=lambda: Path(_env("OM_STUDIO_DATA_DIR", str(REPO_ROOT / "studio_data"))))
    host: str = field(default_factory=lambda: _env("OM_STUDIO_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _env_int("OM_STUDIO_PORT", 8080))

    # Auth
    admin_token: str = field(default_factory=lambda: _env("OM_STUDIO_TOKEN"))
    session_secret: str = field(default_factory=lambda: _env("OM_STUDIO_SESSION_SECRET"))
    session_ttl_seconds: int = field(default_factory=lambda: _env_int("OM_STUDIO_SESSION_TTL", 12 * 3600))

    # Jobs / rendering
    worker_poll_seconds: float = field(default_factory=lambda: float(_env("OM_WORKER_POLL_SECONDS", "1.0")))
    stage_timeout_seconds: int = field(default_factory=lambda: _env_int("OM_STAGE_TIMEOUT_SECONDS", 900))
    render_scale: float = field(default_factory=lambda: float(_env("OM_RENDER_SCALE", "1.0")))
    max_concurrent_jobs: int = field(default_factory=lambda: max(1, _env_int("OM_MAX_CONCURRENT_JOBS", 1)))
    dedupe_window_seconds: int = field(default_factory=lambda: _env_int("OM_DEDUPE_WINDOW_SECONDS", 300))
    max_retries: int = field(default_factory=lambda: _env_int("OM_MAX_RETRIES", 2))
    duration_tolerance_seconds: float = field(default_factory=lambda: float(_env("OM_DURATION_TOLERANCE_SECONDS", "3.0")))

    # Storage
    max_upload_mb: int = field(default_factory=lambda: _env_int("OM_MAX_UPLOAD_MB", 50))
    storage_limit_mb: int = field(default_factory=lambda: _env_int("OM_STORAGE_LIMIT_MB", 2048))
    retention_days: int = field(default_factory=lambda: _env_int("OM_RETENTION_DAYS", 0))  # 0 = keep forever

    # Security
    rate_limit_per_minute: int = field(default_factory=lambda: _env_int("OM_RATE_LIMIT_PER_MINUTE", 120))
    job_create_rate_per_minute: int = field(default_factory=lambda: _env_int("OM_JOB_CREATE_RATE_PER_MINUTE", 6))

    # Research
    research_timeout_seconds: int = field(default_factory=lambda: _env_int("OM_RESEARCH_TIMEOUT_SECONDS", 12))
    research_cache_hours: int = field(default_factory=lambda: _env_int("OM_RESEARCH_CACHE_HOURS", 6))
    research_max_sources: int = field(default_factory=lambda: _env_int("OM_RESEARCH_MAX_SOURCES", 8))
    research_user_feeds: str = field(default_factory=lambda: _env("OM_RESEARCH_FEEDS", ""))

    # TTS
    tts_engine: str = field(default_factory=lambda: _env("OM_TTS_ENGINE", "auto"))  # auto | espeak | piper | none
    tts_voice: str = field(default_factory=lambda: _env("OM_TTS_VOICE", "en-us"))
    tts_rate_wpm: int = field(default_factory=lambda: _env_int("OM_TTS_RATE_WPM", 165))

    # Optional LLM (never required)
    llm_base_url: str = field(default_factory=lambda: _env("OM_LLM_BASE_URL"))
    llm_api_key: str = field(default_factory=lambda: _env("OM_LLM_API_KEY"))
    llm_model: str = field(default_factory=lambda: _env("OM_LLM_MODEL"))

    # Optional stock providers (free keys, never required)
    pexels_api_key: str = field(default_factory=lambda: _env("PEXELS_API_KEY"))
    pixabay_api_key: str = field(default_factory=lambda: _env("PIXABAY_API_KEY"))

    # Optional AI video providers (paid unless user configures; disabled by default)
    fal_api_key: str = field(default_factory=lambda: _env("FAL_KEY") or _env("FAL_AI_API_KEY"))
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    elevenlabs_api_key: str = field(default_factory=lambda: _env("ELEVENLABS_API_KEY"))

    # Paths
    ffmpeg_path: str = field(default_factory=lambda: _env("OM_FFMPEG_PATH"))
    ffprobe_path: str = field(default_factory=lambda: _env("OM_FFPROBE_PATH"))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "studio.db"

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def bin_dir(self) -> Path:
        return self.data_dir / "bin"

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.projects_dir, self.cache_dir, self.bin_dir):
            p.mkdir(parents=True, exist_ok=True)


def load_config() -> StudioConfig:
    cfg = StudioConfig()
    cfg.ensure_dirs()
    return cfg
