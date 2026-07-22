"""OpenFlow config — active STT provider + paths.

Windows: %APPDATA%\\OpenFlow\\config.json
Else:    ~/.openflow/config.json
"""

from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "provider": "grok",
    "fallback": [],
    "providers": {
        "grok": {"enabled": True},
        "chatgpt": {"enabled": True},
        "claude": {"enabled": True},
        "local": {
            "enabled": True,
            # OpenAI-compatible Whisper endpoint (faster-whisper, etc.)
            "url": "http://127.0.0.1:8080/v1/audio/transcriptions",
            "model": "whisper-1",
            "api_key": "",
        },
    },
    "ui": {"brand": "openflow", "accent": "#ff6b2c"},
}

VALID_PROVIDERS = ("grok", "chatgpt", "claude", "local")

_lock = threading.Lock()
_cache: dict[str, Any] = {"mtime": None, "path": None, "data": None}


def config_dir() -> Path:
    appdata = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME")
    if appdata:
        return Path(appdata) / "OpenFlow"
    return Path.home() / ".openflow"


def config_path() -> Path:
    env = os.environ.get("OPENFLOW_CONFIG")
    if env:
        return Path(env)
    return config_dir() / "config.json"


def _merge_defaults(data: dict) -> dict:
    out = deepcopy(DEFAULT_CONFIG)
    if not isinstance(data, dict):
        return out
    prov = data.get("provider")
    if isinstance(prov, str) and prov in VALID_PROVIDERS:
        out["provider"] = prov
    fb = data.get("fallback")
    if isinstance(fb, list):
        out["fallback"] = [x for x in fb if x in VALID_PROVIDERS]
    pmap = data.get("providers")
    if isinstance(pmap, dict):
        for k in VALID_PROVIDERS:
            if k in pmap and isinstance(pmap[k], dict):
                out["providers"][k] = {**out["providers"][k], **pmap[k]}
    ui = data.get("ui")
    if isinstance(ui, dict):
        out["ui"] = {**out["ui"], **ui}
    # First-run setup flags (local only — never leave the machine)
    if "onboarding_skipped" in data:
        out["onboarding_skipped"] = bool(data["onboarding_skipped"])
    if "onboarding_completed" in data:
        out["onboarding_completed"] = bool(data["onboarding_completed"])
    return out


def load_config(*, force: bool = False) -> dict:
    path = config_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    with _lock:
        if (
            not force
            and _cache["data"] is not None
            and _cache["path"] == str(path)
            and _cache["mtime"] == mtime
        ):
            return deepcopy(_cache["data"])  # type: ignore[arg-type]
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                raw = {}
        else:
            raw = {}
        data = _merge_defaults(raw if isinstance(raw, dict) else {})
        _cache.update({"mtime": mtime, "path": str(path), "data": data})
        return deepcopy(data)


def save_config(patch: dict) -> dict:
    """Merge patch into config and write. Returns new config."""
    path = config_path()
    current = load_config(force=True)
    if "provider" in patch and patch["provider"] in VALID_PROVIDERS:
        current["provider"] = patch["provider"]
    if "fallback" in patch and isinstance(patch["fallback"], list):
        current["fallback"] = [x for x in patch["fallback"] if x in VALID_PROVIDERS]
    if "providers" in patch and isinstance(patch["providers"], dict):
        for k, v in patch["providers"].items():
            if k in VALID_PROVIDERS and isinstance(v, dict):
                current["providers"][k] = {**current["providers"].get(k, {}), **v}
    if "ui" in patch and isinstance(patch["ui"], dict):
        current["ui"] = {**current.get("ui", {}), **patch["ui"]}
    if "onboarding_skipped" in patch:
        current["onboarding_skipped"] = bool(patch["onboarding_skipped"])
    if "onboarding_completed" in patch:
        current["onboarding_completed"] = bool(patch["onboarding_completed"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    with _lock:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = None
        _cache.update({"mtime": mtime, "path": str(path), "data": deepcopy(current)})
    return current


def active_provider_id() -> str:
    cfg = load_config()
    p = cfg.get("provider") or "grok"
    return p if p in VALID_PROVIDERS else "grok"
