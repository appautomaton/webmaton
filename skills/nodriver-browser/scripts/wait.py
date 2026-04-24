#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["nodriver"]
# ///
"""
Block up to TIMEOUT seconds for an element (CSS selector) or text to appear.

Usage:  wait.py "#login-button"             — wait for selector
        wait.py "Welcome back" --text       — wait for substring in body text
        wait.py "#foo" --timeout 60         — custom timeout (default 30s)

Returns when the condition is met OR when the timeout expires.
"""
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("UV_LINK_MODE", "copy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from runner import attach, get_persistent_tab, js, output  # noqa: E402


async def main() -> int:
    args = sys.argv[1:]
    if not args:
        print('{"error": "usage: wait.py SELECTOR_OR_TEXT [--text] [--timeout N]"}')
        return 2

    is_text = "--text" in args
    timeout = 30
    if "--timeout" in args:
        i = args.index("--timeout")
        try:
            timeout = int(args[i + 1])
        except (IndexError, ValueError):
            print('{"error": "bad --timeout value"}')
            return 2
        args = args[:i] + args[i + 2:]
    args = [a for a in args if a != "--text"]
    needle = args[0]

    browser = await attach()
    tab = await get_persistent_tab(browser)

    if is_text:
        check_expr = (
            f"document.body.innerText.indexOf({json.dumps(needle)}) !== -1"
        )
    else:
        check_expr = f"!!document.querySelector({json.dumps(needle)})"

    start = time.monotonic()
    deadline = start + timeout
    found = False
    while time.monotonic() < deadline:
        if await js(tab, check_expr):
            found = True
            break
        await tab.wait(0.25)

    elapsed = round(time.monotonic() - start, 2)
    await output({
        "needle": needle,
        "kind": "text" if is_text else "selector",
        "found": found,
        "elapsed_s": elapsed,
        "timeout_s": timeout,
    }, browser=browser)
    return 0 if found else 1


if __name__ == "__main__":
    import nodriver as uc
    uc.loop().run_until_complete(main())
