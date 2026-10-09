/* OpenMontage AI Studio — SPA client (vanilla JS, no build step, iPhone-first). */
"use strict";

const $view = () => document.getElementById("view");
const STAGES = ["QUEUED","RESEARCHING","SCRIPTING","COLLECTING_ASSETS","GENERATING_VOICE",
  "CREATING_CAPTIONS","RENDERING","QUALITY_CHECK","COMPLETED","FAILED","CANCELLED"];

/* ---------------- API client ---------------- */
async function api(path, opts = {}) {
  const headers = Object.assign({ "X-Requested-With": "fetch" }, opts.headers || {});
  if (opts.body && !(opts.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, Object.assign({}, opts, { headers }));
  let data = null;
  try { data = await res.json(); } catch (e) { data = { error: "invalid server response" }; }
  if (!res.ok) {
    const err = new Error(data.error || `HTTP ${res.status}`);
    err.status = res.status; err.data = data;
    throw err;
  }
  return data;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
}
function fmtTime(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString([], { month:"short", day:"numeric", hour:"2-digit", minute:"2-digit" }); }
  catch (e) { return iso; }
}
function statusPill(status) {
  const map = {
    COMPLETED: "ok", FAILED: "err", CANCELLED: "neutral",
    QUEUED: "info", RUNNING: "warn",
    RESEARCHING: "warn", SCRIPTING: "warn", COLLECTING_ASSETS: "warn",
    GENERATING_VOICE: "warn", CREATING_CAPTIONS: "warn", RENDERING: "warn", QUALITY_CHECK: "warn",
    ok: "ok", unavailable: "err", partial: "warn", unknown: "neutral",
  };
  return `<span class="pill ${map[status] || "neutral"}">${esc(status)}</span>`;
}
function loading(label) {
  return `<div class="loading-row"><div class="spinner"></div><div>${esc(label || "Loading…")}</div></div>`;
}
function notice(kind, html) { return `<div class="notice ${kind}">${html}</div>`; }

/* ---------------- modal ---------------- */
function openModal(title, html) {
  document.getElementById("modal-title").textContent = title;
  document.getElementById("modal-body").innerHTML = html;
  document.getElementById("modal").classList.add("open");
}
document.getElementById("modal-close").addEventListener("click", () =>
  document.getElementById("modal").classList.remove("open"));
document.getElementById("modal").addEventListener("click", (e) => {
  if (e.target.id === "modal") e.target.classList.remove("open");
});

/* ---------------- router ---------------- */
const routes = {};
let currentCleanup = null;

function on(route, fn) { routes[route] = fn; }

function navigate(hash) {
  if (location.hash !== hash) location.hash = hash;
  else render();
}

window.addEventListener("hashchange", render);

