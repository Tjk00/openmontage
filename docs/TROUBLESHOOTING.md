# Troubleshooting

## First stops

1. **More → System health** — every dependency has a ✅/❌ with detail.
2. **More → Deployment diagnostics** — auth and storage posture.
3. **Job page → Production log** — each stage logs what it did; the failing
   stage is named on the error banner (`error_stage`).

## Job failed at …

### RESEARCHING
- `feed error … network` — the instance has no outbound internet (or the
  feed is down). The job **continues** with unverified framing; check
  `research.json` in the project. Fix: give the host internet access or add
  reachable `OM_RESEARCH_FEEDS`.
- Rate limited by a feed — research is throttled ≥2 s/host by design; wait
  and retry.

### SCRIPTING
- `script validation failed` — the topic produced unusable text (very rare;
  e.g. numeric claims without sources). Reword the topic or set content
  restrictions; tap Retry.

### COLLECTING_ASSETS
- `No footage could be collected or generated` — FFmpeg is missing
  (System health → ffmpeg ❌). Install FFmpeg or `pip install
  imageio-ffmpeg`; the app bootstraps PATH shims automatically.
- Stock download failures are non-fatal: the pipeline falls back to local
  motion graphics and records why in warnings.

### GENERATING_VOICE
- `Narration FAILED … No TTS engine available` — install `espeakng-loader`
  (pip) or configure Piper (`OM_PIPER_MODEL`), **or** upload a narration
  audio file on the Create form. The job can also complete without
  narration (with an explicit warning — it is never faked).
- Piper errors — verify the voice model path is the `.onnx` file and the
  matching `.onnx.json` sits next to it.

### CREATING_CAPTIONS
- `SRT generation failed` — disk full or permissions; check Storage.
- Timing looks off — caption timing is *estimated-proportional* (no ASR
  model). Word timings are approximate; adjust narration pacing or upload
  audio and re-render.

### RENDERING
- `Final mux failed` — read the ffmpeg tail in the log. Common causes:
  out-of disk, zero-byte input clips (retry), or exotic caption text
  (report it).
- Renders slow? Set `OM_RENDER_SCALE=0.5` (720p-class) or shorter duration.

### QUALITY_CHECK
- `Quality check failed: …` — the QC report on the job page names each
  failed check (`duration_within_tolerance`, `audio_present`,
  `captions_present`, …). The job is intentionally **not** marked completed.
  Fix the cause and Retry.

## Dashboard issues

- **401 authentication required** — sign in via 🔐 with `OM_STUDIO_TOKEN`.
- **403 missing CSRF header** — use the app's own buttons (its requests
  carry the required header); direct curl POSTs need `X-Requested-With: 1`.
- **429 rate limit exceeded** — throttle is per-IP (default 120 req/min;
  job creation 6/min). Wait a minute; raise `OM_RATE_LIMIT_PER_MINUTE` for
  trusted networks.
- **Videos vanish after redeploy** — your host has an ephemeral disk. Set
  `OM_STUDIO_DATA_DIR` to a persistent mount and/or download MP4s promptly
  (the Storage page shows a `persistence_warning` when detected).

## Provider issues

- Pexels/Pixabay `unconfigured` — that is *normal* without keys; local
  motion footage carries the free workflow. Add keys for real stock.
- Paid provider shows `PAID` + disabled — expected. Enabling is a conscious
  act and shows a cost warning.
- Health check fails with network errors — the host cannot reach that
  provider's domain (firewall/allowlist). The core workflow does not need
  them.

## Environment quick reference

| Symptom | Check |
|---|---|
| ffmpeg ❌ in health | `pip install imageio-ffmpeg` or install ffmpeg; `OM_FFMPEG_PATH` override exists |
| ffprobe ❌ in health | install ffmpeg package or copy a static `ffprobe` to `<data>/bin/` |
| espeak TTS ❌ | `pip install espeakng-loader` |
| worker 🔴 | restart `python -m studio`; only one process should own the DB |
| open-mode warning | set `OM_STUDIO_TOKEN` |

## Getting help

Open an issue on the repository with: the job ID, the failing `error_stage`,
the production log tail, and your System health screen (no secrets — the UI
masks them).
