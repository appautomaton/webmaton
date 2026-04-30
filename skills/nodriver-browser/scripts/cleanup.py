#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = ["nodriver"]
# ///
"""
Close every tab except the persistent one (index 0). The "reset stray tabs"
button — run this when state.py shows tabs_open > 1 with a warning.
"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("UV_LINK_MODE", "copy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from runner import attach, cleanup_extra_tabs, output, pop_launch_mode  # noqa: E402


async def main() -> int:
    try:
        mode, args = pop_launch_mode(sys.argv[1:])
    except ValueError as e:
        print(json.dumps({"error": str(e)}, indent=2))
        return 2
    if args:
        print(json.dumps({"error": "usage: cleanup.py [--headed|--headless]"}, indent=2))
        return 2

    browser = await attach(mode=mode)
    closed = await cleanup_extra_tabs(browser)
    await output({"closed": closed}, browser=browser)
    return 0


if __name__ == "__main__":
    import nodriver as uc
    uc.loop().run_until_complete(main())
