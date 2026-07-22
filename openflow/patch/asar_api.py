#!/usr/bin/env python3
"""Shared helpers for locating and verifying a local desktop integration."""

from __future__ import annotations

from pathlib import Path


REQUIRED_MARKERS = {
    "local HTTP": b"http://127.0.0.1:18765/environments/production/run_remote",
    "local gRPC override": b"Using local gRPC route override",
    "timeout 60s": b"TRANSCRIPTION_TIMEOUT=6e4",
    "processing timeout 120s": b"te=12e4",
}


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
    checks["old Baseten gone"] = (
        b"https://chain-o232k03l.api.baseten.co/environments/production/run_remote"
        not in data
    )
    checks["no subscription bypass"] = not any(
        marker in data
        for marker in (
            b"grok-flow-skip-weekly-limit",
            b"grok-flow-pro",
            b"grok-flow-nolimit",
            b"grok-flow-local-offline-token",
        )
    )
    return all(checks.values()), checks
