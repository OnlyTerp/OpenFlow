"""Load Claude Desktop session cookies (sessionKey) for cloud STT WebSocket."""

from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

log = logging.getLogger("openflow.claude.cookies")

_cache_lock = threading.Lock()
_cache: dict = {"mtime": None, "cookies": None, "path": None, "loaded_at": 0.0}
# Re-decrypt at most every N seconds unless force=True (cookie decrypt is ~50–150ms)
CACHE_TTL_S = float(os.environ.get("OPENFLOW_CLAUDE_COOKIE_TTL", "45"))


def _user_data_dirs() -> list[Path]:
    """Prefer the profile whose Cookies DB was touched most recently."""
    cands: list[Path] = []
    la = os.environ.get("LOCALAPPDATA")
    ra = os.environ.get("APPDATA")
    if la:
        packages = Path(la) / "Packages"
        if packages.is_dir():
            try:
                for p in packages.glob("Claude*"):
                    cand = p / "LocalCache" / "Roaming" / "Claude"
                    if cand.is_dir():
                        cands.append(cand)
            except Exception:
                pass
        for rel in ("Claude", "AnthropicClaude"):
            cand = Path(la) / rel
            if cand.is_dir():
                cands.append(cand)
    if ra:
        for rel in ("Claude", "AnthropicClaude"):
            cand = Path(ra) / rel
            if cand.is_dir():
                cands.append(cand)
    # macOS
    mac = Path.home() / "Library" / "Application Support" / "Claude"
    if mac.is_dir():
        cands.append(mac)

    # Dedup + sort by cookie mtime (newest first) so Store app wins over empty Local\Claude
    seen: set[str] = set()
    scored: list[tuple[float, Path]] = []
    for d in cands:
        key = str(d).lower()
        if key in seen:
            continue
        seen.add(key)
        db = _cookie_db(d)
        mt = 0.0
        if db is not None:
            try:
                mt = db.stat().st_mtime
            except OSError:
                mt = 0.0
        scored.append((mt, d))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [d for _, d in scored]


def _cookie_db(user_data: Path) -> Path | None:
    for rel in ("Network/Cookies", "Cookies"):
        p = user_data / rel
        if p.is_file():
            return p
    return None


def _master_key(user_data: Path) -> bytes:
    import win32crypt  # type: ignore

    state = json.loads((user_data / "Local State").read_text(encoding="utf-8"))
    ek = base64.b64decode(state["os_crypt"]["encrypted_key"])
    if ek.startswith(b"DPAPI"):
        ek = ek[5:]
    return win32crypt.CryptUnprotectData(ek, None, None, None, 0)[1]


def _decrypt_value(raw: bytes, key: bytes | None) -> str:
    if not raw:
        return ""
    pt: bytes
    if (raw.startswith(b"v10") or raw.startswith(b"v20")) and key is not None:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        pt = AESGCM(key).decrypt(raw[3:15], raw[15:], None)
    else:
        try:
            import win32crypt  # type: ignore

            pt = win32crypt.CryptUnprotectData(raw, None, None, None, 0)[1]
        except Exception:
            return ""
    # Chromium may prefix a 32-byte domain hash before the value
    if b"sk-ant-" in pt:
        return pt[pt.index(b"sk-ant-") :].decode("utf-8", "replace")
    if len(pt) > 32:
        rest = pt[32:]
        try:
            s = rest.decode("utf-8")
            # uuid / simple tokens
            if s and all(c.isalnum() or c in "-_.=" for c in s):
                return s
        except Exception:
            pass
    return pt.decode("utf-8", "replace")


def _load_from_profile(user_data: Path) -> dict[str, str]:
    db = _cookie_db(user_data)
    if db is None:
        raise RuntimeError(f"No Cookies DB under {user_data}")
    key: bytes | None = None
    try:
        if (user_data / "Local State").is_file():
            key = _master_key(user_data)
    except Exception as e:
        log.warning("cookie master key: %s", e)

    tmp = Path(tempfile.gettempdir()) / f"openflow-claude-cookies-{os.getpid()}.db"
    shutil.copy2(db, tmp)
    try:
        con = sqlite3.connect(str(tmp))
        cur = con.cursor()
        rows = cur.execute(
            "SELECT host_key, name, path, encrypted_value, value FROM cookies"
        ).fetchall()
        con.close()
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass

    out: dict[str, str] = {}
    for host, name, path, enc, plain in rows:
        host = host or ""
        if "claude.ai" not in host:
            continue
        if path not in ("/", "", None):
            continue
        raw = bytes(enc) if enc else b""
        if raw:
            val = _decrypt_value(raw, key)
        else:
            val = plain if isinstance(plain, str) else ""
        if val:
            out[str(name)] = val
    return out


