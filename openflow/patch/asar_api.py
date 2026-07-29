#!/usr/bin/env python3
"""Shared helpers for locating and verifying a local desktop integration."""

from __future__ import annotations

from pathlib import Path


REQUIRED_MARKERS = {
    # ASR routing + timeouts (patch_asr.py)
    "local HTTP": b"http://127.0.0.1:18765/environments/production/run_remote",
    "local gRPC override": b"Using local gRPC route override",
    "timeout 60s": b"TRANSCRIPTION_TIMEOUT=6e4",
    "processing timeout 120s": b"=12e4}",
    "csp connect-src": b"openflow-csp-shim",
    "csp frame-src": b"openflow-csp-frames",
    "auto-updater disabled": b"openflow-disable-updates",
    # Offline-local account patches (patch_offline_local.py)
    "no-login patch": b"grok-flow-no-login",
    "offline local": b"grok-flow-offline-local",
    # Hub JS patches (inject.py)
    "hub quota hidden": b"grok-flow-hide-quota",
    "post-onboarding hidden": b"openflow-hide-post-onboarding",
    "local settings": b"openflow-local-settings",
    # UI theme + engine switcher (inject.py + assets/theme.js)
    "ui theme injected": b"grok-flow-theme",
    "speech engine": b"openflow-speech-engine",
    # Rebrand (rebrand.py)
    "rebrand": b"openflow-rebrand",
}

# Stock Wispr cloud endpoints that must be gone after patching.
STOCK_URLS = (
    b"https://chain-o232k03l.api.baseten.co/environments/production/run_remote",
    b"https://chain-o232k03l.api.baseten.co/environments/staging/run_remote",
)


def newest_app_dir(wispr_root: Path) -> Path:
    apps = [path for path in wispr_root.glob("app-*") if path.is_dir()]
    if not apps:
        raise SystemExit(f"no app-* under {wispr_root}")

    def version_key(path: Path) -> tuple[tuple[int, int | str], ...]:
        parts: list[tuple[int, int | str]] = []
        for part in path.name.removeprefix("app-").split("."):
            try:
                parts.append((1, int(part)))
            except ValueError:
                parts.append((0, part))
        return tuple(parts)

    return max(apps, key=version_key)


def verify_asar(asar: Path) -> tuple[bool, dict[str, bool]]:
    data = asar.read_bytes()
    checks = {name: marker in data for name, marker in REQUIRED_MARKERS.items()}
    checks["old Baseten gone"] = not any(url in data for url in STOCK_URLS)
    return all(checks.values()), checks
