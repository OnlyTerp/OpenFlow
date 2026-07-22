"""Shared HTTP helpers for STT providers."""

from __future__ import annotations

import json
import logging
import threading
import queue
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger("openflow")

_SESSION_POOL_SIZE = 4
_session_pool: queue.LifoQueue[Any] = queue.LifoQueue(maxsize=_SESSION_POOL_SIZE)


class HttpError(Exception):
    def __init__(self, code: int, body: str = ""):
        self.code = code
        self.body = body
        super().__init__(f"HTTP {code}: {body[:200]}")


def _acquire_session() -> Any | None:
    """Borrow one reusable session without sharing it between request threads."""
    try:
        import requests  # type: ignore
    except ImportError:
        return None
    try:
        return _session_pool.get_nowait()
    except queue.Empty:
        return requests.Session()


def _release_session(sess: Any, *, reusable: bool) -> None:
    if sess is None:
        return
    if not reusable:
        sess.close()
        return
    try:
        _session_pool.put_nowait(sess)
    except queue.Full:
        sess.close()


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
    sess = _acquire_session()
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
        reusable = True
        try:
            r = sess.post(url, **kw)
            body = r.content
        except Exception as e:
            reusable = False
            raise RuntimeError(f"request failed: {e}") from e
        finally:
            _release_session(sess, reusable=reusable)
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
