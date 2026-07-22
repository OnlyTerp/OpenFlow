#!/usr/bin/env python3
"""OpenFlow CLI — single entry for install / start / status / patch.

Usage:
  python -m openflow install     # deploy to %LOCALAPPDATA%\\OpenFlow + shortcuts
  python -m openflow start       # silent host (shim + desktop UI)
  python -m openflow serve       # shim only (foreground)
  python -m openflow status      # health check
  python -m openflow patch       # re-apply desktop asar patch
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from openflow import __version__

_INSTALL_FILES = (
    "package.json",
    "package-lock.json",
    "LICENSE",
    "README.md",
    "launch-openflow.vbs",
)


def _repo_root() -> Path:
    # openflow/cli.py -> openflow/ -> repo or install root
    return Path(__file__).resolve().parents[1]


def _windows_path_for_wsl(raw: str) -> Path | None:
    """Translate a Windows drive path to its standard WSL mount."""
    value = raw.strip().replace("\r", "")
    if len(value) < 3 or value[1:3] not in (":\\", ":/"):
        return None
    drive = value[0].lower()
    rest = value[3:].replace("\\", "/").lstrip("/")
    return Path("/mnt") / drive / rest


def _default_install_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "OpenFlow"

    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        return Path(userprofile) / "AppData" / "Local" / "OpenFlow"

    # WSL does not normally inherit LOCALAPPDATA. Ask Windows for the active
    # profile rather than baking a contributor's username into the package.
    try:
        raw = subprocess.check_output(
            ["cmd.exe", "/d", "/c", "echo", "%LOCALAPPDATA%"],
            text=True,
            timeout=3,
            stderr=subprocess.DEVNULL,
        )
        win_local = _windows_path_for_wsl(raw)
        if win_local is not None and win_local.is_dir():
            return win_local / "OpenFlow"
    except (OSError, subprocess.SubprocessError):
        pass

    users = Path("/mnt/c/Users")
    if users.is_dir():
        excluded = {
            "All Users",
            "Default",
            "Default User",
            "Public",
            "CodexSandboxOffline",
        }
        for child in sorted(users.iterdir()):
            if child.name in excluded:
                continue
            candidate = child / "AppData" / "Local"
            try:
                if candidate.is_dir():
                    return candidate / "OpenFlow"
            except OSError:
                continue

    return Path.home() / "OpenFlow"


def _win_path(p: Path) -> str:
    """Path string usable by Windows PowerShell (C:\\... not /mnt/c/...)."""
    s = str(p.resolve())
    if s.startswith("/mnt/c/") or s.startswith("/mnt/c\\"):
        rest = s[7:].replace("/", "\\")
        return "C:\\" + rest
    return s


def cmd_status(_: argparse.Namespace) -> int:
    host = os.environ.get("WISPR_GROK_HOST", "127.0.0.1")
    port = os.environ.get("WISPR_GROK_PORT", "18765")
    url = f"http://{host}:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            body = resp.read().decode("utf-8", "replace")
        data = json.loads(body)
        print(json.dumps(data, indent=2))
        return 0 if data.get("ok") else 1
    except Exception as e:
        print(f"shim offline ({url}): {e}", file=sys.stderr)
        return 1


def cmd_serve(_: argparse.Namespace) -> int:
    from openflow.server.app import main as serve_main

    serve_main()
    return 0


def cmd_start(_: argparse.Namespace) -> int:
    from openflow.host import main as host_main

    return int(host_main() or 0)


def cmd_patch(args: argparse.Namespace) -> int:
    from openflow.patch.ensure import ensure_patched

    ensure_patched(force=bool(args.force))
    print("patch ok")
    return 0


def cmd_restore(_: argparse.Namespace) -> int:
    from openflow.patch.ensure import restore_stock

    restore_stock()
    return 0




def cmd_install(args: argparse.Namespace) -> int:
    """Copy this tree to a single Windows install root and wire shortcuts."""
    src = _repo_root()
    dest = Path(args.dir) if args.dir else _default_install_dir()
    dest = dest.resolve()
    print(f"OpenFlow {__version__}")
    print(f"  source:  {src}")
    print(f"  install: {dest}")

    if not (src / "openflow" / "__init__.py").is_file():
        print("error: openflow package missing in source", file=sys.stderr)
        return 2

    dest.mkdir(parents=True, exist_ok=True)
    # Sync package + launcher assets
    pkg_src = src / "openflow"
    pkg_dst = dest / "openflow"
    if pkg_dst.exists():
        shutil.rmtree(pkg_dst)
    shutil.copytree(
        pkg_src,
        pkg_dst,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
    )

    for name in _INSTALL_FILES:
        s = src / name
        if s.is_file():
            shutil.copy2(s, dest / name)

    # Always write canonical silent VBS at install root
    vbs = dest / "launch-openflow.vbs"
    vbs.write_text(textwrap_vbs_module(), encoding="utf-8")

    # node_modules for asar tooling (devDependency)
    if not (dest / "node_modules" / "@electron" / "asar").is_dir():
        if (src / "node_modules" / "@electron" / "asar").is_dir():
            print("  copying node_modules/@electron/asar …")
            nm = dest / "node_modules"
            if nm.exists():
                shutil.rmtree(nm)
            shutil.copytree(src / "node_modules", nm)
        else:
            print("  note: run npm install in install dir before patching")

    (dest / "logs").mkdir(exist_ok=True)
    # Marker so host/patch know this is the install root
    (dest / "OPENFLOW_HOME").write_text(str(dest), encoding="utf-8")

    # Wire shortcuts to this install only
    if not args.no_shortcuts:
        _install_shortcuts(dest)


    print("install complete")
    print(f"  start:  wscript //B //Nologo \"{dest / 'launch-openflow.vbs'}\"")
    print(f"  or:     python -m openflow start   (with PYTHONPATH={dest})")
    return 0


def textwrap_vbs_module() -> str:
    return (
        "Option Explicit\n"
        "Dim sh, fso, dir, pyw, localApp, candidates, i\n"
        'Set sh = CreateObject("WScript.Shell")\n'
        'Set fso = CreateObject("Scripting.FileSystemObject")\n'
        "dir = fso.GetParentFolderName(WScript.ScriptFullName)\n"
        "sh.CurrentDirectory = dir\n"
        'pyw = ""\n'
        'localApp = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%")\n'
        "candidates = Array( _\n"
        '  localApp & "\\Programs\\Python\\Python313\\pythonw.exe", _\n'
        '  localApp & "\\Programs\\Python\\Python312\\pythonw.exe", _\n'
        '  localApp & "\\Programs\\Python\\Python311\\pythonw.exe" _\n'
        ")\n"
        "For i = 0 To UBound(candidates)\n"
        "  If fso.FileExists(candidates(i)) Then\n"
        "    pyw = candidates(i)\n"
        "    Exit For\n"
        "  End If\n"
        "Next\n"
        'If pyw = "" Then pyw = "pythonw.exe"\n'
        # Set PYTHONPATH=dir so -m openflow resolves
        'sh.Environment("Process")("PYTHONPATH") = dir\n'
        'sh.Run """" & pyw & """ -m openflow start", 0, False\n'
    )


