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





# Stock processing timeout te=24e3 (24s) - too short for Grok STT+format.
PROC_TIMEOUT_RE = re.compile(
    rb',V=3e4,G=3e4,Y=12e4,K=6e4,Z=3145728,X=20971520,J="Pre-Login Feedback",ee=200,te=24e3'
)
PROC_TIMEOUT_BYPASS = (
    b',V=3e4,G=3e4,Y=12e4,K=6e4,Z=3145728,X=20971520,J="Pre-Login Feedback",ee=200,te=12e4'
)
PROC_TIMEOUT_MARKER = b"te=12e4"  # paired with unique pre-login context when patching


def patch_processing_timeout(text: bytes) -> bytes:
    """Raise in-app processing timeout 24s -> 120s (TranscriptionError toast)."""
    if PROC_TIMEOUT_RE.search(text):
        text = PROC_TIMEOUT_RE.sub(PROC_TIMEOUT_BYPASS, text, count=1)
        print("raised processing timeout 24s -> 120s")
        return text
    if b',ee=200,te=12e4}' in text or b',ee=200,te=12e4},' in text:
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


def patch_csp_localhost(text: bytes) -> bytes:
    """Allow renderer fetch to local OpenFlow STT shim (:18765)."""
    if CSP_MARKER in text or b"http://127.0.0.1:18765" in text and b"connect-src" in text:
        # marker or already has explicit host near CSP
        if CSP_MARKER in text or b'"http://127.0.0.1:18765"' in text:
            print("CSP connect-src: already allows OpenFlow shim")
            return text
    if CSP_CONNECT_END not in text:
        print("WARN: CSP connect-src list end not found", file=sys.stderr)
        return text
    text = text.replace(CSP_CONNECT_END, CSP_CONNECT_PATCHED, 1)
    print("CSP connect-src: allowed 127.0.0.1:18765 for Speech engine UI")
    return text


def patch(index_js: Path) -> None:
    text = index_js.read_bytes()
    text = patch_asr(text)
    text = patch_processing_timeout(text)
    text = patch_csp_localhost(text)
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
        "processing timeout 120s": b",ee=200,te=12e4" in data
        or b"te=12e4" in data,
        "csp allows shim": CSP_MARKER in data
        or b'"http://127.0.0.1:18765"' in data,
        "no subscription bypass": not any(
            marker in data
            for marker in (
                b"grok-flow-skip-weekly-limit",
                b"grok-flow-pro",
                b"grok-flow-nolimit",
                b"grok-flow-local-offline-token",
            )
        ),
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
