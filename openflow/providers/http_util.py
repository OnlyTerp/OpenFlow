"""Shared HTTP helpers for STT providers."""

from __future__ import annotations

import json
import queue
import socket
import urllib.error
import urllib.request
from functools import lru_cache
from typing import Any

_SESSION_POOL_SIZE = 4
_session_pools: dict[bool, queue.LifoQueue[Any]] = {
    False: queue.LifoQueue(maxsize=_SESSION_POOL_SIZE),
    True: queue.LifoQueue(maxsize=_SESSION_POOL_SIZE),
}


def _prefer_ipv4(addresses: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    """Prefer IPv4 without removing IPv6 fallback addresses."""
    return sorted(addresses, key=lambda row: row[0] != socket.AF_INET)


@lru_cache(maxsize=1)
def _preferred_ipv4_adapter_type() -> type[Any]:
    """Build a requests adapter whose direct HTTPS sockets try IPv4 first."""
    from requests.adapters import HTTPAdapter  # type: ignore
    from urllib3 import PoolManager
    from urllib3.connection import HTTPSConnection
    from urllib3.connectionpool import HTTPSConnectionPool
    from urllib3.exceptions import (
        ConnectTimeoutError,
        NameResolutionError,
        NewConnectionError,
    )
    from urllib3.util import connection

    class PreferredIPv4HTTPSConnection(HTTPSConnection):
        def _new_conn(self) -> socket.socket:
            try:
                addresses = socket.getaddrinfo(
                    self._dns_host,
                    self.port,
                    socket.AF_UNSPEC,
                    socket.SOCK_STREAM,
                )
            except socket.gaierror as exc:
                raise NameResolutionError(self.host, self, exc) from exc

            last_error: Exception | None = None
            seen: set[str] = set()
            for row in _prefer_ipv4(addresses):
                host = row[4][0]
                if host in seen:
                    continue
                seen.add(host)
                try:
                    return connection.create_connection(
                        (host, self.port),
                        self.timeout,
                        source_address=self.source_address,
                        socket_options=self.socket_options,
                    )
                except TimeoutError as exc:
                    last_error = ConnectTimeoutError(
                        self,
                        f"Connection to {self.host} timed out "
                        f"(connect timeout={self.timeout})",
                    )
                    last_error.__cause__ = exc
                except OSError as exc:
                    last_error = NewConnectionError(
                        self, f"Failed to establish a new connection: {exc}"
                    )

            if last_error is not None:
                raise last_error
            exc = socket.gaierror(f"No address found for {self._dns_host}")
            raise NameResolutionError(self.host, self, exc) from exc

    class PreferredIPv4HTTPSConnectionPool(HTTPSConnectionPool):
        ConnectionCls = PreferredIPv4HTTPSConnection

    class PreferredIPv4PoolManager(PoolManager):
        def __init__(self, *args: Any, **kwargs: Any):
            super().__init__(*args, **kwargs)
            self.pool_classes_by_scheme = dict(self.pool_classes_by_scheme)
            self.pool_classes_by_scheme["https"] = PreferredIPv4HTTPSConnectionPool

    class PreferredIPv4Adapter(HTTPAdapter):
        def init_poolmanager(
            self,
            connections: int,
            maxsize: int,
            block: bool = False,
            **pool_kwargs: Any,
        ) -> None:
            self.poolmanager = PreferredIPv4PoolManager(
                num_pools=connections,
                maxsize=maxsize,
                block=block,
                **pool_kwargs,
            )

    return PreferredIPv4Adapter


def _new_session(*, prefer_ipv4: bool) -> Any | None:
    try:
        import requests  # type: ignore
    except ImportError:
        return None
    sess = requests.Session()
    if prefer_ipv4:
        sess.mount("https://", _preferred_ipv4_adapter_type()())
    return sess


class HttpError(Exception):
    def __init__(self, code: int, body: str = ""):
        self.code = code
        self.body = body
        super().__init__(f"HTTP {code}: {body[:200]}")


def _acquire_session(*, prefer_ipv4: bool = False) -> Any | None:
    """Borrow one reusable session without sharing it between request threads."""
    try:
        return _session_pools[prefer_ipv4].get_nowait()
    except queue.Empty:
        return _new_session(prefer_ipv4=prefer_ipv4)


def _release_session(
    sess: Any,
    *,
    reusable: bool,
    prefer_ipv4: bool = False,
) -> None:
    if sess is None:
        return
    if not reusable:
        sess.close()
        return
    try:
        _session_pools[prefer_ipv4].put_nowait(sess)
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
    prefer_ipv4: bool = False,
) -> Any:
    """POST; return parsed JSON or raw text depending on expect_json / content-type."""
    headers = dict(headers or {})
    sess = _acquire_session(prefer_ipv4=prefer_ipv4)
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
            _release_session(sess, reusable=reusable, prefer_ipv4=prefer_ipv4)
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
