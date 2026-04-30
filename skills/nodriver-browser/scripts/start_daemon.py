#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = []
# ///
"""Explicitly start the nodriver daemon. Usage: start_daemon.py [BROWSER_OPTIONS]"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from runner import (  # noqa: E402
    ensure_daemon, is_daemon_alive, pop_launch_mode, running_launch_mode,
    running_profile, running_no_sandbox, default_launch_mode, launch_profile,
    launch_no_sandbox, PORT, PID_FILE,
)


def main() -> int:
    try:
        mode, args = pop_launch_mode(sys.argv[1:])
    except ValueError as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2))
        return 2
    if args:
        print(json.dumps({
            "ok": False,
            "error": "usage: start_daemon.py [BROWSER_OPTIONS]",
        }, indent=2))
        return 2

    was_alive = is_daemon_alive()
    try:
        pid = ensure_daemon(mode=mode)
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2))
        return 1
    no_sandbox = running_no_sandbox()
    print(json.dumps({
        "ok": True,
        "pid": pid,
        "port": PORT,
        "mode": running_launch_mode() or mode or default_launch_mode(),
        "profile": running_profile() or launch_profile(),
        "no_sandbox": no_sandbox if no_sandbox is not None else launch_no_sandbox(),
        "already_running": was_alive,
        "pid_file": str(PID_FILE),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
