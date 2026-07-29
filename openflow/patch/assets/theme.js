
(function () {
  if (window.__OF_THEME_V3__) return;
  window.__OF_THEME_V3__ = true;

  // Exact promo phrases — hide ONLY the matching control, never a parent that
  // also contains Settings / nav chrome (that ate bottom-left Settings before).
  const PROMO_PHRASE =
    /get a free month|upgrade to pro|invite your team|refer a friend|claim student|words remaining|upgrade for unlimited|you get [\d,]+\s*words per week|make flow sound like you|set up different writing styles|try flow in another app|flow works anywhere you type|discover how you use your voice|unlocks in [\d.,]+\s*k?\s*words|your voice profile|flow on mobile|use flow on the go|with your iphone or android|iphone or android|download wispr flow|wispr flow mobile|download wispr|add openflow to linkedin|add flow to linkedin|linkedin/i;

  const CHROME_WORD =
    /\b(Settings|Shortcuts|Help|Dictation|Dictionary|Snippets|Style|Transforms|Scratchpad|OpenFlow)\b/;

  function textOf(el) {
    return (el && el.innerText ? el.innerText : "").replace(/\s+/g, " ").trim();
  }

  function hasChrome(el) {
    const t = textOf(el);
    if (!t) return false;
    // Promo-only free month button: "Get a free month" alone is not chrome
    if (PROMO_PHRASE.test(t) && !CHROME_WORD.test(t)) return false;
    return CHROME_WORD.test(t);
  }

  function isOurs(el) {
    if (!el || el.nodeType !== 1) return true;
    if (el.id === "openflow-speech-engine" || el.id === "openflow-setup") return true;
    return !!(
      el.closest &&
      el.closest("#openflow-speech-engine, #openflow-setup, [data-grok-keep]")
    );
  }

  function markHidden(target) {
    if (!target || target === document.body || isOurs(target)) return;
    // Never hide a node that still carries real chrome labels
    if (hasChrome(target)) return;
    try {
      const r = target.getBoundingClientRect();
      if (r.height > 200 || r.width > 400) return; // stay small — buttons/rows only
    } catch (e) {
      return;
    }
    target.setAttribute("data-grok-hide", "1");
    target.classList.add("grok-flow-hide");
  }

  function hidePass() {
    const body = document.body;
    if (!body) return;
    // Prefer small interactive nodes so we never swallow the Settings footer.
    body.querySelectorAll("button, a, [role='menuitem'], [role='button'], [role='option'], li, span, p, div").forEach((el) => {
      if (isOurs(el)) return;
      const t = textOf(el);
      if (!t || t.length > 100) return;
      if (!PROMO_PHRASE.test(t)) return;
      // If this node also lists Settings etc., skip (mixed container)
      if (hasChrome(el)) return;
      // Hide the tightest control — the button/link itself when possible
      let target = el;
      if (el.matches && !el.matches("button, a, [role='menuitem'], [role='button']")) {
        const btn = el.closest("button, a, [role='menuitem'], [role='button'], li");
        if (btn && !hasChrome(btn) && textOf(btn).length <= 100) target = btn;
      }
      markHidden(target);
    });
    hideInsightsNav();
    hideProfileAvatar();
  }

  // Insights is cloud-only — remove the sidebar entry only (exact label).
  function hideInsightsNav() {
    const side = findSidebar();
    if (!side) return;
    side.querySelectorAll("a, button, [role='button'], div, span, li").forEach((el) => {
      const t = textOf(el);
      if (t !== "Insights") return;
      const row = el.closest("a, button, [role='button'], li") || el;
      if (hasChrome(row) && textOf(row) !== "Insights") return;
      // Force-hide Insights row even if size guard would skip
      if (isOurs(row)) return;
      row.setAttribute("data-grok-hide", "1");
      row.classList.add("grok-flow-hide");
    });
  }

  function forceHide(el) {
    if (!el || isOurs(el)) return;
    // Never touch speech engine UI or setup sheet (or anything we own)
    if (
      el.id === "openflow-speech-engine" ||
      el.id === "openflow-setup" ||
      (el.closest &&
        el.closest("#openflow-speech-engine, #openflow-setup, [data-grok-keep]"))
    )
      return;
    el.setAttribute("data-grok-hide", "1");
    el.classList.add("grok-flow-hide");
    try {
      el.style.setProperty("display", "none", "important");
      el.style.setProperty("visibility", "hidden", "important");
      el.style.setProperty("pointer-events", "none", "important");
      el.style.setProperty("opacity", "0", "important");
      el.style.setProperty("width", "0", "important");
      el.style.setProperty("height", "0", "important");
      el.style.setProperty("min-width", "0", "important");
      el.style.setProperty("min-height", "0", "important");
      el.style.setProperty("margin", "0", "important");
      el.style.setProperty("padding", "0", "important");
      el.style.setProperty("overflow", "hidden", "important");
      el.style.setProperty("border", "none", "important");
      el.setAttribute("aria-hidden", "true");
      el.setAttribute("tabindex", "-1");
    } catch (e) {}
  }

  // Top-left above the "OpenFlow" brand: keep leftmost control (sidebar),
  // force-hide every other icon-sized control (the profile circle) + flyout.
  function hideProfileAvatar() {
    // Locate brand word so we target icons *above* it (not nav icons below).
    let brandTop = 64;
    let brandLeft = 12;
    document.querySelectorAll("div, span, a, p").forEach((el) => {
      const t = textOf(el);
      if (t !== "OpenFlow") return;
      if (el.children && el.children.length > 3) return;
      try {
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.width < 160 && r.left < 280 && r.top < 200) {
          brandTop = r.top;
          brandLeft = r.left;
        }
      } catch (e) {}
    });

    const cands = [];
    document.querySelectorAll("button, [role='button'], a, div, img, span").forEach((el) => {
      if (isOurs(el)) return;
      let r;
      try {
        r = el.getBoundingClientRect();
      } catch (e) {
        return;
      }
      // Must sit above the OpenFlow brand, in the top-left strip
      if (r.bottom > brandTop - 1) return;
      if (r.top < brandTop - 72) return;
      if (r.left < 0 || r.left > brandLeft + 120) return;
      if (r.width < 18 || r.height < 18) return;
      if (r.width > 48 || r.height > 48) return;
      // Roughly square (icon / circle)
      if (Math.abs(r.width - r.height) > 14) return;
      const t = textOf(el);
      // Skip labeled chrome (plan pill text, nav, etc.) — only icon/avatar circles
      if (t && t.length > 2) return;
      // Prefer clickable / image nodes
      const tag = (el.tagName || "").toLowerCase();
      const clickable =
        tag === "button" ||
        tag === "img" ||
        tag === "a" ||
        el.getAttribute("role") === "button" ||
        (el.tabIndex != null && el.tabIndex >= 0);
      let cursor = "";
      try {
        cursor = window.getComputedStyle(el).cursor || "";
      } catch (e) {}
      if (!clickable && cursor !== "pointer" && tag !== "div") return;
      // Skip pure SVG logo marks that are part of the wordmark row below
      cands.push({ el: el, left: r.left, top: r.top, w: r.width });
    });

    if (cands.length) {
      // Dedupe nested: keep outermost (largest) when one contains another
      const outer = [];
      cands.sort((a, b) => a.left - b.left || a.top - b.top);
      cands.forEach((c) => {
        if (outer.some((o) => o.el.contains(c.el))) return;
        // if c contains an existing outer, replace
        for (let i = outer.length - 1; i >= 0; i--) {
          if (c.el.contains(outer[i].el)) outer.splice(i, 1);
        }
        outer.push(c);
      });
      outer.sort((a, b) => a.left - b.left || a.top - b.top);
      // Keep leftmost = sidebar collapse; hide everything else
      for (let i = 1; i < outer.length; i++) {
        forceHide(outer[i].el);
        outer[i].el.querySelectorAll("*").forEach((n) => forceHide(n));
      }
    }

    // Extra: any circular img above the brand
    document.querySelectorAll("img").forEach((img) => {
      if (isOurs(img)) return;
      let r;
      try {
        r = img.getBoundingClientRect();
      } catch (e) {
        return;
      }
      if (r.bottom > brandTop - 1 || r.top < brandTop - 72) return;
      if (r.left < 0 || r.left > brandLeft + 120) return;
      if (r.width < 18 || r.width > 48) return;
      forceHide(img);
      const wrap = img.closest("button, [role='button'], div, a");
      if (wrap && !hasChrome(wrap)) forceHide(wrap);
    });

    hideProfileFlyout();
  }

  // Account / download panel when profile is clicked (often top-right popover).
  function hideProfileFlyout() {
    document.querySelectorAll("div, section, [role='dialog'], [role='menu'], [role='listbox']").forEach((el) => {
      if (isOurs(el)) return;
      const t = textOf(el);
      if (!t || t.length < 8 || t.length > 500) return;
      const isFly =
        /download wispr|wispr flow mobile|wispr flow|get a free month|flow on mobile|sign out|manage subscription|plans and billing|student plan|invite your team/i.test(
          t
        ) && !/dictation|dictionary|scratchpad|speech engine|sign in to start/i.test(t);
      if (!isFly) return;
      try {
        const r = el.getBoundingClientRect();
        if (r.width < 140 || r.width > 520 || r.height < 60 || r.height > 700) return;
        if (r.top > window.innerHeight * 0.6) return;
      } catch (e) {
        return;
      }
      forceHide(el);
    });
  }

  function findSidebar() {
    const nodes = document.querySelectorAll(
      "aside, nav, [class*='sidebar' i], [class*='Sidebar' i]"
    );
    let best = null;
    let score = 0;
    nodes.forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.width < 160 || r.width > 360 || r.height < 240) return;
      if (r.left > 80) return;
      const s = r.height + (r.width > 200 ? 40 : 0);
      if (s > score) {
        score = s;
        best = el;
      }
    });
    return best;
  }

  function findSpeechAnchor(side) {
    // Insert AFTER the last primary nav row (Scratchpad), NEVER at the absolute
    // end of the sidebar — that used to push Settings/footer chrome off-screen.
    const labels = ["Scratchpad", "Transforms", "Style", "Snippets", "Dictionary", "Insights", "Dictation"];
    let best = null;
    side.querySelectorAll("a, button, [role='button'], div, span").forEach((el) => {
      const t = (el.innerText || "").replace(/\s+/g, " ").trim();
      if (!labels.includes(t)) return;
      // Prefer the outer clickable row
      const row = el.closest("a, button, [role='button'], li") || el;
      best = row;
    });
    // Prefer Scratchpad specifically if present
    side.querySelectorAll("a, button, [role='button'], div, span").forEach((el) => {
      const t = (el.innerText || "").replace(/\s+/g, " ").trim();
      if (t === "Scratchpad") best = el.closest("a, button, [role='button'], li") || el;
    });
    return best;
  }

  function unhideSpeech(el) {
    if (!el) return;
    el.classList.remove("grok-flow-hide");
    el.removeAttribute("data-grok-hide");
    el.removeAttribute("aria-hidden");
    el.removeAttribute("tabindex");
    try {
      [
        "display",
        "visibility",
        "pointer-events",
        "opacity",
        "width",
        "height",
        "min-width",
        "min-height",
        "margin",
        "padding",
        "overflow",
        "border",
      ].forEach((p) => el.style.removeProperty(p));
    } catch (e) {}
  }

  // Cheap: plan pill is already nulled in hub JS. Only hide rare class matches.
  function clearPlanBadge() {
    document
      .querySelectorAll(
        '[class*="basicBadge"], [class*="planPill"], [class*="planBadge"]'
      )
      .forEach((el) => {
        if (isOurs(el)) return;
        forceHide(el);
      });
  }

  let _speechGeom = "";
  let _settingsBottomCache = 88;
  let _settingsBottomAt = 0;

  // Position body-level speech host strictly inside the left column.
  function placeSpeechHost(box) {
    if (!box || !document.body) return;
    if (box.parentNode !== document.body) {
      document.body.appendChild(box);
    }
    let left = 12;
    let width = 200;
    let bottom = _settingsBottomCache;
    const side = findSidebar();
    if (side) {
      try {
        const r = side.getBoundingClientRect();
        if (r.width > 100) {
          left = Math.round(r.left + 12);
          width = Math.round(Math.max(150, Math.min(r.width - 24, 228)));
        }
      } catch (e) {}
    }
    // Refresh Settings anchor at most every 5s (full DOM walk is expensive)
    const now = Date.now();
    if (now - _settingsBottomAt > 5000) {
      _settingsBottomAt = now;
      const sideEl = side;
      const roots = sideEl ? [sideEl] : [document.body];
      roots.forEach((root) => {
        if (!root) return;
        root.querySelectorAll("a, button, [role='button']").forEach((el) => {
          if (isOurs(el)) return;
          if (textOf(el) !== "Settings") return;
          try {
            const r = el.getBoundingClientRect();
            if (r.width < 40 || r.left > 320) return;
            if (r.bottom < window.innerHeight * 0.45) return;
            const fromBottom = window.innerHeight - r.top + 8;
            if (fromBottom > 48 && fromBottom < 300) {
              bottom = fromBottom;
              _settingsBottomCache = fromBottom;
            }
          } catch (e) {}
        });
      });
    } else {
      bottom = _settingsBottomCache;
    }
    const key = left + "|" + width + "|" + bottom;
    if (key === _speechGeom && box.style.position === "fixed") return;
    _speechGeom = key;
    box.style.setProperty("position", "fixed", "important");
    box.style.setProperty("left", left + "px", "important");
    box.style.setProperty("width", width + "px", "important");
    box.style.setProperty("max-width", width + "px", "important");
    box.style.setProperty("bottom", bottom + "px", "important");
    box.style.setProperty("right", "auto", "important");
    box.style.setProperty("top", "auto", "important");
    box.style.setProperty("z-index", "2147483000", "important");
    box.style.setProperty("overflow", "hidden", "important");
    box.style.setProperty("box-sizing", "border-box", "important");
  }

  function mountSpeech() {
    if (!document.body) return false;
    let box = document.getElementById("openflow-speech-engine");
    if (box) {
      // Already mounted outside React — only re-place if needed
      if (box.parentNode !== document.body) {
        document.body.appendChild(box);
        unhideSpeech(box);
      }
      placeSpeechHost(box);
      return true;
    }

    box = document.createElement("div");
    box.id = "openflow-speech-engine";
    box.setAttribute("data-grok-keep", "1");
    box.innerHTML =
      '<div class="of-label">Speech engine</div>' +
      '<div class="of-seg" role="radiogroup" aria-label="Speech engine">' +
      '<button type="button" data-p="grok"><span class="of-dot"></span>Grok</button>' +
      '<button type="button" data-p="chatgpt"><span class="of-dot"></span>GPT</button>' +
      '<button type="button" data-p="claude"><span class="of-dot"></span>Claude</button>' +
      '<button type="button" data-p="local"><span class="of-dot"></span>Local</button>' +
      "</div>" +
      '<div class="of-meta" id="of-meta">…</div>';

    placeSpeechHost(box);

    const meta = box.querySelector("#of-meta");
    const btns = Array.from(box.querySelectorAll("button[data-p]"));
    const LABELS = {
      grok: "Grok",
      chatgpt: "ChatGPT",
      claude: "Claude",
      local: "Local",
    };
    const SHIM = "http://127.0.0.1:18765";

    function mark(id) {
      btns.forEach((b) => b.classList.toggle("of-on", b.getAttribute("data-p") === id));
    }

    function setMeta(text, err) {
      meta.textContent = text;
      meta.classList.toggle("of-err", !!err);
    }

    async function api(path, opts) {
      const r = await fetch(SHIM + path, Object.assign({ cache: "no-store" }, opts || {}));
      const text = await r.text();
      let j = null;
      try {
        j = text ? JSON.parse(text) : {};
      } catch (e) {
        throw new Error("Bad response from engine");
      }
      if (!r.ok) throw new Error((j && j.error) || "HTTP " + r.status);
      return j;
    }

    function pstate(st) {
      if (st.ready && st.stt_capable !== false) return "ready";
      if (st.auth_path && st.stt_capable === false) return "limited";
      if (st.ready) return "limited";
      return "login";
    }

    function paintDots(j) {
      btns.forEach((b) => {
        const pid = b.getAttribute("data-p");
        const st = ((j && j.providers) || {})[pid] || {};
        const ps = j ? pstate(st) : "login";
        const dot = b.querySelector(".of-dot");
        if (dot) {
          dot.className =
            "of-dot" + (ps === "ready" ? " of-ok" : ps === "limited" ? " of-warn" : "");
        }
        b.style.opacity = ps === "login" ? "0.55" : "1";
        b.title = (st.detail || pid) + " — click to use for dictation";
      });
    }

    async function refresh() {
      try {
        const j = await api("/health");
        const id = j.provider || "grok";
        mark(id);
        paintDots(j);
        const p = (j.providers && j.providers[id]) || {};
        const label = LABELS[id] || id;
        const ps = pstate(p);
        if (ps === "ready") {
          setMeta("Active: " + label + " · ready", false);
        } else if (ps === "limited") {
          setMeta("Active: " + label + " · limited — " + (p.detail || "check app"), true);
        } else {
          setMeta("Active: " + label + " · needs login — " + (p.detail || ""), true);
        }
      } catch (e) {
        paintDots(null);
        setMeta("Engine offline — OpenFlow shim not running", true);
      }
    }

    btns.forEach((b) => {
      b.addEventListener("click", async (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const id = b.getAttribute("data-p");
        const label = LABELS[id] || id;
        mark(id);
        setMeta("Switching to " + label + "…", false);
        try {
          const body = JSON.stringify({ provider: id });
          const headers = { "Content-Type": "application/json" };
          try {
            await api("/v1/config", { method: "PUT", headers, body });
          } catch (e1) {
            await api("/v1/config", { method: "POST", headers, body });
          }
          const j = await api("/health");
          if ((j.provider || "") !== id) {
            setMeta("Switch did not stick (still " + (j.provider || "?") + ")", true);
            mark(j.provider || "grok");
            return;
          }
          setMeta("Active: " + label + " · ready", false);
        } catch (e) {
          setMeta("Can't reach engine — shim offline", true);
        }
      });
    });

    const setupLink = document.createElement("button");
    setupLink.type = "button";
    setupLink.id = "of-setup-link";
    setupLink.textContent = "Sign in / manage engines";
    setupLink.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      showSetupPanel();
    });
    box.appendChild(setupLink);

    refresh();
    // Health poll only — no layout thrash
    setInterval(refresh, 15000);
    window.addEventListener("resize", () => {
      _speechGeom = "";
      _settingsBottomAt = 0;
      placeSpeechHost(box);
    });
    return true;
  }

  // ── Connect engines (first-run + manual) ──────────────────────────
  // INLINE UI (not iframe). Electron CSP often blanks iframes to localhost
  // from asar file:// — white box with no content. Render in-hub instead.
  const SHIM = "http://127.0.0.1:18765";
  let _setupBusy = null;
  let _setupTimer = null;

  function hideSetupPanel() {
    if (_setupTimer) {
      clearInterval(_setupTimer);
      _setupTimer = null;
    }
    const host = document.getElementById("openflow-setup");
    if (host) host.remove();
  }

  function _esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  async function _shim(path, opts) {
    const r = await fetch(SHIM + path, Object.assign({ cache: "no-store" }, opts || {}));
    const t = await r.text();
    try {
      return t ? JSON.parse(t) : {};
    } catch (e) {
      throw new Error("OpenFlow shim not responding");
    }
  }

  function _paintSetup(st) {
    const body = document.getElementById("of-setup-body");
    const banner = document.getElementById("of-setup-banner");
    const doneBtn = document.getElementById("of-setup-done");
    if (!body) return;

    // Preserve Local form while typing (refresh would wipe inputs)
    const draft = {
      url: (document.getElementById("of-local-url") || {}).value,
      model: (document.getElementById("of-local-model") || {}).value,
      key: (document.getElementById("of-local-key") || {}).value,
      focus: null,
    };
    try {
      const ae = document.activeElement;
      if (ae && ae.id && ae.id.indexOf("of-local-") === 0) draft.focus = ae.id;
    } catch (e) {}

    const map = (st && st.providers) || {};
    const names = {
      grok: "Grok",
      chatgpt: "ChatGPT",
      claude: "Claude",
      local: "Local",
    };
    const idle = {
      grok: "Uses your xAI / SuperGrok login",
      chatgpt: "Uses your ChatGPT plan",
      claude: "Uses Claude Desktop (sign in once)",
      local: "OpenAI-compatible Whisper on your machine or LAN",
    };
    let anyReady = false;
    let waiting = null;
    let html = "";
    ["grok", "chatgpt", "claude", "local"].forEach((id) => {
      const p = map[id] || {};
      const ready = !!(p.ready && p.stt_capable !== false);
      if (ready) anyReady = true;
      const flow = p.flow || {};
      const phase = flow.phase || (ready ? "ready" : "idle");
      const isWait =
        id !== "local" &&
        !ready &&
        (phase === "browser" ||
          phase === "waiting" ||
          phase === "app" ||
          _setupBusy === id);
      if (isWait) waiting = names[id];
      let msg = idle[id];
      if (ready) msg = "Connected — ready to dictate";
      else if (isWait) msg = flow.detail || "Sign in in the other window, then come back";
      else if (flow.detail) msg = flow.detail;
      else if (p.health_detail) msg = p.health_detail;

      const border = ready
        ? "1px solid rgba(23,138,75,0.3)"
        : isWait || (id === "local" && phase === "error")
          ? "1px solid rgba(196,90,18,0.3)"
          : "1px solid rgba(40,30,20,0.09)";
      const cardBg =
        ready ? "#f3fbf6" : isWait || (id === "local" && phase === "error") ? "#fffaf5" : "#fff";

      if (id === "local") {
        const urlVal =
          draft.url != null && draft.url !== ""
            ? draft.url
            : p.url || "http://127.0.0.1:8080/v1/audio/transcriptions";
        const modelVal =
          draft.model != null && draft.model !== ""
            ? draft.model
            : p.model || "whisper-1";
        const keyVal = draft.key != null ? draft.key : "";
        const keyPh = p.has_api_key ? "•••••••• (saved — leave blank to keep)" : "optional";
        let localBtn = ready ? "Save & retest" : "Save & test";
        if (_setupBusy === "local") localBtn = "Testing…";
        html +=
          '<div id="of-local-card" style="background:' +
          cardBg +
          ";border:" +
          border +
          ';border-radius:16px;padding:16px;margin:0 0 10px">' +
          '<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin:0 0 10px">' +
          '<div style="font-size:16px;font-weight:700;display:flex;align-items:center;gap:8px">' +
          '<span style="width:9px;height:9px;border-radius:50%;background:' +
          (ready ? "#178a4b" : phase === "error" ? "#ff6b2c" : "#cfc8bf") +
          '"></span>Local</div>' +
          (ready
            ? '<span style="font-size:12px;font-weight:700;color:#178a4b">Ready</span>'
            : '<span style="font-size:12px;font-weight:600;color:#8a837a">Needs URL</span>') +
          "</div>" +
          '<div style="font-size:12.5px;line-height:1.4;color:' +
          (ready ? "#178a4b" : phase === "error" ? "#c45a12" : "#5c564e") +
          ';margin:0 0 12px;font-weight:' +
          (ready || phase === "error" ? "600" : "400") +
          '">' +
          _esc(msg) +
          "</div>" +
          '<label style="display:block;font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;opacity:.55;margin:0 0 4px">Whisper URL</label>' +
          '<input id="of-local-url" type="url" spellcheck="false" autocomplete="off" value="' +
          _esc(urlVal) +
          '" placeholder="http://127.0.0.1:8080/v1/audio/transcriptions" style="width:100%;box-sizing:border-box;margin:0 0 10px;padding:10px 12px;border-radius:10px;border:1px solid rgba(40,30,20,.12);font:inherit;font-size:13px;background:#fff;color:inherit"/>' +
          '<div style="display:flex;gap:8px;margin:0 0 10px">' +
          '<div style="flex:1;min-width:0">' +
          '<label style="display:block;font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;opacity:.55;margin:0 0 4px">Model</label>' +
          '<input id="of-local-model" type="text" spellcheck="false" autocomplete="off" value="' +
          _esc(modelVal) +
          '" placeholder="whisper-1" style="width:100%;box-sizing:border-box;padding:10px 12px;border-radius:10px;border:1px solid rgba(40,30,20,.12);font:inherit;font-size:13px;background:#fff;color:inherit"/>' +
          "</div>" +
          '<div style="flex:1;min-width:0">' +
          '<label style="display:block;font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;opacity:.55;margin:0 0 4px">API key</label>' +
          '<input id="of-local-key" type="password" spellcheck="false" autocomplete="off" value="' +
          _esc(keyVal) +
          '" placeholder="' +
          _esc(keyPh) +
          '" style="width:100%;box-sizing:border-box;padding:10px 12px;border-radius:10px;border:1px solid rgba(40,30,20,.12);font:inherit;font-size:13px;background:#fff;color:inherit"/>' +
          "</div></div>" +
          '<button type="button" id="of-local-save" ' +
          (_setupBusy === "local" ? "disabled " : "") +
          'style="appearance:none;border:0;cursor:pointer;font:inherit;font-weight:700;font-size:13px;width:100%;' +
          "padding:11px 16px;border-radius:999px;background:#ff6b2c;color:#fff\">" +
          _esc(localBtn) +
          "</button>" +
          '<div style="margin-top:8px;font-size:11px;line-height:1.4;color:#8a837a">Any OpenAI-compatible <code style="font-size:10px">/v1/audio/transcriptions</code> server (faster-whisper, llama.cpp, …)</div>' +
          "</div>";
        return;
      }

      let label = "Connect";
      let dis = false;
      let bg = "#ff6b2c";
      let color = "#fff";
      if (ready) {
        label = "Connected ✓";
        dis = true;
        bg = "#e8f7ee";
        color = "#178a4b";
      } else if (isWait) {
        label = "Waiting…";
        dis = true;
        bg = "#fff6ed";
        color = "#c45a12";
      }
      html +=
        '<div style="background:' +
        cardBg +
        ";border:" +
        border +
        ';border-radius:16px;padding:16px;margin:0 0 10px">' +
        '<div style="display:flex;align-items:center;justify-content:space-between;gap:12px">' +
        '<div style="font-size:16px;font-weight:700;display:flex;align-items:center;gap:8px">' +
        '<span style="width:9px;height:9px;border-radius:50%;background:' +
        (ready ? "#178a4b" : isWait ? "#ff6b2c" : "#cfc8bf") +
        '"></span>' +
        _esc(names[id]) +
        "</div>" +
        '<button type="button" data-of-connect="' +
        id +
        '" ' +
        (dis ? "disabled " : "") +
        'style="appearance:none;border:0;cursor:pointer;font:inherit;font-weight:700;font-size:13px;' +
        "padding:11px 16px;border-radius:999px;background:" +
        bg +
        ";color:" +
        color +
        '">' +
        _esc(label) +
        "</button></div>" +
        '<div style="margin-top:8px;font-size:13px;line-height:1.4;color:' +
        (ready ? "#178a4b" : isWait ? "#c45a12" : "#5c564e") +
        ';font-weight:' +
        (ready || isWait ? "600" : "400") +
        '">' +
        _esc(msg) +
        "</div></div>";
    });
    body.innerHTML = html;

    // Restore focus after re-paint
    if (draft.focus) {
      try {
        const el = document.getElementById(draft.focus);
        if (el) {
          el.focus();
          if (typeof el.selectionStart === "number") {
            const len = el.value.length;
            el.setSelectionRange(len, len);
          }
        }
      } catch (e) {}
    }

    if (banner) {
      if (waiting) {
        banner.style.display = "block";
        banner.innerHTML =
          "<b>Look for the sign-in window</b><br><span style='font-weight:500;opacity:.9'>Sign in to " +
          _esc(waiting) +
          ", then return here. This updates by itself.</span>";
      } else if (!(st && st.any_ready) && st && st.error) {
        banner.style.display = "block";
        banner.textContent = String(st.error);
      } else {
        banner.style.display = "none";
      }
    }
    if (doneBtn) {
      doneBtn.disabled = !anyReady;
      doneBtn.textContent = anyReady ? "Start dictating →" : "Connect one above first";
      doneBtn.style.opacity = anyReady ? "1" : "0.45";
    }
  }

  async function _refreshSetup() {
    try {
      const st = await _shim("/v1/auth/status");
      // Don't clobber Local form mid-keystroke unless we're testing
      const typing =
        !_setupBusy &&
        document.activeElement &&
        document.activeElement.id &&
        document.activeElement.id.indexOf("of-local-") === 0;
      if (!typing) _paintSetup(st);
      else {
        // Still refresh footer ready state
        const doneBtn = document.getElementById("of-setup-done");
        let anyReady = false;
        const map = (st && st.providers) || {};
        ["grok", "chatgpt", "claude", "local"].forEach((id) => {
          const p = map[id] || {};
          if (p.ready && p.stt_capable !== false) anyReady = true;
        });
        if (doneBtn) {
          doneBtn.disabled = !anyReady;
          doneBtn.textContent = anyReady ? "Start dictating →" : "Connect one above first";
          doneBtn.style.opacity = anyReady ? "1" : "0.45";
        }
      }
      if (_setupBusy) {
        const p = (st.providers || {})[_setupBusy];
        if (
          p &&
          (p.ready ||
            (p.flow && ["error", "need_cli", "ready"].indexOf(p.flow.phase) >= 0))
        ) {
          _setupBusy = null;
        }
      }
    } catch (e) {
      const body = document.getElementById("of-setup-body");
      const banner = document.getElementById("of-setup-banner");
      if (body) {
        body.innerHTML =
          '<div style="padding:16px;border-radius:14px;background:#fff;border:1px solid rgba(40,30,20,.1);color:#5c564e;font-size:14px;line-height:1.45">' +
          "<b>Can't reach OpenFlow</b><br>Start the app fully (shim on port 18765), then open this again." +
          "</div>";
      }
      if (banner) {
        banner.style.display = "block";
        banner.textContent = "OpenFlow shim isn't running";
      }
    }
  }

  function showSetupPanel() {
    hideSetupPanel();
    clearLocalInsights();
    const host = document.createElement("div");
    host.id = "openflow-setup";
    host.setAttribute("data-grok-keep", "1");
    host.style.cssText =
      "position:fixed;inset:0;z-index:9999;background:rgba(20,14,8,0.32);" +
      "display:flex;align-items:center;justify-content:center;padding:20px;" +
      "backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);" +
      "font-family:Figtree,Segoe UI,system-ui,sans-serif;color:#1a1714;";
    host.addEventListener("click", (ev) => {
      if (ev.target === host) hideSetupPanel();
    });
    const panel = document.createElement("div");
    panel.style.cssText =
      "width:min(480px,100%);max-height:min(720px,92vh);overflow:auto;" +
      "background:#faf9f7;border-radius:20px;padding:28px 24px 22px;" +
      "box-shadow:0 24px 80px rgba(20,14,8,0.25);";
    panel.innerHTML =
      '<div style="font-size:11px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#ff6b2c;margin:0 0 8px">Speech engines</div>' +
      '<div style="font-size:26px;font-weight:720;letter-spacing:-.03em;line-height:1.15;margin:0 0 8px">Connect a speech engine</div>' +
      '<div style="font-size:14.5px;line-height:1.5;color:#5c564e;margin:0 0 6px">Cloud: sign in with Grok / ChatGPT / Claude. Local: paste your Whisper server URL.</div>' +
      '<div style="font-size:12px;color:#8a837a;margin:0 0 16px">Passwords never go through OpenFlow — cloud logins open in their own app/browser</div>' +
      '<div id="of-setup-banner" style="display:none;background:#fff6ed;color:#c45a12;border:1px solid rgba(196,90,18,.2);border-radius:12px;padding:12px 14px;margin:0 0 12px;font-size:13px;line-height:1.4"></div>' +
      '<div id="of-setup-body"><div style="color:#8a837a;font-size:13px">Loading…</div></div>' +
      '<button type="button" id="of-setup-done" disabled style="width:100%;margin-top:14px;appearance:none;border:0;border-radius:999px;padding:14px;font:inherit;font-weight:700;font-size:15px;background:#1a1714;color:#fff;cursor:pointer">Connect one above first</button>' +
      '<button type="button" id="of-setup-skip" style="width:100%;margin-top:6px;appearance:none;border:0;background:transparent;color:#8a837a;font:inherit;font-size:13px;padding:10px;cursor:pointer">Not now</button>' +
      '<div style="margin-top:14px;font-size:11px;color:#8a837a;line-height:1.4">Grok · ChatGPT · Claude · or any OpenAI-compatible local Whisper server.</div>';
    host.appendChild(panel);
    document.body.appendChild(host);

    panel.addEventListener("click", async (ev) => {
      // Local: save URL/model/key and probe
      const localSave = ev.target.closest("#of-local-save");
      if (localSave) {
        if (localSave.disabled) return;
        const urlEl = document.getElementById("of-local-url");
        const modelEl = document.getElementById("of-local-model");
        const keyEl = document.getElementById("of-local-key");
        const url = (urlEl && urlEl.value ? urlEl.value : "").trim();
        if (!url) {
          if (urlEl) urlEl.focus();
          return;
        }
        _setupBusy = "local";
        localSave.disabled = true;
        localSave.textContent = "Testing…";
        const body = { provider: "local", url: url };
        const model = modelEl && modelEl.value != null ? String(modelEl.value).trim() : "";
        body.model = model;
        // Only send api_key if user typed something (blank keeps existing)
        if (keyEl && keyEl.value) body.api_key = keyEl.value;
        try {
          const res = await _shim("/v1/auth/connect", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
          if (res && res.ok === false && res.error) {
            const b = document.getElementById("of-setup-banner");
            if (b) {
              b.style.display = "block";
              b.textContent = String(res.error);
            }
          }
        } catch (e) {
          const b = document.getElementById("of-setup-banner");
          if (b) {
            b.style.display = "block";
            b.textContent = "Could not reach OpenFlow shim";
          }
        }
        _setupBusy = null;
        _refreshSetup();
        return;
      }

      const btn = ev.target.closest("[data-of-connect]");
      if (!btn || btn.disabled) return;
      const id = btn.getAttribute("data-of-connect");
      if (id === "local") return; // local uses Save & test only
      _setupBusy = id;
      btn.disabled = true;
      btn.textContent = "Opening…";
      try {
        await _shim("/v1/auth/connect", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider: id }),
        });
      } catch (e) {
        _setupBusy = null;
      }
      _refreshSetup();
    });
    document.getElementById("of-setup-skip").onclick = async () => {
      try {
        await _shim("/v1/auth/skip", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
      } catch (e) {}
      hideSetupPanel();
    };
    document.getElementById("of-setup-done").onclick = async () => {
      try {
        await _shim("/v1/auth/complete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
      } catch (e) {}
      hideSetupPanel();
    };

    _refreshSetup();
    _setupTimer = setInterval(_refreshSetup, 2000);
  }

  function maybeFirstRunSetup() {
    fetch(SHIM + "/v1/auth/status", { cache: "no-store" })
      .then((r) => r.json())
      .then((j) => {
        if (j && j.needs_onboarding) showSetupPanel();
      })
      .catch(() => {});
  }

  // Local Insights: cloud Insights needs a real Wispr account. When the user
  // opens the Insights sidebar item, overlay a local stats view from the shim
  // (computed from flow.sqlite on disk). Remove the overlay when they leave.
  function findMainColumn() {
    const side = findSidebar();
    const all = Array.from(document.querySelectorAll("main, [class*='content' i], [class*='Content' i], div"));
    let best = null, score = 0;
    all.forEach((el) => {
      if (side && (el === side || side.contains(el))) return;
      const r = el.getBoundingClientRect();
      if (r.width < 320 || r.height < 280) return;
      const s = r.width * r.height;
      if (s > score && r.left > 120) {
        score = s;
        best = el;
      }
    });
    return best;
  }

  function clearLocalInsights() {
    /* Insights nav removed — no overlay */
  }

  // Profile/menu items only (exact-ish). Never climbs into Settings footer.
  const CLOUD_ROW_RE =
    /^(Team|Account|Plans and Billing|Plans & Billing|Data and Privacy|Data & Privacy|Refer a friend|Upgrade|Upgrade to Pro|Manage subscription|Sign out|Log out|Invite your team|Claim student|Student plan|Enterprise|Get a free month|Download Wispr Flow|Wispr Flow Mobile|Wispr Flow|Flow on mobile|Insights)$/i;

  function stripCloudRows() {
    document.querySelectorAll(
      "button, a, [role='menuitem'], [role='option'], [role='button'], li"
    ).forEach((el) => {
      if (isOurs(el)) return;
      const t = textOf(el);
      if (!t || t.length > 60) return;
      if (!CLOUD_ROW_RE.test(t) && !PROMO_PHRASE.test(t)) return;
      if (hasChrome(el)) return; // keep Settings etc.
      markHidden(el);
    });
    hideInsightsNav();
    hideProfileAvatar();
  }

  function boot() {
    try {
      // Lightweight boot: no MutationObserver (React re-renders made that laggy).
      // Binary asar patches do the permanent chrome removals.
      let n = 0;
      const tick = () => {
        const speech = mountSpeech();
        if (speech || n++ > 40) {
          // One-shot profile/badge cleanup after UI settles
          clearPlanBadge();
          hideProfileAvatar();
          return;
        }
        setTimeout(tick, 250);
      };
      tick();
      setTimeout(maybeFirstRunSetup, 1500);
      // Rare safety: re-attach speech host if something removed it (not every 2s)
      setInterval(() => {
        const box = document.getElementById("openflow-speech-engine");
        if (!box || box.parentNode !== document.body) mountSpeech();
        else placeSpeechHost(box);
      }, 12000);
    } catch (e) {
      console.warn("[OpenFlow]", e);
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
