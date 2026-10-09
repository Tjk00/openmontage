# Costs & External Limits

> Written 2026-10-09. Free tiers change without notice — **verify current
> terms on each provider's site before relying on any number below.** The
> design rule of this project: *the complete normal workflow must cost $0,
> and nothing may spend money silently.*

## 1. The free workflow — $0

Everything in the standard pipeline runs with **no API keys and no paid
services**:

| Stage | Engine used | Cost | Limits |
|---|---|---|---|
| Research | Public RSS (Google News RSS) + user feeds | $0 | Network only; results cached (default 6 h) and throttled (≥2 s/host). Google News RSS is public but undocumented — it can change or rate-limit you |
| Script / storyboard | Local template engine (optional local LLM) | $0 | CPU only. An optional OpenAI-compatible endpoint (e.g. **local Ollama**) can be configured — still $0 if local |
| Footage | Local motion generator (FFmpeg) or free stock APIs | $0 | Local: unlimited (CPU-bound). Stock: see below |
| Narration | espeak-ng (bundled) or Piper (local) | $0 | CPU only. Voice quality: espeak-ng is robotic-but-clear; Piper is better (one-time ~60 MB model download, free licenses vary per voice) |
| Captions | Local timing + SRT + Pillow burn-in | $0 | CPU only. Timing is *estimated-proportional* (no ASR model download) |
| Music | Locally synthesized ambient bed | $0 | CPU only |
| Render + QC | FFmpeg / FFprobe | $0 | CPU-bound. Expect roughly 1–5 min for a 30 s video at full res on a modest VM; `OM_RENDER_SCALE=0.5` cuts this ~4× |
| Dashboard + jobs | FastAPI + SQLite | $0 | Depends on your host |

## 2. Optional free providers (free keys — never required)

| Provider | What it adds | Free allowance (verify!) | License notes |
|---|---|---|---|
| **Pexels** (free key) | Real stock footage | ~200 requests/hour, ~20,000/month by default ([pexels.com/api](https://www.pexels.com/api/), [overview](https://freeapihub.com/apis/pexels-api)) | Pexels License: free commercial use, no attribution required (linkback appreciated per API guidelines) |
| **Pixabay** (free key) | Real stock footage | Rate-limited; published limits vary ([pixabay.com/api/docs](https://pixabay.com/api/docs/)) | Pixabay Content License: free use incl. commercial; some restrictions (no standalone redistribution) |
| **Wikimedia Commons** (no key) | Freely licensed / PD media | Public API, be considerate with rate | **Per-file license** — always check the recorded attribution metadata |
| **Local Ollama** (no key) | Better scripts | Your own hardware | Model licenses vary (most popular ones are Apache/MIT) |

## 3. Optional paid providers (disabled by default — never used silently)

| Provider | Used for | Pricing model | Guardrails in this app |
|---|---|---|---|
| ElevenLabs | Premium TTS | Paid after trial credits | Provider card shows PAID; disabled until you set key **and** enable it; free workflow never calls it |
| OpenAI (Sora / TTS) | Cloud video/speech | Usage-based, prepaid | Same guardrails |
| fal.ai (Kling/Wan/etc.) | Cloud AI video | Usage-based | Same guardrails |
| Any hosted LLM API | Script polish | Usage-based | Only if `OM_LLM_BASE_URL` points at a paid endpoint — the template engine works without it |

**Rule enforced in code:** paid providers appear with `enabled: false` and
are only used when explicitly enabled. Enabling returns an on-screen cost
warning. Budget governance for upstream tools lives in
`tools/cost_tracker.py` + `config.yaml` (`budget.mode: cap`).

## 4. Hosting limits (as of 2026-10 — verify!)

| Service | Free tier (reported) | Fits this app? |
|---|---|---|
| **Cloudflare Pages** | 500 builds/month, unlimited static requests, 20k files, 25 MB/file ([docs](https://developers.cloudflare.com/pages/platform/limits/), [summary](https://temps.sh/blog/cloudflare-pages-free-tier-limits-2026)) | ✅ for the static SPA only |
| **Cloudflare Workers** | ~100k requests/day, ms-scale CPU ([summary](https://eastondev.com/blog/en/posts/dev/20260526-cloudflare-free-limits/)) | ❌ **cannot run FFmpeg** — proxy/routing only |
| **Cloudflare R2** | ~10 GB storage free (reported) | Possible media store; not wired by default |
| **GitHub Actions** | Monthly minute quota (public repos: generous); artifacts expire | ✅ for scheduled/batch renders with prompt artifact download |
| Free Python PaaS tiers | Varies; many sleep idle apps and wipe disk | ⚠️ works, but **download MP4s promptly**; the app warns on ephemeral storage |
| Local machine / old laptop | Unlimited | ✅ best quality — see `docs/FREE_DEPLOYMENT.md` Option 3 |

There is **no** free host that offers unlimited free AI generation or
unlimited rendering. Anyone claiming that is selling something.

## 5. Resource costs to expect

- **Disk:** ~1–5 MB per finished minute of 1080p H.264 + project workspace
  (clips, audio, caption PNGs) ≈ 20–80 MB per project. Default storage
  limit 2 GB (`OM_STORAGE_LIMIT_MB`), retention configurable
  (`OM_RETENTION_DAYS`, 0 = keep forever).
- **CPU/RAM:** renders are CPU-bound; ~512 MB RAM is enough for 720p-class
  output; 1 GB+ recommended for 1080p.
- **Network:** research + optional stock downloads only; the render itself
  is fully local.

## 6. How to avoid unexpected charges

1. Leave all API keys empty. The free workflow is complete without them.
2. If you add a Pexels/Pixabay key: these are free — monitor their dashboards.
3. Never enable paid providers in Settings unless you intend to pay; the UI
   warns at enable time.
4. Set `budget.mode: cap` in `config.yaml` if you use upstream paid tools.
5. Hosts: never attach a credit card to "free" tiers that require one as a
   fallback — prefer cardless free tiers or local hosting.

## 7. References

- Pexels API pricing/limits: https://www.pexels.com/api/ (key ≈ 200 req/h, 20k/mo as published 2026-10)
- Pixabay API docs: https://pixabay.com/api/docs/
- Cloudflare Pages limits: https://developers.cloudflare.com/pages/platform/limits/
- Cloudflare Workers limits: https://developers.cloudflare.com/workers/platform/limits/
- GitHub Actions billing: https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-actions/about-billing-for-github-actions
