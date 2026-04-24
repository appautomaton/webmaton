#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "httpx>=0.28.0",
#   "tenacity>=8.0.0",
# ]
# ///
"""agentic_get_sources — retrieve cached sessions from disk.

Simple wrapper around `_session.read_session` and `_session.list_sessions`.
Use it to:

- Retrieve a full session (content, sources, fetched_pages, etc.) from a prior
  `agentic_search` call by its `session_id`.
- List recent sessions for diagnostics / picking which one to rerank or extend.

CLI:
    # Retrieve a single session
    python agentic_get_sources.py --session-id abc123def456

    # List all cached sessions, most-recent first
    python agentic_get_sources.py --list

Output: JSON to stdout. On failure, prints `{"error": ...}` to stderr and
exits 1.

The v2 session cache replaces upstream GrokSearch's in-memory SourcesCache
(sources.py:32-51) with a disk-backed equivalent in the system temp dir. LRU
eviction is by file mtime, capped at 256 sessions (matching upstream).

See ../references/provider-quirks.md for the session cache schema and
storage path.
"""

from __future__ import annotations

import argparse
import json
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from _session import list_sessions, read_session, session_dir  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="agentic_get_sources — retrieve a cached session or list recent sessions."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--session-id",
        default="",
        help="Session id returned by a previous agentic_search call.",
    )
    group.add_argument(
        "--list",
        action="store_true",
        help="List recent sessions (most recent first) with diagnostic metadata.",
    )
    args = parser.parse_args()

    if args.list:
        sessions = list_sessions()
        print(
            json.dumps(
                {"cache_dir": str(session_dir()), "count": len(sessions), "sessions": sessions},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    session = read_session(args.session_id)
    if session is None:
        print(
            json.dumps({"error": f"session {args.session_id} not found or expired"}),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(session, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
