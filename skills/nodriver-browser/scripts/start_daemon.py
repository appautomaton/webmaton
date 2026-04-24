#!/usr/bin/env python3
"""Explicitly start the nodriver daemon. Idempotent: no-op if already running."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from runner import ensure_daemon, is_daemon_alive, PORT, PID_FILE  # noqa: E402


def main() -> int:
    was_alive = is_daemon_alive()
    try:
        pid = ensure_daemon()
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2))
        return 1
    print(json.dumps({
        "ok": True,
        "pid": pid,
        "port": PORT,
        "already_running": was_alive,
        "pid_file": str(PID_FILE),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
