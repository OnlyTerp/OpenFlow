#!/usr/bin/env python3
"""Rebrand an extracted Wispr Flow asar root to Grok Flow.

Patches (idempotent via package.json `grokFlowRebrand` / `grok-flow-rebrand`):
  - package.json productName, description, optional name, author display name
  - User-facing "Wispr Flow" → "Grok Flow" in package.json and .webpack/**/*.js
  - Theme greens → Grok orange/dark palette
  - Marker field grokFlowRebrand + string grok-flow-rebrand

Does NOT break:
  - Bundle ids (com.electron.wispr-flow) — no space, never matched
  - URLs (wisprflow.ai) — never matched
  - Filesystem / helper paths that embed the literal "Wispr Flow" directory or binary name
  - Package `name` defaults to leave as wispr-flow unless --rename-package

Usage:
  python3 openflow/patch/rebrand.py /path/to/asar-extract
  python3 openflow/patch/rebrand.py /path/to/asar-extract --rename-package
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MARKER = "grok-flow-rebrand"
MARKER_OPENFLOW = "openflow-rebrand"
MARKER_FIELD = "grokFlowRebrand"

PRODUCT = "OpenFlow"
OLD_PRODUCTS = ("Grok Flow", "Wispr Flow")
OLD_PRODUCT = OLD_PRODUCTS[1]  # original upstream name (path protection reference)

NEW_DESCRIPTION = "OpenFlow — local multi-engine dictation (Grok / ChatGPT / Claude)"

# Theme: Wispr greens → Grok palette (case-insensitive hex)
COLOR_MAP = {
    "#007a5a": "#FF6B2C",  # accent
    "#034f46": "#1A1A1A",  # dark green → near-black
    "#18a558": "#FF6B2C",  # mid green → accent
    "#0b8043": "#FF8A4C",  # deep green → lighter orange
}

# Path / binary segments that must keep the on-disk "Wispr Flow" name so
# config, logs, and helper executables still resolve after product rename.
# Matched as raw bytes; placeholders restored after global product replace.
_PROTECT_RES: list[re.Pattern[bytes]] = [
    # Windows Roaming config / logs / session (webpack path.join style)
    re.compile(rb'(?i)(AppData["\']?\s*,\s*["\']Roaming["\']?\s*,\s*["\'])Wispr Flow'),
    re.compile(rb'(?i)(AppData[\\/]+Roaming[\\/]+)Wispr Flow'),
    re.compile(rb'(?i)((?:process\.env\.)?APPDATA[^,]{0,40},\s*["\'])Wispr Flow'),
    # macOS Application Support / Logs
    re.compile(rb'(?i)(Application Support["\']?\s*,\s*["\'])Wispr Flow'),
    re.compile(rb'(?i)(Application Support[\\/]+)Wispr Flow'),
    re.compile(rb'(?i)(Library["\']?\s*,\s*["\']Logs["\']?\s*,\s*["\'])Wispr Flow'),
    re.compile(rb'(?i)(Logs["\']?\s*,\s*["\'])Wispr Flow'),
    re.compile(rb'(?i)([\\/]Logs[\\/]+)Wispr Flow'),
    # Helper app / binary paths (must match installed helper names)
    re.compile(rb'Wispr Flow Helper'),
    re.compile(rb'Wispr Flow\.app'),
    re.compile(rb'DerivedData[\\/]+Wispr Flow'),
    # macOS helper executable basename inside .app bundle
    re.compile(rb'(Contents/MacOS/)Wispr Flow'),
]


def _protect(data: bytes) -> tuple[bytes, list[bytes]]:
    """Replace protected spans with placeholders; return (data, restore list)."""
    restored: list[bytes] = []

    def _sub(m: re.Match[bytes]) -> bytes:
        full = m.group(0)
        # Keep full match so multi-group patterns restore exactly
        idx = len(restored)
        restored.append(full)
        return f"__GROK_PROTECT_{idx}__".encode("ascii")

    out = data
    for cre in _PROTECT_RES:
        out = cre.sub(_sub, out)
    return out, restored


def _unprotect(data: bytes, restored: list[bytes]) -> bytes:
    for i, original in enumerate(restored):
        ph = f"__GROK_PROTECT_{i}__".encode("ascii")
        data = data.replace(ph, original)
    return data


def _replace_colors(data: bytes) -> tuple[bytes, int]:
    n = 0
    for old, new in COLOR_MAP.items():
        # Case-insensitive hex replace preserving only exact 7-char #rrggbb tokens
        pattern = re.compile(re.escape(old).encode("ascii"), re.IGNORECASE)
        data, c = pattern.subn(new.encode("ascii"), data)
        n += c
    return data, n


def _rebrand_js(path: Path) -> dict[str, int]:
    raw = path.read_bytes()
    if MARKER.encode("ascii") in raw and OLD_PRODUCT.encode("utf-8") not in raw:
        # Already fully rebranded (marker may only live in package.json; still process colors)
        pass

    stats = {"product": 0, "colors": 0, "bytes_delta": 0}
    before = raw

    protected, restore = _protect(raw)
    new_b = PRODUCT.encode("utf-8")
    for old in OLD_PRODUCTS:
        old_b = old.encode("utf-8")
        count = protected.count(old_b)
        if count:
            protected = protected.replace(old_b, new_b)
            stats["product"] += count
    protected = _unprotect(protected, restore)

    protected, c = _replace_colors(protected)
    stats["colors"] = c

    if protected != before:
        path.write_bytes(protected)
        stats["bytes_delta"] = len(protected) - len(before)
    return stats


def _rebrand_package_json(pkg_path: Path, rename_package: bool) -> dict:
    text = pkg_path.read_text(encoding="utf-8")
    data = json.loads(text)

    changes: dict[str, object] = {}
    if data.get("productName") != PRODUCT:
        changes["productName"] = (data.get("productName"), PRODUCT)
        data["productName"] = PRODUCT

    if rename_package and data.get("name") != "grok-flow":
        changes["name"] = (data.get("name"), "grok-flow")
        data["name"] = "grok-flow"

    if data.get("description") != NEW_DESCRIPTION:
        changes["description"] = (data.get("description"), NEW_DESCRIPTION)
        data["description"] = NEW_DESCRIPTION

    author = data.get("author")
    if isinstance(author, dict) and author.get("name") in OLD_PRODUCTS:
        author["name"] = PRODUCT
        changes["author.name"] = PRODUCT
    elif isinstance(author, str) and author in OLD_PRODUCTS:
        data["author"] = PRODUCT
        changes["author"] = PRODUCT

    # Marker field + ensure description / dedicated string for binary greps
    if not data.get(MARKER_FIELD):
        data[MARKER_FIELD] = True
        changes[MARKER_FIELD] = True
    # Embed marker strings somewhere greppable in the asar
    if data.get("grokFlowRebrandMarker") != MARKER:
        data["grokFlowRebrandMarker"] = MARKER
        changes["grokFlowRebrandMarker"] = MARKER
    if data.get("openflowRebrandMarker") != MARKER_OPENFLOW:
        data["openflowRebrandMarker"] = MARKER_OPENFLOW
        changes["openflowRebrandMarker"] = MARKER_OPENFLOW

    # Also replace any remaining user-facing product string in the JSON text
    # (after structured edits) while protecting paths (none expected in package.json).
    out = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    for old in OLD_PRODUCTS:
        if old in out:
            # package.json shouldn't hold filesystem helper paths; safe full replace
            out = out.replace(old, PRODUCT)
            changes["json_string_replace"] = True

    pkg_path.write_text(out, encoding="utf-8")
    return changes


def rebrand(extract_root: Path, rename_package: bool = False) -> int:
    extract_root = extract_root.resolve()
    if not extract_root.is_dir():
        raise SystemExit(f"not a directory: {extract_root}")

    pkg = extract_root / "package.json"
    if not pkg.is_file():
        raise SystemExit(f"missing package.json under {extract_root}")

    already = False
    try:
        meta = json.loads(pkg.read_text(encoding="utf-8"))
        already = bool(meta.get(MARKER_FIELD)) and meta.get("productName") == PRODUCT
    except json.JSONDecodeError:
        pass

    print(f"rebrand root: {extract_root} → {PRODUCT}")
    pkg_changes = _rebrand_package_json(pkg, rename_package=rename_package)
    if pkg_changes:
        print(f"package.json: {pkg_changes}")
    else:
        print(f"package.json: already {PRODUCT}")

    webpack = extract_root / ".webpack"
    if not webpack.is_dir():
        print("WARN: no .webpack directory", file=sys.stderr)
        js_files: list[Path] = []
    else:
        js_files = sorted(webpack.rglob("*.js"))

    total_product = 0
    total_colors = 0
    files_touched = 0
    for path in js_files:
        st = _rebrand_js(path)
        if st["product"] or st["colors"] or st["bytes_delta"]:
            files_touched += 1
            total_product += st["product"]
            total_colors += st["colors"]
            rel = path.relative_to(extract_root)
            print(
                f"  {rel}: product×{st['product']} colors×{st['colors']} "
                f"Δbytes={st['bytes_delta']}"
            )

    print(
        f"js summary: {files_touched}/{len(js_files)} files, "
        f"product replacements={total_product}, color replacements={total_colors}"
    )

    # Verify markers
    meta = json.loads(pkg.read_text(encoding="utf-8"))
    ok = (
        meta.get("productName") == PRODUCT
        and meta.get(MARKER_FIELD) is True
        and meta.get("grokFlowRebrandMarker") == MARKER
        and MARKER in pkg.read_text(encoding="utf-8")
    )
    if not ok:
        raise SystemExit("rebrand verify failed on package.json markers")

    # Spot-check: protected path sample still present if it was in main bundle
    main = extract_root / ".webpack" / "main" / "index.js"
    if main.is_file():
        body = main.read_bytes()
        if b"AppData" in body and b"Roaming" in body:
            # Prefer literal Wispr Flow path segment still present
            if b'"Wispr Flow"' not in body and b"'Wispr Flow'" not in body:
                # Path may use comma-separated join args without quotes adjacent — check join pattern
                if b",\"Wispr Flow\"" not in body and b",'Wispr Flow'" not in body:
                    # After rebrand, user-facing strings changed; path protect should leave some
                    if b"Wispr Flow" not in body:
                        print(
                            "WARN: no remaining 'Wispr Flow' in main/index.js "
                            "(path protect may not have matched this build)",
                            file=sys.stderr,
                        )
                    else:
                        print("path protect: residual Wispr Flow present in main (expected for paths)")
            else:
                print("path protect: config path segments retained")
        if b"com.electron.wispr-flow" not in body:
            print("WARN: bundle id com.electron.wispr-flow missing from main", file=sys.stderr)
        else:
            print("bundle id intact: com.electron.wispr-flow")
        if b"wisprflow.ai" in body:
            print("API host intact: wisprflow.ai")

    if already and total_product == 0 and total_colors == 0:
        print("already rebranded (idempotent no-op)")
    else:
        print("rebrand ok")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "extract_root",
        type=Path,
        help="Extracted asar directory (contains package.json and .webpack/)",
    )
    ap.add_argument(
        "--rename-package",
        action="store_true",
        help='Also set package.json "name" to "grok-flow" (default: leave wispr-flow)',
    )
    args = ap.parse_args()
    raise SystemExit(rebrand(args.extract_root, rename_package=args.rename_package))


if __name__ == "__main__":
    main()
