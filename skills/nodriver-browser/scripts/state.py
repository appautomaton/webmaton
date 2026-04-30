#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = ["nodriver"]
# ///
"""Cheap status read of the persistent tab. No navigation, no DOM mutation."""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("UV_LINK_MODE", "copy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from runner import attach, get_persistent_tab, js, output, pop_launch_mode  # noqa: E402


async def main() -> int:
    try:
        mode, args = pop_launch_mode(sys.argv[1:])
    except ValueError as e:
        print(json.dumps({"error": str(e)}, indent=2))
        return 2
    if args:
        print(json.dumps({"error": "usage: state.py [--headed|--headless]"}, indent=2))
        return 2

    browser = await attach(mode=mode)
    tab = await get_persistent_tab(browser)
    state = await js(tab, """
        ({
            url: location.href,
            title: document.title,
            ready_state: document.readyState,
            scroll: window.scrollY,
            text_len: (document.body && document.body.innerText || '').length,
            viewport: { w: innerWidth, h: innerHeight }
        })
    """)
    await output(state, browser=browser)
    return 0


if __name__ == "__main__":
    import nodriver as uc
    uc.loop().run_until_complete(main())
