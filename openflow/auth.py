"""Launch user-owned login flows for speech engines.

OpenFlow never ships credentials. Each machine connects its own memberships:
  - Grok:     `grok login --oauth` → ~/.grok/auth.json
  - ChatGPT:  `codex login`        → ~/.codex/auth.json
  - Claude:   open Claude Desktop  → session cookies (no CLI STT login)

Normie UX: one button → browser/app opens → we poll /health until ready.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("openflow.auth_login")

# In-memory session of the last connect attempt per provider.
_lock = threading.Lock()
_state: dict[str, dict[str, Any]] = {}


def _home() -> Path:
    return Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or Path.home())


def _which_windows(names: list[str]) -> str | None:
    """Find an executable on Windows PATH or known install locations."""
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    home = _home()
    candidates: list[Path] = []
    # Grok CLI (Windows install)
    candidates += [
        home / ".grok" / "bin" / "grok.exe",
        home / ".grok" / "bin" / "grok",
        home / "AppData" / "Local" / "Programs" / "grok" / "grok.exe",
    ]
    # Codex
    candidates += [
        home / "AppData" / "Roaming" / "npm" / "codex.cmd",
        home / "AppData" / "Roaming" / "npm" / "codex",
        home / ".local" / "bin" / "codex",
        home / ".codex" / "bin" / "codex.exe",
    ]
    la = os.environ.get("LOCALAPPDATA")
    if la:
        candidates.append(Path(la) / "Programs" / "grok" / "grok.exe")
    for c in candidates:
        try:
            if c.is_file():
                return str(c)
        except OSError:
            continue
    return None


def _spawn_detached(cmd: list[str], *, cwd: str | None = None) -> int | None:
    """Start a process without blocking the shim. Returns PID or None."""
    log.info("spawn login: %s", " ".join(cmd))
    # On Windows: DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP so OAuth can
    # open a browser without tying the shim to a console. Do NOT use
    # CREATE_NO_WINDOW — that blocks browser launch for some CLIs.
    creation = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0
    try:
        p = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation,
            start_new_session=(sys.platform != "win32"),
        )
        return p.pid
    except Exception as e:
        log.exception("spawn failed: %s", e)
        raise


def _open_url(url: str) -> None:
    if sys.platform == "win32":
        os.startfile(url)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", url])
    else:
        subprocess.Popen(["xdg-open", url])


def _open_claude_desktop() -> tuple[bool, str]:
    """Try to launch Claude Desktop; always return copy the user can follow."""
    la = os.environ.get("LOCALAPPDATA") or ""
    pf = os.environ.get("ProgramFiles") or r"C:\Program Files"
    candidates = [
        Path(la) / "AnthropicClaude" / "claude.exe",
        Path(la) / "Programs" / "Claude" / "Claude.exe",
        Path(pf) / "Claude" / "Claude.exe",
        Path(pf) / "AnthropicClaude" / "claude.exe",
    ]
    for c in candidates:
        if c.is_file():
            try:
                _spawn_detached([str(c)])
                return True, "Sign into Claude Desktop, then come back here."
            except Exception as e:
                return False, f"Couldn't open Claude Desktop: {e}"
    try:
        _open_url("https://claude.ai/download")
        return True, "Install Claude Desktop, sign in once, then come back here."
    except Exception:
        return False, "Install Claude Desktop, sign in once, then come back here."


def _install_help(provider: str) -> str:
    """Open a download / product page and return plain-language copy."""
    urls = {
        "grok": "https://x.ai/grok",
        "chatgpt": "https://chatgpt.com/",
        "claude": "https://claude.ai/download",
    }
    tips = {
        "grok": "Install the Grok app from x.ai, open it once, then tap Connect again.",
        "chatgpt": "Open ChatGPT / Codex, sign in with your plan, then tap Connect again.",
        "claude": "Install Claude Desktop, sign in once, then come back here.",
    }
    try:
        _open_url(urls.get(provider, "https://x.ai"))
    except Exception:
        pass
    return tips.get(provider, "Install the app, then try again.")


def start_connect(
    provider: str,
    *,
    help: bool = False,
    url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Begin a connect flow. Idempotent restarts the attempt.

    help=True → only open install / product page (Get the app).

    Local STT: pass url / model / api_key to save and probe. Without a URL
    change, re-probes whatever is already in config (does not fake ready).
    """
    provider = (provider or "").strip().lower()
    if provider not in ("grok", "chatgpt", "claude", "local"):
        return {"ok": False, "error": f"unknown provider: {provider}"}

    if provider == "local":
        # Local Whisper — no OAuth. Save endpoint settings, then probe.
        from openflow.config import load_config, save_config

        loc: dict[str, Any] = {"enabled": True}
        if url is not None and str(url).strip():
            loc["url"] = str(url).strip()
        if model is not None:
            loc["model"] = str(model).strip()
        if api_key is not None:
            # Allow empty string to clear a previous key
            loc["api_key"] = str(api_key).strip()

        try:
            save_config({"provider": "local", "providers": {"local": loc}})
        except Exception as e:
            log.exception("save local config")
            with _lock:
                _state[provider] = {
                    "provider": provider,
                    "phase": "error",
                    "detail": f"Could not save config: {e}",
                    "started_at": time.time(),
                    "pid": None,
                    "error": str(e),
                }
            return {"ok": False, "error": str(e), "state": status(provider)}

        # Force re-read + live probe
        try:
            load_config(force=True)
        except Exception:
            pass
        try:
            from openflow.providers.local import LocalProvider

            st = LocalProvider().status()
            ready = bool(st.ready)
            detail = st.detail
            if not ready:
                cfg_url = ((load_config().get("providers") or {}).get("local") or {}).get(
                    "url"
                ) or "http://127.0.0.1:8080/v1/audio/transcriptions"
                detail = (
                    f"{st.detail}. "
                    f"Start your Whisper server or fix the URL (currently {cfg_url})."
                )
        except Exception as e:
            ready = False
            detail = f"Local probe failed: {e}"

        with _lock:
            _state[provider] = {
                "provider": provider,
                "phase": "ready" if ready else "error",
                "detail": (
                    f"Local STT ready — {detail}"
                    if ready
                    else detail
                ),
                "started_at": time.time(),
                "pid": None,
                "error": None if ready else detail,
            }
        return {
            "ok": ready,
            "ready": ready,
            "error": None if ready else detail,
            "state": status(provider),
        }

    if help:
        tip = _install_help(provider)
        with _lock:
            _state[provider] = {
                "provider": provider,
                "phase": "need_cli",
                "detail": tip,
                "started_at": time.time(),
                "pid": None,
                "error": None,
            }
        return {"ok": True, "state": status(provider)}

    with _lock:
        _state[provider] = {
            "provider": provider,
            "phase": "starting",
            "detail": "Opening sign-in…",
            "started_at": time.time(),
            "pid": None,
            "error": None,
        }

    try:
        if provider == "grok":
            exe = _which_windows(["grok.exe", "grok"])
            if not exe:
                tip = _install_help("grok")
                with _lock:
                    _state[provider].update(
                        phase="need_cli",
                        detail=tip,
                        error="grok CLI not found",
                    )
                return {"ok": False, "error": "grok CLI not found", "state": status(provider)}
            pid = _spawn_detached([exe, "login", "--oauth"])
            with _lock:
                _state[provider].update(
                    phase="browser",
                    detail="Sign in in the browser window, then come back here.",
                    pid=pid,
                )
            return {"ok": True, "state": status(provider)}

        if provider == "chatgpt":
            exe = _which_windows(["codex.cmd", "codex.exe", "codex"])
            if not exe:
                tip = _install_help("chatgpt")
                with _lock:
                    _state[provider].update(
                        phase="need_cli",
                        detail=tip,
                        error="codex CLI not found",
                    )
                return {"ok": False, "error": "codex CLI not found", "state": status(provider)}
            pid = _spawn_detached([exe, "login"])
            with _lock:
                _state[provider].update(
                    phase="browser",
                    detail="Sign in in the browser window, then come back here.",
                    pid=pid,
                )
            return {"ok": True, "state": status(provider)}

        # claude
        ok, msg = _open_claude_desktop()
        with _lock:
            _state[provider].update(
                phase="app" if ok else "error",
                detail=msg,
                error=None if ok else msg,
            )
        return {"ok": ok, "state": status(provider)}

    except Exception as e:
        with _lock:
            _state[provider].update(phase="error", detail=str(e), error=str(e))
        return {"ok": False, "error": str(e), "state": status(provider)}


