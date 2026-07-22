#!/usr/bin/env python3
"""Install, verify, or restore the OpenFlow desktop integration.

The patch is applied only to a Wispr Flow installation already present on the
user's machine. Proprietary application files are never bundled with OpenFlow.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from openflow.patch.asar_api import newest_app_dir, verify_asar

SCRIPT_DIR = Path(__file__).resolve().parent


def _localappdata() -> Path:
    # Windows: LOCALAPPDATA. WSL: /mnt/c/Users/.../AppData/Local
    env = os.environ.get("LOCALAPPDATA")
    if env:
        return Path(env)
    # WSL: probe common Windows user profiles under /mnt/c/Users
    users = Path("/mnt/c/Users")
    if users.is_dir():
        try:
            children = sorted(users.iterdir())
        except OSError:
            children = []
        for child in children:
            if child.name in ("Public", "Default", "Default User", "All Users"):
                continue
            cand = child / "AppData" / "Local"
            try:
                if cand.is_dir():
                    return cand
            except OSError:
                continue
    for p in (Path.home() / "AppData" / "Local",):
        try:
            if p.is_dir():
                return p
        except OSError:
            pass
    raise SystemExit("LOCALAPPDATA not set and no fallback found")


def _find_node() -> str | None:
    for name in ("node", "node.exe"):
        path = shutil.which(name)
        if path:
            return path
    # common Windows install
    for p in (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "node.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "nodejs"
        / "node.exe",
    ):
        if p.is_file():
            return str(p)
    return None


def _asar_js(root: Path | None = None) -> Path | None:
    """Directory that has node_modules/@electron/asar (install root or repo)."""
    candidates = []
    if root is not None:
        candidates.append(Path(root))
    # install root = parent of openflow package
    candidates.append(SCRIPT_DIR.parents[1].parent)  # .../OpenFlow
    candidates.append(SCRIPT_DIR.parents[1])  # .../openflow (unlikely)
    # repo checkout root (dev)
    candidates.append(Path(__file__).resolve().parents[2])
    for c in candidates:
        if (c / "node_modules" / "@electron" / "asar").is_dir():
            return c
    return None


def _run_asar(node: str, repo: Path, action: str, src: str, dst: str) -> None:
    # action: extract | pack
    if action == "extract":
        code = (
            "const asar=require('@electron/asar');"
            "asar.extractAll(process.argv[1], process.argv[2]);"
            "console.log('extracted');"
        )
    else:
        code = (
            "const asar=require('@electron/asar');"
            "asar.createPackage(process.argv[1], process.argv[2])"
            ".then(()=>console.log('packed'));"
        )
    subprocess.check_call(
        [node, "-e", code, src, dst],
        cwd=str(repo),
    )


def ensure_patched(wispr_root: Path | None = None, force: bool = False) -> Path:
    if wispr_root is not None:
        root = Path(wispr_root)
    else:
        root = _localappdata() / "WisprFlow"
    app = newest_app_dir(root)
    asar = app / "resources" / "app.asar"
    if not asar.is_file():
        raise SystemExit(f"missing {asar}")

    ok, checks = verify_asar(asar)
    print(f"app: {app.name}")
    for k, v in checks.items():
        print(f"  {'OK' if v else 'MISS'}: {k}")

    if ok and not force:
        print("already fully patched")
        return asar

    print("re-patching from stock backup...")
    backup = asar.with_name("app.asar.bak-pre-grok-stt")
    # The backup is immutable. Rebuilding from it also removes markers left by
    # older private prototypes instead of layering new patches over them.
    if not backup.is_file():
        shutil.copy2(asar, backup)
        print(f"backup -> {backup}")

    node = _find_node()
    if not node:
        raise SystemExit("node not found — needed to extract/pack asar")

    repo = _asar_js()
    if not repo:
        raise SystemExit(
            "@electron/asar not found — run npm install in the OpenFlow install dir"
        )

    # Always rebuild from the immutable stock backup. Each Wispr app-* version
    # has its own resources directory and therefore its own matching backup.
    with tempfile.TemporaryDirectory(prefix="openflow-asar-") as td:
        extract = Path(td) / "extract"
        extract.mkdir()
        _run_asar(node, repo, "extract", str(backup), str(extract))
        patch_script = SCRIPT_DIR / "patch_asr.py"
        subprocess.check_call([sys.executable, str(patch_script), str(extract)])
        out = Path(td) / "app.asar.patched"
        _run_asar(node, repo, "pack", str(extract), str(out))
        shutil.copy2(out, asar)
        print(f"installed -> {asar}")

    ok, checks = verify_asar(asar)
    for k, v in checks.items():
        print(f"  {'OK' if v else 'FAIL'}: {k}")
    if not ok:
        raise SystemExit("verify failed after re-patch")
    return asar


def restore_stock(wispr_root: Path | None = None) -> Path:
    """Restore the stock asar backup created before the first patch."""
    root = Path(wispr_root) if wispr_root is not None else _localappdata() / "WisprFlow"
    app = newest_app_dir(root)
    asar = app / "resources" / "app.asar"
    backup = asar.with_name("app.asar.bak-pre-grok-stt")
    if not backup.is_file():
        raise SystemExit(f"stock backup not found: {backup}")
    shutil.copy2(backup, asar)
    print(f"restored stock asar -> {asar}")
    return asar


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="re-patch even if markers present")
    ap.add_argument(
        "--wispr-root",
        type=Path,
        default=None,
        help="Override WisprFlow install root (default: %LOCALAPPDATA%\\WisprFlow)",
    )
    args = ap.parse_args()
    ensure_patched(args.wispr_root, force=args.force)
    print("ensure-patched ok")


if __name__ == "__main__":
    main()
