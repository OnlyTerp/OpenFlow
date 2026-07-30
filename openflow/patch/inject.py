#!/usr/bin/env python3
"""Inject OpenFlow UI (CSS + JS) into the desktop shell's renderer HTML files.

This is the *visual* half of the patch pipeline.  ``patch_asr.py`` handles ASR
routing, timeouts, and CSP; this module handles the sidebar engine switcher,
first-run setup panel, cloud-chrome removal, and overlay transparency.

The injected assets live as authored files under ``openflow/patch/assets/`` so
they can be reviewed, tested, and diffed independently — they are never inlined
into Python strings.

Idempotent: re-running on an already-injected file strips the old markers and
re-inserts fresh content, so ``ensure_patched`` can rebuild from stock every
time without accumulating duplicate injections.

Usage (called by ``ensure.py`` after ASR patching)::

    python -m openflow.patch.inject <extract_dir>

Verified against Wispr Flow app-1.6.122.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ASSETS = SCRIPT_DIR / "assets"

# Renderer shells that use transparent backgrounds (overlay, status pill, etc.)
TRANSPARENT_SHELLS = frozenset({"overlay", "status", "contextMenu", "feature_tour"})

# Marker IDs in the HTML — used for idempotent strip-and-reinsert
THEME_STYLE_ID = "grok-flow-theme"
THEME_SCRIPT_ID = "grok-flow-theme-js"
OVERLAY_STYLE_ID = "grok-flow-overlay-theme"
OVERLAY_SCRIPT_ID = "grok-flow-overlay-theme-js"


def _shell_name(path: Path) -> str:
    """Renderer shell name from path: …/renderer/<name>/index.html → <name>."""
    return path.parent.name


def _is_transparent_shell(path: Path) -> bool:
    return _shell_name(path) in TRANSPARENT_SHELLS


def _strip_existing(raw: str) -> str:
    """Remove any prior OpenFlow injection markers (idempotent re-patch)."""
    for style_id in (THEME_STYLE_ID, OVERLAY_STYLE_ID):
        raw = re.sub(
            rf'<style id="{style_id}">[\s\S]*?</style>', "", raw, count=1
        )
    for script_id in (THEME_SCRIPT_ID, OVERLAY_SCRIPT_ID):
        raw = re.sub(
            rf'<script id="{script_id}">[\s\S]*?</script>', "", raw, count=1
        )
    return raw


def _read_asset(name: str) -> str:
    p = ASSETS / name
    if not p.is_file():
        raise SystemExit(f"missing asset: {p}")
    return p.read_text(encoding="utf-8")


def inject_html(path: Path) -> bool:
    """Inject theme or overlay CSS+JS into a renderer index.html."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    transparent = _is_transparent_shell(path)

    # Strip prior injections (idempotent)
    if "grok-flow-theme" in raw or "grok-flow-overlay-theme" in raw:
        raw = _strip_existing(raw)

    if transparent:
        # Transparent shells: make background transparent + inject overlay CSS/JS
        raw = re.sub(
            r'style="background-color:#[0-9a-fA-F]{3,8}[^"]*"',
            'style="background:transparent;overflow:hidden"',
            raw,
            count=2,
        )
        raw = raw.replace(
            'style="background-color:#0a0a0a;color:#f4f4f5;overflow:hidden"',
            'style="background:transparent;overflow:hidden"',
        )
        raw = raw.replace(
            'style="background-color:#121212;color:#f2f2f0;overflow:hidden"',
            'style="background:transparent;overflow:hidden"',
        )
        inject = (
            f'<style id="{OVERLAY_STYLE_ID}">{_read_asset("overlay.css")}</style>'
            f'<script id="{OVERLAY_SCRIPT_ID}">{_read_asset("overlay.js")}</script>'
        )
        label = "transparent"
    else:
        # Hub / scratchpad / meeting_recorder: keep app body colors, inject theme
        raw = re.sub(
            r'style="background-color:#[0-9a-fA-F]{3,8};color:#[0-9a-fA-F]{3,8};height:100%;width:100%;overflow:hidden"',
            'style="height:100%;width:100%;overflow:hidden"',
            raw,
        )
        raw = re.sub(
            r'style="background-color:#[0-9a-fA-F]{3,8};color:#[0-9a-fA-F]{3,8};overflow:hidden"',
            'style="overflow:hidden"',
            raw,
        )
        inject = (
            f'<style id="{THEME_STYLE_ID}">{_read_asset("theme.css")}</style>'
            f'<script id="{THEME_SCRIPT_ID}">{_read_asset("theme.js")}</script>'
        )
        label = "hub"

    if "</head>" in raw:
        raw = raw.replace("</head>", inject + "</head>", 1)
    else:
        raw = inject + raw
    path.write_text(raw, encoding="utf-8")
    print(f"  themed ({label}): {_shell_name(path)}/index.html")
    return True


