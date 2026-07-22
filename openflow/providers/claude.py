"""Claude plan STT via claude.ai speech WebSocket (Desktop capture recipe).

Optimizations for parity with Grok/ChatGPT latency:
  - Burst audio ~8× realtime (still framed at 2730 B)
  - Single-thread send/recv interleave (no socket race)
  - Early finish: stable TranscriptText after CloseStream (~250ms)
  - Cookie cache (force refresh only on auth failure / TTL)
  - One automatic reconnect with cookie refresh
  - Snappier endpointing params vs stock Desktop
"""

from __future__ import annotations

import json
import logging
import os
import platform
import struct
import time
import wave
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode

from .base import ProviderStatus, SttError

log = logging.getLogger("openflow.claude")

WS_BASE = os.environ.get(
    "OPENFLOW_CLAUDE_STT_WS",
    "wss://claude.ai/api/ws/speech_to_text/voice_stream",
)
SAMPLE_RATE = int(os.environ.get("OPENFLOW_CLAUDE_SAMPLE_RATE", "16000"))
FRAME_BYTES = int(os.environ.get("OPENFLOW_CLAUDE_FRAME_BYTES", "2730"))
STT_TIMEOUT = float(os.environ.get("OPENFLOW_CLAUDE_STT_TIMEOUT", "30"))
# Burst factor: 1.0 = realtime (Desktop). ~1.8× keeps quality + cuts wait.
# 8× dropped words; 2.5× nearly full but still clipped the last word.
BURST = float(os.environ.get("OPENFLOW_CLAUDE_BURST", "1.8"))
CLIENT_VERSION = os.environ.get("OPENFLOW_CLAUDE_CLIENT_VERSION", "1.22209.0")
STT_PROVIDER = os.environ.get("OPENFLOW_CLAUDE_STT_PROVIDER", "deepgram-nova3")
# Wait for text to stop growing after CloseStream before early-exit
STABLE_MS = float(os.environ.get("OPENFLOW_CLAUDE_STABLE_MS", "600")) / 1000.0
# Never early-exit until this long after CloseStream (lets progressive text catch up)
MIN_POST_CLOSE_S = float(os.environ.get("OPENFLOW_CLAUDE_MIN_POST_CLOSE", "0.9"))
CONNECT_TIMEOUT = float(os.environ.get("OPENFLOW_CLAUDE_CONNECT_TIMEOUT", "8"))
POST_CLOSE_MAX = float(os.environ.get("OPENFLOW_CLAUDE_POST_CLOSE_MAX", "8"))
# Trailing silence so Deepgram can finalize the last word before CloseStream
TRAIL_MS = float(os.environ.get("OPENFLOW_CLAUDE_TRAIL_MS", "280"))


def _os_headers() -> dict[str, str]:
    force_darwin = os.environ.get("OPENFLOW_CLAUDE_SPOOF_DARWIN", "1").lower() in {
        "1",
        "true",
        "yes",
    }
    if force_darwin or platform.system() == "Darwin":
        ver = (
            platform.mac_ver()[0]
            if platform.system() == "Darwin"
            else os.environ.get("OPENFLOW_CLAUDE_OS_VERSION", "26.3.1")
        )
        return {
            "anthropic-client-os-platform": "darwin",
            "anthropic-client-os-version": ver or "26.3.1",
            "user-agent": (
                f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                f"AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Claude/{CLIENT_VERSION} Chrome/148.0.0.0 Electron/42.5.1 Safari/537.36"
            ),
        }
    ver = platform.version() or "10.0.26100"
    return {
        "anthropic-client-os-platform": "win32",
        "anthropic-client-os-version": ver,
        "user-agent": (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Claude/{CLIENT_VERSION} Chrome/148.0.0.0 Electron/42.5.1 Safari/537.36"
        ),
    }


