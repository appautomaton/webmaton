#!/usr/bin/env python3
"""Stop the nodriver daemon. Cleans state files and stale singleton locks."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from runner import stop_daemon  # noqa: E402


def main() -> int:
    try:
        stopped = stop_daemon()
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2))
        return 1
    print(json.dumps({"ok": True, "stopped": stopped}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