async function render() {
  if (typeof currentCleanup === "function") { try { currentCleanup(); } catch (e) {} currentCleanup = null; }
  const raw = (location.hash || "#/home").replace(/^#\/?/, "");
  const [route, ...rest] = raw.split("/");
  const param = rest.join("/");
  document.querySelectorAll(".nav-item").forEach(b =>
    b.classList.toggle("active", b.dataset.route === route ||
      (route === "job" && b.dataset.route === "queue") ||
      (["storage","health","deployment","help","more"].includes(route) && b.dataset.route === "more")));
  $view().innerHTML = loading();
  try {
    const fn = routes[route] || routes.home;
    await fn(param);
  } catch (err) {
    $view().innerHTML = notice("err", `<b>Something went wrong:</b> ${esc(err.message)}`);
  }
  window.scrollTo({ top: 0 });
}

document.querySelectorAll(".nav-item").forEach(b =>
  b.addEventListener("click", () => navigate("#/" + b.dataset.route)));
document.getElementById("btn-health").addEventListener("click", () => navigate("#/health"));
document.getElementById("btn-account").addEventListener("click", showAccount);

async function showAccount() {
  let st = { auth_enabled: false };
  try { st = await api("/api/auth/status"); } catch (e) {}
  const form = st.auth_enabled
    ? `<label class="field"><span>Admin token</span>
         <input type="password" id="login-token" autocomplete="current-password" placeholder="OM_STUDIO_TOKEN"></label>
       <button class="btn btn-primary" id="login-btn">Sign in</button>
       <button class="btn btn-secondary" id="logout-btn" style="margin-top:10px">Sign out</button>`
    : notice("warn", "Auth is disabled (open local mode). Set <code>OM_STUDIO_TOKEN</code> and restart to require sign-in.");
  openModal("Session", `<p class="muted small">Admin authentication for private deployment.</p>${form}`);
  const btn = document.getElementById("login-btn");
  if (btn) btn.addEventListener("click", async () => {
    try {
      await api("/api/auth/login", { method: "POST", body: { token: document.getElementById("login-token").value } });
      openModal("Session", notice("ok", "Signed in."));
    } catch (e) { openModal("Session", notice("err", esc(e.message))); }
  });
  const lo = document.getElementById("logout-btn");
  if (lo) lo.addEventListener("click", async () => {
    await api("/api/auth/logout", { method: "POST", body: {} });
    openModal("Session", notice("info", "Signed out."));
  });
}

/* ======================================================================
   VIEW: Home dashboard
====================================================================== */
on("home", async () => {
  const [stats, health, jobs] = await Promise.all([
    api("/api/stats"), api("/api/health").catch(() => ({ status: "unreachable" })),
    api("/api/jobs?limit=5"),
  ]);
  const by = stats.jobs_by_status || {};
  const active = (by.RUNNING || 0) + (by.QUEUED || 0);
  $view().innerHTML = `
    <div class="view-title"><h1>Dashboard</h1><span class="sub">real production stats</span></div>
    ${stats.auth_enabled === false ? notice("warn", "⚠️ Instance is <b>open</b> (no OM_STUDIO_TOKEN). Fine on localhost; set a token before any public deployment.") : ""}
    ${health.status !== "ok" ? notice("err", "Backend unreachable — start the server with <code>python -m studio</code>.") : ""}
    <div class="grid cols-3">
      <div class="stat"><div class="num">${active}</div><div class="lbl">Active jobs</div></div>
      <div class="stat"><div class="num">${by.COMPLETED || 0}</div><div class="lbl">Completed</div></div>
      <div class="stat"><div class="num">${by.FAILED || 0}</div><div class="lbl">Failed</div></div>
      <div class="stat"><div class="num">${stats.projects || 0}</div><div class="lbl">Projects</div></div>
      <div class="stat"><div class="num">${stats.worker_alive ? "🟢" : "🔴"}</div><div class="lbl">Worker</div></div>
      <div class="stat"><div class="num">${by.CANCELLED || 0}</div><div class="lbl">Cancelled</div></div>
    </div>
    <div class="card" style="margin-top:14px">
      <h2>🚀 Start a production</h2>
      <p class="muted small">Describe any topic — research, script, footage, narration, captions and a finished MP4 are produced automatically.</p>
      <button class="btn btn-primary" id="go-create">Create a video</button>
    </div>
    <div class="card">
      <h2>🕘 Recent jobs</h2>
      <div class="list">${jobs.jobs.length ? jobs.jobs.map(jobRow).join("") :
        `<p class="muted small">No jobs yet — your first production will appear here.</p>`}</div>
    </div>`;
  document.getElementById("go-create").addEventListener("click", () => navigate("#/create"));
  bindJobRows();
});

function jobRow(j) {
  return `<button class="list-item" data-job="${esc(j.id)}">
    <div class="grow">
      <div class="title">${esc(j.request?.topic || j.id)}</div>
      <div class="sub">${esc(j.stage)} · ${j.progress ?? 0}% · ${fmtTime(j.created_at)}</div>
    </div>
    ${statusPill(j.status)}
  </button>`;
}
function bindJobRows() {
  document.querySelectorAll("[data-job]").forEach(el =>
    el.addEventListener("click", () => navigate("#/job/" + el.dataset.job)));
}

/* ======================================================================
   VIEW: Create video
====================================================================== */
on("create", async (param) => {
  const angle = sessionStorage.getItem("selectedAngle") || "";
  sessionStorage.removeItem("selectedAngle");
  $view().innerHTML = `
    <div class="view-title"><h1>Create video</h1><span class="sub">universal topic input</span></div>
    <div class="card">
      <form id="create-form" novalidate>
        <label class="field"><span>Topic or research request *</span>
          <textarea id="f-topic" maxlength="500" required
            placeholder="e.g. How coral reefs protect coastlines — or any topic in plain English">${esc(angle)}</textarea>
          <div class="help-text">Any reasonable topic. Nothing is hardcoded — free-form text works.</div>
        </label>
        <div class="grid cols-2">
          <label class="field"><span>Target audience</span>
            <input type="text" id="f-audience" value="general viewers" maxlength="200"></label>
          <label class="field"><span>Target platform</span>
            <select id="f-platform">
              <option value="tiktok">TikTok</option><option value="youtube">YouTube Shorts</option>
              <option value="instagram">Instagram Reels</option><option value="x">X</option>
              <option value="linkedin">LinkedIn</option><option value="facebook">Facebook</option>
              <option value="other">Other</option>
            </select></label>
        </div>
        <label class="field"><span>Video duration</span>
          <select id="f-duration">
            <option value="15">15 seconds</option><option value="30" selected>30 seconds</option>
            <option value="45">45 seconds</option><option value="60">60 seconds</option>
            <option value="90">90 seconds</option>
          </select>
          <div class="help-text">Rendered duration is validated against the request in QC.</div>
        </label>
        <div class="grid cols-2">
          <label class="field"><span>Video language</span>
            <select id="f-language">
              <option value="en" selected>English</option><option value="en-GB">English (UK)</option>
              <option value="es">Spanish</option><option value="fr">French</option><option value="de">German</option>
              <option value="it">Italian</option><option value="pt">Portuguese</option><option value="nl">Dutch</option>
              <option value="pl">Polish</option><option value="ru">Russian</option><option value="zh">Chinese</option>
            </select></label>
          <label class="field"><span>Preferred voice</span>
            <select id="f-voice">
              <option value="en-us" selected>en-us (default)</option><option value="en-gb">en-gb</option>
              <option value="de">de</option><option value="fr">fr</option><option value="es">es</option>
              <option value="it">it</option><option value="pt">pt</option><option value="ru">ru</option>
              <option value="zh">zh</option>
            </select>
            <div class="help-text">Voice availability depends on the installed TTS engine.</div>
          </label>
        </div>
        <label class="field"><span>Content style</span>
          <select id="f-style">
            <option value="documentary">Documentary</option>
            <option value="educational">Educational explainer</option>
            <option value="motivation">Motivation</option>
            <option value="news">News analysis</option>
            <option value="technology">Technology</option>
            <option value="finance">Finance &amp; crypto</option>
            <option value="business">Business</option>
            <option value="nature">Animals &amp; nature</option>
            <option value="health">Health education</option>
            <option value="history">History</option>
            <option value="storytelling">Storytelling</option>
            <option value="product">Product explainer</option>
            <option value="custom" selected>Custom</option>
          </select>
          <div class="help-text">A starting point — every topic is accepted regardless of style.</div>
        </label>
        <label class="field"><span>Video format</span>
          <select id="f-aspect">
            <option value="9:16" selected>9:16 vertical (TikTok / Reels / Shorts)</option>
            <option value="16:9">16:9 landscape (YouTube)</option>
            <option value="1:1">1:1 square (feed posts)</option>
          </select></label>
        <div class="grid cols-2">
          <label class="field"><span>Research depth</span>
            <select id="f-depth">
              <option value="quick">Quick</option>
              <option value="standard" selected>Standard</option>
              <option value="deep">Deep</option>
            </select></label>
          <label class="field"><span>Footage preference</span>
            <select id="f-footage">
              <option value="auto" selected>Auto (stock → local motion)</option>
              <option value="stock">Stock footage</option>
              <option value="open">Openly licensed only</option>
              <option value="local">Local motion graphics</option>
            </select></label>
        </div>
        <div class="grid cols-2">
          <label class="field"><span>Captions</span>
            <select id="f-captions">
              <option value="burned" selected>Burned-in + SRT</option>
              <option value="srt-only">SRT file only</option>
              <option value="none">No captions</option>
            </select></label>
          <label class="field"><span>Background music</span>
            <select id="f-music">
              <option value="ambient" selected>Ambient (locally synthesized)</option>
              <option value="none">No music</option>
              <option value="upload">Use uploaded track</option>
            </select></label>
        </div>
        <label class="field"><span>Reference URLs (optional)</span>
          <input type="url" id="f-refs" placeholder="https://… (comma-separated, optional)">
          <div class="help-text">RSS/feed URLs are used as research sources. Other URLs are recorded as references.</div>
        </label>
        <label class="field"><span>Content restrictions (optional)</span>
          <input type="text" id="f-restrictions" maxlength="1000" placeholder="e.g. no speculation, keep it child-friendly"></label>
        <label class="field"><span>Narration audio upload (optional fallback)</span>
          <input type="file" id="f-audio" accept="audio/*">
          <div class="help-text">If local TTS is unavailable you can upload your own narration (.wav/.mp3).</div>
        </label>
        <div id="create-error"></div>
        <button type="submit" class="btn btn-primary" id="create-submit">🎬 Start production</button>
        <p class="help-text" style="margin-top:10px">Validation runs before anything is queued. Duplicate submissions return the existing job.</p>
      </form>
    </div>`;
  document.getElementById("create-form").addEventListener("submit", submitCreate);
});

async function submitCreate(ev) {
  ev.preventDefault();
  const errBox = document.getElementById("create-error");
  const btn = document.getElementById("create-submit");
  errBox.innerHTML = "";
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner" style="width:18px;height:18px;border-width:2px"></span> Validating…`;
  try {
    let narration_upload_id = null;
    const fileInput = document.getElementById("f-audio");
    if (fileInput.files && fileInput.files.length) {
      const fd = new FormData();
      fd.append("file", fileInput.files[0]);
      const up = await api("/api/uploads/audio", { method: "POST", body: fd });
      narration_upload_id = up.upload_id;
    }
    const body = {
      topic: document.getElementById("f-topic").value,
      audience: document.getElementById("f-audience").value,
      platform: document.getElementById("f-platform").value,
      duration_seconds: parseInt(document.getElementById("f-duration").value, 10),
      language: document.getElementById("f-language").value,
      voice: document.getElementById("f-voice").value,
      style: document.getElementById("f-style").value,
      aspect: document.getElementById("f-aspect").value,
      research_depth: document.getElementById("f-depth").value,
      footage_preference: document.getElementById("f-footage").value,
      caption_preference: document.getElementById("f-captions").value,
      music_preference: document.getElementById("f-music").value,
      reference_urls: document.getElementById("f-refs").value.split(",").map(s => s.trim()).filter(Boolean),
      restrictions: document.getElementById("f-restrictions").value,
      narration_upload_id,
    };
    const res = await api("/api/jobs", { method: "POST", body });
    navigate("#/job/" + res.job_id);
  } catch (err) {
    let detail = "";
    if (err.data && err.data.details) {
      detail = "<ul class='small'>" + err.data.details.map(d =>
        `<li>${esc((d.loc || []).join("."))}: ${esc(d.msg)}</li>`).join("") + "</ul>";
    }
    errBox.innerHTML = notice("err", `<b>Request rejected:</b> ${esc(err.message)}${detail}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "🎬 Start production";
  }
}

/* ======================================================================
   VIEW: Trend research
====================================================================== */
on("research", async () => {
  const recent = await api("/api/research/recent").catch(() => ({ runs: [] }));
  $view().innerHTML = `
    <div class="view-title"><h1>Trend research</h1><span class="sub">public sources, no paid APIs</span></div>
    <div class="card">
      <form id="research-form">
        <label class="field"><span>Research query *</span>
          <input type="text" id="r-query" maxlength="300" required placeholder="e.g. solid-state batteries"></label>
        <label class="field"><span>Depth</span>
          <select id="r-depth"><option>quick</option><option selected>standard</option><option>deep</option></select></label>
        <button class="btn btn-primary" type="submit">🔎 Run research</button>
      </form>
    </div>
    <div id="research-result"></div>
    <div class="card">
      <h2>Recent runs</h2>
      <div class="list">${recent.runs.length ? recent.runs.map(r =>
        `<div class="list-item"><div class="grow"><div class="title">${esc(r.query)}</div>
         <div class="sub">${fmtTime(r.created_at)}</div></div>${statusPill(r.status)}</div>`).join("")
        : `<p class="muted small">No research runs yet.</p>`}</div>
    </div>`;
  document.getElementById("research-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const box = document.getElementById("research-result");
    box.innerHTML = `<div class="card">${loading("Searching public sources…")}</div>`;
    try {
      const res = await api("/api/research", {
        method: "POST",
        body: { query: document.getElementById("r-query").value, depth: document.getElementById("r-depth").value },
      });
      box.innerHTML = researchCard(res.result);
      bindAngleButtons();
    } catch (err) {
      box.innerHTML = `<div class="card">${notice("err", esc(err.message))}</div>`;
    }
  });
});

function researchCard(r) {
  const src = r.sources.map(s => `
    <div class="list-item" style="cursor:default">
      <div class="grow"><div class="title">${esc(s.title)}</div>
        <div class="sub">${esc(s.published_iso || s.published || "date n/a")}</div>
        <div class="small"><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.url).slice(0, 60)}…</a></div>
      </div>
    </div>`).join("");
  const findings = r.findings.map(f => `
    <div class="list-item" style="cursor:default;flex-direction:column;align-items:flex-start">
      <div>${f.claim_type === "sourced_statement" ? "📎" : "💭"} ${esc(f.statement)}</div>
      <div class="small muted">${f.claim_type === "sourced_statement" ? "sourced statement" : "opinion / prediction"} —
        <a href="${esc(f.source_url)}" target="_blank" rel="noopener noreferrer">source</a></div>
    </div>`).join("");
  const angles = r.angles.map(a => `
    <button class="list-item" data-angle="${esc(a.title)}">
      <div class="grow"><div class="title">${esc(a.title)}</div>
        <div class="sub">${esc(a.description)}</div>
        <div class="small">Evidence: ${esc(a.evidence_strength)}</div></div>
      <span class="pill info">Use →</span>
    </button>`).join("");
  return `<div class="card">
    <h2>Research result ${statusPill(r.status)} ${r.cached ? '<span class="pill neutral">cached</span>' : ""}</h2>
    ${r.verified ? notice("ok", "Multiple sources found — findings below carry source links. Individual claims still deserve verification.")
      : notice("warn", "⚠️ Trend status is <b>NOT verified</b>. " + esc(r.notes || "Fewer than two sources found."))}
    ${r.errors.length ? notice("err", "Errors: " + esc(r.errors.join("; "))) : ""}
    <h3>Video angles</h3><div class="list">${angles}</div>
    <h3 style="margin-top:14px">Sources (${r.sources.length})</h3><div class="list">${src || '<p class="muted small">No sources retrieved in this environment.</p>'}</div>
    <h3 style="margin-top:14px">Findings</h3><div class="list">${findings || '<p class="muted small">No findings — nothing can be asserted as fact.</p>'}</div>
    ${r.uncertainties.length ? `<h3 style="margin-top:14px">Uncertainties</h3><ul class="small muted">${r.uncertainties.map(u => `<li>${esc(u)}</li>`).join("")}</ul>` : ""}
  </div>`;
}
function bindAngleButtons() {
  document.querySelectorAll("[data-angle]").forEach(b =>
    b.addEventListener("click", () => {
      sessionStorage.setItem("selectedAngle", b.dataset.angle);
      navigate("#/create");
    }));
}

/* ======================================================================
   VIEW: Production queue
====================================================================== */
on("queue", async () => {
  const jobs = await api("/api/jobs?limit=100");
  const groups = {};
  for (const j of jobs.jobs) { (groups[j.status] = groups[j.status] || []).push(j); }
  $view().innerHTML = `
    <div class="view-title"><h1>Production queue</h1><span class="sub">${jobs.jobs.length} jobs</span></div>
    ${["RUNNING","QUEUED","FAILED","COMPLETED","CANCELLED"].map(s =>
      groups[s] ? `<div class="card"><h2>${statusPill(s)} <span class="muted small">${groups[s].length}</span></h2>
        <div class="list">${groups[s].map(jobRow).join("")}</div></div>` : "").join("") ||
      notice("info", "Queue is empty — create a video to get started.")}`;
  bindJobRows();
});

/* ======================================================================
   VIEW: Active production details (job page)
====================================================================== */
on("job", async (jobId) => {
  const job = await api("/api/jobs/" + jobId);
  const logs = await api(`/api/jobs/${jobId}/logs`);
  const stageIdx = STAGES.indexOf(job.stage);
  const rail = STAGES.slice(0, 8).map((s, i) => {
    let cls = "";
    if (job.status === "FAILED" && STAGES[i] === job.error_stage) cls = "failed";
    else if (job.status === "COMPLETED" || i < stageIdx) cls = "done";
    else if (i === stageIdx && job.status === "RUNNING") cls = "current";
    return `<span class="stage-step ${cls}">${s.replaceAll("_", " ")}</span>`;
  }).join("");
  const qc = job.qc ? `<h3>Quality control ${job.qc.passed ? "✅ passed" : "❌ failed"}</h3>
    <div class="list">${job.qc.checks.map(c =>
      `<div class="list-item" style="cursor:default"><div class="grow"><div class="title">${c.passed ? "✅" : "❌"} ${esc(c.name)}</div>
       <div class="sub">${esc(c.detail || "")}</div></div></div>`).join("")}</div>` : "";
  $view().innerHTML = `
    <div class="view-title"><h1>Production</h1>${statusPill(job.status)}</div>
    <div class="card">
      <h2>${esc(job.request?.topic || job.id)}</h2>
      <p class="muted small mono">${esc(job.id)} · project ${esc(job.project_id)} · created ${fmtTime(job.created_at)} · retries ${job.retry_count}</p>
      <div class="stage-rail">${rail}</div>
      <div class="progress"><i style="width:${job.progress || 0}%"></i></div>
      <p class="small muted" style="margin-top:8px">${esc(job.stage)} — ${job.progress || 0}%</p>
      ${job.error ? notice("err", `<b>${esc(job.error_stage || "error")}:</b> ${esc(job.error)}`) : ""}
      <div class="btn-row" style="margin-top:12px">
        ${job.status === "RUNNING" || job.status === "QUEUED"
          ? `<button class="btn btn-danger" id="job-cancel">Cancel</button>` : ""}
        ${job.status === "FAILED"
          ? `<button class="btn btn-primary" id="job-retry">Retry</button>` : ""}
        ${job.status === "COMPLETED"
          ? `<a class="btn btn-ok" href="/api/projects/${esc(job.project_id)}/download/renders/final.mp4">⬇️ Download MP4</a>
             <button class="btn btn-secondary" id="job-qcdetail">QC report</button>` : ""}
      </div>
    </div>
    ${qc}
    <div class="card">
      <h2>📜 Production log</h2>
      <div class="logs" id="log-box">${logs.logs.map(l =>
        `<div class="lvl-${esc(l.level)}">${esc(l.ts)} [${esc(l.level)}] ${esc(l.stage || "-")} · ${esc(l.message)}</div>`).join("") || "No log entries."}</div>
    </div>`;
  const cancel = document.getElementById("job-cancel");
  if (cancel) cancel.addEventListener("click", async () => {
    cancel.disabled = true;
    try { await api(`/api/jobs/${jobId}/cancel`, { method: "POST", body: {} }); render(); }
    catch (e) { cancel.disabled = false; alert(e.message); }
  });
  const retry = document.getElementById("job-retry");
  if (retry) retry.addEventListener("click", async () => {
    retry.disabled = true;
    try { await api(`/api/jobs/${jobId}/retry`, { method: "POST", body: {} }); render(); }
    catch (e) { retry.disabled = false; alert(e.message); }
  });
  const qcd = document.getElementById("job-qcdetail");
  if (qcd) qcd.addEventListener("click", () =>
    openModal("QC report", `<div class="logs">${esc(JSON.stringify(job.qc, null, 2))}</div>`));

  if (job.status === "RUNNING" || job.status === "QUEUED") {
    const t = setTimeout(render, 3000);
    currentCleanup = () => clearTimeout(t);
  }
});

/* ======================================================================
   VIEW: Completed videos
====================================================================== */
on("completed", async () => {
  const jobs = await api("/api/jobs?status=COMPLETED&limit=50");
  $view().innerHTML = `
    <div class="view-title"><h1>Completed videos</h1><span class="sub">download your MP4s</span></div>
    ${jobs.jobs.length ? jobs.jobs.map(j => `
      <div class="card">
        <h2>${esc(j.request?.topic || j.id)}</h2>
        <p class="muted small">${esc(j.request?.aspect || "9:16")} · ${esc(j.request?.duration_seconds || "?")}s · finished ${fmtTime(j.finished_at)}</p>
        <video controls playsinline preload="metadata"
          src="/api/projects/${esc(j.project_id)}/download/renders/final.mp4"></video>
        <div class="btn-row" style="margin-top:10px">
          <a class="btn btn-primary" href="/api/projects/${esc(j.project_id)}/download/renders/final.mp4" download>⬇️ Download MP4</a>
          <a class="btn btn-secondary" href="/api/projects/${esc(j.project_id)}/download/captions.srt">Captions SRT</a>
          <button class="btn btn-secondary" data-job="${esc(j.id)}">Details</button>
        </div>
      </div>`).join("") : notice("info", "No completed videos yet.")}`;
  bindJobRows();
});

/* ======================================================================
   VIEW: Project history
====================================================================== */
on("projects", async () => {
  const data = await api("/api/projects");
  $view().innerHTML = `
    <div class="view-title"><h1>Project history</h1><span class="sub">metadata + media library</span></div>
    <div class="list">
      ${data.projects.map(p => `
        <div class="list-item" style="cursor:default">
          <div class="grow">
            <div class="title">${esc(p.title)}</div>
            <div class="sub">${esc(p.status)} · ${fmtTime(p.created_at)}</div>
            <div class="small muted mono">${esc(p.id)}</div>
          </div>
          <button class="chip" data-proj="${esc(p.id)}">Open</button>
          <button class="chip" data-del="${esc(p.id)}" style="color:var(--err)">Delete</button>
        </div>`).join("") || notice("info", "No projects yet.")}
    </div>`;
  document.querySelectorAll("[data-proj]").forEach(b => b.addEventListener("click", async () => {
    const p = await api("/api/projects/" + b.dataset.proj);
    openModal("Project " + p.id, `
      <p><b>${esc(p.title)}</b></p>
      <p class="small muted">${esc(p.topic)}</p>
      <p class="small">Status: ${statusPill(p.status)} · created ${fmtTime(p.created_at)}</p>
      ${p.output_path ? `<p class="small mono">${esc(p.output_path)}</p>
        <a class="btn btn-primary" href="/api/projects/${esc(p.id)}/download/renders/final.mp4" download>⬇️ Download MP4</a>` : ""}
      ${p.attribution?.length ? `<h3 style="margin-top:12px">Source attribution</h3>
        <div class="logs">${esc(JSON.stringify(p.attribution, null, 2))}</div>` : ""}
      <h3 style="margin-top:12px">Files</h3>
      <div class="logs">${p.files.map(f => `${esc(f.name)} (${(f.size/1024).toFixed(1)} KB)`).join("\n") || "none"}</div>`);
  }));
  document.querySelectorAll("[data-del]").forEach(b => b.addEventListener("click", async () => {
    if (!confirm("Delete this project and all its media? This cannot be undone.")) return;
    try {
      await api("/api/projects/" + b.dataset.del, { method: "DELETE", body: { confirm: true } });
      render();
    } catch (e) { alert(e.message); }
  }));
});

/* ======================================================================
   VIEW: Provider settings
====================================================================== */
on("providers", async () => {
  const data = await api("/api/providers");
  const cat = { rendering: "🎬 Rendering", tts: "🗣 Narration", footage: "🎞 Footage",
    captions: "💬 Captions", music: "🎵 Music", llm: "🧠 LLM (optional)",
    "ai-video": "🤖 AI video (optional/paid)" };
  const groups = {};
  for (const p of data.providers) (groups[p.category] = groups[p.category] || []).push(p);
  $view().innerHTML = `
    <div class="view-title"><h1>Provider settings</h1><span class="sub">free-first, secrets masked</span></div>
    ${notice("info", "Free/local providers run first. <b>Paid providers are disabled by default</b> and are never used silently. Keys are stored in <code>.env</code> on the server — never in the browser, never in Git.")}
    ${Object.entries(groups).map(([k, ps]) => `
      <div class="card"><h2>${cat[k] || esc(k)}</h2>
        ${ps.map(p => `
          <div class="list-item" style="cursor:default;flex-wrap:wrap">
            <div class="grow" style="min-width:200px">
              <div class="title">${esc(p.name)}
                ${p.cost_status === "paid" ? '<span class="pill err">PAID</span>'
                  : p.cost_status === "free-tier" || p.cost_status === "freemium"
                    ? '<span class="pill warn">FREE TIER</span>' : '<span class="pill ok">FREE</span>'}
                ${p.required_for_free_workflow ? '<span class="pill info">core</span>' : ""}
              </div>
              <div class="sub">${esc(p.purpose)}</div>
              <div class="small muted">${esc(p.free_tier_notes)}</div>
              ${p.credentials_required.length ? `<div class="small mono muted">creds: ${esc(p.credentials_required.join(", "))}</div>` : ""}
              ${Object.entries(p.secrets_display || {}).map(([k2, v2]) =>
                `<div class="small mono">${esc(k2)}=${v2 ? esc(v2) : '<i>not set</i>'}</div>`).join("")}
              <div class="small">Health: ${statusPill(p.health_status)} ${esc(p.health_detail)}</div>
              ${p.last_error ? `<div class="small" style="color:var(--err)">Last error: ${esc(p.last_error)}</div>` : ""}
            </div>
            <div style="display:flex;flex-direction:column;gap:8px">
              <button class="chip" data-check="${esc(p.id)}">Health check</button>
              <button class="chip ${p.enabled ? "active" : ""}" data-toggle="${esc(p.id)}" data-enabled="${p.enabled}">
                ${p.enabled ? "Enabled" : "Disabled"}</button>
            </div>
          </div>`).join("")}
      </div>`).join("")}`;
  document.querySelectorAll("[data-check]").forEach(b => b.addEventListener("click", async () => {
    b.textContent = "Checking…";
    try {
      const r = await api(`/api/providers/${b.dataset.check}/check`, { method: "POST", body: {} });
      openModal("Health check", notice(r.ok ? "ok" : "warn", `${esc(r.status)} — ${esc(r.detail || "")}`));
    } catch (e) { openModal("Health check", notice("err", esc(e.message))); }
    b.textContent = "Health check";
  }));
  document.querySelectorAll("[data-toggle]").forEach(b => b.addEventListener("click", async () => {
    const enable = b.dataset.enabled !== "true";
    try {
      const r = await api(`/api/providers/${b.dataset.toggle}/toggle`, { method: "POST", body: { enabled: enable } });
      if (r.warning) alert(r.warning);
      render();
    } catch (e) { alert(e.message); }
  }));
});

/* ======================================================================
   VIEW: Storage settings
====================================================================== */
on("storage", async () => {
  const s = await api("/api/storage");
  $view().innerHTML = `
    <div class="view-title"><h1>Storage settings</h1><span class="sub">project library</span></div>
    ${s.persistence_warning ? notice("warn", esc(s.persistence_warning)) : ""}
    ${s.limit_exceeded ? notice("err", "Storage limit exceeded — delete old projects or raise OM_STORAGE_LIMIT_MB.") : ""}
    <div class="grid cols-2">
      <div class="stat"><div class="num">${s.used_mb} MB</div><div class="lbl">Used</div></div>
      <div class="stat"><div class="num">${s.limit_mb} MB</div><div class="lbl">Configured limit</div></div>
      <div class="stat"><div class="num">${s.retention_days || "∞"}</div><div class="lbl">Retention (days, 0 = keep)</div></div>
      <div class="stat"><div class="num">${s.max_upload_mb} MB</div><div class="lbl">Max upload size</div></div>
    </div>
    <div class="card" style="margin-top:14px">
      <h2>Cleanup</h2>
      <p class="small muted">Retention rules are configured with <code>OM_RETENTION_DAYS</code>. Completed projects are only deleted when the retention rule applies or when you explicitly confirm deletion — never automatically without a rule.</p>
      <button class="btn btn-secondary" id="storage-cleanup">Apply retention rules now</button>
      <div id="cleanup-result"></div>
    </div>
    <div class="card">
      <h2>Paths</h2>
      <p class="mono small">Projects: ${esc(s.projects_dir)}</p>
    </div>`;
  document.getElementById("storage-cleanup").addEventListener("click", async () => {
    const r = await api("/api/storage/cleanup", { method: "POST", body: {} });
    document.getElementById("cleanup-result").innerHTML =
      notice("info", esc(JSON.stringify(r)));
  });
});

/* ======================================================================
   VIEW: System health
====================================================================== */
on("health", async () => {
  const d = await api("/api/diagnostics");
  $view().innerHTML = `
    <div class="view-title"><h1>System health</h1><span class="sub">live diagnostics</span></div>
    <div class="card">
      <p class="small muted">Python ${esc(d.python)} · ${esc(d.platform)}</p>
      <div class="list">
        ${d.checks.map(c => `<div class="list-item" style="cursor:default">
          <div class="grow"><div class="title">${c.ok ? "✅" : "❌"} ${esc(c.name)}</div>
          <div class="sub">${esc(c.detail || "")}</div></div></div>`).join("")}
      </div>
    </div>
    <div class="card"><h2>Environment tips</h2>
      <ul class="small muted">${d.env_tips.map(t => `<li>${esc(t)}</li>`).join("")}</ul>
      <button class="btn btn-secondary" id="refresh-health">Refresh</button>
    </div>`;
  document.getElementById("refresh-health").addEventListener("click", render);
});

/* ======================================================================
   VIEW: Deployment diagnostics
====================================================================== */
on("deployment", async () => {
  const [d, s, auth] = await Promise.all([
    api("/api/diagnostics"), api("/api/storage"),
    api("/api/auth/status").catch(() => ({})),
  ]);
  $view().innerHTML = `
    <div class="view-title"><h1>Deployment diagnostics</h1><span class="sub">free-first deployment</span></div>
    ${auth.open_local_mode ? notice("warn", "Instance is in <b>open local mode</b>. Before deploying publicly: set <code>OM_STUDIO_TOKEN</code>.") : notice("ok", "Admin authentication is enabled.")}
    ${s.persistence_warning ? notice("warn", esc(s.persistence_warning)) : notice("ok", "Data directory appears persistent.")}
    <div class="card">
      <h2>Architecture checklist</h2>
      <ul class="small">
        <li>✅ Static frontend + API served by this Python app (works on any free Python host).</li>
        <li>✅ Rendering worker runs out-of-process from request handlers (background thread; safe for long renders).</li>
        <li>⚠️ Cloudflare Pages can host the static frontend; Cloudflare Workers <b>cannot</b> run FFmpeg — keep rendering in the Python worker.</li>
        <li>⚠️ Free hosting that wipes the filesystem will lose projects — configure a persistent <code>OM_STUDIO_DATA_DIR</code> or download videos promptly.</li>
        <li>📖 Full instructions: <code>docs/FREE_DEPLOYMENT.md</code> and <code>docs/IPHONE_SETUP.md</code>.</li>
      </ul>
    </div>
    <div class="card">
      <h2>Security posture</h2>
      <ul class="small">
        <li>${auth.auth_enabled ? "✅" : "❌"} Admin authentication ${auth.auth_enabled ? "configured" : "NOT configured"}</li>
        <li>✅ Secrets masked in this UI; stored only in server-side environment variables</li>
        <li>✅ Input validation, rate limiting, safe file paths, SSRF guards, no shell=True</li>
        <li>✅ No unrestricted public rendering endpoint</li>
      </ul>
    </div>`;
});

/* ======================================================================
   VIEW: Help & documentation
====================================================================== */
on("help", async () => {
  $view().innerHTML = `
    <div class="view-title"><h1>Help &amp; documentation</h1><span class="sub">how this works</span></div>
    <div class="card">
      <h2>Workflow</h2>
      <ol class="small">
        <li><b>Create</b> — enter any topic and options.</li>
        <li><b>Research</b> — public RSS/web sources (optional; unverified when offline).</li>
        <li><b>Script</b> — duration-matched script + storyboard (template engine, optional LLM).</li>
        <li><b>Assets</b> — free stock footage (Pexels/Pixabay keys optional) or local motion graphics.</li>
        <li><b>Narration</b> — local TTS (espeak-ng / Piper) or your uploaded audio.</li>
        <li><b>Captions</b> — timed cues, SRT export, burned-in styling.</li>
        <li><b>Render</b> — FFmpeg composition (9:16 / 16:9 / 1:1).</li>
        <li><b>Quality control</b> — the job completes ONLY after output validation passes.</li>
      </ol>
    </div>
    <div class="card">
      <h2>What works with zero API keys?</h2>
      <ul class="small">
        <li>✅ The complete pipeline: research (best-effort), script, local motion footage, narration, captions, render, QC, download.</li>
        <li>🔑 Optional free keys improve footage realism: Pexels, Pixabay.</li>
        <li>🧠 Optional LLM (e.g. free local Ollama) improves scripts — never required.</li>
        <li>💳 Paid providers (ElevenLabs, OpenAI, fal.ai) are optional and disabled by default.</li>
      </ul>
    </div>
    <div class="card">
      <h2>From your iPhone</h2>
      <ul class="small">
        <li>Open this dashboard in Safari — it is built mobile-first.</li>
        <li>Add to Home Screen for an app-like icon.</li>
        <li>Create jobs, monitor stages, cancel/retry, and download MP4s directly to Photos/Files.</li>
        <li>Deployment from an iPhone uses the GitHub and Cloudflare web dashboards — see <code>docs/IPHONE_SETUP.md</code>.</li>
      </ul>
    </div>
    <div class="card">
      <h2>Docs</h2>
      <ul class="small">
        <li><code>README.md</code> — overview & quick start</li>
        <li><code>docs/IMPLEMENTATION_AUDIT.md</code> — what exists, what was tested</li>
        <li><code>docs/ARCHITECTURE.md</code> — system design</li>
        <li><code>docs/FREE_DEPLOYMENT.md</code> — $0 deployment paths</li>
        <li><code>docs/TEST_REPORT.md</code> — actual test results</li>
        <li><code>docs/COST_AND_LIMITS.md</code> — costs & external limits</li>
        <li><code>docs/IPHONE_SETUP.md</code> — iPhone workflow</li>
        <li><code>docs/TROUBLESHOOTING.md</code> — fixing failed jobs</li>
      </ul>
    </div>`;
});

/* ======================================================================
   VIEW: More (mobile overflow menu)
====================================================================== */
on("more", async () => {
  $view().innerHTML = `
    <div class="view-title"><h1>More</h1></div>
    <div class="list">
      ${[["storage","🗄 Storage settings"],["health","❤️ System health"],
         ["deployment","🚀 Deployment diagnostics"],["help","📖 Help & documentation"]]
        .map(([r, t]) => `<button class="list-item" data-go="${r}"><div class="grow"><div class="title">${t}</div></div><span>›</span></button>`).join("")}
    </div>`;
  document.querySelectorAll("[data-go]").forEach(b =>
    b.addEventListener("click", () => navigate("#/" + b.dataset.go)));
});

/* boot */
render();
