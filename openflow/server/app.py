#!/usr/bin/env python3
"""OpenFlow local Baseten-compatible backend → multi-provider STT + cleanup.

POST .../environments/{env}/run_remote
  1) Active provider STT (Grok / ChatGPT-Codex / Claude*) → asr_text
  2) Optional Grok chat cleanup (→ llm_text)

* Claude plan STT is macOS-only; Windows reports status honestly.

Also serves OpenFlow Control Center at GET / and /ui.
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
import re
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

# Allow `providers` package next to this file
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

HOST = os.environ.get("WISPR_GROK_HOST", "127.0.0.1")
PORT = int(os.environ.get("WISPR_GROK_PORT", "18765"))
STT_URL = os.environ.get("WISPR_GROK_STT_URL", "https://api.x.ai/v1/stt")
CHAT_URL = os.environ.get("WISPR_GROK_CHAT_URL", "https://api.x.ai/v1/chat/completions")
CHAT_MODEL = os.environ.get("WISPR_GROK_CHAT_MODEL", "grok-4.20-0309-non-reasoning")
USER_AGENT = os.environ.get("WISPR_GROK_UA", "grok-cli/0.2.101")
# Per-request read timeout floor. GrokProvider scales up for long audio so
# multi-sentence dictations don't get truncated by a 12s hard kill.
# CLIENT_BUDGET must stay above (timeout × attempts) or the client abandons.
STT_TIMEOUT = float(os.environ.get("WISPR_GROK_STT_TIMEOUT", "22"))
STT_CONNECT_TIMEOUT = float(os.environ.get("WISPR_GROK_STT_CONNECT", "3"))
FORMAT_TIMEOUT = float(os.environ.get("WISPR_GROK_FORMAT_TIMEOUT", "8"))
MAX_BODY_BYTES = int(os.environ.get("WISPR_GROK_MAX_BODY", str(25_000_000)))
CLIENT_BUDGET_S = float(os.environ.get("WISPR_GROK_CLIENT_BUDGET", "45"))
STT_RETRIES = int(os.environ.get("WISPR_GROK_STT_RETRIES", "2"))
# STT format=true = free inverse-text-normalization on the same STT call (no extra RTT).
STT_FORMAT = os.environ.get("WISPR_GROK_STT_FORMAT", "true").lower() in {
    "1",
    "true",
    "yes",
}
# Default OFF: chat format doubles latency and caused multi-chunk pastes to hang.
# Local light cleanup always runs (lexicon + stutter/filler) even when this is off.
LLM_FORMAT = os.environ.get("WISPR_GROK_LLM_FORMAT", "false").lower() in {
    "1",
    "true",
    "yes",
}
# Deterministic cleanup after STT (no network). Disable with WISPR_GROK_LOCAL_CLEANUP=false.
LOCAL_CLEANUP = os.environ.get("WISPR_GROK_LOCAL_CLEANUP", "true").lower() in {
    "1",
    "true",
    "yes",
}
_debug_audio_path = os.environ.get("WISPR_GROK_DEBUG_AUDIO", "").strip()
# Failed recordings can contain sensitive speech. Retention is opt-in only.
DEBUG_AUDIO_DIR: Path | None = (
    Path(_debug_audio_path).expanduser() if _debug_audio_path else None
)

# Optional, user-supplied cleanup examples. This file is private, gitignored,
# and never copied by the installer.
EXAMPLES_PATH = Path(
    os.environ.get(
        "WISPR_GROK_EXAMPLES",
        str(Path(__file__).resolve().parents[1].parent / "format_examples.json"),
    )
)

FORMAT_SYSTEM = """You are OpenFlow Auto Cleanup (Light).

Match any supplied BEFORE→AFTER examples in spirit: same voice, details, and length.