def _build_url(org_uuid: str | None, language: str) -> str:
    lang = language or "en-US"
    if len(lang) == 2:
        lang = f"{lang}-US" if lang.lower() == "en" else lang
    q = {
        "encoding": "linear16",
        "sample_rate": str(SAMPLE_RATE),
        "channels": "1",
        # Snappier than stock Desktop so short dictations finish faster
        "endpointing_ms": "250",
        "utterance_end_ms": "600",
        "language": lang,
        "use_conversation_engine": "true",
        "stt_provider": STT_PROVIDER,
        "client_platform": "desktop_app",
    }
    if org_uuid:
        q["organization_uuid"] = org_uuid
    return f"{WS_BASE}?{urlencode(q)}"


def _wav_to_pcm16_mono(wav_bytes: bytes, target_rate: int) -> bytes:
    bio = BytesIO(wav_bytes)
    try:
        with wave.open(bio, "rb") as w:
            ch = w.getnchannels()
            sw = w.getsampwidth()
            rate = w.getframerate()
            raw = w.readframes(w.getnframes())
    except wave.Error:
        if wav_bytes[:4] == b"RIFF":
            raise SttError("Invalid WAV for Claude STT")
        return wav_bytes

    if sw != 2:
        raise SttError(f"Claude STT needs 16-bit PCM (got sampwidth={sw})")

    if ch == 1:
        mono = raw
    elif ch == 2:
        samples = struct.unpack("<" + "h" * (len(raw) // 2), raw)
        mixed = [
            int((samples[i] + samples[i + 1]) / 2) for i in range(0, len(samples) - 1, 2)
        ]
        mono = struct.pack("<" + "h" * len(mixed), *mixed)
    else:
        samples = struct.unpack("<" + "h" * (len(raw) // 2), raw)
        first = samples[0::ch]
        mono = struct.pack("<" + "h" * len(first), *first)

    if rate == target_rate:
        return mono

    import array

    src = array.array("h")
    src.frombytes(mono)
    if not src:
        return b""
    ratio = rate / float(target_rate)
    out_len = max(1, int(len(src) / ratio))
    out = array.array("h", [0] * out_len)
    for i in range(out_len):
        src_i = i * ratio
        j = int(src_i)
        frac = src_i - j
        a = src[j]
        b = src[j + 1] if j + 1 < len(src) else a
        out[i] = int(a + (b - a) * frac)
    return out.tobytes()


def _pad_frame(piece: bytes, frame: int) -> bytes:
    if len(piece) >= frame:
        return piece[:frame]
    return piece + b"\x00" * (frame - len(piece))


def _handshake_headers(cookie: str) -> list[str]:
    os_h = _os_headers()
    return [
        f"Cookie: {cookie}",
        f"User-Agent: {os_h['user-agent']}",
        "Origin: https://claude.ai",
        "Pragma: no-cache",
        "Cache-Control: no-cache",
        "Accept-Language: en-US",
        "anthropic-client-app: com.anthropic.claudefordesktop",
        f"anthropic-client-os-platform: {os_h['anthropic-client-os-platform']}",
        f"anthropic-client-os-version: {os_h['anthropic-client-os-version']}",
        "anthropic-client-platform: desktop_app",
        f"anthropic-client-version: {CLIENT_VERSION}",
        "anthropic-desktop-topbar: 1",
    ]


def transcribe_ws(pcm: bytes, cookie: str, org_uuid: str | None, language: str) -> str:
    try:
        import websocket
        from websocket import ABNF
    except ImportError as e:
        raise SttError("Install websocket-client: pip install websocket-client") from e

    if not org_uuid:
        raise SttError("Claude STT needs organization_uuid (lastActiveOrg cookie)")

    url = _build_url(org_uuid, language)
    headers = _handshake_headers(cookie)
    latest = ""
    nmsg = 0
    t0 = time.time()
    log.info(
        "Claude WS connect org=%s pcm=%d frame=%d burst=%.1fx",
        org_uuid[:8],
        len(pcm),
        FRAME_BYTES,
        BURST,
    )

    try:
        ws = websocket.create_connection(
            url,
            header=headers,
            suppress_origin=True,
            timeout=CONNECT_TIMEOUT,
            skip_utf8_validation=True,
        )
    except Exception as e:
        err = str(e)
        log.warning("Claude WS handshake failed: %s", err[:300])
        if "403" in err or "challenge" in err.lower():
            raise SttError(
                "Claude STT Cloudflare 403 — open Claude Desktop once to refresh cookies."
            ) from e
        if "400" in err:
            raise SttError(
                "Claude STT handshake 400 — open Claude Desktop, then retry."
            ) from e
        raise SttError(f"Claude WS connect failed: {err[:240]}") from e

    def handle(message) -> str | None:
        nonlocal latest, nmsg
        if not message:
            return None
        if isinstance(message, bytes):
            try:
                message = message.decode("utf-8")
            except Exception:
                return None
        try:
            obj = json.loads(message)
        except Exception:
            return None
        if not isinstance(obj, dict):
            return None
        nmsg += 1
        typ = str(obj.get("type") or "")
        if typ == "error" or (
            isinstance(obj.get("error"), dict) and obj.get("type") == "error"
        ):
            err_obj = obj.get("error") if isinstance(obj.get("error"), dict) else obj
            if isinstance(err_obj, dict):
                return "error:" + str(err_obj.get("message") or err_obj)
            return "error:" + str(obj)
        if typ == "TranscriptText":
            data = obj.get("data")
            if isinstance(data, str) and data:
                latest = data
            return None
        if typ == "TranscriptEndpoint":
            return "end"
        return None

    def try_recv(timeout: float) -> str | None:
        try:
            ws.settimeout(timeout)
            return handle(ws.recv())
        except Exception:
            return None

    fatal: str | None = None
    try:
        frame = max(320, FRAME_BYTES)
        realtime = (frame / 2) / float(SAMPLE_RATE)
        pace = max(0.0, realtime / max(1.0, BURST))
        if os.environ.get("OPENFLOW_CLAUDE_FRAME_SLEEP") is not None:
            pace = float(os.environ["OPENFLOW_CLAUDE_FRAME_SLEEP"])

        # Pad trailing silence so the last phonemes aren't cut by CloseStream
        trail_bytes = int(SAMPLE_RATE * 2 * (TRAIL_MS / 1000.0))
        if trail_bytes > 0:
            pcm = pcm + (b"\x00" * trail_bytes)

        r = try_recv(0.03)
        if r and r.startswith("error:"):
            fatal = r[6:]
        else:
            # Drain every frame with a short timeout so progressive text lands mid-send
            # (Deepgram needs the stream paced; pure blast loses accuracy).
            for i in range(0, len(pcm), frame):
                piece = pcm[i : i + frame]
                if not piece:
                    continue
                if i + frame >= len(pcm) and len(piece) < frame:
                    piece = _pad_frame(piece, frame)
                try:
                    ws.send(piece, opcode=ABNF.OPCODE_BINARY)
                except Exception as e:
                    if latest:
                        log.warning("send stopped with transcript: %s", e)
                        break
                    fatal = f"send failed: {e}"
                    break
                r = try_recv(0.01)
                if r == "end":
                    break
                if r and r.startswith("error:"):
                    fatal = r[6:]
                    break
                if pace > 0:
                    time.sleep(pace)

            if not fatal:
                try:
                    ws.send(json.dumps({"type": "KeepAlive"}))
                    ws.send(json.dumps({"type": "CloseStream"}))
                except Exception as e:
                    if not latest:
                        fatal = f"close failed: {e}"

                # Wait for TranscriptEndpoint OR stable full text.
                # Early-exit is gated: min post-close wait + stable window, and
                # never cut short if text is still thin vs audio length.
                close_at = time.time()
                stable_since = time.time() if latest else None
                last_seen = latest
                audio_s = max(0.1, len(pcm) / (SAMPLE_RATE * 2))
                # Heuristic: ~12 chars/s speech → expect roughly that many chars
                expect_chars = max(8, int(audio_s * 10))
                deadline = time.time() + min(POST_CLOSE_MAX, STT_TIMEOUT)
                while time.time() < deadline and not fatal:
                    r = try_recv(0.12)
                    if r == "end":
                        break
                    if r and r.startswith("error:"):
                        if not latest:
                            fatal = r[6:]
                        break
                    now = time.time()
                    if latest != last_seen:
                        last_seen = latest
                        stable_since = now
                        continue
                    if not latest or not stable_since:
                        continue
                    elapsed_close = now - close_at
                    stable_for = now - stable_since
                    thin = len(latest.strip()) < expect_chars
                    # Allow early exit only after min wait + stable text
                    # and either enough content or quite long stable
                    if elapsed_close < MIN_POST_CLOSE_S:
                        continue
                    if stable_for < STABLE_MS:
                        continue
                    if thin and stable_for < (STABLE_MS + 0.45):
                        # still thin — give Deepgram more time for the rest
                        continue
                    log.info(
                        "Claude early finish (stable %.0fms chars=%d expect~%d)",
                        stable_for * 1000,
                        len(latest),
                        expect_chars,
                    )
                    break
    finally:
        try:
            ws.close()
        except Exception:
            pass

    if fatal and not latest:
        raise SttError(fatal)

    text = (latest or "").strip()
    log.info(
        "Claude WS done t=%.2fs chars=%d msgs=%d",
        time.time() - t0,
        len(text),
        nmsg,
    )
    return text


def _session_status() -> tuple[bool, str, str | None]:
    try:
        from .claude_cookies import load_claude_ai_cookies

        cookies = load_claude_ai_cookies()
        sk = cookies.get("sessionKey", "")
        org = cookies.get("lastActiveOrg", "")
        ok = bool(sk.startswith("sk-ant-sid") or sk.startswith("sk-ant-"))
        detail = (
            f"Desktop session ready · {STT_PROVIDER}"
            f"{' · org' if org else ''} · burst={BURST:g}x"
            if ok
            else "Claude cookie found but not a sessionKey"
        )
        return ok, detail, "Claude Desktop cookies"
    except Exception as e:
        cred = Path.home() / ".claude" / ".credentials.json"
        up = os.environ.get("USERPROFILE")
        if up and (Path(up) / ".claude" / ".credentials.json").is_file():
            cred = Path(up) / ".claude" / ".credentials.json"
        if cred.is_file():
            return (
                False,
                "CLI OAuth present — open Claude Desktop for sessionKey cookies",
                str(cred),
            )
        return False, f"No Claude session: {e}", None


class ClaudeProvider:
    id = "claude"
    label = "Claude"

    def status(self) -> ProviderStatus:
        ready, detail, path = _session_status()
        return ProviderStatus(
            id=self.id,
            label=self.label,
            ready=ready,
            detail=detail,
            auth_path=path,
            stt_capable=ready,
            extra={
                "transport": "wss://claude.ai/api/ws/speech_to_text/voice_stream",
                "stt_provider": STT_PROVIDER,
                "sample_rate": SAMPLE_RATE,
                "burst": BURST,
            },
        )

    def transcribe(self, wav_bytes: bytes, language: str = "en") -> dict:
        from .claude_cookies import cookie_header, load_claude_ai_cookies

        def once(force_cookies: bool) -> str:
            if force_cookies:
                load_claude_ai_cookies(force=True)
            cookie, org, _sk = cookie_header()
            pcm = _wav_to_pcm16_mono(wav_bytes, SAMPLE_RATE)
            if len(pcm) < 320:
                raise SttError("Audio too short for Claude STT")
            log.info(
                "Claude STT pcm=%d rate=%d cookie_len=%d org=%s",
                len(pcm),
                SAMPLE_RATE,
                len(cookie),
                bool(org),
            )
            return transcribe_ws(pcm, cookie, org, language)

        try:
            text = once(force_cookies=False)
        except SttError as e:
            msg = str(e).lower()
            if any(
                x in msg
                for x in ("403", "400", "cookie", "handshake", "connect", "401")
            ):
                log.warning("Claude STT retry with fresh cookies: %s", e)
                text = once(force_cookies=True)
            else:
                raise

        if not text:
            log.warning("Claude STT empty transcript")
        return {
            "text": text or "",
            "language": language,
            "provider": "claude",
            "sample_rate": SAMPLE_RATE,
            "stt_backend": STT_PROVIDER,
        }
