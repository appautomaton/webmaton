#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["nodriver"]
# ///
"""
Close every tab except the persistent one (index 0). The "reset stray tabs"
button — run this when state.py shows tabs_open > 1 with a warning.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("UV_LINK_MODE", "copy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from runner import attach, cleanup_extra_tabs, output  # noqa: E402


async def main() -> int:
    browser = await attach()
    closed = await cleanup_extra_tabs(browser)
    await output({"closed": closed}, browser=browser)
    return 0


if __name__ == "__main__":
    import nodriver as uc
    uc.loop().run_until_complete(main())