def status(provider: str | None = None) -> dict[str, Any]:
    """Return connect-flow state, enriched with live provider readiness."""
    from openflow.providers.registry import provider_status_map

    providers = provider_status_map()
    with _lock:
        snap = {k: dict(v) for k, v in _state.items()}

    def one(pid: str) -> dict[str, Any]:
        st = providers.get(pid) or {}
        flow = snap.get(pid) or {}
        ready = bool(st.get("ready") and st.get("stt_capable", True))
        # If login finished, promote phase
        if ready and flow.get("phase") in ("browser", "app", "starting", "waiting"):
            flow = {
                **flow,
                "phase": "ready",
                "detail": "Connected — ready to dictate",
            }
            with _lock:
                _state[pid] = flow
            # If active engine isn't ready, switch dictation to this one.
            try:
                from openflow.config import load_config, save_config
                from openflow.providers.registry import provider_status_map

                cfg = load_config()
                active = cfg.get("provider") or "grok"
                all_st = provider_status_map()
                active_ok = bool(
                    (all_st.get(active) or {}).get("ready")
                    and (all_st.get(active) or {}).get("stt_capable", True)
                )
                if not active_ok and active != pid:
                    save_config({"provider": pid})
            except Exception:
                pass
        elif flow.get("phase") in ("browser", "app", "waiting") and not ready:
            elapsed = time.time() - float(flow.get("started_at") or time.time())
            if elapsed > 2:
                flow = {
                    **flow,
                    "phase": "waiting",
                    "detail": flow.get("detail")
                    or "Sign in in the other window, then come back — we detect it automatically.",
                }
        # Soften stock CLI jargon for the setup UI
        detail = st.get("detail") or ""
        soft = detail
        if "auth.json not found" in detail.lower() or "not found" in detail.lower():
            soft = "Not connected yet"
        elif "run `" in detail or "CLI" in detail:
            soft = "Not connected yet — tap Connect"
        elif "sessionKey" in detail or "Claude Desktop" in detail:
            if ready:
                soft = "Connected — ready to dictate"
            else:
                soft = "Open Claude Desktop and sign in once"
        out: dict[str, Any] = {
            "provider": pid,
            "ready": ready,
            "health_detail": soft,
            "auth_path": st.get("auth_path"),
            "stt_capable": st.get("stt_capable", True),
            "flow": flow or None,
        }
        # Local: expose config so the UI can prefill URL / model fields
        if pid == "local":
            out["url"] = st.get("url") or st.get("auth_path")
            out["model"] = st.get("model")
            try:
                from openflow.config import load_config

                loc = (load_config().get("providers") or {}).get("local") or {}
                if isinstance(loc, dict):
                    out["url"] = loc.get("url") or out.get("url")
                    out["model"] = loc.get("model") if loc.get("model") is not None else out.get("model")
                    # Never send the raw key back; only whether one is set
                    out["has_api_key"] = bool(str(loc.get("api_key") or "").strip())
            except Exception:
                out["has_api_key"] = False
        return out

    if provider:
        return one(provider.strip().lower())
    pids = ("grok", "chatgpt", "claude", "local")
    return {
        "providers": {pid: one(pid) for pid in pids},
        "any_ready": any(
            (providers.get(p) or {}).get("ready")
            and (providers.get(p) or {}).get("stt_capable", True)
            for p in pids
        ),
    }


def needs_onboarding() -> bool:
    """True when no engine is ready for dictation."""
    try:
        from openflow.providers.registry import provider_status_map

        m = provider_status_map()
        for pid in ("grok", "chatgpt", "claude", "local"):
            st = m.get(pid) or {}
            if st.get("ready") and st.get("stt_capable", True):
                return False
        return True
    except Exception:
        return True
