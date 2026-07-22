/* ==========================================================================
   OpenFlow control center — SPA
   Talks to the local OpenFlow shim on :18765. No build step, no framework.
   ========================================================================== */
"use strict";

/* ── tiny helpers ────────────────────────────────────────────────────── */

const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

const esc = (s) =>
  String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

const fmtSecs = (s) => {
  if (s == null || isNaN(s)) return "—";
  if (s > 0 && s < 0.1) return Math.round(s * 1000) + "ms";
  if (s < 60) return s.toFixed(1) + "s";
  const m = Math.floor(s / 60);
  return m + "m " + Math.round(s % 60) + "s";
};
const fmtClock = (ts) => {
  try { return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }); }
  catch { return ""; }
};
const truncate = (s, n) => (s && s.length > n ? s.slice(0, n - 1) + "…" : s || "");

function toast(msg, isErr) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.toggle("of-err", !!isErr);
  el.classList.add("of-show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove("of-show"), 3200);
}

/* ── brand mark (open ring + signal bars) ────────────────────────────── */

let _markSeq = 0;
function markSVG() {
  const g = "ofg" + ++_markSeq;
  return (
    `<svg viewBox="0 0 32 32" aria-hidden="true">` +
    `<defs><linearGradient id="${g}" x1="0" y1="0" x2="1" y2="1">` +
    `<stop offset="0" stop-color="#FFB25C"/><stop offset="1" stop-color="#FF6B2C"/>` +
    `</linearGradient></defs>` +
    `<circle cx="16" cy="16" r="11.5" fill="none" stroke="url(#${g})" stroke-width="2.4" ` +
    `stroke-linecap="round" stroke-dasharray="59 13.3" transform="rotate(-38 16 16)"/>` +
    `<rect x="9.4" y="13" width="2.6" height="7" rx="1.3" fill="url(#${g})"/>` +
    `<rect x="14.7" y="9.5" width="2.6" height="14" rx="1.3" fill="url(#${g})"/>` +
    `<rect x="20" y="12" width="2.6" height="9" rx="1.3" fill="url(#${g})"/>` +
    `</svg>`
  );
}
$("#brandMark").innerHTML = markSVG();

/* ── OS bridge (stub until the desktop shell lands) ──────────────────── */
/* A native shell (Tauri/Electron) injects window.openflowBridge with     */
/* registerHotkey(combo) and pasteText(text). Until then we keep the      */
/* preference locally and paste via the clipboard as an honest fallback.  */

const osb = {
  get native() { return !!window.openflowBridge; },
  async registerHotkey(combo) {
    if (window.openflowBridge && window.openflowBridge.registerHotkey) {
      return window.openflowBridge.registerHotkey(combo);
    }
    localStorage.setItem("of_hotkey", combo);
    return { stub: true };
  },
  savedHotkey() { return localStorage.getItem("of_hotkey") || "Ctrl+Shift+Space"; },
  async pasteText(text) {
    if (window.openflowBridge && window.openflowBridge.pasteText) {
      return window.openflowBridge.pasteText(text);
    }
    try { await navigator.clipboard.writeText(text); return { stub: true, clipboard: true }; }
    catch { return { stub: true, clipboard: false }; }
  },
};

/* ── API client ──────────────────────────────────────────────────────── */

async function api(path, opts) {
  const res = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, opts));
  let body = null;
  try { body = await res.json(); } catch { /* non-json */ }
  if (!res.ok) {
    const err = new Error((body && (body.error || body.error_message)) || ("HTTP " + res.status));
    err.status = res.status; err.body = body;
    throw err;
  }
  return body;
}

async function saveConfig(patch) {
  const body = JSON.stringify(patch);
  try {
    return await api("/v1/config", { method: "PUT", body });
  } catch (e) {
    return await api("/v1/config", { method: "POST", body });
  }
}

/* ── state ───────────────────────────────────────────────────────────── */

const state = {
  online: false,
  health: null,
  metrics: null,
  configPath: null,
  route: "home",
  recording: false,
};

const PROVIDERS = {
  grok:    { name: "Grok",    by: "xAI",       plan: "SuperGrok plan",   transport: "POST api.x.ai/v1/stt" },
  chatgpt: { name: "ChatGPT", by: "OpenAI",    plan: "ChatGPT plan",     transport: "POST chatgpt.com/backend-api/transcribe" },
  claude:  { name: "Claude",  by: "Anthropic", plan: "Claude plan",      transport: "WSS claude.ai voice_stream" },
};
const ORDER = ["grok", "chatgpt", "claude"];

function providerStatus(st) {
  if (!state.online) return { label: "shim offline", cls: "mute", kind: "offline" };
  if (!st) return { label: "unknown", cls: "mute", kind: "offline" };
  if (st.ready && st.stt_capable !== false) return { label: "ready", cls: "ok", kind: "ready" };
  if (st.auth_path && st.stt_capable === false) return { label: "limited", cls: "warn", kind: "limited" };
  if (st.ready) return { label: "limited", cls: "warn", kind: "limited" };
  return { label: "needs login", cls: "warn", kind: "login" };
}

/* ── polling ─────────────────────────────────────────────────────────── */

async function poll() {
  try {
    const h = await api("/health");
    state.health = h;
    state.online = !!h.ok;
    applyAccent(h.config && h.config.ui && h.config.ui.accent);
  } catch {
    state.online = false;
    state.health = null;
  }
  if (state.online && state.route === "activity") {
    try { state.metrics = await api("/metrics"); } catch { state.metrics = null; }
  }
  if (state.online) {
    try {
      const c = await api("/v1/config");
      state.configPath = c.path || null;
    } catch { /* optional */ }
  }
  renderChrome();
  if (!state.recording) render();
}

