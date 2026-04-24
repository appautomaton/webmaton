"""Disk-backed session cache for agentic-search.

Stores search sessions as individual JSON files in the system temp directory,
under `agentic-search/sessions/`. Mirrors the LRU semantics of upstream
GrokSearch's in-memory `SourcesCache` (sources.py:32-51) — 256 sessions max,
oldest evicted by mtime when the cap is exceeded.

Pure stdlib. No locks (each session_id is unique; concurrent rewrites of the
same session are rare and tolerated by atomic write-then-rename). No TTL —
size-based eviction only, matching upstream.

Public surface:
    new_session_id() -> str
    session_dir() -> Path
    write_session(session_id, data) -> Path
    read_session(session_id) -> dict | None
    list_sessions() -> list[dict]
    prune_sessions(max_count=256) -> int
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional

_DIR_NAME = "agentic-search"
_SUBDIR_NAME = "sessions"
_DEFAULT_MAX = 256


def new_session_id() -> str:
    """12-char hex session id. Matches upstream sources.py:28-29 exactly."""
    return uuid.uuid4().hex[:12]


def session_dir() -> Path:
    """Return (and create if missing) the disk session cache directory.

    Path: tempfile.gettempdir() / agentic-search / sessions /
    On macOS this is typically /var/folders/.../T/agentic-search/sessions/.
    On Linux: /tmp/agentic-search/sessions/.
    """
    base = Path(tempfile.gettempdir()) / _DIR_NAME / _SUBDIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def _session_path(session_id: str) -> Path:
    return session_dir() / f"{session_id}.json"


def write_session(session_id: str, data: dict) -> Path:
    """Atomically write session JSON to disk and return its path.

    Uses write-to-temp + os.replace for atomicity, so a crashed write never
    leaves a partial file. Existing sessions with the same id are overwritten.
    """
    path = _session_path(session_id)
    tmp = path.with_suffix(".json.tmp")
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)
    return path


def read_session(session_id: str) -> Optional[dict]:
    """Return the session dict or None if not found / unreadable."""
    path = _session_path(session_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def list_sessions() -> list[dict]:
    """Return a list of session diagnostics dicts, most-recent first.

    Each entry: {session_id, mtime, query?, model?, sources_count?}.
    Best-effort: corrupted sessions are listed with only the session_id and
    mtime; their query/model/sources_count fields are omitted.
    """
    base = session_dir()
    entries = []
    for path in base.glob("*.json"):
        if path.suffix.endswith(".tmp"):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        entry: dict = {
            "session_id": path.stem,
            "mtime": stat.st_mtime,
        }
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                if "query" in data:
                    entry["query"] = data["query"]
                if "model" in data:
                    entry["model"] = data["model"]
                if "sources" in data and isinstance(data["sources"], list):
                    entry["sources_count"] = len(data["sources"])
                if "created_at" in data:
                    entry["created_at"] = data["created_at"]
        except (OSError, json.JSONDecodeError):
            pass
        entries.append(entry)
    entries.sort(key=lambda e: e["mtime"], reverse=True)
    return entries


def prune_sessions(max_count: int = _DEFAULT_MAX) -> int:
    """Evict oldest sessions (by mtime) so at most `max_count` remain.

    Returns the number of sessions deleted. Mirrors upstream's LRU eviction
    in sources.py:42-43 (`while len(self._cache) > self._max_size:
    self._cache.popitem(last=False)`), adapted to disk via mtime ordering.
    """
    base = session_dir()
    paths = []
    for path in base.glob("*.json"):
        if path.suffix.endswith(".tmp"):
            continue
        try:
            paths.append((path, path.stat().st_mtime))
        except OSError:
            continue
    if len(paths) <= max_count:
        return 0
    # Oldest first
    paths.sort(key=lambda p: p[1])
    to_delete = paths[: len(paths) - max_count]
    deleted = 0
    for path, _ in to_delete:
        try:
            path.unlink()
            deleted += 1
        except OSError:
            continue
    return deleted
