#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["nodriver"]
# ///
"""List every open tab in the daemon (index, url, title, target_id)."""
import os
import sys
from pathlib import Path

os.environ.setdefault("UV_LINK_MODE", "copy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from runner import attach, list_tabs, output  # noqa: E402


async def main() -> int:
    browser = await attach()
    tabs = await list_tabs(browser)
    await output({"tabs": tabs}, browser=browser)
    return 0


if __name__ == "__main__":
    import nodriver as uc
    uc.loop().run_until_complete(main())
