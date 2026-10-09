# OpenMontage AI Studio — Implementation Audit

> Audited: 2026-10-09, from the actual checkout of `Tjk00/openmontage`
> (branch `arena/847a5366-openmontage`, base commit `9327439`). Every claim
> below was verified against source files; items that were **executed** say so.

## 1. What OpenMontage is (upstream)

OpenMontage is an **agent-orchestrated, instruction-driven video production
platform** (AGPL-3.0). The AI coding agent *is* the orchestrator: Python
provides tools and persistence; YAML pipeline manifests + markdown skills
drive stages. There is intentionally **no upstream Python orchestrator** —
the studio layer added by this project is a new, self-contained consumer of
the same tools (see "AI Studio additions" below).

## 2. Existing Python modules (verified present)

| Area | Path | Status |
|---|---|---|
| Core infra | `lib/` — `config_model.py`, `checkpoint.py`, `pipeline_loader.py`, `media_profiles.py`, `paths.py`, `corpus.py`, `scoring.py`, … | Present, imported by tools |
| Tool base + registry | `tools/base_tool.py` (ToolContract, `run_command`, instrumentation), `tools/tool_registry.py` | Present |
| Budget governance | `tools/cost_tracker.py`, `tools/provider_pricing.py`, `tools/provider_routing.py` | Present |
| TTS providers | `tools/audio/` — `piper_tts.py`, `elevenlabs_tts.py`, `google_tts.py`, `openai_tts.py`, `azure_tts.py`, `tts_selector.py`, + more | Present |
| Audio post | `tools/audio/audio_mixer.py` (`full_mix` w/ ducking + loudnorm), `audio_enhance.py`, `music_library.py`, `pixabay_music.py` | Present |
| Video assembly | `tools/video/video_stitch.py` (concat/normalize), `video_compose.py` (Remotion/HyperFrames/FFmpeg routing), `video_trimmer.py`, `silence_cutter.py` | Present |
| Stock footage | `tools/video/pexels_video.py`, `pixabay_video.py`, `clip_search.py`, `corpus_builder.py`, `stock_sources/` | Present |
| Subtitles | `tools/subtitle/subtitle_gen.py` — pure-Python SRT/VTT/JSON from word timings | Present, reused by Studio |
| Media probing | `tools/analysis/audio_probe.py` (ffprobe wrapper), `transcriber.py`, `scene_detect.py`, `video_downloader.py` | Present |
| Persistence | `lib/checkpoint.py`, project workspaces under `projects/<id>/` (gitignored) | Present |
| Local board UI | `backlot/` — FastAPI + vanilla-JS read-only "living storyboard" with SSE watcher | Present |
| Pipeline manifests | `pipeline_defs/*.yaml` (13 pipelines: documentary-montage, animated-explainer, talking-head, …) | Present |
| Skills | `skills/` (Layer 2) and `.agents/skills/` (Layer 3, incl. ffmpeg, piper TTS, stock APIs) | Present |

## 3. Existing tests (upstream)

`tests/` — ~100 test modules: contracts (`tests/contracts/`), tools
(`tests/tools/`), backlot (`tests/backlot/`), lib (`tests/lib/`), QA
(`tests/qa/`). **Executed** after studio integration (sample):
`tests/contracts/test_env_example.py`, `tests/lib/`, `tests/backlot/`,
`tests/tools/test_{subtitle_timestamps,video_compose_vertical,stock_source_adapters,scoring,base_tool_dependencies}.py`,
`tests/test_network_guard.py` → **103 passed, 4 skipped/xfail** (no upstream
regressions observed).

## 4. Dependencies & OS requirements (verified)

- `requirements.txt`: pyyaml, pydantic, jsonschema, python-dotenv, Pillow,
  numpy, requests, google-auth, google-genai, openai + backlot (fastapi,
  uvicorn, watchfiles). **Studio additions**: `python-multipart`,
  `espeakng-loader`, `imageio-ffmpeg` (all PyPI, free).
- `requirements-dev.txt`: pytest, pytest-asyncio, httpx.
- **FFmpeg/FFprobe**: required by the media tools (`cmd:ffmpeg`, `cmd:ffprobe`
  dependencies). Not bundled upstream; must be installed **or** provided via
  `imageio-ffmpeg` (ffmpeg) + a bootstrapped ffprobe (see
  `docs/FREE_DEPLOYMENT.md`).
- Python ≥ 3.10 (`.python-version` says 3.11; verified on 3.11.2).

## 5. API providers (upstream inventory)

Upstream supports many cloud providers (fal, Replicate, Kling, Runway, Veo,
Sora, MiniMax, HeyGen, Azure, Google Vertex, ElevenLabs, Cartesia, Suno,
Pixabay, Pexels, …). **All optional**; keys via `.env` (placeholders only in
git). **None of them are required** for the Studio free workflow.