def load_claude_ai_cookies(*, force: bool = False) -> dict[str, str]:
    """Return path=/ cookies for claude.ai including sessionKey + lastActiveOrg."""
    user_dirs = _user_data_dirs()
    if not user_dirs:
        raise RuntimeError("Claude Desktop profile not found")

    # Cache key on the first (newest) cookie DB
    primary_db = _cookie_db(user_dirs[0])
    mtime = None
    if primary_db is not None:
        try:
            mtime = primary_db.stat().st_mtime
        except OSError:
            mtime = None

    with _cache_lock:
        age = time.time() - float(_cache.get("loaded_at") or 0)
        if (
            not force
            and _cache["cookies"] is not None
            and _cache["path"] == str(primary_db)
            and _cache["mtime"] == mtime
            and age < CACHE_TTL_S
        ):
            return dict(_cache["cookies"])  # type: ignore[arg-type]

    last_err: Exception | None = None
    out: dict[str, str] = {}
    used_db: Path | None = primary_db
    for user_data in user_dirs:
        try:
            cand = _load_from_profile(user_data)
            if "sessionKey" in cand:
                out = cand
                used_db = _cookie_db(user_data)
                break
            if cand and not out:
                out = cand  # keep first non-empty even without sessionKey for better error
                used_db = _cookie_db(user_data)
        except Exception as e:
            last_err = e
            log.debug("claude cookies profile %s: %s", user_data, e)
            continue

    if "sessionKey" not in out:
        if last_err:
            raise RuntimeError(
                f"No sessionKey cookie — open Claude Desktop once and log into claude.ai ({last_err})"
            )
        raise RuntimeError(
            "No sessionKey cookie — open Claude Desktop once and log into claude.ai"
        )

    with _cache_lock:
        try:
            mt2 = used_db.stat().st_mtime if used_db else mtime
        except OSError:
            mt2 = mtime
        _cache.update(
            {
                "mtime": mt2,
                "path": str(used_db) if used_db else None,
                "cookies": dict(out),
                "loaded_at": time.time(),
            }
        )
    return out


def _is_clean_cookie_value(v: str) -> bool:
    """Reject decrypt garbage / binary so WS handshake doesn't 400."""
    if not v or not v.isprintable():
        return False
    # reject NUL / high control
    if any(ord(c) < 32 for c in v):
        return False
    return True


def cookie_header(cookies: dict[str, str] | None = None) -> tuple[str, str | None, str]:
    """Return (Cookie header, lastActiveOrg, sessionKey).

    Live Claude Desktop capture uses the full jar, but sending every decrypted
    Chromium cookie from Windows often includes binary garbage → HTTP 400 on
    WS upgrade. Stick to the auth-critical + clean CF cookies.
    """
    cookies = cookies or load_claude_ai_cookies()
    # Required + optional CF (only if clean ASCII)
    prefer = [
        "sessionKey",
        "lastActiveOrg",
        "cf_clearance",
        "__cf_bm",
        "_cfuvid",
        "anthropic-device-id",
        "activitySessionId",
    ]
    parts: list[str] = []
    for k in prefer:
        v = cookies.get(k)
        if not v or not _is_clean_cookie_value(v):
            continue
        # sessionKey must look like Anthropic session id
        if k == "sessionKey" and not (
            v.startswith("sk-ant-sid") or v.startswith("sk-ant-")
        ):
            continue
        parts.append(f"{k}={v}")
    if not any(p.startswith("sessionKey=") for p in parts):
        raise RuntimeError("No clean sessionKey cookie for Claude STT")
    org = cookies.get("lastActiveOrg")
    if org and not _is_clean_cookie_value(org):
        org = None
    sk = next(p.split("=", 1)[1] for p in parts if p.startswith("sessionKey="))
    return "; ".join(parts), org, sk