def verify_injected(extract: Path) -> dict[str, bool]:
    """Check that injection markers are present in renderer HTML files."""
    renderer = extract / ".webpack" / "renderer"
    if not renderer.is_dir():
        return {"renderer dir": False}

    hub = renderer / "hub" / "index.html"
    overlay = renderer / "overlay" / "index.html"
    return {
        "hub theme style": hub.is_file()
        and f'id="{THEME_STYLE_ID}"' in hub.read_text(encoding="utf-8", errors="replace"),
        "hub theme script": hub.is_file()
        and f'id="{THEME_SCRIPT_ID}"' in hub.read_text(encoding="utf-8", errors="replace"),
        "overlay theme style": overlay.is_file()
        and f'id="{OVERLAY_STYLE_ID}"' in overlay.read_text(encoding="utf-8", errors="replace"),
        "overlay theme script": overlay.is_file()
        and f'id="{OVERLAY_SCRIPT_ID}"' in overlay.read_text(encoding="utf-8", errors="replace"),
        "hub js quota patch": (renderer / "hub" / "index.js").is_file()
        and b"grok-flow-hide-quota" in (renderer / "hub" / "index.js").read_bytes(),
        "hub js settings patch": (renderer / "hub" / "index.js").is_file()
        and b"openflow-local-settings" in (renderer / "hub" / "index.js").read_bytes(),
    }


# ── Hub JS binary patches ────────────────────────────────────────────
# These remove cloud-only chrome (quota CTA, post-onboarding interstitial,
# cloud settings tabs, brand strings) from the minified hub bundle.
# Idempotent: each patch checks for its marker before applying.

_HUB_PATCHES = [
    # Hide quota CTA
    (
        b"if(!ie(ua.Eg.BasicUpgradeCTA)||P||I||x)return null;",
        b"return null/*grok-flow-hide-quota*/;if(!ie(ua.Eg.BasicUpgradeCTA)||P||I||x)return null;",
        b"grok-flow-hide-quota",
    ),
    # Disable post-onboarding interstitial
    (
        b"if(!e.user.postOnboardingCompleted&&e.user.onboardingCompletedTime&&!ne.current)return ne.current=!0,void en();",
        b"if(false/*openflow-hide-post-onboarding*/&&e.user.onboardingCompletedTime&&!ne.current)return ne.current=!0,void en();",
        b"openflow-hide-post-onboarding",
    ),
    # Settings: only General + System tabs, no Account/cloud tabs
    (
        b"general:Object.values(q.$t).filter(e=>!(e===q.$t.Connectors&&!a||e===q.$t.Mcp&&!o||e===q.$t.Notetaker&&!t||e===q.$t.Internal&&!s||e===q.$t.Experimental&&!l||e===q.$t.Testing&&!r)),account:Object.values(q.EK).filter(e=>!(e===q.EK.Team&&!n))",
        b"general:Object.values(q.$t).filter(e=>e===q.$t.General||e===q.$t.System)/*openflow-local-settings*/,account:Object.values(q.EK).filter(e=>false)/*openflow-local-settings*/",
        b"openflow-local-settings",
    ),
    # app-1.6.288 variants
    (
        b"if(k)return null;if(!re(Di.Eg.BasicUpgradeCTA)||I||T||$)return null;",
        b"return null/*grok-flow-hide-quota*/;if(k)return null;if(!re(Di.Eg.BasicUpgradeCTA)||I||T||$)return null;",
        b"grok-flow-hide-quota",
    ),
    (
        b"if((!r||e.user.dictationOnboardingCompleted)&&!e.user.postOnboardingCompleted&&e.user.onboardingCompletedTime&&!he.current)return he.current=!0,void bn();",
        b"if((!r||e.user.dictationOnboardingCompleted)&&false/*openflow-hide-post-onboarding*/&&e.user.onboardingCompletedTime&&!he.current)return he.current=!0,void bn();",
        b"openflow-hide-post-onboarding",
    ),
    (
        b"general:Object.values(q.$t).filter(e=>!(e===q.$t.Connectors&&!i||e===q.$t.Mcp&&!o||e===q.$t.Notetaker&&!t||e===q.$t.Internal&&!s||e===q.$t.Experimental&&!l||e===q.$t.Testing&&!r)),account:Object.values(q.EK).filter(e=>!(e===q.EK.Team&&!n))",
        b"general:Object.values(q.$t).filter(e=>e===q.$t.General||e===q.$t.System)/*openflow-local-settings*/,account:Object.values(q.EK).filter(e=>false)/*openflow-local-settings*/",
        b"openflow-local-settings",
    ),
]

