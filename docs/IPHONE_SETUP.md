# iPhone Setup — Run OpenMontage AI Studio from Your Phone

> Everything in this guide can be done from Safari on an iPhone. No PC is
> required for account/deploy steps. (Video *rendering* needs a computer
> somewhere — a free cloud host or any old machine; see
> `docs/FREE_DEPLOYMENT.md`.)

## 1. Create a video (daily workflow)

1. Open your Studio URL in Safari (e.g. `https://studio.example.com` or
   `http://<home-computer-ip>:8080` on your Wi-Fi).
2. **Add to Home Screen**: Safari Share button → *Add to Home Screen* —
   full-screen app-like experience (the UI is built for it: big tap
   targets, dark theme, safe-area insets).
3. Tap **Create** → enter any topic in plain English → pick duration
   (15/30/45/60/90 s), format (9:16 / 16:9 / 1:1), style, captions,
   music → **Start production**.
4. Watch stages light up live on the job page (research → script →
   assets → voice → captions → render → QC). The page auto-refreshes.
5. When status is **COMPLETED**, tap **⬇️ Download MP4** — Safari saves it
   to Files; long-press the video preview to save to Photos.
6. Failed job? Open the job → read the production log → tap **Retry**.

### Optional: upload your own narration
On the Create form, choose an audio file (`.wav`/`.mp3`/`.m4a`). Used when
you prefer your own voice over the built-in TTS.

## 2. Deploy the app itself (one-time)

### Path A — host on a free Python PaaS (cardless where possible)
1. **Fork the repo** in Safari: open GitHub → *Fork*.
2. Open your chosen host's dashboard in Safari → *New app from GitHub* →
   pick your fork.
3. Set environment variables in their dashboard (see the list in
   `docs/FREE_DEPLOYMENT.md` — the important ones: `OM_STUDIO_TOKEN`,
   `OM_STUDIO_SESSION_SECRET`, `OM_STUDIO_DATA_DIR` on a persistent path).
4. Start command: `pip install -r requirements.txt && python -m studio`
5. Open the app's URL in Safari and sign in with your token.

### Path B — static frontend on Cloudflare Pages
1. dash.cloudflare.com → *Pages* → *Create project* → *Upload assets*
   (upload the `studio/static/` folder as a zip) — drag-and-drop works in
   Safari.
2. Remember: Pages hosts the UI only; the API/render worker must run
   elsewhere (`docs/FREE_DEPLOYMENT.md` Option 2).

### Path C — render on your own always-on machine
Any old computer at home running `python -m studio`; reach it from your
phone over Wi-Fi, or put a free tunnel (Cloudflare Tunnel / Tailscale) in
front. Best quality and zero hosting cost.

## 3. Settings you may want

- **Provider settings** (bottom nav → Providers): enable Pexels/Pixabay with
  free keys for real stock footage; health-check buttons verify each
  provider; secrets are masked.
- **Storage settings** (More → Storage): usage, retention rules, cleanup.
- **System health** (More → Health): ffmpeg/tts/worker/database checks.
- **Deployment diagnostics** (More → Deployment): auth + persistence
  posture before you share the URL.

## 4. Sign in

If `OM_STUDIO_TOKEN` is set, tap 🔐 in the header → enter the token once;
a signed cookie keeps you signed in (12 h default). Signing out is in the
same dialog.

## 5. Tips for iOS Safari

- Large jobs: keep the tab open while rendering; the job page polls every
  3 s and survives reloads (all state is server-side).
- If downloads open in a preview tab: long-press → *Share* → *Save to Files*.
- Low-power mode slows polling perception but jobs keep running on the
  server — you can close the tab and come back.

## 6. What you need accounts for (all free)

| Account | Why | Needed? |
|---|---|---|
| GitHub | Host/track the code | Yes (for deploy paths) |
| Cloudflare (optional) | Pages/Tunnel | No |
| Pexels / Pixabay (optional) | Real stock footage keys | No |
| Any paid service | — | **Never required** |
