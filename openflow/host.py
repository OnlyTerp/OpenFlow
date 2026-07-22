#!/usr/bin/env python3
"""OpenFlow silent host - one process, zero CMD windows.

What it does:
  1. If the STT shim (:18765) is already healthy → leave it alone
  2. Otherwise start the packaged server with pythonw (no console)
  3. Wait briefly for /health
  4. Launch the desktop UI if it is not already running
  5. Exit (shim keeps running as a detached process)

Entry point: launch-openflow.vbs (desktop / Startup, fully silent).

Never uses `start "title" /MIN cmd /c ...` (those flash taskbar CMD windows).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # install root (parent of openflow/)
LOG_DIR = ROOT / "logs"
HOST = os.environ.get("WISPR_GROK_HOST", "127.0.0.1")
PORT = int(os.environ.get("WISPR_GROK_PORT", "18765"))
HEALTH_URL = f"http://{HOST}:{PORT}/health"

# Windows process creation flags
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def _log(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n"
    try:
        with (LOG_DIR / "host.log").open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def _find_python() -> tuple[str, str]:
    """Return (console_python, windowless_pythonw). Prefer install next to each other."""
    env = os.environ.get("PY") or os.environ.get("PYTHON")
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env))
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python"
    for ver in ("Python313", "Python312", "Python311", "Python310"):
        candidates.append(local / ver / "python.exe")
    candidates.append(Path(sys.executable))

    py: Path | None = None
    for c in candidates:
        try:
            if c.is_file():
                py = c
                break
        except OSError:
            continue
    if py is None:
        py = Path(sys.executable)

    # pythonw next to python.exe (same install) - no console flash
    pyw = py.with_name("pythonw.exe")
    if not pyw.is_file():
        pyw = py
    return str(py), str(pyw)


def _apply_env() -> None:
    """Stable defaults for the shim child process."""
    defaults = {
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "FLOW_GRPC_URL_OVERRIDE": "127.0.0.1:1",
        "FLOW_GRPC_MODEL_ID_OVERRIDE": "local",
        "FLOW_GRPC_ENVIRONMENT_OVERRIDE": "production",
        "WISPR_GROK_HOST": HOST,
        "WISPR_GROK_PORT": str(PORT),
        "WISPR_GROK_LLM_FORMAT": "false",
        "WISPR_GROK_STT_FORMAT": "true",
        "WISPR_GROK_LOCAL_CLEANUP": "true",
        "WISPR_GROK_CHAT_MODEL": "grok-4.20-0309-non-reasoning",
        "WISPR_GROK_STT_TIMEOUT": "22",
        "WISPR_GROK_STT_CONNECT": "3",
        "WISPR_GROK_FORMAT_TIMEOUT": "8",
        "WISPR_GROK_CLIENT_BUDGET": "45",
        "WISPR_GROK_STT_RETRIES": "2",
    }
    for k, v in defaults.items():
        os.environ.setdefault(k, v)
    if not os.environ.get("GROK_AUTH_JSON"):
        home = os.environ.get("USERPROFILE") or os.environ.get("HOME") or ""
        os.environ["GROK_AUTH_JSON"] = str(Path(home) / ".grok" / "auth.json")


def health_ok(timeout: float = 1.2) -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            body = resp.read(512)
            try:
                data = json.loads(body.decode("utf-8", "replace"))
            except Exception:
                return True
            return bool(data.get("ok", True))
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _creationflags_silent() -> int:
    if sys.platform != "win32":
        return 0
    # DETACHED + NO_WINDOW: child outlives us, no console, no taskbar flash
    return CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def start_shim_silent(pyw: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    # Run as module so package imports resolve (openflow.server.app).
    env = os.environ.copy()
    # Ensure install root is on PYTHONPATH
    pp = env.get("PYTHONPATH", "")
    root_s = str(ROOT)
    env["PYTHONPATH"] = root_s if not pp else root_s + os.pathsep + pp
    kwargs: dict = {
        "args": [pyw, "-u", "-m", "openflow.server.app"],
        "cwd": str(ROOT),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": env,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = _creationflags_silent()
        kwargs["close_fds"] = True
    else:
        kwargs["start_new_session"] = True
    p = subprocess.Popen(**kwargs)
    _log(f"started shim pid={p.pid} via {pyw} -m openflow.server.app")



def wait_health(seconds: float = 8.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if health_ok():
            return True
        time.sleep(0.25)
    return False


def find_wispr_exe() -> Path | None:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates = [
        local / "WisprFlow" / "app-1.6.122" / "Wispr Flow.exe",
        local / "WisprFlow" / "Wispr Flow.exe",
    ]
    # Prefer newest app-* if version folder changes
    root = local / "WisprFlow"
    if root.is_dir():
        apps = sorted(
            (p for p in root.glob("app-*") if p.is_dir()),
            key=lambda p: p.name,
        )
        for app in reversed(apps):
            candidates.insert(0, app / "Wispr Flow.exe")
    for c in candidates:
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    return None


def ui_running() -> bool:
    if sys.platform != "win32":
        return False
    try:
        # tasklist is light; avoid WMI (can hang on this machine)
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Wispr Flow.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return "Wispr Flow.exe" in (r.stdout or "")
    except Exception:
        return False


def launch_ui(exe: Path) -> None:
    if ui_running():
        _log("UI already running - not starting another instance")
        return
    kwargs: dict = {
        "args": [str(exe)],
        "cwd": str(exe.parent),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": os.environ.copy(),
    }
    if sys.platform == "win32":
        # GUI app - don't attach a console
        kwargs["creationflags"] = CREATE_NO_WINDOW | DETACHED_PROCESS
        kwargs["close_fds"] = True
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(**kwargs)
    _log(f"started UI {exe}")




def main() -> int:
    _apply_env()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _log("==== openflow_host start ====")
    py, pyw = _find_python()
    _log(f"py={py} pyw={pyw}")

    already = health_ok()
    if already:
        _log("shim already healthy - reusing (no restart, no kill)")
    else:
        _log("shim not up - starting silent")
        try:
            start_shim_silent(pyw)
        except Exception as e:
            _log(f"FATAL start shim: {e}")
            return 1
        if not wait_health(10.0):
            _log("WARN: health not ready after 10s - starting UI anyway")
        else:
            _log("shim healthy")


    exe = find_wispr_exe()
    if not exe:
        _log("ERROR: Wispr Flow.exe not found under %LOCALAPPDATA%\\WisprFlow")
        return 2
    try:
        launch_ui(exe)
    except Exception as e:
        _log(f"ERROR launch UI: {e}")
        return 3

    _log("host done (shim detached)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:
        try:
            _log(f"crash: {e!r}")
        except Exception:
            pass
        raise
