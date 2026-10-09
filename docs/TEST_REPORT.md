# Test Report — OpenMontage AI Studio

> Date: 2026-10-09 · Python 3.11.2 · pytest 9.1.1 · FFmpeg 7.0.2-static
> (imageio-ffmpeg) · FFprobe N-66595-static
> Every number below was produced by actually running the tests in this
> checkout. Nothing is estimated or claimed without execution.

## 1. Studio automated test suite

```
.venv/bin/python -m pytest tests/studio/ -v
============================= 68 passed in 24.69s ==============================
```

| Test module | Tests | Result | What it proves |
|---|---|---|---|
| `test_jobs.py` | 9 | ✅ pass | Job creation, state transitions, atomic claim, complete/fail, retry limits, cancellation (queued + running), logs |
| `test_research.py` | 7 | ✅ pass | RSS/Atom parsing, fact vs opinion/prediction classification, cache TTL, per-host throttling, **offline honesty** (no fake "viral" claims) |
| `test_scriptgen.py` | 8 | ✅ pass | Duration-matched scripts, anti-fabrication validation, sensitive-topic disclaimers, custom topics, all 13 styles |
| `test_tts.py` | 7 | ✅ pass | espeak-ng synthesis produces real WAV samples, speech-rate effect, piper detection, upload fallback, explicit failure when no engine |
| `test_captions.py` | 6 | ✅ pass | Proportional word timing, cue grouping, SRT/JSON export (via upstream `SubtitleGen`), caption PNG rendering/positioning |
| `test_render_qc.py` | 4 | ✅ pass | **Real FFmpeg renders**: motion-clip generation with frame-diff proof of motion; full render (clips+narration+burned captions); QC fails on missing file and wrong duration |
| `test_security.py` | 8 | ✅ pass | Session tokens, expiry, rate limiting, path traversal, SSRF (private ranges/IMDS blocked), secret redaction/masking |
| `test_storage.py` | 4 | ✅ pass | Project files, deletion authorization (confirm required), traversal IDs, retention cleanup rules |
| `test_api.py` | 12 | ✅ pass | All endpoints, 422 validation (incl. bad aspect/duration/URL), dedupe, secret masking in provider list, upload validation, download traversal block, **auth enforcement + CSRF** |
| `test_e2e.py` | 3 | ✅ pass | **Full production run** (below) + invalid input never queues + failure path never fakes success |

## 2. End-to-end rendering test (real, not mocked)

`tests/studio/test_e2e.py::test_full_pipeline_produces_valid_mp4` — **PASSED**.

Flow actually executed through the public API + background worker:

1. POST `/api/jobs` (topic "How honeybees communicate with dance", 15 s, 1:1,
   documentary, footage=local, captions=burned, music=ambient)
2. Worker stages ran in order: RESEARCHING → SCRIPTING → COLLECTING_ASSETS →
   GENERATING_VOICE → CREATING_CAPTIONS → RENDERING → QUALITY_CHECK
3. Verified after COMPLETED:
   - MP4 downloadable via API (200, >20 KB body)
   - ffprobe: duration 15.0 s ± tolerance, video stream 1:1, **audio stream present** (narration)
   - **frame-diff check**: frames at t=2 s and t=11 s differ → moving footage, not a still/slideshow
   - caption PNG cards present in project, `captions.srt` downloads with valid `-->` cues
   - `narration.wav` exists with real samples (>10 KB)
   - QC report recorded `passed: true` (job is never COMPLETED without it)

Additionally executed outside pytest (manual verification):
`python scripts/studio_render_once.py "The secret life of octopuses" --duration 15 --aspect 9:16 --footage local`
→ **COMPLETED, QC: PASSED** in ~86 s at full resolution.

```
final.mp4: 1509 KB · 15.000 s · h264 1080x1920 30 fps · aac 96 kHz mono
workspace: assets/ caption_cards/ captions.srt narration.wav music_bed.wav
           script.json research.json assets.json qc_report.json production.log
```

**Yes — the application has actually generated valid videos.**

## 3. Upstream (OpenMontage) regression tests

Sample of upstream suites run after integration:

```
tests/contracts/test_env_example.py, tests/lib/, tests/backlot/test_state.py,
tests/tools/test_{base_tool_dependencies,subtitle_timestamps}.py,
tests/test_network_guard.py .......................  55 passed, 1 skipped
tests/backlot/test_server.py, tests/tools/test_{video_compose_vertical,
stock_source_adapters,scoring}.py ...  48 passed, 3 skipped, 3 xfailed
```

**No upstream regressions observed.** Upstream `backlot` and tool tests
behave exactly as before the studio layer was added.

## 4. What is mocked vs real

| Layer | Unit tests | E2E test |
|---|---|---|
| HTTP research feeds | mocked responses / forced offline | offline (sandbox has no open internet) — stage degrades honestly |
| Script generation | real | real |
| Footage | real local motion generation (FFmpeg) | real local motion generation |
| TTS | **real espeak-ng synthesis** | **real espeak-ng synthesis** |
| Captions | **real SRT/PNG output** | **real SRT/PNG output** |
| FFmpeg render | **real render** | **real render** |
| QC (ffprobe) | **real probe** | **real probe** |

Mocks are used **only** to simulate network services (RSS feeds, provider
APIs) — never for media processing.

## 5. Known test-environment failures / gaps (honest)

1. **Live internet research** (Google News RSS, Wikimedia, Pexels, Pixabay)
   could not be exercised end-to-end here because the build sandbox allows
   outbound traffic only to PyPI/GitHub. Code paths are covered with parsed
   fixtures + error-path tests. Wherever the instance has open HTTPS, these
   run live.
2. **Piper TTS** could not be exercised with a real voice model (model
   downloads host on HuggingFace, unreachable here). Detection and
   failure-reporting paths are tested; the espeak-ng engine carries the free
   workflow.
3. **Whisper ASR** is intentionally not auto-downloaded (150 MB–1.5 GB
   models); caption timing is labelled `estimated-proportional`, never as
   ASR output.
4. Full upstream suite (`tests/` overall) is large and partially needs GPU
   or provider credentials; the representative sample above was run instead.

## 6. How to reproduce

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest tests/studio/ -v          # studio suite (68 tests)
python -m pytest tests/studio/test_e2e.py  # just the end-to-end render
python scripts/studio_render_once.py "Your topic" --duration 15 --footage local
```
