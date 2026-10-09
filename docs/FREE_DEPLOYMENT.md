# Free Deployment Guide

> Goal: run OpenMontage AI Studio for **$0**. Paid options are described only
> as optional extras. Nothing here enables billing automatically. Free-tier
> quotas change frequently — verify current terms before you rely on them;
> see `docs/COST_AND_LIMITS.md` for the honest limits list.

## Architecture to deploy

```
A. Static frontend  → any static host (Cloudflare Pages works; the SPA is
                       plain HTML/CSS/JS served by FastAPI too)
B. Lightweight API  → this FastAPI app (auth, jobs, research, downloads)
C. Rendering worker → SAME Python process by default (background thread).
                       FFmpeg MUST run here — Cloudflare Workers cannot.
D. Durable queue    → SQLite file on persistent storage (upgrade path:
                       swap Database for Postgres/Redis later without
                       changing pipeline code)
E. Media storage    → local directory (adapter boundary:
                       studio/pipeline/storage.py)
```

**Do NOT try to run FFmpeg in Cloudflare Workers.** Workers have no
subprocess support and no persistent disk. The dashboard *can* be hosted on
Cloudflare Pages with the API pointed at a Python host (see "Split deploy"
below), but the renderer must be a real Python environment.

## Option 1 — Everything on one free Python host (simplest)

Any host that gives you Python 3.10+, a shell, and persistent disk:

1. Push this repo to **your** GitHub account.
2. Create a new app from the repo on a free Python-capable host (e.g. a free
   tier of a PaaS that supports long-running processes + FFmpeg install, or
   a free Linux VM/old laptop — see Option 3).
3. Set environment variables (use the provider's dashboard):

```
OM_STUDIO_TOKEN=<long random string>       # REQUIRED for public hosts
OM_STUDIO_SESSION_SECRET=<long random>
OM_STUDIO_DATA_DIR=/data/openmontage       # MUST be a persistent path
OM_RENDER_SCALE=0.5                        # optional: faster renders
```

4. Start command: `pip install -r requirements.txt && python -m studio`
5. FFmpeg: either `apt/apk add ffmpeg` in the build step, or rely on
   `imageio-ffmpeg` (bundled ffmpeg). For FFprobe, add `apt add ffmpeg` or
   copy a static `ffprobe` into `OM_STUDIO_DATA_DIR/bin/` — the app
   bootstraps PATH shims automatically (`studio/ffmpeg_env.py`).

**Honest limits:** free PaaS tiers usually sleep idle apps, cap CPU/RAM,
and often have **ephemeral disks** (projects vanish on redeploy). The app
detects ephemeral data dirs and shows a warning on `/storage` and
`/api/diagnostics`. Always download finished MP4s promptly.

## Option 2 — Split deploy (Cloudflare Pages + Python API)

1. **Cloudflare Pages** (free): the SPA in `studio/static/` is static.
   Deploy that folder as a Pages project (drag-and-drop in the dashboard
   works from an iPhone).
2. **Python API + worker** on any free Python host (Option 1's steps).
3. In `studio/static/app.js` the API base is same-origin; for a split
   deploy, put the API behind a Cloudflare Worker route that proxies to the
   Python host, or serve the SPA from the Python host (simplest: just use
   Option 1 and skip Pages entirely — the FastAPI app already serves the
   frontend at `/`).

**Cloudflare Workers** may be used for *routing/proxying* only. Never for
rendering. Workers free tier: verify current request limits at
developers.cloudflare.com.

## Option 3 — Zero-cost local rendering (recommended quality)

If you have ANY computer that stays on (home PC, old laptop, Raspberry Pi 4+,
a friend's spare machine):

```bash
git clone https://github.com/YOUR-NAME/openmontage.git
cd openmontage
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
sudo apt install ffmpeg          # or brew install ffmpeg
export OM_STUDIO_TOKEN=...       # if exposing beyond localhost
python -m studio --host 0.0.0.0 --port 8080
```

Open `http://<machine-ip>:8080` from your iPhone on the same Wi-Fi. This
runs the full pipeline offline (research needs internet; everything else is
local and free). **No hosting bills, no usage caps, no cold starts.**

Zero-cost tunneling options to reach it from outside your Wi-Fi exist
(Cloudflare Tunnel free tier, Tailscale free for personal use) — both keep
the render local; verify their current terms.

## Option 4 — GitHub Actions as a render runner (advanced, still free*)

You can trigger renders with a workflow that runs `python -m studio`'s
worker in a job and uploads the MP4 as an artifact. GitHub free accounts
include Actions minutes for public repos. *Limits: minutes quota, ephemeral
disk (download artifacts promptly), not an interactive dashboard host.*
A starter sketch:

```yaml
name: render
on: [workflow_dispatch]
jobs:
  render:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r requirements.txt && sudo apt-get install -y ffmpeg
      - run: python scripts/studio_render_once.py   # thin CLI wrapper around the worker
      - uses: actions/upload-artifact@v4
        with: { name: video, path: studio_data/projects/*/renders/final.mp4 }
```

## Split of responsibilities (final checklist)

| Component | Where it can run free | Notes |
|---|---|---|
| SPA frontend | Cloudflare Pages / same Python host | No build step |
| Job API + worker | Any Python host / local machine | Needs ≥512 MB RAM |
| FFmpeg rendering | Local machine / VM with CPU | NOT on Workers/Pages |
| SQLite job state | Persistent disk | Warns on ephemeral disks |
| Media files | Persistent disk or download | Retention rules configurable |

## Security before going public

1. Set `OM_STUDIO_TOKEN` (the app refuses to be called "ready" without it —
   `/api/diagnostics` flags open mode).
2. Keep `.env` out of Git (already in `.gitignore`).
3. Put HTTPS in front (any reverse proxy / tunnel provides it).
4. Review `docs/ARCHITECTURE.md` security notes; the API enforces auth,
   CSRF header on mutations, rate limits, and safe file paths.

## Deployment from an iPhone only

See `docs/IPHONE_SETUP.md` — everything above can be done in Safari through
GitHub + host dashboards; no PC required for the deploy steps (rendering
still needs *some* computer somewhere, which can be the free host itself).
