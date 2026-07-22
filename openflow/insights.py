"""Local Insights — compute dictation stats from the local flow.sqlite.

This replaces Wispr's cloud-computed Insights (which requires a real account)
with honest, locally-computed numbers from the on-device history database.
Read-only: we never write to flow.sqlite, and we query it in immutable ro mode.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

# Candidates, most-specific first. Overridable via OPENFLOW_FLOW_DB.
_DEFAULT_DB_LOCATIONS = [
    r"%APPDATA%\Wispr Flow\flow.sqlite",
    r"%APPDATA%\OpenFlow\flow.sqlite",
]

# WSL mounts the Windows drive at /mnt/c; the shim normally runs on Windows,
# but for local testing / dev we also look through the WSL mount.
_WSL_APPDATA_GLOBS = [
    "/mnt/c/Users/*/AppData/Roaming/Wispr Flow/flow.sqlite",
    "/mnt/c/Users/*/AppData/Roaming/OpenFlow/flow.sqlite",
]


def _flow_db_path() -> Path | None:
    import glob

    cands: list[Path] = []
    env = os.environ.get("OPENFLOW_FLOW_DB")
    if env:
        cands.append(Path(env))
    appdata = os.environ.get("APPDATA")
    for raw in _DEFAULT_DB_LOCATIONS:
        p = raw
        if appdata:
            p = p.replace("%APPDATA%", appdata)
        cands.append(Path(os.path.expandvars(p)))
    for pattern in _WSL_APPDATA_GLOBS:
        for hit in glob.glob(pattern):
            cands.append(Path(hit))
    for c in cands:
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    return None


def _connect(db: Path) -> sqlite3.Connection:
    # immutable=1: open read-only without taking locks (safe while app is live).
    uri = f"file:{db.as_posix()}?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


def compute_insights() -> dict:
    """Return a dict of local dictation stats, or {"available": False}."""
    db = _flow_db_path()
    if not db:
        return {"available": False, "reason": "flow.sqlite not found"}

    try:
        con = _connect(db)
    except sqlite3.Error as e:
        return {"available": False, "reason": f"cannot open db: {e}"}

    try:
        cur = con.cursor()
        # Guards: table may not exist on a fresh install.
        tables = {r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "History" not in tables:
            return {"available": False, "reason": "no History table"}

        total_rows, total_words, total_speech = cur.execute(
            "SELECT COUNT(*), COALESCE(SUM(numWords),0), COALESCE(SUM(speechDuration),0) "
            "FROM History WHERE COALESCE(isArchived,0)=0"
        ).fetchone()

        total_words = int(total_words or 0)
        total_speech = float(total_speech or 0.0)
        avg_wpm = round(total_words / (total_speech / 60.0), 1) if total_speech > 0 else None

        # Words per day (local dates), most recent first.
        by_day = [
            {"date": d, "dictations": int(n), "words": int(w or 0)}
            for d, n, w in cur.execute(
                "SELECT date(timestamp) d, COUNT(*), COALESCE(SUM(numWords),0) "
                "FROM History WHERE COALESCE(isArchived,0)=0 "
                "GROUP BY d ORDER BY d DESC LIMIT 60"
            )
        ]

        # Streak: consecutive days (ending today or yesterday) with >=1 dictation.
        days = {r[0] for r in cur.execute(
            "SELECT DISTINCT date(timestamp) FROM History WHERE COALESCE(isArchived,0)=0")}
        streak = _compute_streak(days)

        # Top apps by dictation count.
        top_apps = [
            {"app": a or "Unknown", "dictations": int(n), "words": int(w or 0)}
            for a, n, w in cur.execute(
                "SELECT COALESCE(NULLIF(app,''),'Unknown'), COUNT(*), COALESCE(SUM(numWords),0) "
                "FROM History WHERE COALESCE(isArchived,0)=0 "
                "GROUP BY 1 ORDER BY 2 DESC LIMIT 8"
            )
        ]

        # Words corrected (auto-cleanup value) if the column has data.
        try:
            corrected = cur.execute(
                "SELECT COALESCE(SUM(numWordsCorrected),0) FROM History "
                "WHERE COALESCE(isArchived,0)=0").fetchone()[0]
            corrected = int(corrected or 0)
        except sqlite3.Error:
            corrected = 0

        recent = [
            {
                "timestamp": ts,
                "words": int(w or 0),
                "app": a or "Unknown",
                "text": (t or "")[:140],
            }
            for ts, w, a, t in cur.execute(
                "SELECT timestamp, numWords, app, COALESCE(formattedText, asrText) "
                "FROM History WHERE COALESCE(isArchived,0)=0 "
                "ORDER BY timestamp DESC LIMIT 20"
            )
        ]

        first, last = cur.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM History WHERE COALESCE(isArchived,0)=0"
        ).fetchone()

        return {
            "available": True,
            "source": "flow.sqlite (local)",
            "total_dictations": int(total_rows or 0),
            "total_words": total_words,
            "total_speech_seconds": round(total_speech, 1),
            "avg_wpm": avg_wpm,
            "streak_days": streak,
            "words_corrected": corrected,
            "by_day": by_day,
            "top_apps": top_apps,
            "recent": recent,
            "first_dictation": first,
            "last_dictation": last,
        }
    except sqlite3.Error as e:
        return {"available": False, "reason": f"query failed: {e}"}
    finally:
        con.close()


def _compute_streak(days: set[str]) -> int:
    """Consecutive-day streak ending today or yesterday (UTC date strings)."""
    import datetime as _dt

    if not days:
        return 0
    today = _dt.date.today()
    # Start from today if active today, else yesterday (still "current" streak).
    start = today if today.isoformat() in days else today - _dt.timedelta(days=1)
    if start.isoformat() not in days:
        return 0
    streak = 0
    d = start
    while d.isoformat() in days:
        streak += 1
        d -= _dt.timedelta(days=1)
    return streak


if __name__ == "__main__":
    import json

    print(json.dumps(compute_insights(), indent=2)[:2000])