## 6. License obligations

- **AGPL-3.0** (`LICENSE`). Any deployed modified version offered to users
  over a network must make its source available under AGPL terms. The Studio
  layer lives in-repo and inherits this — keep the license notice when
  deploying; link to your fork's source in the UI/README when you deploy.
- Upstream media examples are illustrative; the Studio records per-asset
  license/attribution metadata for every downloaded clip and prefers
  permissively licensed sources (Pexels License, Pixabay Content License,
  Wikimedia per-file licenses) or locally generated media (no third-party
  rights).

## 7. What already worked (and was reused, not rewritten)

| Component | Reused by Studio | How |
|---|---|---|
| `SubtitleGen` | ✅ Captions stage | SRT/VTT/JSON from word timings (`tools/subtitle/subtitle_gen.py`) |
| `AudioMixer.full_mix` | ✅ Render stage | narration+music ducking/loudnorm (with ffmpeg fallback) |
| `VideoStitch` | ✅ Render stage | clip assembly with auto-normalize (with ffmpeg-concat fallback) |
| `audio_probe.probe_duration` | ✅ available | duration helpers |
| `backlot` | ✅ untouched | still serves the live storyboard board |
| Tool contract (`BaseTool`) | ✅ understood | Studio tools-call the same `execute()` surface |

## 8. What was missing (and is now implemented in `studio/`)

| Requirement | Before | Now |
|---|---|---|
| Mobile-first web dashboard | ❌ (backlot is read-only board) | ✅ `studio/static/` — 12-view dark SPA |
| Universal topic form + validation | ❌ | ✅ `studio/models.py`, Create view |
| Research pipeline (RSS/web, cached, honest) | ❌ | ✅ `studio/pipeline/research.py` |
| Script + storyboard generation (no API key) | ❌ (agent-authored) | ✅ `studio/pipeline/scriptgen.py` (+ optional LLM) |
| Background job manager (states/retry/cancel/dedupe) | ❌ | ✅ `studio/jobs.py` + `studio/worker.py` + SQLite |
| Free-first footage workflow + license metadata | partial tools | ✅ `studio/pipeline/assets.py` |
| Offline TTS that works with zero keys | piper tool (needs binary+voice) | ✅ `studio/pipeline/tts.py` (espeak-ng bundled engine + piper + upload) |
| Caption timing + burn-in + SRT | tools only | ✅ `studio/pipeline/captions.py` |
| QC gate before COMPLETED | ❌ | ✅ `studio/pipeline/qc.py` (ffprobe-based) |
| Provider manager with health-checks/masking | ❌ | ✅ `studio/pipeline/providers.py` |
| Storage library, retention, safe deletion | ❌ | ✅ `studio/pipeline/storage.py` |
| Security (auth, CSRF, SSRF, throttling, safe paths) | ❌ | ✅ `studio/security.py` + API middleware |
| Deployment docs from an iPhone | ❌ | ✅ `docs/FREE_DEPLOYMENT.md`, `docs/IPHONE_SETUP.md` |

## 9. Honest limitations found in this environment

1. **Outbound network is restricted** in the build sandbox (only PyPI/GitHub
   reachable). Live research (Google News RSS), Wikimedia/Pexels/Pixabay
   downloads therefore **could not be exercised against the real internet**
   here; they are unit-tested against parsed fixtures and will work wherever
   outbound HTTPS is available. The pipeline reports `RESEARCH UNAVAILABLE`
   honestly instead of inventing trends.
2. **No system FFmpeg** in the sandbox; resolved via `imageio-ffmpeg`'s
   bundled ffmpeg 7.0.2 (includes libx264/aac/fontconfig/libass) + a static
   ffprobe. Install paths are documented; `ensure_tools()` abstracts it.
3. **Piper voice models** live on HuggingFace (not reachable/needed here);
   the Piper adapter is implemented and tested for detection/failure
   reporting, and falls back to espeak-ng.
4. **Whisper-class ASR** needs a large model download (~150 MB–1.5 GB);
   not auto-downloaded. Caption timing is therefore **estimated
   proportionally** from narration text + measured audio duration and is
   labelled as such (`timing_source: estimated-proportional`).
5. **Hosted free tiers change**; nothing in the docs claims unlimited free
   hosting or generation. See `docs/COST_AND_LIMITS.md`.

## 10. Verdict

Functioning upstream tool layer ✅ preserved and reused. The AI Studio layer
is a real, tested application (68 automated tests incl. a true end-to-end
render in `tests/studio/`), produces a **valid MP4 with moving footage,
narration audio, and burned-in captions**, and never requires a paid API.