function applyAccent(accent) {
  if (accent && /^#[0-9a-f]{6}$/i.test(accent)) {
    document.documentElement.style.setProperty("--of-ember", accent);
  }
}

function renderChrome() {
  const dot = $("#shimDot"), txt = $("#shimState");
  dot.className = "of-dot " + (state.online ? "of-dot--ok" : "of-dot--err");
  txt.textContent = state.online ? "online" : "offline";
}

/* ── router ──────────────────────────────────────────────────────────── */

const ROUTES = { home: 1, engine: 1, activity: 1, settings: 1 };

function route() {
  const h = (location.hash || "#/home").replace(/^#\//, "").split("?")[0];
  state.route = ROUTES[h] ? h : "home";
  $("#app").dataset.route = state.route;
  $$(".of-nav a").forEach((a) => a.classList.toggle("of-on", a.dataset.nav === state.route));
  render();
}
window.addEventListener("hashchange", route);

/* ── shared fragments ────────────────────────────────────────────────── */

function pageHead(kicker, title, lede) {
  return (
    `<div class="of-kicker">${esc(kicker)}</div>` +
    `<h1 class="of-title">${esc(title)}</h1>` +
    (lede ? `<p class="of-lede">${esc(lede)}</p>` : "")
  );
}

function offlineNotice() {
  return (
    `<div class="of-notice of-notice--err"><div>` +
    `<b>Shim offline.</b> The OpenFlow shim is not answering on <span class="of-mono">127.0.0.1:18765</span>. ` +
    `Start it with <span class="of-chip">python -m openflow serve</span> from the OpenFlow directory, then ` +
    `<a href="javascript:location.reload()"><u>reload</u></a>.` +
    `</div></div>`
  );
}

function activeProviderId() { return (state.health && state.health.provider) || "grok"; }
function providerMap() { return (state.health && state.health.providers) || {}; }

function pillFor(id) {
  const st = providerMap()[id] || {};
  const ps = providerStatus(st);
  return `<span class="of-pill of-pill--${ps.cls}"><span class="of-dot of-dot--${ps.cls === "ok" ? "ok" : ps.cls === "warn" ? "warn" : "idle"}"></span>${ps.label}</span>`;
}

function statTile(value, label, unit) {
  return (
    `<div class="of-stat"><div class="of-stat-value">${esc(value)}${unit ? ` <small>${esc(unit)}</small>` : ""}</div>` +
    `<div class="of-stat-label">${esc(label)}</div></div>`
  );
}

/* ── home ────────────────────────────────────────────────────────────── */

function viewHome() {
  if (!state.online) return pageHead("control center", "Home") + offlineNotice();

  const h = state.health || {};
  const active = activeProviderId();
  const meta = PROVIDERS[active] || { name: active };
  const st = providerMap()[active] || {};
  const ps = providerStatus(st);
  const lastLat = h.last_stt_latency_s;
  const okRate = h.requests ? null : null;

  let html = pageHead(
    "control center",
    "Home",
    "Hold your hotkey, speak, and text lands at your cursor — routed to the speech membership you already pay for."
  );

  /* now card */
  html +=
    `<div class="of-card of-card--active"><div class="of-card-head">` +
    `<span class="of-pdot of-pdot--${esc(active)}"></span>` +
    `<div><div class="of-card-title">${esc(meta.name)} <span class="of-muted of-small">· ${esc(meta.by)}</span></div>` +
    `<div class="of-card-sub">${esc(st.detail || meta.plan)}</div></div>` +
    `<span style="flex:1"></span>${pillFor(active)}` +
    `</div>` +
    `<div class="of-row">` +
    `<span class="of-chip">${esc(meta.transport)}</span>` +
    (lastLat != null ? `<span class="of-chip">last ${esc(fmtSecs(lastLat))}</span>` : "") +
    (h.last_stt_ok === false ? `<span class="of-pill of-pill--err">last dictation failed</span>` : "") +
    `</div>` +
    `<div class="of-card-actions">` +
    `<span class="of-section-label" style="margin:0">quick switch</span>` +
    `<div class="of-seg" role="radiogroup" aria-label="Speech engine">` +
    ORDER.map((id) => {
      const pst = providerMap()[id] || {};
      const dis = state.online && (pst.ready || pst.stt_capable !== false) ? "" : "disabled";
      return `<button type="button" data-sw="${id}" class="${id === active ? "of-on" : ""}" ${dis} title="${esc((pst.detail || id))}">${esc(PROVIDERS[id].name)}</button>`;
    }).join("") +
    `</div><span class="of-spacer"></span>` +
    `<a class="of-btn of-btn--ghost of-btn--sm" href="#/engine">engine settings →</a>` +
    `</div></div>`;

  /* stats */
  html +=
    `<div class="of-section-label">shim</div>` +
    `<div class="of-grid of-grid--stats">` +
    statTile(fmtSecs(h.uptime_s || 0), "uptime") +
    statTile(String(h.requests || 0), "dictations") +
    statTile(lastLat != null ? fmtSecs(lastLat) : "—", "last latency") +
    statTile(h.last_provider ? (PROVIDERS[h.last_provider] || {}).name || h.last_provider : "—", "last engine") +
    `</div>`;

  /* bench */
  html +=
    `<div class="of-section-label">test bench</div>` +
    `<div class="of-card of-bench" id="bench">` +
    `<div class="of-bench-stage">` +
    `<button class="of-btn of-btn--rec" id="recBtn" type="button"><span class="of-rec-dot"></span><span id="recLabel">Hold to dictate</span></button>` +
    `<span class="of-wave" id="benchWave"><b></b><b></b><b></b><b></b><b></b><b></b><b></b></span>` +
    `<span class="of-bench-timer" id="benchTimer"></span>` +
    `<span class="of-spacer" style="flex:1"></span>` +
    `<label class="of-switch" title="Run the cleanup/format pass after transcription">` +
    `<input type="checkbox" id="benchFmt" checked><span class="of-track"></span>` +
    `<span class="of-switch-label">format pass</span></label>` +
    `<button class="of-btn of-btn--ghost of-btn--sm" id="toneBtn" type="button" title="Send a generated 1s tone through the full pipeline">send test tone</button>` +
    `</div>` +
    `<div class="of-small of-muted">Uses your microphone and the active engine (<b>${esc(meta.name)}</b>) via <span class="of-mono">POST /v1/run_remote</span> — the same call the desktop shell makes.</div>` +
    `<div class="of-bench-result of-hidden" id="benchResult"></div>` +
    `</div>`;

  if (h.last_stt_error) {
    html +=
      `<div class="of-notice of-notice--warn of-mt"><div><b>Last engine error:</b> ` +
      `<span class="of-mono">${esc(truncate(h.last_stt_error, 220))}</span></div></div>`;
  }
  return html;
}

/* ── engine ──────────────────────────────────────────────────────────── */

function viewEngine() {
  if (!state.online) return pageHead("speech engine", "Providers") + offlineNotice();

  const active = activeProviderId();
  const cfg = (state.health && state.health.config) || {};
  const fallback = cfg.fallback || [];

  let html = pageHead(
    "speech engine",
    "Providers",
    "Audio goes only to the engine you select. Credentials stay on this machine; OpenFlow has no cloud middleman."
  );

  html += `<div class="of-grid of-grid--3">` + ORDER.map((id) => {
    const meta = PROVIDERS[id];
    const st = providerMap()[id] || {};
    const ps = providerStatus(st);
    const isActive = id === active;
    const enabled = st.enabled !== false;
    const isFallback = fallback.includes(id);

    const kv = [
      ["engine", `<dd class="of-mono">${esc(id)}</dd>`, `<dt>engine</dt>`],
    ];
    let rows =
      `<dt>transport</dt><dd class="of-mono">${esc(meta.transport)}</dd>` +
      (st.auth_path ? `<dt>auth file</dt><dd class="of-mono">${esc(st.auth_path)}</dd>` : `<dt>auth file</dt><dd>none found</dd>`) +
      (st.auth_mode ? `<dt>session</dt><dd class="of-mono">${esc(st.auth_mode)}</dd>` : "") +
      `<dt>status</dt><dd>${esc(st.detail || "—")}</dd>` +
      (st.error ? `<dt>error</dt><dd class="of-mono">${esc(truncate(st.error, 140))}</dd>` : "");

    return (
      `<div class="of-card ${isActive ? "of-card--active" : ""} ${enabled ? "" : "of-card--off"}" data-pcard="${id}">` +
      `<div class="of-card-head">` +
      `<span class="of-pdot of-pdot--${id}"></span>` +
      `<div><div class="of-card-title">${esc(meta.name)}</div>` +
      `<div class="of-card-sub">${esc(meta.by)} · ${esc(meta.plan)}</div></div>` +
      `<span style="flex:1"></span>${pillFor(id)}` +
      (isActive ? `<span class="of-pill of-pill--ember">active</span>` : "") +
      `</div>` +
      `<dl class="of-kv">${rows}</dl>` +
      `<div class="of-card-actions">` +
      `<label class="of-switch"><input type="checkbox" data-en="${id}" ${enabled ? "checked" : ""}><span class="of-track"></span><span class="of-switch-label">enabled</span></label>` +
      `<span class="of-spacer"></span>` +
      (!isActive && enabled
        ? `<label class="of-switch" title="Try this engine if the active one fails"><input type="checkbox" data-fb="${id}" ${isFallback ? "checked" : ""}><span class="of-track"></span><span class="of-switch-label">fallback</span></label>`
        : "") +
      (isActive
        ? `<button class="of-btn of-btn--sm" disabled>active</button>`
        : `<button class="of-btn of-btn--primary of-btn--sm" data-mk="${id}" ${enabled && (st.ready || st.stt_capable !== false) ? "" : "disabled"}>make active</button>`) +
      `</div></div>`
    );
  }).join("") + `</div>`;

  html +=
    `<div class="of-notice of-mt"><div><b>Honest status.</b> Cards reflect live session files on this machine. ` +
    `Claude's voice stream can still be refused by Cloudflare from non-browser clients — if that happens the card stays ` +
    `<span class="of-mono">ready</span> but dictations fail, and the error shows on the Activity page.</div></div>`;

  return html;
}

/* ── activity ────────────────────────────────────────────────────────── */

function localHistory() {
  try { return JSON.parse(localStorage.getItem("of_history") || "[]"); } catch { return []; }
}
function pushHistory(entry) {
  const h = localHistory();
  h.unshift(entry);
  localStorage.setItem("of_history", JSON.stringify(h.slice(0, 50)));
}

function viewActivity() {
  if (!state.online) return pageHead("activity", "Activity") + offlineNotice();

  const h = state.health || {};
  const m = state.metrics || {};
  const byP = (m.provider_stats && m.provider_stats.by_provider) || {};

  let html = pageHead("activity", "Activity", "What the shim has done since it started, plus test dictations from this control center.");

  html +=
    `<div class="of-grid of-grid--stats">` +
    statTile(String(m.requests != null ? m.requests : h.requests || 0), "requests") +
    statTile(String(m.stt_ok != null ? m.stt_ok : "—"), "succeeded") +
    statTile(String(m.stt_fail != null ? m.stt_fail : "—"), "failed") +
    statTile(m.avg_total_s != null ? fmtSecs(m.avg_total_s) : "—", "avg total") +
    statTile(m.avg_asr_s != null ? fmtSecs(m.avg_asr_s) : "—", "avg asr") +
    statTile(String(m.lexicon_rules != null ? m.lexicon_rules : "—"), "lexicon rules") +
    `</div>`;

  /* per-provider table */
  html += `<div class="of-section-label">per engine</div><div class="of-card"><table class="of-table"><thead><tr>` +
    `<th>engine</th><th>status</th><th>ok</th><th>fail</th><th>last latency</th></tr></thead><tbody>` +
    ORDER.map((id) => {
      const s = byP[id] || {};
      const st = providerMap()[id] || {};
      const lat = (state.health.last_provider === id) ? state.health.last_stt_latency_s : null;
      return `<tr><td><span class="of-pdot of-pdot--${id}" style="display:inline-block;margin-right:8px;vertical-align:-1px"></span>${esc(PROVIDERS[id].name)}</td>` +
        `<td>${pillFor(id)}</td>` +
        `<td class="of-mono">${s.ok || 0}</td><td class="of-mono">${s.fail || 0}</td>` +
        `<td class="of-mono">${lat != null ? esc(fmtSecs(lat)) : "—"}</td></tr>`;
    }).join("") +
    `</tbody></table></div>`;

  if (h.last_stt_error) {
    html += `<div class="of-notice of-notice--err of-mt"><div><b>Last error</b> (engine <span class="of-mono">${esc(h.last_provider || "?")}</span>): ` +
      `<span class="of-mono">${esc(truncate(h.last_stt_error, 260))}</span></div></div>`;
  }

  /* local bench history */
  const hist = localHistory();
  html += `<div class="of-section-label">test bench history (this browser)</div>`;
  if (!hist.length) {
    html += `<div class="of-empty"><div class="of-empty-title">No test dictations yet</div>` +
      `Use the test bench on the Home page to exercise the full pipeline.</div>`;
  } else {
    html += `<div class="of-card"><table class="of-table"><thead><tr>` +
      `<th>time</th><th>engine</th><th>audio</th><th>latency</th><th>text</th></tr></thead><tbody>` +
      hist.map((e) =>
        `<tr><td class="of-mono">${esc(fmtClock(e.ts))}</td>` +
        `<td>${esc((PROVIDERS[e.provider] || {}).name || e.provider || "?")}</td>` +
        `<td class="of-mono">${e.secs != null ? esc(e.secs.toFixed(1) + "s") : "—"}</td>` +
        `<td class="of-mono">${e.latency != null ? esc(fmtSecs(e.latency)) : "—"}</td>` +
        `<td>${esc(truncate(e.text, 90)) || "<span class='of-muted'>(no text)</span>"}</td></tr>`
      ).join("") +
      `</tbody></table></div>` +
      `<div class="of-mt"><button class="of-btn of-btn--ghost of-btn--sm" id="clearHist">clear history</button></div>`;
  }
  return html;
}

/* ── settings ────────────────────────────────────────────────────────── */

const ACCENTS = [
  ["#ff6b2c", "Ember"],
  ["#ffa41b", "Amber"],
  ["#ff5c6c", "Flare"],
  ["#e9b949", "Signal"],
];

function viewSettings() {
  if (!state.online) return pageHead("settings", "Settings") + offlineNotice();

  const h = state.health || {};
  const cfg = h.config || {};
  const accent = (cfg.ui && cfg.ui.accent) || "#ff6b2c";
  const hotkey = osb.savedHotkey();

  let html = pageHead("settings", "Settings");

  /* shim */
  html += `<div class="of-section-label">local shim</div>` +
    `<div class="of-card"><dl class="of-kv">` +
    `<dt>endpoint</dt><dd class="of-mono">http://127.0.0.1:18765</dd>` +
    `<dt>config file</dt><dd class="of-mono">${esc(state.configPath || "%APPDATA%\\OpenFlow\\config.json")}</dd>` +
    `<dt>stt route</dt><dd class="of-mono">${esc(h.stt || "—")}</dd>` +
    `<dt>cleanup</dt><dd>${h.local_cleanup ? "local light cleanup on" : "off"}${h.llm_format ? ` · format model <span class="of-mono">${esc(h.format_model || "")}</span>` : ""}</dd>` +
    `</dl></div>`;

  /* appearance */
  html += `<div class="of-section-label">appearance</div>` +
    `<div class="of-card"><div class="of-row">` +
    ACCENTS.map(([hex, name]) =>
      `<button class="of-btn of-btn--sm ${hex === accent.toLowerCase() ? "of-btn--primary" : "of-btn--ghost"}" data-accent="${hex}" type="button">` +
      `<span class="of-pdot" style="background:${hex}"></span> ${name}</button>`
    ).join("") +
    `<span class="of-spacer"></span><span class="of-small of-muted">saved to <span class="of-mono">config.ui.accent</span></span>` +
    `</div></div>`;

  /* hotkey */
  html += `<div class="of-section-label">dictation hotkey</div>` +
    `<div class="of-card">` +
    `<div class="of-row"><span class="of-hotkey" id="hkShow">${hotkey.split("+").map((k) => `<kbd>${esc(k)}</kbd>`).join("")}</span>` +
    `<button class="of-btn of-btn--ghost of-btn--sm" id="hkCap" type="button">capture…</button>` +
    `<span class="of-spacer"></span>` +
    `<button class="of-btn of-btn--ghost of-btn--sm" id="ovPrev" type="button">preview overlay</button></div>` +
    `<div class="of-small of-muted of-mt">` +
    (osb.native
      ? `Registered with the Windows desktop integration.`
      : `OpenFlow uses the installed desktop shell for the global hotkey and recording overlay. ` +
        `This control stores a dashboard preference only; configure the active shortcut in the desktop shell. ` +
        `The preview shows OpenFlow's overlay design.`) +
    `</div></div>`;

  /* about */
  html += `<div class="of-section-label">about</div>` +
    `<div class="of-card"><div class="of-row">` +
    `<span class="of-brand-mark" style="width:34px;height:34px">${markSVG()}</span>` +
    `<div><div class="of-card-title">OpenFlow</div>` +
    `<div class="of-card-sub">open-source, local-first dictation controller</div></div></div>` +
    `<div class="of-small of-muted of-mt">Audio goes to the engine you choose — Grok, ChatGPT, or Claude — using a membership you already have. ` +
    `No separate dictation subscription, no account wall, no OpenFlow cloud. ` +
    `OpenFlow is an original project; it is not affiliated with or endorsed by xAI, OpenAI, Anthropic, or Wispr.</div>` +
    `</div>`;

  return html;
}

/* ── render ──────────────────────────────────────────────────────────── */

const VIEWS = { home: viewHome, engine: viewEngine, activity: viewActivity, settings: viewSettings };

function render() {
  const view = $("#view");
  view.innerHTML = (VIEWS[state.route] || viewHome)();
  bind(view);
}

function bind(root) {
  /* quick switch + make active */
  $$("[data-sw]", root).forEach((b) => b.addEventListener("click", () => switchProvider(b.dataset.sw)));
  $$("[data-mk]", root).forEach((b) => b.addEventListener("click", () => switchProvider(b.dataset.mk)));

  /* enable toggles */
  $$("[data-en]", root).forEach((t) =>
    t.addEventListener("change", async () => {
      const id = t.dataset.en, on = t.checked;
      try {
        await saveConfig({ providers: { [id]: { enabled: on } } });
        toast(`${PROVIDERS[id].name} ${on ? "enabled" : "disabled"}`);
      } catch (e) { toast("save failed: " + e.message, true); t.checked = !on; }
      poll();
    })
  );

  /* fallback toggles */
  $$("[data-fb]", root).forEach((t) =>
    t.addEventListener("change", async () => {
      const id = t.dataset.fb;
      const cfg = (state.health && state.health.config) || {};
      let fb = Array.isArray(cfg.fallback) ? cfg.fallback.slice() : [];
      if (t.checked && !fb.includes(id)) fb.push(id);
      if (!t.checked) fb = fb.filter((x) => x !== id);
      try {
        await saveConfig({ fallback: fb });
        toast(`fallback: ${fb.length ? fb.map((x) => PROVIDERS[x].name).join(" → ") : "none"}`);
      } catch (e) { toast("save failed: " + e.message, true); }
      poll();
    })
  );

  /* accent swatches */
  $$("[data-accent]", root).forEach((b) =>
    b.addEventListener("click", async () => {
      const hex = b.dataset.accent;
      applyAccent(hex);
      try { await saveConfig({ ui: { accent: hex } }); toast("accent saved"); }
      catch (e) { toast("save failed: " + e.message, true); }
      poll();
    })
  );

  /* bench */
  const recBtn = $("#recBtn", root);
  if (recBtn) {
    recBtn.addEventListener("pointerdown", (e) => { e.preventDefault(); recStart(); });
    const stop = () => recStop();
    recBtn.addEventListener("pointerup", stop);
    recBtn.addEventListener("pointerleave", stop);
    recBtn.addEventListener("keydown", (e) => {
      if ((e.key === " " || e.key === "Enter") && !state.recording) { e.preventDefault(); recStart(); }
    });
    recBtn.addEventListener("keyup", (e) => { if (e.key === " " || e.key === "Enter") recStop(); });
  }
  const toneBtn = $("#toneBtn", root);
  if (toneBtn) toneBtn.addEventListener("click", () => sendTone());

  /* history clear */
  const ch = $("#clearHist", root);
  if (ch) ch.addEventListener("click", () => { localStorage.removeItem("of_history"); render(); });

  /* hotkey capture */
  const hkCap = $("#hkCap", root);
  if (hkCap) hkCap.addEventListener("click", () => captureHotkey(hkCap));

  const ovPrev = $("#ovPrev", root);
  if (ovPrev) ovPrev.addEventListener("click", () => window.open("/ui/overlay.html?demo=1", "of_overlay", "width=420,height=200"));

  /* onboarding bench reuse */
  const obRec = $("#obRecBtn", root);
  if (obRec) {
    obRec.addEventListener("pointerdown", (e) => { e.preventDefault(); recStart("ob"); });
    obRec.addEventListener("pointerup", () => recStop("ob"));
    obRec.addEventListener("pointerleave", () => recStop("ob"));
  }
  const obTone = $("#obToneBtn", root);
  if (obTone) obTone.addEventListener("click", () => sendTone("ob"));
}

async function switchProvider(id) {
  if (!PROVIDERS[id]) return;
  try {
    await saveConfig({ provider: id });
    const h = await api("/health");
    if ((h.provider || "") !== id) {
      toast("switch did not stick (still " + (h.provider || "?") + ")", true);
    } else {
      toast("active engine: " + PROVIDERS[id].name);
    }
    state.health = h;
  } catch (e) {
    toast("can't reach shim: " + e.message, true);
  }
  render();
}

/* ── test bench (mic → 16k WAV → run_remote) ─────────────────────────── */

const bench = { ctx: null, stream: null, proc: null, chunks: [], t0: 0, timer: null, target: "bench" };

function benchEls(target) {
  const root = target === "ob" ? $("#onboard") : document;
  return {
    btn: target === "ob" ? $("#obRecBtn") : $("#recBtn"),
    label: target === "ob" ? $("#obRecLabel") : $("#recLabel"),
    wave: target === "ob" ? $("#obWave") : $("#benchWave"),
    timer: target === "ob" ? $("#obTimer") : $("#benchTimer"),
    result: target === "ob" ? $("#obResult") : $("#benchResult"),
    fmt: target === "ob" ? $("#obFmt") : $("#benchFmt"),
  };
}

async function recStart(target) {
  if (state.recording) return;
  target = target || "bench";
  if (!state.online) { toast("shim offline", true); return; }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    toast("microphone not available in this context", true);
    return;
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
  } catch (e) {
    toast("mic denied: " + e.message, true);
    return;
  }
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const src = ctx.createMediaStreamSource(stream);
  const proc = ctx.createScriptProcessor(4096, 1, 1);
  bench.chunks = [];
  proc.onaudioprocess = (e) => bench.chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  src.connect(proc);
  proc.connect(ctx.destination);
  Object.assign(bench, { ctx, stream, proc, t0: performance.now(), target });
  state.recording = true;

  const els = benchEls(target);
  if (els.btn) els.btn.classList.add("of-live");
  if (els.label) els.label.textContent = "Listening… release to send";
  if (els.wave) els.wave.classList.add("of-live");
  bench.timer = setInterval(() => {
    const s = (performance.now() - bench.t0) / 1000;
    if (els.timer) els.timer.textContent = s.toFixed(1) + "s";
  }, 100);
}

