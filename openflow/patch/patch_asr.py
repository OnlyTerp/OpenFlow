#!/usr/bin/env python3
"""Route a user-installed desktop shell to the OpenFlow loopback shim.

Edits `.webpack/main/index.js` in place. The integration redirects the
transcription endpoint, prevents the stock cloud gRPC path from winning the
request race, raises processing timeouts, and allows the renderer to contact
the loopback service. It does not alter subscription, quota, login, or update
controls.

Verified against Wispr Flow app-1.6.30 and app-1.6.122.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# ASR routing
# ---------------------------------------------------------------------------

OLD_PROD = b"https://chain-o232k03l.api.baseten.co/environments/production/run_remote"
OLD_STAGE = b"https://chain-o232k03l.api.baseten.co/environments/staging/run_remote"
NEW_PROD = b"http://127.0.0.1:18765/environments/production/run_remote"
NEW_STAGE = b"http://127.0.0.1:18765/environments/staging/run_remote"
LOCAL_HTTP_MARKER = b"http://127.0.0.1:18765/environments/production/run_remote"

GUARD_RE = re.compile(
    rb"if\(!([A-Za-z_$][\w$]*)\.app\.isPackaged\)\{const ([A-Za-z_$][\w$]*)=process\.env\.FLOW_GRPC_URL_OVERRIDE"
)

OLD_GRPC_RE = re.compile(
    rb'if\(1\)\{const e=process\.env\.FLOW_GRPC_URL_OVERRIDE\?\.trim\(\);'
    rb'if\(e\)\{const t=process\.env\.FLOW_GRPC_MODEL_ID_OVERRIDE\?\.trim\(\)\?\?"",'
    rb'n=process\.env\.FLOW_GRPC_ENVIRONMENT_OVERRIDE\?\.trim\(\)\?\?"";'
    rb'return ([A-Za-z_$][\w$]*)\(\)\.info\("Using dev gRPC route override from env",'
    rb"\{customAttributes:\{url:e,modelId:t,environment:n\}\}\),"
    rb"\{modelId:t,environment:n,url:e\}\}\}"
)



def patch_asr(text: bytes) -> bytes:
    if LOCAL_HTTP_MARKER in text and b"Using local gRPC route override" in text:
        print("ASR route: already patched")
        # still allow timeout bump if missing
    else:
        if OLD_PROD not in text or OLD_STAGE not in text:
            if LOCAL_HTTP_MARKER not in text:
                raise SystemExit(
                    "Baseten run_remote URLs not found — Wispr version changed; update this script"
                )
        else:
            text = text.replace(OLD_PROD, NEW_PROD).replace(OLD_STAGE, NEW_STAGE)
            print("rewrote HTTP run_remote -> 127.0.0.1:18765")

        if b"Using local gRPC route override" not in text:
            m = GUARD_RE.search(text)
            if m:
                text = GUARD_RE.sub(
                    rb"if(1){const \2=process.env.FLOW_GRPC_URL_OVERRIDE", text, count=1
                )
                print("unlocked FLOW_GRPC_URL_OVERRIDE for packaged builds")
            elif b"FLOW_GRPC_URL_OVERRIDE" in text and b"if(1){const" in text:
                print("FLOW_GRPC guard: already unlocked")
            else:
                raise SystemExit(
                    "FLOW_GRPC_URL_OVERRIDE isPackaged guard not found"
                )

            m = OLD_GRPC_RE.search(text)
            if m:
                log = m.group(1)
                new_block = (
                    b'if(1){const e=(process.env.FLOW_GRPC_URL_OVERRIDE?.trim()||"127.0.0.1:1");'
                    b'const t=process.env.FLOW_GRPC_MODEL_ID_OVERRIDE?.trim()??"local",'
                    b'n=process.env.FLOW_GRPC_ENVIRONMENT_OVERRIDE?.trim()??"production";'
                    b"return "
                    + log
                    + b'().info("Using local gRPC route override",'
                    b"{customAttributes:{url:e,modelId:t,environment:n}}),"
                    b"{modelId:t,environment:n,url:e}}"
                )
                text = OLD_GRPC_RE.sub(new_block, text, count=1)
                print("forced default gRPC -> 127.0.0.1:1")
            else:
                print(
                    "WARN: exact gRPC override block not found; set FLOW_GRPC_URL_OVERRIDE=127.0.0.1:1 at launch",
                    file=sys.stderr,
                )
        else:
            print("gRPC default already local")

    old_t = b"TRANSCRIPTION_TIMEOUT=1e4"
    new_t = b"TRANSCRIPTION_TIMEOUT=6e4"
    if old_t in text:
        text = text.replace(old_t, new_t, 1)
        print("bumped TRANSCRIPTION_TIMEOUT 10s -> 60s")
    elif new_t in text:
        print("timeout already 60s")
    else:
        print("WARN: TRANSCRIPTION_TIMEOUT pattern not found", file=sys.stderr)

    return text





# Stock processing timeout is 24e3 (24s) - too short for Grok STT+format.
# Variable names change between builds, so we target the constant pair near the
# "Pre-Login Feedback" label and bump the 24e3 value to 12e4 (120s).
PROC_TIMEOUT_RE = re.compile(
    rb'"Pre-Login Feedback",[A-Za-z_$][\w$]{0,3}=200,[A-Za-z_$][\w$]{0,3}=24e3\}'
)
PROC_TIMEOUT_MARKER = b"=12e4}"  # paired with unique pre-login context when patching


def patch_processing_timeout(text: bytes) -> bytes:
    """Raise in-app processing timeout 24s -> 120s (TranscriptionError toast)."""
    if PROC_TIMEOUT_RE.search(text):
        text = PROC_TIMEOUT_RE.sub(lambda m: m.group(0).replace(b"24e3", b"12e4"), text, count=1)
        print("raised processing timeout 24s -> 120s")
        return text
    if PROC_TIMEOUT_MARKER in text:
        print("processing timeout: already 120s")
        return text
    # looser fallback
    if b",te=24e3}" in text:
        text = text.replace(b",te=24e3}", b",te=12e4}", 1)
        print("raised processing timeout 24s -> 120s (loose match)")
        return text
    print("WARN: processing timeout pattern not found", file=sys.stderr)
    return text


# CSP connect-src — hub renderer cannot fetch OpenFlow shim without this
CSP_CONNECT_END = (
    b'"https://*.cloudflarestream.com","https://*.videodelivery.net"].join(" ")'
)
CSP_CONNECT_PATCHED = (
    b'"https://*.cloudflarestream.com","https://*.videodelivery.net",'
    b'"http://127.0.0.1:18765","http://localhost:18765",'
    b'"http://127.0.0.1:*","http://localhost:*"].join(" ")/*openflow-csp-shim*/'
)
CSP_MARKER = b"openflow-csp-shim"

# CSP frame-src — feature nav panels use iframes to localhost
CSP_FRAME_END = b't=["https://www.loom.com","wispr-extension:"].join(" ")'
CSP_FRAME_PATCHED = (
    b't=["https://www.loom.com","wispr-extension:",'
    b'"http://127.0.0.1:18765","http://localhost:18765"].join(" ")/*openflow-csp-frames*/'
)
CSP_FRAME_MARKER = b"openflow-csp-frames"


def patch_csp_localhost(text: bytes) -> bytes:
    """Allow renderer fetch + iframe to local OpenFlow shim (:18765)."""
    # connect-src
    if CSP_MARKER in text or b"http://127.0.0.1:18765" in text and b"connect-src" in text:
        if CSP_MARKER in text or b'"http://127.0.0.1:18765"' in text:
            print("CSP connect-src: already allows OpenFlow shim")
        elif CSP_CONNECT_END in text:
            text = text.replace(CSP_CONNECT_END, CSP_CONNECT_PATCHED, 1)
            print("CSP connect-src: allowed 127.0.0.1:18765 for Speech engine UI")
    else:
        if CSP_CONNECT_END not in text:
            print("WARN: CSP connect-src list end not found", file=sys.stderr)
        else:
            text = text.replace(CSP_CONNECT_END, CSP_CONNECT_PATCHED, 1)
            print("CSP connect-src: allowed 127.0.0.1:18765 for Speech engine UI")

    # frame-src — allow iframes to the shim for feature panels
    if CSP_FRAME_MARKER in text:
        print("CSP frame-src: already allows OpenFlow shim")
    elif CSP_FRAME_END in text:
        text = text.replace(CSP_FRAME_END, CSP_FRAME_PATCHED, 1)
        print("CSP frame-src: allowed 127.0.0.1:18765 for feature panels")
    else:
        print("WARN: CSP frame-src list not found", file=sys.stderr)

    return text
# Auto-updater disable — prevent Wispr from auto-updating to an unpatched
# version (e.g. 1.6.224) that would strip all OpenFlow patches.
UPDATER_MARKER = b"openflow-disable-updates"
_UPDATER_OLD = b"async checkForUpdates(e=!1){if(this.updateState!==d.D9.AVAILABLE)"
_UPDATER_NEW = b"async checkForUpdates(e=!1){return;/*openflow-disable-updates*/if(this.updateState!==d.D9.AVAILABLE)"


def _replace_method_body(text: bytes, signature: bytes) -> bytes:
    """Replace the { ... } body of the method identified by signature with a no-op."""
    idx = text.find(signature)
    if idx == -1:
        return text
    open_brace = text.find(b"{", idx)
    if open_brace == -1:
        return text
    depth = 0
    in_string: bytes | None = None
    escape = False
    i = open_brace
    while i < len(text):
        c = text[i:i+1]
        if in_string:
            if escape:
                escape = False
            elif c == b"\\":
                escape = True
            elif c == in_string:
                in_string = None
            i += 1
            continue
        if c in (b'"', b"'", b"`"):
            in_string = c
            i += 1
            continue
        if c == b"{":
            depth += 1
        elif c == b"}":
            depth -= 1
            if depth == 0:
                return text[:open_brace] + b"{/*openflow-disable-updates*/}" + text[i + 1:]
        i += 1
    return text


def patch_disable_updates(text: bytes) -> bytes:
    """Disable Wispr auto-updater to prevent auto-update to unpatched versions."""
    if _UPDATER_OLD in text:
        text = text.replace(_UPDATER_OLD, _UPDATER_NEW, 1)
        print("auto-updater: disabled checkForUpdates")
    elif UPDATER_MARKER in text:
        print("auto-updater: checkForUpdates already disabled")
    else:
        print("WARN: checkForUpdates pattern not found - updater may auto-update", file=sys.stderr)

    # Nerf the rest of the update manager so menu/manual update flows cannot
    # trigger a download, install, or UI prompt either.
    if b"openflow-disable-listeners" not in text:
        text = _replace_method_body(
            text,
            b'setupListeners(){r.autoUpdater.on("checking-for-update",()=>this.setUpdateState(d.D9.CHECKING))',
        )
        text = _replace_method_body(
            text,
            b'handleDownloadAvailable(){const e=v.RA.prefs?.updateRetry',
        )
        text = _replace_method_body(
            text,
            b'async applyUpdate(){const e=r.app.getVersion(),t=v.RA.prefs?.updateRetry?.retryCount??0',
        )
        if b"{/*openflow-disable-updates*/}" in text:
            print("auto-updater: disabled listeners / download / install flow")
    else:
        print("auto-updater: listeners already disabled")
    return text

def patch(index_js: Path) -> None:
    text = index_js.read_bytes()
    text = patch_asr(text)
    text = patch_processing_timeout(text)
    text = patch_csp_localhost(text)
    text = patch_disable_updates(text)
    index_js.write_bytes(text)
    print("wrote", index_js)


def verify_bytes(data: bytes) -> dict[str, bool]:
    """Shared checklist for asar / index.js contents."""
    return {
        "local HTTP": LOCAL_HTTP_MARKER in data,
        "old Baseten gone": OLD_PROD not in data,
        "local gRPC override": b"Using local gRPC route override" in data
        or b"FLOW_GRPC_URL_OVERRIDE" in data,
        "timeout 60s": b"TRANSCRIPTION_TIMEOUT=6e4" in data,
        "processing timeout 120s": b"=12e4}" in data,
        "csp allows shim": CSP_MARKER in data
        or b'"http://127.0.0.1:18765"' in data,
        "csp allows frames": CSP_FRAME_MARKER in data,
        "auto-updater disabled": UPDATER_MARKER in data,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "extract_dir",
        type=Path,
        help="Path to extracted asar root (contains .webpack/main/index.js)",
    )
    args = ap.parse_args()
    index = args.extract_dir / ".webpack" / "main" / "index.js"
    if not index.is_file():
        raise SystemExit(f"missing {index}")
    patch(index)
    checks = verify_bytes(index.read_bytes())
    for k, v in checks.items():
        print(f"  {'OK' if v else 'FAIL'}: {k}")
    if not all(checks.values()):
        raise SystemExit("post-patch verify failed")


if __name__ == "__main__":
    main()
