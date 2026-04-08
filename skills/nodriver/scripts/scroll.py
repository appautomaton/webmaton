#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["nodriver"]
# ///
"""
Scroll the persistent tab.

Usage:  scroll.py up        — one viewport up
        scroll.py down      — one viewport down
        scroll.py top       — to page top
        scroll.py bottom    — to page bottom
        scroll.py 500       — by 500 pixels (positive = down, negative = up)
"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("UV_LINK_MODE", "copy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from runner import attach, get_persistent_tab, js, output  # noqa: E402


async def main() -> int:
    if len(sys.argv) < 2:
        print('{"error": "usage: scroll.py up|down|top|bottom|N"}')
        return 2
    arg = sys.argv[1]

    browser = await attach()
    tab = await get_persistent_tab(browser)

    if arg == "up":
        expr = "window.scrollBy(0, -window.innerHeight * 0.9)"
    elif arg == "down":
        expr = "window.scrollBy(0, window.innerHeight * 0.9)"
    elif arg == "top":
        expr = "window.scrollTo(0, 0)"
    elif arg == "bottom":
        expr = "window.scrollTo(0, document.body.scrollHeight)"
    else:
        try:
            n = int(arg)
        except ValueError:
            print(json.dumps({"error": f"bad arg {arg!r}"}, indent=2))
            return 2
        expr = f"window.scrollBy(0, {n})"

    await js(tab, f"({expr}, true)")
    await tab.wait(0.3)
    state = await js(tab, """
        ({
            scroll: window.scrollY,
            max_scroll: document.body.scrollHeight - innerHeight,
            at_top: window.scrollY === 0,
            at_bottom: (window.innerHeight + window.scrollY) >= document.body.scrollHeight - 1
        })
    """)
    await output({"action": arg, **state}, browser=browser)
    return 0


if __name__ == "__main__":
    import nodriver as uc
    uc.loop().run_until_complete(main())