async function recStop(target) {
  if (!state.recording) return;
  target = target || bench.target;
  state.recording = false;
  clearInterval(bench.timer);

  const els = benchEls(target);
  if (els.btn) els.btn.classList.remove("of-live");
  if (els.label) els.label.textContent = "Hold to dictate";
  if (els.wave) els.wave.classList.remove("of-live");

  const secs = (performance.now() - bench.t0) / 1000;
  try {
    bench.proc.disconnect();
    bench.stream.getTracks().forEach((t) => t.stop());
    const rate = bench.ctx.sampleRate;
    await bench.ctx.close();
    if (secs < 0.25) { if (els.timer) els.timer.textContent = ""; return; }
    const pcm = downsample(concat(bench.chunks), rate, 16000);
    if (els.timer) els.timer.textContent = "sending…";
    await submitAudio(pcm, secs, target);
  } catch (e) {
    if (els.timer) els.timer.textContent = "";
    toast("capture failed: " + e.message, true);
  }
}

function concat(chunks) {
  const n = chunks.reduce((a, c) => a + c.length, 0);
  const out = new Float32Array(n);
  let o = 0;
  for (const c of chunks) { out.set(c, o); o += c.length; }
  return out;
}

function downsample(input, from, to) {
  if (from === to) return input;
  const ratio = from / to;
  const n = Math.floor(input.length / ratio);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const pos = i * ratio;
    const i0 = Math.floor(pos);
    const i1 = Math.min(i0 + 1, input.length - 1);
    out[i] = input[i0] + (input[i1] - input[i0]) * (pos - i0);
  }
  return out;
}

