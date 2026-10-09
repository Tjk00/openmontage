"""Real FFmpeg rendering + QC tests (no mocks — actual media is produced)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from studio.ffmpeg_env import find_ffmpeg, find_ffprobe
from studio.pipeline import assets as A
from studio.pipeline import qc as Q
from studio.pipeline import render as RD


def _probe_dims(path):
    ffprobe = find_ffprobe(_cfg())
    out = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, timeout=60)
    w, h = out.stdout.strip().split(",")[:2]
    return int(w), int(h)


class _Cfg:
    ffmpeg_path = ""
    ffprobe_path = ""
    duration_tolerance_seconds = 3.0
    bin_dir = None


def _cfg():
    from studio.config import load_config

    return load_config()


def test_generate_motion_clip_is_real_video(tmp_path):
    dest = tmp_path / "motion.mp4"
    info = A.generate_motion_clip(_cfg(), dest, width=216, height=216, duration=2.0,
                                  seed=1, style="zoompan")
    assert dest.exists() and dest.stat().st_size > 5000
    w, h = _probe_dims(dest)
    assert (w, h) == (216, 216)
    # must contain actual motion: compare two frames
    ffmpeg = find_ffmpeg(_cfg())
    for t, name in ((0.2, "f1.png"), (1.5, "f2.png")):
        subprocess.run([ffmpeg, "-y", "-ss", str(t), "-i", str(dest), "-frames:v", "1",
                        str(tmp_path / name)], capture_output=True, timeout=60)
    f1 = (tmp_path / "f1.png").read_bytes()
    f2 = (tmp_path / "f2.png").read_bytes()
    assert f1 != f2, "clip frames identical — not moving footage"


def test_render_video_with_narration_and_captions(tmp_path):
    cfg = _cfg()
    # two real moving clips
    clips = []
    for i in range(2):
        dest = tmp_path / f"clip{i}.mp4"
        A.generate_motion_clip(cfg, dest, width=216, height=216, duration=2.0, seed=i + 1,
                               style="pattern" if i else "zoompan")
        clips.append({"path": str(dest), "duration": 2.0})
    # narration
    from studio.pipeline import tts as T

    tts = T.synthesize(cfg, "Rendering test narration for the studio pipeline.",
                       tmp_path / "nar.wav")
    assert tts.ok
    # captions
    from studio.pipeline import captions as C

    cap = C.build_captions("Rendering test narration for the studio pipeline.",
                           4.0, tmp_path)
    cards = C.render_caption_cards(cap.cues, tmp_path, width=162, height=288)
    out = tmp_path / "final.mp4"
    res = RD.render_video(cfg, clips=clips, aspect="9:16", output_path=out,
                          narration=Path(tts.audio_path), caption_cards=cards, scale=0.15)
    assert res.ok, res.error
    assert out.exists() and out.stat().st_size > 10000
    w, h = _probe_dims(out)
    assert abs(w / h - 9 / 16) < 0.05
    assert "ffmpeg-mux" in res.used_tools

    report = Q.run_qc(cfg, output_path=out, requested_duration=4.0, aspect="9:16",
                      narration_required=True, captions_requested=True,
                      captions_produced=bool(cards))
    assert report.passed, report.to_dict()
    assert report.media["width"] == w


def test_qc_fails_on_missing_file(tmp_path):
    report = Q.run_qc(_cfg(), output_path=tmp_path / "nope.mp4", requested_duration=10,
                      aspect="9:16", narration_required=True, captions_requested=True,
                      captions_produced=False)
    assert report.passed is False
    assert report.checks[0].name == "output_exists"


def test_qc_fails_on_wrong_duration(tmp_path):
    cfg = _cfg()
    dest = tmp_path / "short.mp4"
    A.generate_motion_clip(cfg, dest, width=128, height=128, duration=2.0, seed=3)
    report = Q.run_qc(cfg, output_path=dest, requested_duration=30, aspect="1:1",
                      narration_required=False, captions_requested=False,
                      captions_produced=False)
    assert report.passed is False
    failed = {c.name for c in report.checks if not c.passed}
    assert "duration_within_tolerance" in failed or "audio_present" in failed