Edit LESS than a "Polish" rewrite. Auto Cleanup Light only:
- Fix stutters / accidental repeats ("I I think", "it's, it's")
- Apply explicit backtracks ("scratch that", "no wait", "I mean …")
- Drop empty vocal fillers only: standalone um/uh/er/ah
- Punctuation, capitalization, light grammar (thats→that's, missing commas)
- Keep profanity, hedging, asides, and "unimportant" detail

Never paraphrase, summarize, or delete clauses because they seem unimportant.
Never invent content. If unsure, keep the original words.
Output ONLY the cleaned transcript.
"""


_APOS_TRANS = str.maketrans({
    "\N{RIGHT SINGLE QUOTATION MARK}": "'",
    "\N{LEFT SINGLE QUOTATION MARK}": "'",
    "\N{LEFT DOUBLE QUOTATION MARK}": '"',
    "\N{RIGHT DOUBLE QUOTATION MARK}": '"',
})
_BACKTRACK_RE = re.compile(
    r"\b(scratch that|no wait|ignore that|strike that|forget that|i mean)\b",
    re.I,
)
# Immediate word/phrase stutters: "I I think", "it's, it's", "the the"
_STUTTER_RE = re.compile(
    r"\b([A-Za-z']{1,24})(?:\s*[,;:]?\s+\1)+\b",
    re.I,
)
# Standalone vocal fillers only (not "um" inside words)
_FILLER_RE = re.compile(
    r"(?:(?<=\s)|^)(?:um+|uh+|erm+|uh[mh]+|ah+)(?:\s*,)?(?=\s|$)",
    re.I,
)
_SPACE_RE = re.compile(r"[ \t]{2,}")
_CONTRACTION_FIXES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bthats\b", re.I), "that's"),
    (re.compile(r"\bwont\b", re.I), "won't"),
    (re.compile(r"\bdont\b", re.I), "don't"),
    (re.compile(r"\bcant\b", re.I), "can't"),
    (re.compile(r"\bdidnt\b", re.I), "didn't"),
    (re.compile(r"\bdoesnt\b", re.I), "doesn't"),
    (re.compile(r"\bisnt\b", re.I), "isn't"),
    (re.compile(r"\barent\b", re.I), "aren't"),
    (re.compile(r"\bwasnt\b", re.I), "wasn't"),
    (re.compile(r"\bwerent\b", re.I), "weren't"),
    (re.compile(r"\bhavent\b", re.I), "haven't"),
    (re.compile(r"\bhasnt\b", re.I), "hasn't"),
    (re.compile(r"\bwouldnt\b", re.I), "wouldn't"),
    (re.compile(r"\bcouldnt\b", re.I), "couldn't"),
    (re.compile(r"\bshouldnt\b", re.I), "shouldn't"),
    (re.compile(r"\bim\b", re.I), "I'm"),
    (re.compile(r"\bive\b", re.I), "I've"),
    (re.compile(r"\bid\b(?=\s+(?:like|love|prefer|rather|say|go))", re.I), "I'd"),
    (re.compile(r"\byoure\b", re.I), "you're"),
    (re.compile(r"\btheyre\b", re.I), "they're"),
]

_tls = threading.local()
_bearer_lock = threading.Lock()
_bearer_cache: dict = {
    "token": None,
    "path": None,
    "mtime": None,
    "loaded_at": 0.0,
}


def _words(s: str) -> list[str]:
    s = (s or "").translate(_APOS_TRANS)
    return re.findall(r"[a-z0-9']+", s.lower())


def load_format_examples() -> dict:
    if not EXAMPLES_PATH.is_file():
        return {"examples": [], "dictionary": []}
    try:
        data = json.loads(EXAMPLES_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("examples"), list):
            return data
    except Exception as e:
        logging.getLogger("openflow").warning(
            "Could not load format examples from %s: %s", EXAMPLES_PATH, e
        )
    return {"examples": [], "dictionary": []}


# Built-in STT mishear fixes (always applied; no chat model needed).
# Order matters: longer / more specific patterns first.
_BUILTIN_LEXICON: list[tuple[str, str]] = [
    # --- Grok Flow / Wispr (heard as "croc flow" in real History) ---
    (r"\bcroc\s*flow\b", "Grok Flow"),
    (r"\bcrock\s*flow\b", "Grok Flow"),
    (r"\bgrock\s*flow\b", "Grok Flow"),
    (r"\bgrok\s*flow\b", "Grok Flow"),
    (r"\bcroc\b(?=\s+(?:flow|shim|backend|stt))", "Grok"),
    (r"\bgrock\b", "Grok"),
    (r"\bwhisper\s*flow\b", "Wispr Flow"),
    (r"\bwisper\s*flow\b", "Wispr Flow"),
    (r"\bwhisperflow\b", "Wispr Flow"),
    (r"\bwisperflow\b", "Wispr Flow"),
    (r"\bwisper\b", "Wispr"),
    # --- Devin CLI ---
    (r"\bdev\s*and\s*c\s*[\.\s]*l\s*[\.\s]*i\b", "Devin CLI"),
    (r"\bdev\s*and\s*c\.?\s*l\.?\s*i\.?\b", "Devin CLI"),
    (r"\bdev\s*and\s*cli\b", "Devin CLI"),
    (r"\bdev\s*n\s*cli\b", "Devin CLI"),
    (r"\bdevon\s*c\s*[\.\s]*l\s*[\.\s]*i\b", "Devin CLI"),
    (r"\bdevon\s*cli\b", "Devin CLI"),
    (r"\bdevin\s*c\s*[\.\s]*l\s*[\.\s]*i\b", "Devin CLI"),
    (r"\bdev\s*in\s*cli\b", "Devin CLI"),
    (r"\bdev\s*in\s*c\s*[\.\s]*l\s*[\.\s]*i\b", "Devin CLI"),
    (r"\bdevon\b", "Devin"),
    (r"\bc\s*[\.\s]+l\s*[\.\s]+i\b", "CLI"),
    # --- OAuth ---
    (r"\bo\s*off\b", "oauth"),
    (r"\boh\s*off\b", "oauth"),
    (r"\bo\s*auth\b", "oauth"),
    (r"\boh\s*auth\b", "oauth"),
    (r"\b0\s*auth\b", "oauth"),
    (r"\bo\s*a\s*u\s*t\s*h\b", "oauth"),
    # --- Agent stack / tools (this machine) ---
    (r"\bcloud\s*code\b", "Claude Code"),
    (r"\bclawed\s*code\b", "Claude Code"),
    (r"\bcode\s*x\b", "Codex"),
    (r"\bcodex\s*cli\b", "Codex CLI"),
    (r"\bopen\s*router\b", "OpenRouter"),
    (r"\bopen\s*a\s*i\b", "OpenAI"),
    (r"\bsuper\s*grok\b", "SuperGrok"),
    (r"\bbase\s*10\b", "Baseten"),
    (r"\bbase\s*ten\b", "Baseten"),
    (r"\bbas[ae]\s*ten\b", "Baseten"),
    (r"\bwsl\s*d\s*2\b", "WSL2"),
    (r"\bwsl\s*d2\b", "WSL2"),
    (r"\bwsld\s*2\b", "WSL2"),
    (r"\bwsl\s*2\b", "WSL2"),
    (r"\bt\s*3\s*code\b", "T3 Code"),
    (r"\btee\s*3\s*code\b", "T3 Code"),
    (r"\bvs\s*code\b", "VS Code"),
    (r"\bgit\s*hub\b", "GitHub"),
    (r"\bgit\s*lab\b", "GitLab"),
    (r"\bpost\s*gre\s*s(?:ql)?\b", "Postgres"),
    (r"\bpost\s*gres\b", "Postgres"),
    (r"\brtx\s*50\s*90\b", "RTX 5090"),
    (r"\brtx\s*40\s*90\b", "RTX 4090"),
]


def _compile_lexicon() -> list[tuple[re.Pattern[str], str]]:
    """Merge built-in + format_examples dictionary replacements into compiled rules."""
    rules: list[tuple[str, str]] = list(_BUILTIN_LEXICON)
    for d in (FORMAT_DATA.get("dictionary") or []):
        if not isinstance(d, dict):
            continue
        phrase = (d.get("phrase") or "").strip()
        rep = d.get("replacement")
        if not phrase or not rep or not str(rep).strip():
            continue
        # Exact phrase match (case-insensitive), whole words when alphanumeric edges
        esc = re.escape(phrase)
        rules.append((rf"(?i)(?<!\w){esc}(?!\w)", str(rep).strip()))
    compiled: list[tuple[re.Pattern[str], str]] = []
    for pat, repl in rules:
        try:
            compiled.append((re.compile(pat, re.IGNORECASE), repl))
        except re.error as e:
            logging.getLogger("openflow").warning("bad lexicon pattern %r: %s", pat, e)
    return compiled


def apply_lexicon(text: str, rules: list[tuple[re.Pattern[str], str]] | None = None) -> str:
    """Deterministic post-STT spelling fixes (runs even when chat format is off)."""
    if not text:
        return text
    rules = rules if rules is not None else LEXICON_RULES
    out = text
    for pat, repl in rules:
        out2 = pat.sub(repl, out)
        if out2 != out:
            logging.getLogger("openflow").debug(
                "lexicon: %r -> %r", pat.pattern[:48], repl
            )
            out = out2
    return out


def local_light_cleanup(text: str) -> str:
    """Zero-latency Auto Cleanup Light: lexicon + stutters + fillers + light contractions.

    No network. Safe to run on every chunk/final paste. Does not paraphrase.
    """
    if not text or not LOCAL_CLEANUP:
        return text
    out = apply_lexicon(text.translate(_APOS_TRANS))
    prev = None
    # Collapse multi-stutters in a couple of passes
    for _ in range(3):
        prev = out
        out = _STUTTER_RE.sub(r"\1", out)
        if out == prev:
            break
    out = _FILLER_RE.sub(" ", out)
    for pat, repl in _CONTRACTION_FIXES:
        out = pat.sub(repl, out)
    out = _SPACE_RE.sub(" ", out)
    # Tidy spaces before punctuation
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    return out.strip()


def format_is_faithful(asr: str, cleaned: str) -> bool:
    """Reject aggressive rewrites / summarization — keep full dictation length."""
    aw, cw = _words(asr), _words(cleaned)
    if not aw:
        return True
    if not cw:
        return False
    backtrack = bool(_BACKTRACK_RE.search(asr))
    min_ratio = 0.55 if backtrack else 0.82
    if len(cw) < max(3, int(len(aw) * min_ratio)):
        return False
    char_floor = 0.40 if backtrack else 0.75
    if len(cleaned.strip()) < max(12, int(len(asr.strip()) * char_floor)):
        return False
    aset = set(aw)
    overlap = sum(1 for w in cw if w in aset)
    if overlap / max(len(cw), 1) < 0.70:
        return False
    if len(cw) > int(len(aw) * 1.25) + 6:
        return False
    return True


def _few_shot_messages(asr_text: str, req: dict) -> list[dict]:
    """Build chat messages: system + few-shot pairs + current transcript."""
    msgs: list[dict] = [{"role": "system", "content": FORMAT_SYSTEM}]
    examples = FORMAT_DATA.get("examples") or []
    # Cap shots to keep latency down; prefer highest-overlap first (file already sorted).
    for ex in examples[:5]:
        raw = (ex.get("asr") or "").strip()
        cleaned = (ex.get("fmt") or "").strip()
        if not raw or not cleaned:
            continue
        msgs.append(
            {
                "role": "user",
                "content": f"Clean this dictation (Auto Cleanup Light):\n{raw}",
            }
        )
        msgs.append({"role": "assistant", "content": cleaned})

    dict_terms = _dictionary_terms(req)
    # Merge frozen dictionary from mined file
    for d in FORMAT_DATA.get("dictionary") or []:
        if isinstance(d, dict):
            phrase = (d.get("phrase") or "").strip()
            rep = d.get("replacement")
            if phrase:
                dict_terms.append(phrase if not rep else f"{phrase}→{rep}")
        elif isinstance(d, str) and d.strip():
            dict_terms.append(d.strip())
    # de-dupe
    seen = set()
    merged = []
    for t in dict_terms:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            merged.append(t)

    parts = [f"Clean this dictation (Auto Cleanup Light):\n{asr_text}"]
    app = _app_hint(req)
    if app:
        parts.append(f"Focused app: {app}")
    if merged:
        parts.append("Dictionary / preferred spellings: " + ", ".join(merged[:40]))
    msgs.append({"role": "user", "content": "\n\n".join(parts)})
    return msgs


def _default_auth_path() -> Path:
    env = os.environ.get("GROK_AUTH_JSON")
    if env:
        return Path(env)
    candidates = [
        Path.home() / ".grok" / "auth.json",
    ]
    up = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if up:
        candidates.append(Path(up) / ".grok" / "auth.json")
    wsl_user = os.environ.get("USER") or os.environ.get("USERNAME") or "user"
    candidates.extend(
        [
            Path(r"\\wsl$\Ubuntu\home") / wsl_user / ".grok" / "auth.json",
            Path(r"\\wsl.localhost\Ubuntu\home") / wsl_user / ".grok" / "auth.json",
        ]
    )
    for c in candidates:
        try:
            if c.is_file():
                return c
        except Exception:
            continue
    return candidates[0]


AUTH_PATH = _default_auth_path()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("openflow")
FORMAT_DATA = load_format_examples()
LEXICON_RULES = _compile_lexicon()
_examples_mtime: float | None = None
_EXAMPLE_RELOAD_INTERVAL_S = max(
    0.0, float(os.environ.get("OPENFLOW_EXAMPLE_RELOAD_INTERVAL", "1.0"))
)
_examples_checked_at = 0.0
_examples_reload_lock = threading.Lock()
try:
    _examples_mtime = EXAMPLES_PATH.stat().st_mtime
except OSError:
    pass

# Lightweight request metrics (process-local)
_metrics_lock = threading.Lock()
_metrics: dict = {
    "started_at": time.time(),
    "requests": 0,
    "stt_ok": 0,
    "stt_fail": 0,
    "format_ok": 0,
    "format_skip": 0,
    "empty": 0,
    "last_total_s": 0.0,
    "last_asr_s": 0.0,
    "sum_total_s": 0.0,
    "sum_asr_s": 0.0,
    "last_provider": "",
}

STATIC_DIR = Path(__file__).resolve().parents[1] / "static" / "openflow"


def _metrics_note(**kwargs) -> None:
    with _metrics_lock:
        for k, v in kwargs.items():
            if k not in _metrics:
                _metrics[k] = v
                continue
            if isinstance(_metrics[k], (int, float)) and isinstance(v, (int, float)):
                if k.startswith("sum_") or k in (
                    "requests",
                    "stt_ok",
                    "stt_fail",
                    "format_ok",
                    "format_skip",
                    "empty",
                ):
                    _metrics[k] = _metrics[k] + v
                else:
                    _metrics[k] = v
            else:
                _metrics[k] = v


def maybe_reload_examples() -> None:
    """Hot-reload examples while avoiding a filesystem stat on every dictation."""
    global FORMAT_DATA, LEXICON_RULES, _examples_checked_at, _examples_mtime
    now = time.monotonic()
    if now - _examples_checked_at < _EXAMPLE_RELOAD_INTERVAL_S:
        return
    with _examples_reload_lock:
        if now - _examples_checked_at < _EXAMPLE_RELOAD_INTERVAL_S:
            return
        _examples_checked_at = now
        try:
            mtime = EXAMPLES_PATH.stat().st_mtime
        except OSError:
            return
        if _examples_mtime is not None and mtime <= _examples_mtime:
            return
        FORMAT_DATA = load_format_examples()
        LEXICON_RULES = _compile_lexicon()
        _examples_mtime = mtime
        log.info(
            "Reloaded format examples: %d few-shots, %d lexicon rules",
            len(FORMAT_DATA.get("examples") or []),
            len(LEXICON_RULES),
        )


def _setup_file_logging() -> None:
    """Always write to logs/shim.log (install root or package parent)."""
    # openflow/server/app.py -> package openflow/ -> install root
    pkg_root = Path(__file__).resolve().parents[1]  # openflow/
    install_root = pkg_root.parent
    log_dir = install_root / "logs"
    if not (pkg_root / "static").is_dir():
        log_dir = pkg_root / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "shim.log"
        # Avoid duplicate handlers on reload
        for h in list(log.handlers):
            if isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "").endswith(
                "shim.log"
            ):
                return
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logging.getLogger().addHandler(fh)
    except Exception as e:
        logging.getLogger("openflow").warning("file logging unavailable: %s", e)


log.info(
    "Loaded %d format few-shots and %d lexicon rules from %s",
    len(FORMAT_DATA.get("examples") or []),
    len(LEXICON_RULES),
    EXAMPLES_PATH,
)


def _parse_auth_token(data: dict) -> str:
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
        log.warning("Grok OAuth token appears expired in %s — trying anyway", AUTH_PATH)
        return expired_fallback
    raise RuntimeError(f"No OAuth key in {AUTH_PATH} — run `grok login`")


def load_bearer() -> str:
    """Load SuperGrok OAuth bearer; cache by auth.json mtime (avoids re-read per request)."""
    path = AUTH_PATH
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    with _bearer_lock:
        if (
            _bearer_cache["token"]
            and _bearer_cache["path"] == str(path)
            and _bearer_cache["mtime"] == mtime
            and (time.time() - float(_bearer_cache["loaded_at"] or 0)) < 300
        ):
            return _bearer_cache["token"]  # type: ignore[return-value]
        data = json.loads(path.read_text(encoding="utf-8"))
        token = _parse_auth_token(data)
        _bearer_cache.update(
            {
                "token": token,
                "path": str(path),
                "mtime": mtime,
                "loaded_at": time.time(),
            }
        )
        return token


def _http_session():
    """Thread-local requests.Session for TLS connection reuse to api.x.ai."""
    try:
        import requests  # type: ignore
    except ImportError:
        return None
    sess = getattr(_tls, "session", None)
    if sess is None:
        sess = requests.Session()
        sess.headers.update({"User-Agent": USER_AGENT})
        _tls.session = sess
    return sess


def decode_audio_b64(audio_b64: str) -> bytes:
    raw = base64.b64decode(audio_b64)
    if raw[:4] == b"RIFF":
        return raw
    n = len(raw)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + n,
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        16000,
        16000 * 2,
        2,
        16,
        b"data",
        n,
    )
    return header + raw


class SttHttpError(Exception):
    def __init__(self, code: int, body: str = ""):
        self.code = code
        self.body = body
        super().__init__(f"HTTP {code}: {body[:200]}")


def _http_post_json(
    url: str,
    *,
    headers: dict,
    data: bytes | None = None,
    files: dict | None = None,
    form: dict | None = None,
    timeout: float = 15.0,
    connect_timeout: float = 3.0,
) -> dict:
    """POST and parse JSON. Prefer requests (better SSL under threads on Windows).

    Reuses a thread-local Session for keep-alive to api.x.ai (saves ~50–150ms/call
    after the first). Falls back to a one-shot session if thread-local is unavailable.
    """
    session = _http_session()
    if session is not None:
        kw: dict = {
            "headers": {**headers, "User-Agent": USER_AGENT},
            "timeout": (connect_timeout, timeout),
        }
        if files is not None:
            kw["files"] = files
            kw["data"] = form or {}
        else:
            kw["data"] = data
        try:
            resp = session.post(url, **kw)
        except Exception:
            # Drop broken pooled connection and retry once with a fresh session.
            try:
                session.close()
            except Exception:
                pass
            _tls.session = None
            session = _http_session()
            if session is None:
                raise
            resp = session.post(url, **kw)
        if resp.status_code >= 400:
            raise SttHttpError(resp.status_code, resp.text[:500])
        return resp.json()

    if files is not None:
        boundary = "----GrokFlowBoundary7"
        parts: list[bytes] = []
        for name, (filename, content, ctype) in files.items():
            parts.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{name}"; '
                    f'filename="{filename}"\r\n'
                    f"Content-Type: {ctype}\r\n\r\n"
                ).encode()
                + content
                + b"\r\n"
            )
        if form:
            for k, v in form.items():
                parts.append(
                    (
                        f"--{boundary}\r\n"
                        f'Content-Disposition: form-data; name="{k}"\r\n\r\n'
                        f"{v}\r\n"
                    ).encode()
                )
        parts.append(f"--{boundary}--\r\n".encode())
        data = b"".join(parts)
        headers = {
            **headers,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": USER_AGENT,
        }

    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read()[:500].decode("utf-8", "replace")
        raise SttHttpError(e.code, body) from e


def grok_stt(wav_bytes: bytes, language: str = "en") -> dict:
    """Call Grok STT. Retries once on timeout (common Windows SSL glitch)."""
    bearer = load_bearer()
    headers = {"Authorization": f"Bearer {bearer}", "User-Agent": USER_AGENT}
    form: dict[str, str] = {"language": language or "en"}
    if STT_FORMAT:
        form["format"] = "true"
    files = {"file": ("dictation.wav", wav_bytes, "audio/wav")}

    last_err: Exception | None = None
    attempts = max(1, STT_RETRIES + 1)
    for attempt in range(1, attempts + 1):
        t0 = time.time()
        try:
            log.info(
                "STT attempt %d/%d wav=%d bytes (%.1fs audio est)",
                attempt,
                attempts,
                len(wav_bytes),
                max(0, len(wav_bytes) - 44) / 32000.0,
            )
            result = _http_post_json(
                STT_URL,
                headers=headers,
                files=files,
                form=form,
                timeout=STT_TIMEOUT,
                connect_timeout=STT_CONNECT_TIMEOUT,
            )
            log.info("STT ok t=%.2fs keys=%s", time.time() - t0, list(result)[:8])
            return result
        except Exception as e:
            last_err = e
            log.warning(
                "STT attempt %d failed t=%.2fs: %s: %s",
                attempt,
                time.time() - t0,
                type(e).__name__,
                e,
            )
            if attempt < attempts:
                time.sleep(0.15)
                continue
    assert last_err is not None
    raise last_err


def _dictionary_terms(req: dict) -> list[str]:
    terms: list[str] = []
    for key in ("dictionary", "dictionaries", "words", "custom_words"):
        v = req.get(key)
        if isinstance(v, list):
            for item in v:
                if isinstance(item, str) and item.strip():
                    terms.append(item.strip())
                elif isinstance(item, dict):
                    w = item.get("word") or item.get("text") or item.get("term")
                    if isinstance(w, str) and w.strip():
                        terms.append(w.strip())
        elif isinstance(v, dict):
            for w in v.keys():
                if isinstance(w, str) and w.strip():
                    terms.append(w.strip())
    ctx = req.get("context") or {}
    if isinstance(ctx, dict):
        for key in ("dictionary", "words"):
            v = ctx.get(key)
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, str) and item.strip():
                        terms.append(item.strip())
    # de-dupe, keep order
    seen = set()
    out = []
    for t in terms:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out[:80]


def _app_hint(req: dict) -> str:
    ctx = req.get("context") or {}
    if not isinstance(ctx, dict):
        return ""
    app = ctx.get("app") or {}
    if isinstance(app, dict):
        name = app.get("name") or app.get("bundleId") or ""
        kind = app.get("type") or ""
        return f"{name} ({kind})".strip()
    return str(app) if app else ""


def grok_format(asr_text: str, req: dict) -> str:
    bearer = load_bearer()
    max_tokens = max(256, min(8192, len(asr_text) // 3 + 128))
    payload = {
        "model": CHAT_MODEL,
        "messages": _few_shot_messages(asr_text, req),
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }
    body = json.dumps(payload).encode("utf-8")
    data = _http_post_json(
        CHAT_URL,
        headers={
            "Authorization": f"Bearer {bearer}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        data=body,
        timeout=FORMAT_TIMEOUT,
        connect_timeout=STT_CONNECT_TIMEOUT,
    )
    text = (data["choices"][0]["message"]["content"] or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text


def pick_language(req: dict) -> str:
    lang = req.get("language")
    if isinstance(lang, str) and lang:
        return lang.split("-")[0].lower()
    langs = req.get("languages") or []
    if isinstance(langs, list) and langs:
        v = langs[0]
        if isinstance(v, str):
            return v.split("-")[0].lower()
    return "en"


def _wants_format(req: dict) -> bool:
    pipeline = req.get("pipeline") or []
    if isinstance(pipeline, list):
        return any(str(x).lower() == "format" for x in pipeline)
    return True


def _join_prev_and_chunk(prev: str, chunk: str) -> str:
    prev = (prev or "").strip()
    chunk = (chunk or "").strip()
    if prev and chunk:
        return f"{prev} {chunk}"
    return prev or chunk


def _prev_field(req: dict, *names: str) -> str:
    for n in names:
        v = req.get(n)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _result(
    *,
    status: str,
    asr_text: str,
    llm_text: str,
    detected: str,
    t0: float,
    asr_time: float = 0.0,
    llm_time: float = 0.0,
    error_message: str | None = None,
) -> dict:
    total = time.time() - t0
    out = {
        "status": status,
        "asr_text": asr_text,
        "llm_text": llm_text,
        "pipeline_text": llm_text,
        "detected_language": detected,
        "asr_time": round(asr_time, 3),
        "llm_time": round(llm_time, 3),
        "total_time": round(total, 3),
        "component_times": {
            "transcribe": round(asr_time, 3),
            "align": 0,
            "format": round(llm_time, 3),
        },
    }
    if error_message:
        out["error_message"] = error_message
    return out


def handle_transcribe(req: dict) -> dict:
    """Transcribe one Wispr audio chunk.

    Wispr splits long hold-to-talk into multiple HTTP calls:
      - mid-stream: pipeline without format; asr_text is *this chunk only*
      - final: pipeline includes format; request carries prev_asr_text
        (all earlier chunks joined). Paste uses the *last* non-empty
        llm_text, so format responses must return the FULL utterance in
        llm_text while keeping asr_text as the new chunk only.
    """
    t0 = time.time()
    maybe_reload_examples()
    _metrics_note(requests=1)
    language = pick_language(req)
    prev_asr = _prev_field(
        req,
        "prev_asr_text",
        "prevAsrText",
        "previous_asr_text",
        "prev_asr",
        "previousAsrText",
    )
    prev_llm = _prev_field(
        req, "prev_llm_text", "prevLlmText", "previous_llm_text", "previousLlmText"
    )
    audio_b64 = req.get("audio")
    wants_fmt = _wants_format(req)

    # Text-only finalize (no new audio)
    if not audio_b64:
        if prev_asr and wants_fmt:
            log.info("format-only finalize prev_asr=%d (no audio)", len(prev_asr))
            base = local_light_cleanup(prev_asr)
            llm = base
            if LLM_FORMAT and (time.time() - t0) < CLIENT_BUDGET_S - 5:
                try:
                    cleaned = grok_format(base, req)
                    if cleaned and format_is_faithful(base, cleaned):
                        llm = local_light_cleanup(cleaned)
                except Exception:
                    log.exception("format-only pass failed")
            return _result(
                status="formatted",
                asr_text="",
                llm_text=llm,
                detected=language,
                t0=t0,
            )
        return _result(
            status="error",
            asr_text="",
            llm_text="",
            detected=language,
            t0=t0,
            error_message="no audio field (audio_packets-only not supported yet)",
        )

    try:
        if not isinstance(audio_b64, (str, bytes, bytearray)):
            raise TypeError("audio must be base64 string")
        if isinstance(audio_b64, (bytes, bytearray)):
            audio_b64 = audio_b64.decode("ascii", "ignore")
        wav = decode_audio_b64(audio_b64)
    except Exception as e:
        log.exception("audio decode failed")
        if prev_asr:
            return _result(
                status="formatted" if wants_fmt else "raw_transcript",
                asr_text="",
                llm_text=prev_asr,
                detected=language,
                t0=t0,
                error_message=f"audio decode: {e}",
            )
        return _result(
            status="error",
            asr_text="",
            llm_text="",
            detected=language,
            t0=t0,
            error_message=f"audio decode: {e}",
        )

    pcm_bytes = max(0, len(wav) - 44) if wav[:4] == b"RIFF" else len(wav)
    audio_secs = pcm_bytes / (16000 * 2)

    log.info(
        "audio wav=%d bytes est=%.1fs language=%s",
        len(wav),
        audio_secs,
        language,
    )
    try:
        from openflow.providers.registry import transcribe_with_active

        stt = transcribe_with_active(wav, language=language)
        _metrics_note(stt_ok=1)
        try:
            from openflow.providers.registry import stats_snapshot

            snap = stats_snapshot()
            if snap.get("last_provider"):
                _metrics_note(last_provider=snap["last_provider"])  # type: ignore[arg-type]
        except Exception:
            pass
    except Exception as stt_err:
        _metrics_note(stt_fail=1)
        # Failed recordings are retained only when the user explicitly sets
        # WISPR_GROK_DEBUG_AUDIO to a directory.
        if DEBUG_AUDIO_DIR is not None:
            try:
                DEBUG_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
                stamp = time.strftime("%Y%m%d-%H%M%S")
                audio_path = DEBUG_AUDIO_DIR / f"fail-{stamp}.wav"
                audio_path.write_bytes(wav)
                log.info("wrote opt-in debug audio %s", audio_path)
            except Exception:
                log.exception("could not write opt-in debug audio")
        log.exception("STT failed")
        if isinstance(stt_err, SttHttpError):
            err_msg = f"stt http {stt_err.code}"
            log.error("STT HTTP %s: %s", stt_err.code, stt_err.body[:300])
        else:
            err_msg = str(stt_err)
        if prev_asr:
            log.warning("STT failed; pasting prev_asr (%d chars)", len(prev_asr))
            return _result(
                status="formatted" if wants_fmt else "raw_transcript",
                asr_text="",
                llm_text=prev_asr,
                detected=language,
                t0=t0,
                asr_time=time.time() - t0,
                error_message=f"{err_msg}; used prev_asr",
            )
        return _result(
            status="error",
            asr_text="",
            llm_text="",
            detected=language,
            t0=t0,
            asr_time=time.time() - t0,
            error_message=err_msg,
        )

    # STT field variants
    chunk_asr = (
        stt.get("text")
        or stt.get("transcript")
        or stt.get("asr_text")
        or ""
    )
    if isinstance(chunk_asr, str):
        chunk_asr = chunk_asr.strip()
    else:
        chunk_asr = str(chunk_asr or "").strip()

    # One local cleanup pass (lexicon + stutter/filler) — no chat needed.
    before_clean = chunk_asr
    chunk_asr = local_light_cleanup(chunk_asr)
    if prev_asr:
        prev_asr = local_light_cleanup(prev_asr)
    if chunk_asr != before_clean:
        log.info(
            "local cleanup changed transcript input_chars=%d output_chars=%d",
            len(before_clean),
            len(chunk_asr),
        )

    detected = stt.get("language") or language
    asr_time = time.time() - t0
    full_asr = _join_prev_and_chunk(prev_asr, chunk_asr)

    log.info(
        "chunk audio=%.1fs prev_asr=%d chunk_asr=%d full_asr=%d format=%s",
        audio_secs,
        len(prev_asr),
        len(chunk_asr),
        len(full_asr),
        wants_fmt,
    )

    if not chunk_asr and not prev_asr:
        _metrics_note(empty=1, last_total_s=time.time() - t0, last_asr_s=asr_time)
        return _result(
            status="empty",
            asr_text="",
            llm_text="",
            detected=detected,
            t0=t0,
            asr_time=asr_time,
        )

    # Empty new chunk but we have history (trailing silence on stop)
    if not chunk_asr and prev_asr:
        llm = local_light_cleanup(prev_asr)
        llm_time = 0.0
        status = "formatted" if wants_fmt else "raw_transcript"
        if wants_fmt and LLM_FORMAT and (time.time() - t0) < CLIENT_BUDGET_S - 5:
            t1 = time.time()
            try:
                cleaned = grok_format(prev_asr, req)
                llm_time = time.time() - t1
                if cleaned and format_is_faithful(prev_asr, cleaned):
                    llm = local_light_cleanup(cleaned)
            except Exception:
                log.exception("format on prev_asr-only failed")
                llm_time = time.time() - t1
        return _result(
            status=status,
            asr_text="",
            llm_text=llm,
            detected=detected,
            t0=t0,
            asr_time=asr_time,
            llm_time=llm_time,
        )

    # Chunk-only asr for client join
    asr_text = chunk_asr
    llm_text = chunk_asr
    llm_time = 0.0
    status = "raw_transcript"

    if wants_fmt and full_asr:
        # Always put FULL utterance in llm_text so paste is not last-chunk-only.
        llm_text = full_asr
        status = "formatted"
        if LLM_FORMAT and (time.time() - t0) < CLIENT_BUDGET_S - 5:
            t1 = time.time()
            try:
                cleaned = grok_format(full_asr, req)
                llm_time = time.time() - t1
                if cleaned and format_is_faithful(full_asr, cleaned):
                    llm_text = local_light_cleanup(cleaned)
                elif cleaned:
                    log.warning(
                        "format rejected (full_words=%d llm_words=%d full_chars=%d llm_chars=%d)",
                        len(_words(full_asr)),
                        len(_words(cleaned)),
                        len(full_asr),
                        len(cleaned),
                    )
                    llm_text = full_asr
            except Exception:
                log.exception("format pass failed; pasting full ASR")
                llm_time = time.time() - t1
                llm_text = full_asr
        else:
            if LLM_FORMAT:
                log.info(
                    "skipping chat format (near client budget t=%.1fs)",
                    time.time() - t0,
                )

    # Safety: formatted llm must not be a short stub vs known full ASR
    if status == "formatted" and full_asr and len(llm_text.strip()) < int(
        len(full_asr) * 0.75
    ):
        log.warning(
            "llm_text still short (llm=%d full=%d); forcing full ASR",
            len(llm_text),
            len(full_asr),
        )
        llm_text = full_asr

    total = time.time() - t0
    _metrics_note(
        last_total_s=total,
        last_asr_s=asr_time,
        sum_total_s=total,
        sum_asr_s=asr_time,
        format_ok=1 if (status == "formatted" and llm_time > 0) else 0,
        format_skip=1 if (status == "formatted" and llm_time == 0) else 0,
    )
    log.info(
        "done status=%s chunk_asr=%d llm=%d full_ref=%d prev_llm=%d t=%.2fs",
        status,
        len(asr_text),
        len(llm_text),
        len(full_asr),
        len(prev_llm),
        total,
    )
    return _result(
        status=status,
        asr_text=asr_text,
        llm_text=llm_text,
        detected=detected,
        t0=t0,
        asr_time=asr_time,
        llm_time=llm_time,
    )



def _origin_allowed(origin: str | None) -> bool:
    """Allow the bundled UI and local Electron shell, never arbitrary websites."""
    if not origin:
        return True
    if origin in {"null", "file://"}:
        return True
    try:
        parsed = urlparse(origin)
        return (
            parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            and (parsed.port or 80) == PORT
        )
    except ValueError:
        return False


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        msg = fmt % args
        # Wispr TLS-probes plain HTTP; ignore the noise
        if (
            "Bad request version" in msg
            or "Bad HTTP/0.9" in msg
            or "Bad request syntax" in msg
            or "code 400" in msg
        ):
            return
        # Binary TLS ClientHello often shows up as mojibake request lines
        if sum(1 for c in msg if ord(c) < 32 or ord(c) > 126) > 4:
            return
        log.info("%s - %s", self.address_string(), msg)

    def _cors(self):
        origin = self.headers.get("Origin")
        if origin and _origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, PUT, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _reject_cross_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if _origin_allowed(origin):
            return False
        log.warning("blocked cross-origin request origin=%r path=%s", origin, self.path)
        self._send(403, {"error": "cross-origin request denied"})
        return True

    def _send(self, code: int, obj: dict):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        if self._reject_cross_origin():
            return
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        if self._reject_cross_origin():
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send(
                400,
                {
                    "status": "error",
                    "asr_text": None,
                    "llm_text": None,
                    "error_message": "bad Content-Length",
                },
            )
            return
        if length < 0 or length > MAX_BODY_BYTES:
            self._send(
                413,
                {
                    "status": "error",
                    "asr_text": None,
                    "llm_text": None,
                    "error_message": "payload too large",
                },
            )
            return
        raw = self.rfile.read(length) if length else b"{}"
        path = self.path.split("?", 1)[0]
        # Allow POST /v1/config as well as PUT (some clients / proxies dislike PUT)
        if path.rstrip("/") in ("/v1/config", "/config"):
            try:
                body = raw.decode("utf-8") if raw else "{}"
                patch = json.loads(body.strip() or "{}")
            except Exception as e:
                self._send(400, {"error": "invalid json", "detail": str(e)})
                return
            if not isinstance(patch, dict):
                self._send(400, {"error": "body must be object"})
                return
            try:
                from openflow.config import save_config

                cfg = save_config(patch)
                log.info("config updated (POST) provider=%s", cfg.get("provider"))
                self._send(200, {"ok": True, "config": cfg, "provider": cfg.get("provider")})
            except Exception as e:
                log.exception("save_config failed")
                self._send(500, {"error": str(e)})
            return

        # Connect a speech engine (user-owned OAuth — never ships secrets)
        if path.rstrip("/") in ("/v1/auth/connect", "/auth/connect"):
            try:
                body = raw.decode("utf-8") if raw else "{}"
                patch = json.loads(body.strip() or "{}")
            except Exception as e:
                self._send(400, {"error": "invalid json", "detail": str(e)})
                return
            provider = (patch or {}).get("provider") if isinstance(patch, dict) else None
            help_only = bool((patch or {}).get("help")) if isinstance(patch, dict) else False
            # Local STT settings (optional — only used when provider=local)
            loc_url = (patch or {}).get("url") if isinstance(patch, dict) else None
            loc_model = (patch or {}).get("model") if isinstance(patch, dict) else None
            loc_key = (patch or {}).get("api_key") if isinstance(patch, dict) else None
            try:
                from openflow.auth import start_connect
                from openflow.providers.registry import invalidate_status_cache

                result = start_connect(
                    str(provider or ""),
                    help=help_only,
                    url=str(loc_url) if loc_url is not None else None,
                    model=str(loc_model) if loc_model is not None else None,
                    api_key=str(loc_key) if loc_key is not None else None,
                )
                invalidate_status_cache()
                # Local may return ok=False when the server is offline — still 200
                # so the UI can show the error detail without treating it as HTTP fail.
                code = 200
                if provider and str(provider).lower() != "local" and not result.get("ok"):
                    code = 400
                self._send(code, result)
            except Exception as e:
                log.exception("auth connect")
                self._send(500, {"ok": False, "error": str(e)})
            return

        if path.rstrip("/") in ("/v1/auth/skip", "/auth/skip"):
            try:
                from openflow.config import save_config

                cfg = save_config({"onboarding_skipped": True})
                self._send(200, {"ok": True, "config": cfg})
            except Exception as e:
                self._send(500, {"ok": False, "error": str(e)})
            return

        if path.rstrip("/") in ("/v1/auth/complete", "/auth/complete"):
            try:
                from openflow.config import save_config

                cfg = save_config(
                    {"onboarding_completed": True, "onboarding_skipped": False}
                )
                self._send(200, {"ok": True, "config": cfg})
            except Exception as e:
                self._send(500, {"ok": False, "error": str(e)})
            return

        if not path.rstrip("/").endswith("run_remote"):
            self._send(404, {"error": "not found", "path": path})
            return
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send(
                400,
                {
                    "status": "error",
                    "asr_text": None,
                    "llm_text": None,
                    "error_message": "invalid json",
                },
            )
            return
        req = payload.get("request") if isinstance(payload, dict) else None
        if not isinstance(req, dict):
            req = payload if isinstance(payload, dict) else {}
        prev_len = len(
            _prev_field(
                req, "prev_asr_text", "prevAsrText", "previous_asr_text", "prev_asr"
            )
        )
        log.info(
            "transcribe audio=%s packets=%s pipeline=%s prev_asr=%d",
            bool(req.get("audio")),
            bool(req.get("audio_packets")),
            req.get("pipeline"),
            prev_len,
        )
        try:
            result = handle_transcribe(req)
        except Exception as e:
            log.exception("handle_transcribe crashed")
            result = {
                "status": "error",
                "asr_text": None,
                "llm_text": None,
                "error_message": str(e),
                "total_time": 0,
            }
        log.info(
            "-> status=%s asr_chars=%s llm_chars=%s t=%.2fs (asr=%.2f fmt=%.2f)",
            result.get("status"),
            len(result.get("asr_text") or "") if result.get("asr_text") is not None else 0,
            len(result.get("llm_text") or "") if result.get("llm_text") is not None else 0,
            result.get("total_time") or 0,
            result.get("asr_time") or 0,
            result.get("llm_time") or 0,
        )
        self._send(200, result)

    def do_PUT(self):
        if self._reject_cross_origin():
            return
        path = self.path.split("?", 1)[0]
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length else b"{}"
        if path.rstrip("/") in ("/v1/config", "/config"):
            try:
                body = raw.decode("utf-8") if raw else "{}"
                body = body.strip() or "{}"
                patch = json.loads(body)
            except Exception as e:
                log.warning("config PUT bad json: %r err=%s", raw[:200], e)
                self._send(400, {"error": "invalid json", "detail": str(e)})
                return
            if not isinstance(patch, dict):
                self._send(400, {"error": "body must be object"})
                return
            try:
                from openflow.config import save_config

                cfg = save_config(patch)
                log.info("config updated provider=%s", cfg.get("provider"))
                self._send(200, {"ok": True, "config": cfg, "provider": cfg.get("provider")})
            except Exception as e:
                log.exception("save_config failed")
                self._send(500, {"error": str(e)})
            return
        self._send(404, {"error": "not found"})

    def _serve_static(self, rel: str) -> bool:
        if not STATIC_DIR.is_dir():
            return False
        rel = rel.lstrip("/")
        if not rel or rel.endswith("/"):
            rel = "index.html"
        # path traversal guard
        target = (STATIC_DIR / rel).resolve()
        try:
            target.relative_to(STATIC_DIR.resolve())
        except ValueError:
            return False
        if not target.is_file():
            return False
        data = target.read_bytes()
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self._send_bytes(200, data, ctype)
        return True

    def do_GET(self):
        if self._reject_cross_origin():
            return
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path in ("/v1/insights", "/insights"):
            # Local Insights: honest stats computed from the on-device history
            # database (replaces Wispr's cloud-only Insights). Read-only.
            try:
                from openflow.insights import compute_insights

                self._send(200, compute_insights())
            except Exception as e:
                log.exception("insights")
                self._send(500, {"available": False, "error": str(e)})
            return

        if path.rstrip("/") in ("/v1/auth/status", "/auth/status"):
            try:
                from openflow.auth import needs_onboarding, status as auth_status
                from openflow.config import load_config

                cfg = load_config()
                st = auth_status()
                st["needs_onboarding"] = needs_onboarding() and not cfg.get(
                    "onboarding_skipped"
                )
                st["onboarding_skipped"] = bool(cfg.get("onboarding_skipped"))
                self._send(200, st)
            except Exception as e:
                log.exception("auth status")
                self._send(500, {"error": str(e)})
            return

        if path in ("/health", "/healthz"):
            try:
                from openflow.config import load_config
                from openflow.providers.registry import provider_status_map, stats_snapshot

                cfg = load_config()
                active = cfg.get("provider") or "grok"
                providers = provider_status_map(cfg=cfg)
                snap = stats_snapshot()
            except Exception as e:
                log.exception("health providers")
                providers = {}
                active = "grok"
                cfg = {}
                snap = {}
                log.warning("%s", e)
            grok_auth = bool((providers.get("grok") or {}).get("ready"))
            self._send(
                200,
                {
                    "ok": True,
                    "brand": "OpenFlow",
                    "auth": grok_auth,
                    "provider": active,
                    "providers": providers,
                    "config": cfg,
                    "stt": STT_URL,
                    "stt_format": STT_FORMAT,
                    "local_cleanup": LOCAL_CLEANUP,
                    "format_model": CHAT_MODEL if LLM_FORMAT else None,
                    "llm_format": LLM_FORMAT,
                    "uptime_s": round(time.time() - float(_metrics["started_at"]), 1),
                    "requests": _metrics["requests"],
                    "last_provider": snap.get("last_provider")
                    or _metrics.get("last_provider"),
                    "last_stt_ok": snap.get("last_ok"),
                    "last_stt_latency_s": snap.get("last_latency_s"),
                    "last_stt_error": snap.get("last_error"),
                },
            )
            return

        if path.rstrip("/") in ("/v1/providers", "/providers"):
            try:
                from openflow.config import load_config
                from openflow.providers.registry import provider_status_map

                cfg = load_config()
                active = cfg.get("provider") or "grok"
                self._send(
                    200,
                    {
                        "ok": True,
                        "active": active,
                        "providers": provider_status_map(cfg=cfg, force=True),
                    },
                )
            except Exception as e:
                self._send(500, {"error": str(e)})
            return

        if path.rstrip("/") in ("/v1/config", "/config"):
            try:
                from openflow.config import config_path, load_config

                self._send(
                    200,
                    {
                        "ok": True,
                        "path": str(config_path()),
                        "config": load_config(),
                    },
                )
            except Exception as e:
                self._send(500, {"error": str(e)})
            return

        if path in ("/metrics", "/stats"):
            with _metrics_lock:
                m = dict(_metrics)
            n = max(1, int(m.get("requests") or 1))
            m["avg_total_s"] = round(float(m.get("sum_total_s") or 0) / n, 3)
            m["avg_asr_s"] = round(float(m.get("sum_asr_s") or 0) / n, 3)
            m["uptime_s"] = round(time.time() - float(m["started_at"]), 1)
            m["lexicon_rules"] = len(LEXICON_RULES)
            m["few_shots"] = len(FORMAT_DATA.get("examples") or [])
            try:
                from openflow.providers.registry import stats_snapshot

                m["provider_stats"] = stats_snapshot()
            except Exception:
                pass
            self._send(200, m)
            return

        # Control Center UI
        if path in ("/", "/ui", "/ui/", "/openflow", "/openflow/"):
            if self._serve_static("index.html"):
                return
            self._send(
                200,
                {
                    "ok": True,
                    "brand": "OpenFlow",
                    "message": "UI not bundled; use /health and /v1/providers",
                },
            )
            return
        if path.startswith("/ui/") or path.startswith("/static/"):
            rel = path.split("/", 2)[-1] if path.startswith("/ui/") else path[len("/static/") :]
            if path.startswith("/ui/"):
                rel = path[len("/ui/") :]
            if self._serve_static(rel):
                return
        # allow common UI assets at root (incl. local Insights + setup wizard)
        if path.lstrip("/") in (
            "app.css",
            "app.js",
            "index.html",
            "stats.html",
            "overlay.html",
            "setup.html",
        ):
            if self._serve_static(path.lstrip("/")):
                return

        self._send(404, {"error": "not found"})


class ReuseThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True  # don't block process exit on hung request threads


def main():
    _setup_file_logging()
    # Soft-start: Grok auth optional if ChatGPT provider will be used
    try:
        b = load_bearer()
        log.info("Loaded Grok OAuth bearer (%d chars) from %s", len(b), AUTH_PATH)
    except Exception as e:
        log.warning("Grok auth not ready: %s (ChatGPT/Claude may still work)", e)
    try:
        from openflow.config import active_provider_id, config_path
        from openflow.providers.registry import prewarm, provider_status_map

        log.info("OpenFlow active provider=%s config=%s", active_provider_id(), config_path())
        prewarm()
        for pid, st in provider_status_map().items():
            log.info(
                "  provider %s ready=%s stt=%s — %s",
                pid,
                st.get("ready"),
                st.get("stt_capable"),
                st.get("detail"),
            )
    except Exception:
        log.exception("provider status at boot")
    # Write PID for watchdog / ops
    try:
        pid_path = Path(__file__).resolve().parents[1].parent / "logs" / "shim.pid"
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass
    httpd = ReuseThreadingHTTPServer((HOST, PORT), Handler)
    log.info(
        "OpenFlow shim on http://%s:%d ui=http://%s:%d/ (STT format=%s local_cleanup=%s llm_format=%s model=%s lexicon=%d)",
        HOST,
        PORT,
        HOST,
        PORT,
        STT_FORMAT,
        LOCAL_CLEANUP,
        LLM_FORMAT,
        CHAT_MODEL,
        len(LEXICON_RULES),
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
