"""Resolve active STT provider + optional fallback chain."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from openflow.config import VALID_PROVIDERS, load_config

from .base import SttError, UnsupportedSttError
from .chatgpt import ChatGptProvider
from .claude import ClaudeProvider
from .grok import GrokProvider
from .local import LocalProvider

log = logging.getLogger("openflow.registry")

_providers = {
    "grok": GrokProvider(),
    "chatgpt": ChatGptProvider(),
    "claude": ClaudeProvider(),
    "local": LocalProvider(),
}

_STATUS_CACHE_TTL_S = max(
    0.0, float(os.environ.get("OPENFLOW_PROVIDER_STATUS_TTL", "30"))
)
_status_lock = threading.Lock()
_status_cache: dict[str, Any] = {
    "key": None,
    "expires_at": 0.0,
    "value": None,
}

_stats_lock = threading.Lock()
_stats: dict[str, Any] = {
    "last_provider": None,
    "last_ok": None,
    "last_error": None,
    "last_latency_s": None,
    "by_provider": {p: {"ok": 0, "fail": 0} for p in VALID_PROVIDERS},
}


def get_registry() -> dict[str, Any]:
    return dict(_providers)


def _active_from_config(cfg: dict) -> str:
    active = cfg.get("provider")
    return active if active in VALID_PROVIDERS else "grok"


def _status_cache_key(cfg: dict) -> tuple[Any, ...]:
    providers = cfg.get("providers") or {}
    local = providers.get("local") or {}
    return (
        _active_from_config(cfg),
        tuple(
            (
                pid,
                bool((providers.get(pid) or {}).get("enabled", True)),
            )
            for pid in VALID_PROVIDERS
        ),
        str(local.get("url") or ""),
        str(local.get("model") or ""),
    )


def _copy_status_map(statuses: dict[str, Any]) -> dict[str, Any]:
    return {pid: dict(status) for pid, status in statuses.items()}


def invalidate_status_cache() -> None:
    with _status_lock:
        _status_cache.update({"key": None, "expires_at": 0.0, "value": None})


def provider_status_map(
    *,
    cfg: dict | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Probe provider readiness at most once per cache window."""
    cfg = cfg if cfg is not None else load_config()
    active = _active_from_config(cfg)
    key = _status_cache_key(cfg)
    now = time.monotonic()
    with _status_lock:
        cached = _status_cache["value"]
        if (
            not force
            and cached is not None
            and _status_cache["key"] == key
            and now < _status_cache["expires_at"]
        ):
            return _copy_status_map(cached)

        out = {}
        providers = cfg.get("providers") or {}
        for pid, provider in _providers.items():
            status = provider.status().as_dict()
            status["enabled"] = bool(
                (providers.get(pid) or {}).get("enabled", True)
            )
            status["active"] = pid == active
            out[pid] = status
        _status_cache.update(
            {
                "key": key,
                "expires_at": time.monotonic() + _STATUS_CACHE_TTL_S,
                "value": out,
            }
        )
        return _copy_status_map(out)


def _chain_for(active: str, cfg: dict) -> list[str]:
    """Return the active provider followed by explicitly configured fallbacks.

    Audio must never leave the selected provider unless the user opted into
    that fallback. In particular, a failed local endpoint must stay local.
    Empty transcripts are successful silence and never trigger fallback.
    """
    chain: list[str] = [active]
    for fallback in cfg.get("fallback") or []:
        if fallback in _providers and fallback not in chain:
            chain.append(fallback)
    return chain


def transcribe_with_active(wav_bytes: bytes, language: str = "en") -> dict:
    """Try active provider, then fallback chain on hard failures."""
    cfg = load_config()
    active = _active_from_config(cfg)
    chain = _chain_for(active, cfg)

    last_err: Exception | None = None
    for pid in chain:
        prov = _providers.get(pid)
        if prov is None:
            continue
        enabled = (cfg.get("providers") or {}).get(pid, {}).get("enabled", True)
        if not enabled:
            continue
        # Skip providers that know they can't STT (e.g. Claude without Desktop cookies)
        # when they're not the explicit active choice — status check is cheap-ish
        if pid != active:
            try:
                st = prov.status()
                if not st.ready or not st.stt_capable:
                    log.info("skip fallback %s (not ready)", pid)
                    continue
            except Exception:
                pass
        t0 = time.time()
        try:
            log.info("STT via provider=%s wav=%d", pid, len(wav_bytes))
            result = prov.transcribe(wav_bytes, language=language)
            if not isinstance(result, dict):
                result = {"text": str(result)}
            result.setdefault("provider", pid)
            text = (result.get("text") or result.get("transcript") or "").strip()
            # Empty transcript from primary is OK (silence); don't fallback
            if not text and pid == active:
                log.info(
                    "STT provider=%s empty transcript t=%.2fs (keeping)",
                    pid,
                    time.time() - t0,
                )
            lat = time.time() - t0
            with _stats_lock:
                _stats["last_provider"] = pid
                _stats["last_ok"] = True
                _stats["last_error"] = None
                _stats["last_latency_s"] = round(lat, 3)
                _stats["by_provider"][pid]["ok"] += 1
            if pid != active:
                log.info("STT fallback %s → %s ok t=%.2fs", active, pid, lat)
            else:
                log.info("STT provider=%s ok t=%.2fs", pid, lat)
            return result
        except UnsupportedSttError as e:
            last_err = e
            log.warning("provider %s unsupported: %s", pid, e)
            with _stats_lock:
                _stats["by_provider"][pid]["fail"] += 1
                _stats["last_provider"] = pid
                _stats["last_ok"] = False
                _stats["last_error"] = str(e)
            continue
        except Exception as e:
            last_err = e
            log.warning("provider %s failed: %s", pid, e)
            with _stats_lock:
                _stats["by_provider"][pid]["fail"] += 1
                _stats["last_provider"] = pid
                _stats["last_ok"] = False
                _stats["last_error"] = str(e)
                _stats["last_latency_s"] = round(time.time() - t0, 3)
            continue
    if last_err:
        raise last_err
    raise SttError("No STT provider available")


def stats_snapshot() -> dict[str, Any]:
    with _stats_lock:
        return {
            "last_provider": _stats["last_provider"],
            "last_ok": _stats["last_ok"],
            "last_error": _stats["last_error"],
            "last_latency_s": _stats["last_latency_s"],
            "by_provider": {k: dict(v) for k, v in _stats["by_provider"].items()},
        }


def prewarm() -> None:
    """Warm auth and readiness caches before the first UI poll."""
    try:
        statuses = provider_status_map(force=True)
    except Exception as exc:
        log.warning("provider prewarm failed: %s", exc)
        return
    for pid, status in statuses.items():
        log.info(
            "prewarm %s ready=%s detail=%s",
            pid,
            status.get("ready"),
            status.get("detail"),
        )
