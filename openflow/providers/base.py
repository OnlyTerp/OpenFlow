"""STT provider protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ProviderStatus:
    id: str
    label: str
    ready: bool
    detail: str
    auth_path: str | None = None
    stt_capable: bool = True
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "ready": self.ready,
            "detail": self.detail,
            "auth_path": self.auth_path,
            "stt_capable": self.stt_capable,
            "error": self.error,
            **self.extra,
        }


class SttError(Exception):
    def __init__(self, message: str, *, code: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class UnsupportedSttError(SttError):
    """Provider logged in but has no STT path on this platform."""


class SttProvider(Protocol):
    id: str
    label: str

    def status(self) -> ProviderStatus: ...

    def transcribe(self, wav_bytes: bytes, language: str = "en") -> dict:
        """Return dict with at least text/transcript key (same shape as Grok STT)."""
        ...
