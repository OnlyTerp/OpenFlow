#!/usr/bin/env python3
"""Install, verify, or restore the OpenFlow desktop integration.

The patch is applied only to a Wispr Flow installation already present on the
user's machine. Proprietary application files are never bundled with OpenFlow.

Orchestrates the full patch pipeline against the immutable stock backup
(``app.asar.bak-pre-grok-stt``) and always rebuilds the live asar from stock:

    patch_asr.py  -> ASR routing, timeouts, CSP, auto-update pin
    patch_offline_local.py -> local account / no-login-wall patches
    rebrand.py    -> product strings, package.json, safe color swaps
    inject.py     -> UI theme/overlay assets + hub JS chrome patches

Verified against Wispr Flow app-1.6.122.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from openflow.patch.asar_api import newest_app_dir, verify_asar

SCRIPT_DIR = Path(__file__).resolve().parent

STOCK_BACKUP_NAME = "app.asar.bak-pre-grok-stt"

# Pipeline order is load-bearing: binary patches first, strings/rebrand next,
# renderer asset injection last.
PIPELINE = (
    "patch_asr.py",
    "patch_offline_local.py",
    "rebrand.py",
    "inject.py",
)


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
    # repo checkout root (dev) — may have node_modules here
    candidates.append(Path(__file__).resolve().parents[2])
    # install root = parent of openflow package (e.g. .../OpenFlow)
    candidates.append(SCRIPT_DIR.parents[1].parent)  # .../OpenFlow
    candidates.append(SCRIPT_DIR.parents[1])  # .../openflow (unlikely)
    # WSL install root (LOCALAPPDATA/OpenFlow)
    try:
        la = _localappdata()
        candidates.append(la / "OpenFlow")
    except Exception:
        pass
    for c in candidates:
        if (c / "node_modules" / "@electron" / "asar").is_dir():
            return c
    return None


def _wsl_to_win(path: str) -> str:
    """Convert /mnt/c/... WSL paths to C:\\... Windows paths for Node interop."""
    if path.startswith("/mnt/"):
        drive = path[5]  # drive letter
        rest = path[6:].replace("/", "\\")
        return f"{drive.upper()}:\\{rest}"
    return path


def _run_asar(node: str, repo: Path, action: str, src: str, dst: str) -> None:
    """Extract or pack an asar (no unpack globs — all files inlined)."""
    src_win = _wsl_to_win(src)
    dst_win = _wsl_to_win(dst)
    if action == "extract":
        code = (
            "const asar=require('@electron/asar');"
            "asar.extractAll(process.argv[1], process.argv[2]);"
            "console.log('extracted');"
        )
        argv = [node, "-e", code, src_win, dst_win]
    else:
        code = (
            "const asar=require('@electron/asar');"
            "asar.createPackage(process.argv[1], process.argv[2])"
            ".then(()=>console.log('packed'));"
        )
        argv = [node, "-e", code, src_win, dst_win]
    subprocess.check_call(argv, cwd=str(repo))


def _run_asar_with_unpack(node: str, repo: Path, src: str, dst: str,
                          unpack_glob: str | None,
                          unpack_dir: str | None) -> None:
    """Pack an asar with optional unpack globs for native modules."""
    src_win = _wsl_to_win(src)
    dst_win = _wsl_to_win(dst)
    opts_parts = []
    if unpack_glob:
        opts_parts.append("unpack:" + json.dumps(unpack_glob))
    if unpack_dir:
        opts_parts.append("unpackDir:" + json.dumps(unpack_dir))
    opts = "{" + ",".join(opts_parts) + "}" if opts_parts else "{}"
    code = (
        "const asar=require('@electron/asar');"
        "asar.createPackageWithOptions(process.argv[1], process.argv[2],"
        + opts + ")"
        ".then(()=>console.log('packed'));"
    )
    subprocess.check_call([node, "-e", code, src_win, dst_win], cwd=str(repo))


def _detect_unpack_globs(asar: Path) -> tuple[str | None, str | None]:
    """Inspect the asar header to find which file patterns are unpacked.

    Returns (unpack_glob, unpack_dir_glob) suitable for createPackageWithOptions,
    or (None, None) if no files are unpacked (all inlined).

    Parses the ASAR binary header directly (first 16 bytes = size fields,
    JSON starts at byte 16) to avoid reading the entire ~196 MB file.
    """
    import struct as _struct
    import json as _json

    with asar.open("rb") as f:
        hdr = f.read(16)
        if len(hdr) < 16:
            return None, None
        # ASAR header: four uint32 LE fields, each decrementing by 4:
        #   [0:4]   pickle_size (always 4)
        #   [4:8]   payload_size (JSON + 8 bytes of size fields)
        #   [8:12]  payload_size - 4
        #   [12:16] json_length (the actual JSON string length)
        fields = _struct.unpack("<IIII", hdr)
        pickle_size, payload_size, mid, json_len = fields
        # Validate the expected decrement pattern
        if pickle_size != 4 or mid != payload_size - 4 or json_len != payload_size - 8:
            return None, None
        if json_len <= 0 or json_len > 10_000_000:
            return None, None
        header_bytes = f.read(json_len)

    if len(header_bytes) < json_len:
        return None, None

    header = _json.loads(header_bytes.decode("utf-8", errors="replace"))

    unpacked_exts = set()
    unpacked_dirs = set()

    def walk(node, prefix=""):
        if "files" in node:
            for name, child in node["files"].items():
                path = prefix + "/" + name if prefix else name
                if child.get("unpacked"):
                    basename = path.rsplit("/", 1)[-1]
                    if "." in basename:
                        ext = basename.rsplit(".", 1)[-1]
                        unpacked_exts.add(ext)
                    parts = path.split("/")
                    if len(parts) > 1:
                        unpacked_dirs.add("/".join(parts[:3]))
                walk(child, path)

    walk(header)
    if not unpacked_exts:
        return None, None

    exts = sorted(unpacked_exts)
    unpack_glob = "*{" + ",".join(exts) + "}"
    if unpacked_dirs:
        dirs = [d for d in sorted(unpacked_dirs) if d]
        unpack_dir = "{" + ",".join(dirs) + "}/**"
    else:
        unpack_dir = None
    return unpack_glob, unpack_dir


def _version_key(path: Path) -> tuple[tuple[int, int | str], ...]:
    parts: list[tuple[int, int | str]] = []
    for part in path.name.removeprefix("app-").split("."):
        try:
            parts.append((1, int(part)))
        except ValueError:
            parts.append((0, part))
    return tuple(parts)


def _newest_app_with_asar(root: Path) -> Path:
    """Newest app-* dir that actually contains a working resources/app.asar."""
    apps = [p for p in root.glob("app-*") if p.is_dir()]
    if not apps:
        raise SystemExit(f"no app-* under {root}")
    for app in sorted(apps, key=_version_key, reverse=True):
        if (app / "resources" / "app.asar").is_file():
            return app
    raise SystemExit(f"no app-* with resources/app.asar under {root}")


def _stock_backup(asar: Path) -> Path:
    """Return the immutable stock backup, creating it from a clean live asar.

    The backup is only created when the live asar does NOT already carry
    OpenFlow pipeline markers — a patched live asar can never become the
    stock baseline.
    """
    backup = asar.with_name(STOCK_BACKUP_NAME)
    if backup.is_file():
        return backup
    ok, _ = verify_asar(asar)
    if ok:
        raise SystemExit(
            f"live asar is already patched but stock backup {backup} is missing; "
            "cannot synthesize a stock baseline from patched bytes — reinstall "
            "Wispr Flow or restore an unpatched app.asar first"
        )
    shutil.copy2(asar, backup)
    print(f"stock backup -> {backup}")
    return backup


def ensure_patched(wispr_root: Path | None = None, force: bool = False) -> Path:
    """Patch the Wispr Flow ASAR by rebuilding from the immutable stock backup.

    Runs the full pipeline (patch_asr -> patch_offline_local -> rebrand ->
    inject) against a pristine extraction of ``app.asar.bak-pre-grok-stt``,
    repacks with the same unpack globs the stock build used, verifies the
    full marker set, and atomically swaps the live asar.
    """
    if wispr_root is not None:
        root = Path(wispr_root)
    else:
        root = _localappdata() / "WisprFlow"
    app = _newest_app_with_asar(root)
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

    backup = _stock_backup(asar)
    print("rebuilding from stock backup...")

    node = _find_node()
    if not node:
        raise SystemExit("node not found — needed to extract/pack asar")

    repo = _asar_js()
    if not repo:
        raise SystemExit(
            "@electron/asar not found — run npm install in the OpenFlow install dir"
        )

    # Detect the stock backup's unpack settings to preserve them on repack
    unpack_glob, unpack_dir = _detect_unpack_globs(backup)
    if unpack_glob:
        print(f"detected unpack glob: {unpack_glob}")
    else:
        print("no unpacked files (all inlined)")

    # Stage in a Windows-accessible temp dir (Node runs on the Windows side
    # when invoked from WSL against /mnt/c paths).
    import platform
    import time as _time

    stage_root = None
    if platform.system() == "Linux" and _localappdata().as_posix().startswith("/mnt/"):
        stage_root = _localappdata() / "OpenFlow" / "tmp-asar-stage"
        stage_root.mkdir(parents=True, exist_ok=True)
        stage_dir = stage_root / f"stage-{int(_time.time())}"
        stage_dir.mkdir(parents=True, exist_ok=True)
    else:
        stage_dir = Path(tempfile.mkdtemp(prefix="openflow-asar-"))
    try:
        extract = stage_dir / "extract"
        extract.mkdir()

        # If the stock backup has an .unpacked companion requirement, make the
        # live .unpacked visible under the backup's sibling name so extractAll
        # can copy unpacked payloads.
        backup_unpacked = backup.with_name(backup.stem + ".unpacked")
        if backup_unpacked.exists() and not backup_unpacked.is_dir():
            backup_unpacked.unlink()
        if not backup_unpacked.is_dir():
            live_unpacked = asar.with_name("app.asar.unpacked")
            if live_unpacked.is_dir() and unpack_glob:
                bu_win = _wsl_to_win(str(backup_unpacked))
                lu_win = _wsl_to_win(str(live_unpacked))
                subprocess.run(
                    ["powershell.exe", "-NoProfile", "-Command",
                     f"New-Item -ItemType Junction -Path '{bu_win}' "
                     f"-Target '{lu_win}' -ErrorAction SilentlyContinue"],
                    capture_output=True, text=True,
                )

        # Always extract from the immutable stock backup
        _run_asar(node, repo, "extract", str(backup), str(extract))

        # Run the full patch pipeline in order
        for name in PIPELINE:
            script = SCRIPT_DIR / name
            print(f"pipeline: {name}")
            subprocess.check_call([sys.executable, str(script), str(extract)])

        # Repack with the same unpack settings as the stock build so
        # .node/.dll/.exe payloads stay unpacked
        out = stage_dir / "app.asar.patched"
        if unpack_glob:
            _run_asar_with_unpack(node, repo, str(extract), str(out),
                                  unpack_glob, unpack_dir)
        else:
            _run_asar(node, repo, "pack", str(extract), str(out))

        # Atomically replace the live asar
        shutil.copy2(out, asar)

        # Handle .unpacked companion
        out_unpacked = stage_dir / "app.asar.patched.unpacked"
        if out_unpacked.is_dir():
            live_unpacked = asar.with_name("app.asar.unpacked")
            if live_unpacked.is_dir():
                shutil.rmtree(live_unpacked)
            shutil.copytree(str(out_unpacked), str(live_unpacked))
        elif not unpack_glob:
            live_unpacked = asar.with_name("app.asar.unpacked")
            if live_unpacked.is_dir():
                shutil.rmtree(live_unpacked)

        # Clean up any junctions created for extraction
        if backup_unpacked.is_dir() or backup_unpacked.is_symlink():
            try:
                subprocess.run(
                    ["powershell.exe", "-NoProfile", "-Command",
                     f"Remove-Item -Force '{_wsl_to_win(str(backup_unpacked))}'"],
                    capture_output=True, text=True,
                )
            except OSError:
                pass

        print(f"installed -> {asar}")
    finally:
        if stage_root is None or stage_dir != stage_root:
            shutil.rmtree(stage_dir, ignore_errors=True)

    ok, checks = verify_asar(asar)
    for k, v in checks.items():
        print(f"  {'OK' if v else 'FAIL'}: {k}")
    if not ok:
        raise SystemExit("verify failed after patch")
    return asar


def restore_stock(wispr_root: Path | None = None) -> Path:
    """Restore the stock asar backup created before the first patch."""
    root = Path(wispr_root) if wispr_root is not None else _localappdata() / "WisprFlow"
    app = newest_app_dir(root)
    asar = app / "resources" / "app.asar"
    backup = asar.with_name(STOCK_BACKUP_NAME)
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
