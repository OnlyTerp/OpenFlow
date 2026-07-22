"""Local Whisper-compatible STT (OpenAI-style /v1/audio/transcriptions).

Point OpenFlow at any local server that accepts multipart WAV + returns text, e.g.:
  - faster-whisper-server / openai-whisper-api
  - llama.cpp whisper server
  - any OpenAI-compatible STT proxy on LAN

Config (OpenFlow config.json → providers.local):
  url:      default http://127.0.0.1:8080/v1/audio/transcriptions
  model:    optional model name (e.g. whisper-1, large-v3)
  api_key:  optional Bearer token
  enabled:  true/false
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from openflow.config import load_config

from .base import ProviderStatus, SttError

log = logging.getLogger("openflow.local")

DEFAULT_URL = os.environ.get(
    "OPENFLOW_LOCAL_STT_URL", "http://127.0.0.1:8080/v1/audio/transcriptions"
)
DEFAULT_MODEL = os.environ.get("OPENFLOW_LOCAL_STT_MODEL", "whisper-1")
STT_TIMEOUT = float(os.environ.get("OPENFLOW_LOCAL_STT_TIMEOUT", "60"))


def _local_cfg() -> dict[str, Any]:
    cfg = load_config()
    p = (cfg.get("providers") or {}).get("local") or {}
    return p if isinstance(p, dict) else {}


def _url() -> str:
    p = _local_cfg()
    u = p.get("url") or DEFAULT_URL
    return str(u).strip()


def _model() -> str | None:
    p = _local_cfg()
    m = p.get("model") or DEFAULT_MODEL
    return str(m).strip() if m else None


def _api_key() -> str | None:
    p = _local_cfg()
    k = p.get("api_key") or os.environ.get("OPENFLOW_LOCAL_STT_KEY")
    return str(k).strip() if k else None


def _probe() -> tuple[bool, str]:
    """Best-effort readiness: config present + host looks reachable."""
    url = _url()
    if not url:
        return False, "Set providers.local.url in OpenFlow config"
    # Light TCP-ish probe via OPTIONS/GET on origin (many servers 404 — still means up)
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}/"
        req = Request(base, method="GET")
        with urlopen(req, timeout=1.5) as resp:
            resp.read(64)
        return True, f"Local STT at {parsed.netloc}"
    except HTTPError:
        # Server responded — good enough
        from urllib.parse import urlparse

        return True, f"Local STT at {urlparse(url).netloc}"
    except Exception as e:
        return False, f"Local STT offline ({e.__class__.__name__}) — start your Whisper server"


class LocalProvider:
    id = "local"
    label = "Local"

    def status(self) -> ProviderStatus:
        p = _local_cfg()
        enabled = p.get("enabled", True)
        url = _url()
        if not enabled:
            return ProviderStatus(
                id=self.id,
                label=self.label,
                ready=False,
                detail="Local engine disabled in config",
                auth_path=None,
                stt_capable=True,
            )
        ok, detail = _probe()
        return ProviderStatus(
            id=self.id,
            label=self.label,
            ready=ok,
            detail=detail,
            auth_path=url,
            stt_capable=True,
            extra={"url": url, "model": _model()},
        )

    def transcribe(self, wav_bytes: bytes, language: str = "en") -> dict:
        url = _url()
        model = _model()
        if not url:
            raise SttError("Local STT URL not configured")

        # multipart/form-data by hand (no requests dependency)
        boundary = f"----OpenFlow{int(time.time() * 1000)}"
        parts: list[bytes] = []

        def field(name: str, value: str) -> None:
            parts.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                    f"{value}\r\n"
                ).encode("utf-8")
            )

        field("language", language or "en")
        if model:
            field("model", model)
        field("response_format", "json")

        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="dictation.wav"\r\n'
                f"Content-Type: audio/wav\r\n\r\n"
            ).encode("utf-8")
        )
        parts.append(wav_bytes)
        parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(parts)

        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
            "Accept": "application/json",
        }
        key = _api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"

        req = Request(url, data=body, headers=headers, method="POST")
        t0 = time.time()
        try:
            with urlopen(req, timeout=STT_TIMEOUT) as resp:
                raw = resp.read()
        except HTTPError as e:
            err_body = e.read().decode("utf-8", "replace")[:300]
            raise SttError(f"Local STT HTTP {e.code}: {err_body}", code=e.code) from e
        except URLError as e:
            raise SttError(f"Local STT unreachable: {e.reason}") from e
        except Exception as e:
            raise SttError(f"Local STT failed: {e}") from e

        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            text = raw.decode("utf-8", "replace").strip()
            return {"text": text, "transcript": text, "provider": "local"}

        text = (
            data.get("text")
            or data.get("transcript")
            or data.get("transcription")
            or ""
        )
        if isinstance(text, dict):
            text = text.get("text") or ""
        text = str(text).strip()
        log.info("local STT t=%.2fs chars=%d url=%s", time.time() - t0, len(text), url)
        return {
            "text": text,
            "transcript": text,
            "provider": "local",
            "model": model,
        }
