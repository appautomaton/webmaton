#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = ["nodriver"]
# ///
"""
Run arbitrary JS in the persistent tab. Escape hatch.

Usage:  eval.py 'document.title'
        eval.py 'document.querySelectorAll("a").length'
        eval.py 'JSON.stringify(Object.keys(window))'

The expression should be a single JS expression, not statements. Wrap
multi-statement code in an IIFE: '(() => { ...; return value; })()'
"""
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
    if len(args) < 1:
        print('{"error": "usage: eval.py [--headed|--headless] JS_EXPRESSION"}')
        return 2
    expr = args[0]

    browser = await attach(mode=mode)
    tab = await get_persistent_tab(browser)
    try:
        result = await js(tab, expr)
        await output({"result": result}, browser=browser)
    except Exception as e:
        await output({"error": str(e), "type": type(e).__name__}, browser=browser)
        return 1
    return 0


if __name__ == "__main__":
    import nodriver as uc
    uc.loop().run_until_complete(main())
