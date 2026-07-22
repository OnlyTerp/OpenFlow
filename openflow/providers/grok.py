"""Grok / xAI STT via SuperGrok OAuth."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from .base import ProviderStatus, SttError
from .http_util import HttpError, post

log = logging.getLogger("openflow.grok")

STT_URL = os.environ.get("WISPR_GROK_STT_URL", "https://api.x.ai/v1/stt")
USER_AGENT = os.environ.get("WISPR_GROK_UA", "grok-cli/0.2.101")
STT_TIMEOUT = float(os.environ.get("WISPR_GROK_STT_TIMEOUT", "22"))
STT_CONNECT = float(os.environ.get("WISPR_GROK_STT_CONNECT", "2.0"))
STT_FORMAT = os.environ.get("WISPR_GROK_STT_FORMAT", "true").lower() in {
    "1",
    "true",
    "yes",
}
STT_RETRIES = int(os.environ.get("WISPR_GROK_STT_RETRIES", "2"))
# 16-bit mono 16 kHz ≈ 32 KB/s. Used to scale read timeout for long takes.
_WAV_BYTES_PER_SEC = 32000.0
_STT_TIMEOUT_CAP = float(os.environ.get("WISPR_GROK_STT_TIMEOUT_CAP", "60"))


def _timeout_for_wav(wav_bytes: bytes) -> float:
    """Longer audio needs more STT budget; floor is STT_TIMEOUT, cap 60s."""
    est_s = max(0.5, len(wav_bytes or b"") / _WAV_BYTES_PER_SEC)
    # network + model: ~1.4× realtime plus a fixed floor
    scaled = 8.0 + est_s * 1.4
    return min(_STT_TIMEOUT_CAP, max(STT_TIMEOUT, scaled))

# Bearer cache (mtime + short TTL)
_bearer_lock = __import__("threading").Lock()
_bearer_cache: dict = {"mtime": None, "path": None, "token": None, "loaded_at": 0.0}


def _auth_candidates() -> list[Path]:
    env = os.environ.get("GROK_AUTH_JSON")
    out: list[Path] = []
    if env:
        out.append(Path(env))
    out.append(Path.home() / ".grok" / "auth.json")
    up = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if up:
        out.append(Path(up) / ".grok" / "auth.json")
    # WSL path when shim runs on Windows
    wsl_user = os.environ.get("USER") or os.environ.get("USERNAME") or "user"
    out.extend(
        [
            Path(r"\\wsl$\Ubuntu\home") / wsl_user / ".grok" / "auth.json",
            Path(r"\\wsl.localhost\Ubuntu\home") / wsl_user / ".grok" / "auth.json",
        ]
    )
    return out


def find_auth_path() -> Path | None:
    for c in _auth_candidates():
        try:
            if c.is_file():
                return c
        except Exception:
            continue
    return None


def _parse_token(data: dict) -> str:
    now = time.time()
    expired_fallback = None
    for v in data.values():
        if not (isinstance(v, dict) and isinstance(v.get("key"), str) and v["key"]):
            continue
        exp_raw = v.get("expires_at") or v.get("expiry")
        exp_f = None
        if isinstance(exp_raw, (int, float)):
            exp_f = float(exp_raw)
        elif isinstance(exp_raw, str) and exp_raw:
            try:
                exp_f = float(exp_raw)
            except ValueError:
                try:
                    from datetime import datetime

                    exp_f = datetime.fromisoformat(
                        exp_raw.replace("Z", "+00:00")
                    ).timestamp()
                except Exception:
                    exp_f = None
        if exp_f is not None and exp_f < now:
            expired_fallback = expired_fallback or v["key"]
            continue
        return v["key"]
    if expired_fallback:
        return expired_fallback
    raise SttError("No Grok OAuth key — run `grok login`")


def load_bearer(*, force: bool = False) -> tuple[str, Path]:
    path = find_auth_path()
    if path is None:
        raise SttError("Grok auth.json not found — run `grok login`")
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    with _bearer_lock:
        if (
            not force
            and _bearer_cache["token"]
            and _bearer_cache["path"] == str(path)
            and _bearer_cache["mtime"] == mtime
            and (time.time() - float(_bearer_cache["loaded_at"] or 0)) < 300
        ):
            return _bearer_cache["token"], path  # type: ignore[return-value]
        data = json.loads(path.read_text(encoding="utf-8"))
        token = _parse_token(data)
        _bearer_cache.update(
            {
                "mtime": mtime,
                "path": str(path),
                "token": token,
                "loaded_at": time.time(),
            }
        )
        return token, path


class GrokProvider:
    id = "grok"
    label = "Grok (xAI)"

    def status(self) -> ProviderStatus:
        path = find_auth_path()
        if path is None:
            return ProviderStatus(
                id=self.id,
                label=self.label,
                ready=False,
                detail="Sign in with Grok CLI (`grok login`)",
                auth_path=None,
                stt_capable=True,
            )
        try:
            load_bearer()
            return ProviderStatus(
                id=self.id,
                label=self.label,
                ready=True,
                detail="SuperGrok OAuth ready",
                auth_path=str(path),
                stt_capable=True,
            )
        except Exception as e:
            return ProviderStatus(
                id=self.id,
                label=self.label,
                ready=False,
                detail=str(e),
                auth_path=str(path),
                stt_capable=True,
                error=str(e),
            )

    def transcribe(self, wav_bytes: bytes, language: str = "en") -> dict:
        last_err: Exception | None = None
        attempts = max(1, STT_RETRIES + 1)
        for attempt in range(1, attempts + 1):
            t0 = time.time()
            try:
                bearer, _ = load_bearer(force=(attempt > 1))
                headers = {
                    "Authorization": f"Bearer {bearer}",
                    "User-Agent": USER_AGENT,
                }
                form: dict[str, str] = {"language": language or "en"}
                if STT_FORMAT:
                    form["format"] = "true"
                files = {"file": ("dictation.wav", wav_bytes, "audio/wav")}
                read_timeout = _timeout_for_wav(wav_bytes)
                log.info(
                    "Grok STT attempt %d/%d wav=%d timeout=%.1fs",
                    attempt,
                    attempts,
                    len(wav_bytes),
                    read_timeout,
                )
                result = post(
                    STT_URL,
                    headers=headers,
                    files=files,
                    form=form,
                    timeout=read_timeout,
                    connect_timeout=STT_CONNECT,
                    expect_json=True,
                )
                if not isinstance(result, dict):
                    result = {"text": str(result)}
                result.setdefault("provider", "grok")
                log.info("Grok STT ok t=%.2fs", time.time() - t0)
                return result
            except HttpError as e:
                last_err = SttError(
                    f"Grok STT HTTP {e.code}",
                    code=e.code,
                    retryable=e.code in (401, 429, 500, 502, 503),
                )
                log.warning("Grok STT HTTP %s: %s", e.code, e.body[:200])
                if e.code == 401 and attempt < attempts:
                    time.sleep(0.1)
                    continue
            except Exception as e:
                last_err = e
                log.warning("Grok STT fail: %s", e)
            if attempt < attempts:
                time.sleep(0.12)
        raise last_err or SttError("Grok STT failed")
