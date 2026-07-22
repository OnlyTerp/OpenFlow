"""Shared HTTP helpers for STT providers."""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger("openflow")

_tls = threading.local()


class HttpError(Exception):
    def __init__(self, code: int, body: str = ""):
        self.code = code
        self.body = body
        super().__init__(f"HTTP {code}: {body[:200]}")


def session():
    try:
        import requests  # type: ignore
    except ImportError:
        return None
    sess = getattr(_tls, "session", None)
    if sess is None:
        sess = requests.Session()
        _tls.session = sess
    return sess


def post(
    url: str,
    *,
    headers: dict | None = None,
    data: bytes | None = None,
    files: dict | None = None,
    form: dict | None = None,
    timeout: float = 15.0,
    connect_timeout: float = 3.0,
    expect_json: bool = True,
) -> Any:
    """POST; return parsed JSON or raw text depending on expect_json / content-type."""
    headers = dict(headers or {})
    sess = session()
    if sess is not None:
        kw: dict = {
            "headers": headers,
            "timeout": (connect_timeout, timeout),
        }
        if files is not None:
            kw["files"] = files
            if form:
                kw["data"] = form
        elif form is not None:
            kw["data"] = form
        elif data is not None:
            kw["data"] = data
        try:
            r = sess.post(url, **kw)
        except Exception as e:
            raise RuntimeError(f"request failed: {e}") from e
        body = r.content
        if r.status_code >= 400:
            raise HttpError(r.status_code, body[:800].decode("utf-8", "replace"))
        ctype = (r.headers.get("Content-Type") or "").lower()
        if expect_json and "json" in ctype:
            return r.json()
        text = body.decode("utf-8", "replace")
        if expect_json:
            try:
                return json.loads(text)
            except Exception:
                return {"text": text}
        return text

    # urllib fallback
    if files is not None:
        raise RuntimeError("multipart requires 'requests' package")
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if expect_json:
                return json.loads(raw.decode("utf-8"))
            return raw.decode("utf-8")
    except urllib.error.HTTPError as e:
        body = e.read()[:800].decode("utf-8", "replace")
        raise HttpError(e.code, body) from e
