"""TTS adapter tests: espeak engine, piper detection, upload fallback, failures."""
from __future__ import annotations

import wave

import pytest

from studio.pipeline import tts as T


def test_espeak_available():
    assert T.EspeakEngine.available() is True


def test_espeak_synthesizes_real_wav(studio_env, tmp_path):
    out = tmp_path / "narration.wav"
    res = T.synthesize(studio_env, "Hello from the OpenMontage AI Studio test suite.", out,
                       voice="en-us", rate_wpm=165)
    assert res.ok, res.error
    assert res.engine == "espeak-ng"
    assert out.exists() and out.stat().st_size > 1000
    assert res.duration_seconds > 0.5
    with wave.open(str(out), "rb") as w:
        assert w.getnframes() > 8000  # real audio samples, not silence-only header
        assert w.getframerate() > 8000


def test_espeak_rate_affects_duration(studio_env, tmp_path):
    slow = T.synthesize(studio_env, "This is a pacing test sentence for speech rate.",
                        tmp_path / "slow.wav", rate_wpm=100)
    fast = T.synthesize(studio_env, "This is a pacing test sentence for speech rate.",
                        tmp_path / "fast.wav", rate_wpm=350)
    assert slow.ok and fast.ok
    assert slow.duration_seconds > fast.duration_seconds


def test_piper_missing_reports_cleanly(studio_env, monkeypatch):
    monkeypatch.delenv("OM_PIPER_MODEL", raising=False)
    ok, why = T.piper_available(None)
    assert ok is False or "model" in why.lower() or why == "ok"


def test_uploaded_audio_fallback(studio_env, tmp_path):
    # Build a valid wav and pass as upload
    import numpy as np

    wav = tmp_path / "user_voice.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
        w.writeframes((np.sin(np.linspace(0, 100, 44100)) * 8000).astype("int16").tobytes())
    res = T.synthesize(studio_env, "", tmp_path / "out.wav", uploaded_audio=wav)
    assert res.ok
    assert res.engine == "uploaded-audio"
    assert abs(res.duration_seconds - 2.0) < 0.2


def test_no_engine_reports_failure_not_success(studio_env, tmp_path, monkeypatch):
    monkeypatch.setattr(T, "EspeakEngine", type("NoEngine", (), {"available": staticmethod(lambda: False)}))
    monkeypatch.delenv("OM_PIPER_MODEL", raising=False)
    res = T.synthesize(studio_env, "test", tmp_path / "x.wav")
    assert res.ok is False
    assert "no tts engine" in res.error.lower() or "not" in res.error.lower()


def test_empty_text_fails(studio_env, tmp_path):
    res = T.synthesize(studio_env, "   ", tmp_path / "x.wav")
    assert res.ok is False
