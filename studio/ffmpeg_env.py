"""Locate FFmpeg/FFprobe binaries and expose them on PATH.

Resolution order:
  1. Explicit env overrides (OM_FFMPEG_PATH / OM_FFPROBE_PATH)
  2. System PATH (excluding our own shim dir to avoid self-recursion)
  3. imageio-ffmpeg bundled ffmpeg (pure-Python wheel, no external download)
  4. ffprobe previously bootstrapped into ``<data>/bin`` (see docs/FREE_DEPLOYMENT.md)

``ensure_tools()`` writes tiny shims into ``<data>/bin`` and prepends that
directory to ``PATH`` so the existing OpenMontage tools (which shell out to
``ffmpeg``/``ffprobe``) work unmodified.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from studio.config import StudioConfig

_shims_done = False


def _which_excluding(name: str, exclude_dir: Path) -> Optional[str]:
    """shutil.which, but never resolve to our own shim (avoids shim→shim recursion)."""
    path = os.environ.get("PATH", "")
    for d in path.split(os.pathsep):
        if not d:
            continue
        cand = Path(d) / name
        try:
            if cand.is_file() and os.access(str(cand), os.X_OK):
                if Path(d).resolve() == exclude_dir.resolve():
                    continue
                return str(cand)
        except OSError:
            continue
    return None


def find_ffmpeg(cfg: StudioConfig) -> Optional[str]:
    if cfg.ffmpeg_path and Path(cfg.ffmpeg_path).exists():
        return cfg.ffmpeg_path
    found = _which_excluding("ffmpeg", cfg.bin_dir)
    if found:
        return found
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def find_ffprobe(cfg: StudioConfig) -> Optional[str]:
    if cfg.ffprobe_path and Path(cfg.ffprobe_path).exists():
        return cfg.ffprobe_path
    found = _which_excluding("ffprobe", cfg.bin_dir)
    if found:
        return found
    # Bootstrapped copy inside the data dir
    local = cfg.bin_dir / "ffprobe"
    if local.exists() and not _is_shell_shim(local):
        return str(local)
    # Common location used by this repo's sandbox bootstrap
    repo_local = Path(__file__).resolve().parent.parent / ".tools" / "bin" / "ffprobe"
    if repo_local.exists():
        return str(repo_local)
    return None


def _is_shell_shim(path: Path) -> bool:
    try:
        return path.stat().st_size < 4096 and path.read_bytes()[:2] == b"#!"
    except OSError:
        return False


def ensure_tools(cfg: StudioConfig) -> dict:
    """Create PATH shims for ffmpeg/ffprobe. Returns a diagnostics dict."""
    global _shims_done
    ffmpeg = find_ffmpeg(cfg)
    ffprobe = find_ffprobe(cfg)
    info = {"ffmpeg": ffmpeg, "ffprobe": ffprobe, "shim_dir": str(cfg.bin_dir)}

    cfg.bin_dir.mkdir(parents=True, exist_ok=True)

    def write_shim(shim: Path, target: str) -> None:
        if Path(target).resolve() == shim.resolve():
            return  # never point a shim at itself
        shim.write_text(f'#!/bin/sh\nexec "{target}" "$@"\n', encoding="utf-8")
        shim.chmod(0o755)

    if ffmpeg:
        write_shim(cfg.bin_dir / "ffmpeg", ffmpeg)
    if ffprobe:
        shim_ffprobe = cfg.bin_dir / "ffprobe"
        if Path(ffprobe).resolve() != shim_ffprobe.resolve():
            if _is_shell_shim(Path(ffprobe)):
                write_shim(shim_ffprobe, ffprobe)
            else:
                shutil.copy2(ffprobe, shim_ffprobe)
                shim_ffprobe.chmod(0o755)

    if not _shims_done:
        path = os.environ.get("PATH", "")
        if str(cfg.bin_dir) not in path.split(os.pathsep):
            os.environ["PATH"] = str(cfg.bin_dir) + os.pathsep + path
        _shims_done = True

    info["ffmpeg_version"] = _version(ffmpeg)
    info["ffprobe_version"] = _version(ffprobe)
    return info


def _version(binary: Optional[str]) -> Optional[str]:
    if not binary:
        return None
    try:
        out = subprocess.run([binary, "-version"], capture_output=True, text=True, timeout=15,
                             stdin=subprocess.DEVNULL)
        first = (out.stdout or "").splitlines()[0] if out.stdout else ""
        return first.strip() or None
    except Exception:
        return None
