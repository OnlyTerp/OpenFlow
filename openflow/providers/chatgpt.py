"""ChatGPT / Codex plan STT via chatgpt.com/backend-api/transcribe.

Uses OAuth tokens from Codex CLI auth.json (auth_mode=chatgpt).
Optimizations: token cache, connection reuse, one retry on 401/5xx.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

from .base import ProviderStatus, SttError
from .http_util import HttpError, post

log = logging.getLogger("openflow.chatgpt")

TRANSCRIBE_URL = os.environ.get(
    "OPENFLOW_CHATGPT_STT_URL",
    "https://chatgpt.com/backend-api/transcribe",
)
STT_TIMEOUT = float(os.environ.get("OPENFLOW_CHATGPT_STT_TIMEOUT", "25"))
STT_CONNECT = float(os.environ.get("OPENFLOW_CHATGPT_STT_CONNECT", "6"))
USER_AGENT = os.environ.get(
    "OPENFLOW_CHATGPT_UA",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
)
STT_RETRIES = int(os.environ.get("OPENFLOW_CHATGPT_STT_RETRIES", "1"))

_token_lock = threading.Lock()
_token_cache: dict = {"mtime": None, "path": None, "access": None, "account": None}


def _auth_candidates() -> list[Path]:
    env = os.environ.get("CODEX_AUTH_JSON") or os.environ.get("OPENFLOW_CODEX_AUTH")
    out: list[Path] = []
    if env:
        out.append(Path(env))
    out.append(Path.home() / ".codex" / "auth.json")
    up = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if up:
        out.append(Path(up) / ".codex" / "auth.json")
    wsl_user = os.environ.get("USER") or os.environ.get("USERNAME") or "user"
    out.extend(
        [
            Path(r"\\wsl$\Ubuntu\home") / wsl_user / ".codex" / "auth.json",
            Path(r"\\wsl.localhost\Ubuntu\home") / wsl_user / ".codex" / "auth.json",
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


def load_tokens(*, force: bool = False) -> tuple[str, str | None, Path]:
    path = find_auth_path()
    if path is None:
        raise SttError(
            "Codex/ChatGPT auth.json not found — log into Codex Desktop or `codex login`"
        )
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    with _token_lock:
        if (
            not force
            and _token_cache["access"]
            and _token_cache["path"] == str(path)
            and _token_cache["mtime"] == mtime
        ):
            return (
                _token_cache["access"],  # type: ignore[return-value]
                _token_cache["account"],
                path,
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        tokens = data.get("tokens") or {}
        if not isinstance(tokens, dict):
            raise SttError("Invalid Codex auth.json (no tokens)")
        access = tokens.get("access_token")
        if not isinstance(access, str) or not access.strip():
            api_key = data.get("OPENAI_API_KEY")
            if isinstance(api_key, str) and api_key.strip():
                raise SttError(
                    "Codex is on API key mode — ChatGPT plan STT needs auth_mode=chatgpt"
                )
            raise SttError("No ChatGPT access_token in Codex auth.json")
        account_id = tokens.get("account_id")
        if not isinstance(account_id, str):
            account_id = None
        access = access.strip()
        _token_cache.update(
            {
                "mtime": mtime,
                "path": str(path),
                "access": access,
                "account": account_id,
            }
        )
        return access, account_id, path


class ChatGptProvider:
    id = "chatgpt"
    label = "ChatGPT / Codex"

    def status(self) -> ProviderStatus:
        path = find_auth_path()
        if path is None:
            return ProviderStatus(
                id=self.id,
                label=self.label,
                ready=False,
                detail="Log into Codex Desktop (ChatGPT plan) or run codex login",
                auth_path=None,
                stt_capable=True,
            )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            mode = data.get("auth_mode") or "unknown"
            access, account_id, _ = load_tokens()
            return ProviderStatus(
                id=self.id,
                label=self.label,
                ready=True,
                detail=f"ChatGPT OAuth ready (mode={mode})",
                auth_path=str(path),
                stt_capable=True,
                extra={"auth_mode": mode, "has_account_id": bool(account_id)},
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
            force = attempt > 1
            try:
                access, account_id, _ = load_tokens(force=force)
                headers = {
                    "Authorization": f"Bearer {access}",
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json, text/plain, */*",
                    "OAI-Language": language or "en",
                    "OAI-Device-Id": os.environ.get(
                        "OPENFLOW_OAI_DEVICE_ID", "openflow-desktop"
                    ),
                }
                if account_id:
                    headers["ChatGPT-Account-Id"] = account_id

                form = {"language": language or "en"}
                files = {"file": ("dictation.wav", wav_bytes, "audio/wav")}

                t0 = time.time()
                log.info(
                    "ChatGPT STT attempt %d/%d wav=%d connect=%.1fs read=%.1fs",
                    attempt,
                    attempts,
                    len(wav_bytes),
                    STT_CONNECT,
                    STT_TIMEOUT,
                )
                result = post(
                    TRANSCRIBE_URL,
                    headers=headers,
                    files=files,
                    form=form,
                    timeout=STT_TIMEOUT,
                    connect_timeout=STT_CONNECT,
                    expect_json=True,
                )
                text = ""
                if isinstance(result, dict):
                    text = (
                        result.get("text")
                        or result.get("transcript")
                        or result.get("asr_text")
                        or ""
                    )
                    if not text and isinstance(result.get("message"), str):
                        text = result["message"]
                elif isinstance(result, str):
                    text = result
                text = (text or "").strip()
                log.info(
                    "ChatGPT STT ok t=%.2fs chars=%d", time.time() - t0, len(text)
                )
                return {"text": text, "language": language, "provider": "chatgpt"}
            except HttpError as e:
                last_err = SttError(
                    f"ChatGPT STT HTTP {e.code}",
                    code=e.code,
                    retryable=e.code in (401, 429, 500, 502, 503),
                )
                log.error("ChatGPT STT HTTP %s: %s", e.code, e.body[:300])
                if e.code in (401, 429, 500, 502, 503) and attempt < attempts:
                    time.sleep(0.15)
                    continue
                raise last_err from e
            except Exception as e:
                last_err = e
                log.warning("ChatGPT STT attempt %d failed: %s", attempt, e)
                if attempt < attempts:
                    time.sleep(0.12)
                    continue
                raise
        raise last_err or SttError("ChatGPT STT failed")