function wavBytes(pcm, rate) {
  const n = pcm.length;
  const buf = new ArrayBuffer(44 + n * 2);
  const v = new DataView(buf);
  const wstr = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  wstr(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); wstr(8, "WAVE");
  wstr(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  wstr(36, "data"); v.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) {
    const s = Math.max(-1, Math.min(1, pcm[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Uint8Array(buf);
}

function b64(bytes) {
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return btoa(s);
}

async function submitAudio(pcm, secs, target) {
  const els = benchEls(target);
  const wav = wavBytes(pcm, 16000);
  const wantFmt = !els.fmt || els.fmt.checked;
  const t0 = performance.now();
  let res;
  try {
    res = await api("/v1/run_remote", {
      method: "POST",
      body: JSON.stringify({
        request: { audio: b64(wav), language: "en", pipeline: wantFmt ? ["format"] : [] },
      }),
    });
  } catch (e) {
    if (els.timer) els.timer.textContent = "";
    showBenchResult(target, { error: e.message, secs });
    return;
  }
  const lat = (performance.now() - t0) / 1000;
  if (els.timer) els.timer.textContent = "";
  showBenchResult(target, Object.assign({ secs, latency: lat }, res));
}

async function sendTone(target) {
  target = target || "bench";
  if (!state.online) { toast("shim offline", true); return; }
  const rate = 16000, secs = 1.0;
  const pcm = new Float32Array(rate * secs);
  for (let i = 0; i < pcm.length; i++) {
    const t = i / rate;
    const env = Math.min(1, t * 40) * Math.min(1, (secs - t) * 40);
    pcm[i] = 0.35 * env * Math.sin(2 * Math.PI * 440 * t);
  }
  toast("sending test tone through the pipeline…");
  await submitAudio(pcm, secs, target);
}

function showBenchResult(target, r) {
  const els = benchEls(target);
  if (!els.result) return;
  els.result.classList.remove("of-hidden");

  const active = (r.provider) || activeProviderId();
  if (r.error || r.status === "error") {
    els.result.innerHTML =
      `<div class="of-notice of-notice--err"><div><b>engine error:</b> ` +
      `<span class="of-mono">${esc(truncate(r.error || r.error_message || "unknown", 240))}</span></div></div>`;
    pushHistory({ ts: Date.now(), provider: active, secs: r.secs, latency: r.latency, text: "" });
    return;
  }

  const asr = r.asr_text || "";
  const llm = r.llm_text || "";
  const text = llm || asr;
  els.result.innerHTML =
    `<div class="of-row">` +
    `<span class="of-pill of-pill--${r.status === "error" ? "err" : "ok"}">${esc(r.status || "ok")}</span>` +
    `<span class="of-chip">engine ${esc((PROVIDERS[active] || {}).name || active)}</span>` +
    (r.total_time != null ? `<span class="of-chip">total ${esc(fmtSecs(r.total_time))}</span>` : "") +
    (r.asr_time != null ? `<span class="of-chip">asr ${esc(fmtSecs(r.asr_time))}</span>` : "") +
    (r.llm_time != null && r.llm_time ? `<span class="of-chip">fmt ${esc(fmtSecs(r.llm_time))}</span>` : "") +
    `<span class="of-spacer" style="flex:1"></span>` +
    `<button class="of-btn of-btn--ghost of-btn--sm" id="benchPaste">copy as paste (stub)</button>` +
    `</div>` +
    (llm
      ? `<div><div class="of-transcript-label">final (what would paste)</div><div class="of-transcript">${esc(llm) || "<span class='of-muted'>(empty)</span>"}</div></div>` +
        (asr && asr !== llm
          ? `<div><div class="of-transcript-label">raw transcript</div><div class="of-transcript of-dim">${esc(asr)}</div></div>`
          : "")
      : `<div><div class="of-transcript-label">transcript</div><div class="of-transcript">${esc(asr) || "<span class='of-muted'>(no speech detected)</span>"}</div></div>`);

  const pb = $("#benchPaste", els.result);
  if (pb) pb.addEventListener("click", async () => {
    const out = await osb.pasteText(text);
    toast(out.clipboard ? "no desktop shell yet — copied to clipboard instead" : "paste stub: bridge not present");
  });

  pushHistory({ ts: Date.now(), provider: active, secs: r.secs, latency: r.latency, text: truncate(text, 140) });
}

/* ── hotkey capture ──────────────────────────────────────────────────── */

function captureHotkey(btn) {
  btn.textContent = "press keys…";
  btn.disabled = true;
  const done = (combo) => {
    btn.textContent = "capture…";
    btn.disabled = false;
    if (combo) {
      osb.registerHotkey(combo).then(() => {
        toast("hotkey preference saved: " + combo + (osb.native ? "" : " (local stub)"));
        render();
      });
    }
  };
  const onKey = (e) => {
    e.preventDefault();
    if (e.key === "Escape") { cleanup(); done(null); return; }
    if (["Control", "Shift", "Alt", "Meta"].includes(e.key)) return;
    const parts = [];
    if (e.ctrlKey) parts.push("Ctrl");
    if (e.altKey) parts.push("Alt");
    if (e.shiftKey) parts.push("Shift");
    if (e.metaKey) parts.push("Meta");
    parts.push(e.key.length === 1 ? e.key.toUpperCase() : e.key);
    cleanup();
    done(parts.join("+"));
  };
  const cleanup = () => {
    window.removeEventListener("keydown", onKey, true);
    window.removeEventListener("blur", onBlur);
  };
  const onBlur = () => { cleanup(); done(null); };
  window.addEventListener("keydown", onKey, true);
  window.addEventListener("blur", onBlur);
}

/* ── onboarding ──────────────────────────────────────────────────────── */

const ob = { open: false, step: 0 };

function obOpen() {
  ob.open = true; ob.step = 0;
  obRender();
}
function obClose(markDone) {
  ob.open = false;
  $("#onboard").innerHTML = "";
  if (markDone) localStorage.setItem("of_onboarded_v1", "1");
}
$("#onboardBtn").addEventListener("click", obOpen);

function obRender() {
  const steps = ["welcome", "connect", "engine", "hotkey", "test"];
  const wrap = $("#onboard");
  const bar = `<div class="of-ob-steps">` + steps.map((_, i) => `<i class="${i <= ob.step ? "of-on" : ""}"></i>`).join("") + `</div>`;
  let body = "";

  if (ob.step === 0) {
    body =
      `<div class="of-ob-brand"><span class="of-brand-mark">${markSVG()}</span>` +
      `<div><div class="of-ob-title">Welcome to OpenFlow</div>` +
      `<div class="of-brand-sub">many sources · one stream</div></div></div>` +
      `<p class="of-ob-body">OpenFlow turns a hotkey into dictation: hold it, speak, and text lands at your cursor. ` +
      `A tiny local shim on this machine routes your audio to <b>Grok</b>, <b>ChatGPT</b>, or <b>Claude</b> — ` +
      `whichever membership you already pay for. No dictation subscription, no account wall, no cloud middleman.</p>` +
      `<div class="of-ob-actions"><span class="of-spacer"></span>` +
      `<button class="of-btn of-btn--ghost" data-ob="skip">skip setup</button>` +
      `<button class="of-btn of-btn--primary" data-ob="next">get started</button></div>`;
  } else if (ob.step === 1) {
    body =
      `<div class="of-ob-title">Connect your engines</div>` +
      `<p class="of-ob-body">OpenFlow reads sessions you already have on this machine. Sign in with any of these, then refresh:</p>` +
      `<div class="of-ob-list">` +
      ORDER.map((id) => {
        const st = providerMap()[id] || {};
        const hint = { grok: "grok login (SuperGrok)", chatgpt: "sign into Codex Desktop / codex login", claude: "sign into Claude Desktop" }[id];
        const usable = st.ready && st.stt_capable !== false;
        return `<div class="of-ob-row"><span class="of-pdot of-pdot--${id}"></span>` +
          `<div class="of-grow"><div class="of-name">${esc(PROVIDERS[id].name)}</div>` +
          `<div class="of-detail">${esc(st.detail || hint)}</div></div>` +
          pillFor(id) +
          (usable ? "" : `<span class="of-chip">${esc(hint)}</span>`) +
          `</div>`;
      }).join("") +
      `</div>` +
      `<div class="of-ob-actions">` +
      `<button class="of-btn of-btn--ghost" data-ob="back">back</button><span class="of-spacer"></span>` +
      `<button class="of-btn of-btn--ghost" data-ob="refresh">refresh status</button>` +
      `<button class="of-btn of-btn--primary" data-ob="next">continue</button></div>`;
  } else if (ob.step === 2) {
    const active = activeProviderId();
    body =
      `<div class="of-ob-title">Choose your speech engine</div>` +
      `<p class="of-ob-body">This is the provider your audio is sent to. You can change it any time in Speech engine settings.</p>` +
      `<div class="of-ob-list">` +
      ORDER.map((id) => {
        const st = providerMap()[id] || {};
        const usable = st.ready || st.stt_capable !== false;
        return `<div class="of-ob-row" style="${id === active ? "border-color:var(--of-ember-line);box-shadow:var(--of-glow)" : ""}">` +
          `<span class="of-pdot of-pdot--${id}"></span>` +
          `<div class="of-grow"><div class="of-name">${esc(PROVIDERS[id].name)}</div>` +
          `<div class="of-detail">${esc(PROVIDERS[id].transport)}</div></div>` +
          pillFor(id) +
          (id === active
            ? `<span class="of-pill of-pill--ember">active</span>`
            : `<button class="of-btn of-btn--sm ${usable ? "of-btn--primary" : ""}" data-ob-use="${id}" ${usable ? "" : "disabled"}>use</button>`) +
          `</div>`;
      }).join("") +
      `</div>` +
      `<div class="of-ob-actions"><button class="of-btn of-btn--ghost" data-ob="back">back</button><span class="of-spacer"></span>` +
      `<button class="of-btn of-btn--primary" data-ob="next">continue</button></div>`;
  } else if (ob.step === 3) {
    const hotkey = osb.savedHotkey();
    body =
      `<div class="of-ob-title">Set your hotkey</div>` +
      `<p class="of-ob-body">OpenFlow uses the installed desktop shell for the global hotkey. This dashboard stores ` +
      `the preference locally; configure the active shortcut in the desktop shell.</p>` +
      `<div class="of-ob-row"><div class="of-grow"><div class="of-name">Push-to-talk</div>` +
      `<div class="of-detail">hold to record · release to paste</div></div>` +
      `<span class="of-hotkey">${hotkey.split("+").map((k) => `<kbd>${esc(k)}</kbd>`).join("")}</span>` +
      `<button class="of-btn of-btn--ghost of-btn--sm" id="obHkCap">capture…</button></div>` +
      `<div class="of-ob-actions"><button class="of-btn of-btn--ghost" data-ob="back">back</button><span class="of-spacer"></span>` +
      `<button class="of-btn of-btn--ghost" data-ob="overlay">preview overlay</button>` +
      `<button class="of-btn of-btn--primary" data-ob="next">continue</button></div>`;
  } else {
    body =
      `<div class="of-ob-title">Test a dictation</div>` +
      `<p class="of-ob-body">Hold the button, say something, release. The audio goes to your active engine through the same ` +
      `<span class="of-mono">run_remote</span> call the shell uses.</p>` +
      `<div class="of-card of-bench"><div class="of-bench-stage">` +
      `<button class="of-btn of-btn--rec" id="obRecBtn" type="button"><span class="of-rec-dot"></span><span id="obRecLabel">Hold to dictate</span></button>` +
      `<span class="of-wave" id="obWave"><b></b><b></b><b></b><b></b><b></b><b></b><b></b></span>` +
      `<span class="of-bench-timer" id="obTimer"></span>` +
      `<span class="of-spacer" style="flex:1"></span>` +
      `<label class="of-switch"><input type="checkbox" id="obFmt" checked><span class="of-track"></span><span class="of-switch-label">format pass</span></label>` +
      `<button class="of-btn of-btn--ghost of-btn--sm" id="obToneBtn" type="button">send test tone</button>` +
      `</div><div class="of-bench-result of-hidden" id="obResult"></div></div>` +
      `<div class="of-ob-actions"><button class="of-btn of-btn--ghost" data-ob="back">back</button><span class="of-spacer"></span>` +
      `<button class="of-btn of-btn--primary" data-ob="done">finish setup</button></div>`;
  }

  wrap.innerHTML =
    `<div class="of-ob-backdrop"><div class="of-ob" role="dialog" aria-modal="true">` +
    bar + body + `</div></div>`;

  $$("[data-ob]", wrap).forEach((b) =>
    b.addEventListener("click", async () => {
      const a = b.dataset.ob;
      if (a === "next") ob.step = Math.min(4, ob.step + 1);
      if (a === "back") ob.step = Math.max(0, ob.step - 1);
      if (a === "skip") { obClose(true); return; }
      if (a === "done") { obClose(true); toast("setup complete — welcome to OpenFlow"); location.hash = "#/home"; return; }
      if (a === "refresh") { await poll(); }
      if (a === "overlay") { window.open("/ui/overlay.html?demo=1", "of_overlay", "width=420,height=200"); }
      obRender();
    })
  );
  $$("[data-ob-use]", wrap).forEach((b) =>
    b.addEventListener("click", async () => { await switchProvider(b.dataset.obUse); obRender(); })
  );
  const hk = $("#obHkCap", wrap);
  if (hk) hk.addEventListener("click", () => captureHotkey(hk));
  const obRec = $("#obRecBtn", wrap);
  if (obRec) {
    obRec.addEventListener("pointerdown", (e) => { e.preventDefault(); recStart("ob"); });
    obRec.addEventListener("pointerup", () => recStop("ob"));
    obRec.addEventListener("pointerleave", () => recStop("ob"));
  }
  const obTone = $("#obToneBtn", wrap);
  if (obTone) obTone.addEventListener("click", () => sendTone("ob"));
}

/* ── boot ────────────────────────────────────────────────────────────── */

route();
poll();
setInterval(poll, 5000);
if (!localStorage.getItem("of_onboarded_v1")) obOpen();