_HUB_BRAND_REPLACEMENTS = [
    (b'"Wispr Flow"', b'"OpenFlow"'),
    (b'"WisprFlow"', b'"OpenFlow"'),
    (b'"Grok Flow"', b'"OpenFlow"'),
    (b'"hub_plan_name_basic":"Basic"', b'"hub_plan_name_basic":"OpenFlow"'),
    (b'"hub_plan_name_basic":"Grok"', b'"hub_plan_name_basic":"OpenFlow"'),
    (b'"Make Flow sound like you"', b'"Speech settings"'),
    (b'"Welcome back to Flow,"', b'"Welcome back,"'),
    (b"You get {{weeklyCap}} words per week. Upgrade for unlimited access.",
     b"Unlimited local dictation."),
    (b'document.title="Hub"', b'document.title="OpenFlow"'),
]


def patch_hub_js(path: Path) -> None:
    """Apply binary patches to the minified hub index.js."""
    data = path.read_bytes()
    orig = data

    for old, new, marker in _HUB_PATCHES:
        if marker in data:
            print(f"  already: {marker.decode()}")
        elif old in data:
            data = data.replace(old, new, 1)
            print(f"  OK: {marker.decode()}")
        else:
            print(f"  WARN: {marker.decode()} pattern not found")

    for old, new in _HUB_BRAND_REPLACEMENTS:
        if old in data:
            n = data.count(old)
            data = data.replace(old, new)
            print(f"  OK: brand {old[:30]!r} x{n}")

    if data != orig:
        path.write_bytes(data)
        print("  wrote hub JS patches")
    else:
        print("  hub JS unchanged")


def run(extract: Path) -> None:
    """Inject UI assets into all renderer HTML files in the extracted asar."""
    print("inject-ui:", extract)
    renderer = extract / ".webpack" / "renderer"
    if not renderer.is_dir():
        raise SystemExit(f"missing {renderer}")

    for html in renderer.rglob("index.html"):
        inject_html(html)

    # Binary patches to hub JS (cloud chrome removal, branding)
    hub_js = renderer / "hub" / "index.js"
    if hub_js.is_file():
        patch_hub_js(hub_js)

    checks = verify_injected(extract)
    for k, v in checks.items():
        print(f"  {'OK' if v else 'FAIL'}: {k}")
    if not all(checks.values()):
        raise SystemExit("inject verify failed")


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("extract_dir", type=Path)
    args = ap.parse_args()
    if not args.extract_dir.is_dir():
        raise SystemExit(f"not a dir: {args.extract_dir}")
    run(args.extract_dir)


if __name__ == "__main__":
    main()
