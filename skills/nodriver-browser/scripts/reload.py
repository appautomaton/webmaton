#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["nodriver"]
# ///
"""Reload the persistent tab."""
import os
import sys
from pathlib import Path

os.environ.setdefault("UV_LINK_MODE", "copy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from runner import attach, get_persistent_tab, js, output  # noqa: E402


async def main() -> int:
    browser = await attach()
    tab = await get_persistent_tab(browser)
    await js(tab, "(location.reload(), true)")
    await tab.wait(1.5)
    state = await js(tab, "({url: location.href, title: document.title, ready_state: document.readyState})")
    await output({"action": "reload", **state}, browser=browser)
    return 0


if __name__ == "__main__":
    import nodriver as uc
    uc.loop().run_until_complete(main())