def _install_shortcuts(install_dir: Path) -> None:
    """Create OpenFlow.lnk → launch-openflow.vbs; remove stock dual-launch shortcuts."""
    if sys.platform != "win32" and not str(install_dir).startswith("/mnt/c"):
        # Best-effort from WSL via powershell
        pass
    vbs = install_dir / "launch-openflow.vbs"
    icon = install_dir / "openflow" / "static"  # fallback later
    # Prefer assets if present
    for cand in (
        install_dir / "assets" / "openflow.ico",
        _repo_root() / "assets" / "openflow.ico",
    ):
        if cand.is_file():
            icon = cand
            break
    else:
        local = os.environ.get("LOCALAPPDATA", "")
        icon = Path(local) / "WisprFlow" / "app-1.6.122" / "Wispr Flow.exe"

    launcher = _win_path(vbs)
    icon_s = _win_path(icon)
    ps = f"""
$ErrorActionPreference = 'Stop'
$Launcher = '{launcher.replace("'", "''")}'
$Icon = '{icon_s.replace("'", "''")}'
if (-not (Test-Path -LiteralPath $Launcher)) {{ throw "Launcher missing: $Launcher" }}
function Set-Shortcut($Path, $Target) {{
  $dir = Split-Path -Parent $Path
  if (-not (Test-Path $dir)) {{ New-Item -ItemType Directory -Path $dir -Force | Out-Null }}
  $shell = New-Object -ComObject WScript.Shell
  $s = $shell.CreateShortcut($Path)
  $s.TargetPath = $Target
  $s.WorkingDirectory = (Split-Path -Parent $Target)
  $s.WindowStyle = 7
  if (Test-Path -LiteralPath $Icon) {{ $s.IconLocation = "$Icon,0" }}
  $s.Description = 'OpenFlow - local dictation'
  $s.Save()
  Write-Output "OK $Path -> $Target"
}}
# Remove dual-tree / stock launchers
$kill = @(
  "$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\Wispr Flow.lnk",
  "$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\Grok Flow Shim.lnk",
  "$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\Grok Flow.lnk",
  "$env:USERPROFILE\\Desktop\\Wispr Flow.lnk",
  "$env:USERPROFILE\\OneDrive\\Desktop\\Wispr Flow.lnk"
)
foreach ($p in $kill) {{ if (Test-Path -LiteralPath $p) {{ Remove-Item -LiteralPath $p -Force; Write-Output "Removed $p" }} }}
Set-Shortcut "$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\OpenFlow.lnk" $Launcher
Set-Shortcut "$env:USERPROFILE\\Desktop\\OpenFlow.lnk" $Launcher
if (Test-Path "$env:USERPROFILE\\OneDrive\\Desktop") {{
  Set-Shortcut "$env:USERPROFILE\\OneDrive\\Desktop\\OpenFlow.lnk" $Launcher
}}
Set-Shortcut "$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\OpenFlow.lnk" $Launcher
"""
    try:
        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps,
            ],
            check=False,
            timeout=60,
        )
    except Exception as e:
        print(f"  warn: shortcuts: {e}")




def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="openflow",
        description=f"OpenFlow {__version__} — local multi-engine dictation",
    )
    ap.add_argument("--version", action="version", version=f"OpenFlow {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_install = sub.add_parser("install", help="Deploy to a single install root + shortcuts")
    p_install.add_argument(
        "--dir",
        default=None,
        help="Install directory (default: %%LOCALAPPDATA%%\\OpenFlow)",
    )
    p_install.add_argument("--no-shortcuts", action="store_true")
    p_install.set_defaults(func=cmd_install)

    sub.add_parser("start", help="Silent start shim + desktop UI").set_defaults(
        func=cmd_start
    )
    sub.add_parser("serve", help="Run STT shim in foreground").set_defaults(func=cmd_serve)
    sub.add_parser("status", help="GET /health").set_defaults(func=cmd_status)

    p_patch = sub.add_parser("patch", help="Ensure desktop asar is OpenFlow-patched")
    p_patch.add_argument("--force", action="store_true")
    p_patch.set_defaults(func=cmd_patch)
    sub.add_parser(
        "restore",
        help="Restore the stock desktop asar backup",
    ).set_defaults(func=cmd_restore)


    args = ap.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
