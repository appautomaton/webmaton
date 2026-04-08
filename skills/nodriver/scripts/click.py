#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["nodriver"]
# ///
"""
Click an element by ref id from the latest snapshot. Usage: click.py r17

Refs come from snapshot.py. They expire when the page navigates or the SPA
re-renders the relevant subtree — re-snapshot if click fails with "not found".
"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("UV_LINK_MODE", "copy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from runner import attach, get_persistent_tab, js, output, REFS_FILE  # noqa: E402


async def main() -> int:
    if len(sys.argv) < 2:
        print('{"error": "usage: click.py REF"}')
        return 2
    ref = sys.argv[1]

    if not REFS_FILE.exists():
        print(json.dumps({
            "error": "no snapshot yet — run snapshot.py first",
            "refs_file": str(REFS_FILE),
        }, indent=2))
        return 1

    refs = json.loads(REFS_FILE.read_text())
    selector = refs.get(ref)
    if not selector:
        print(json.dumps({
            "error": f"ref {ref!r} not in last snapshot",
            "available_refs": list(refs.keys())[:20],
        }, indent=2))
        return 1

    browser = await attach()
    tab = await get_persistent_tab(browser)

    # Check the element still exists, then click it.
    found = await js(tab, f"!!document.querySelector({json.dumps(selector)})")
    if not found:
        await output({
            "error": f"ref {ref} no longer in DOM (page may have re-rendered)",
            "selector": selector,
            "hint": "re-run snapshot.py and try again",
        }, browser=browser)
        return 1

    # Capture pre-click state for the report.
    before = await js(tab, """
        ({ url: location.href, title: document.title })
    """)

    await js(tab, f"document.querySelector({json.dumps(selector)}).click()")
    # Wait for any navigation/transition.
    await tab.wait(1.5)

    after = await js(tab, """
        ({ url: location.href, title: document.title })
    """)

    await output({
        "ref": ref,
        "selector": selector,
        "before": before,
        "after": after,
        "navigated": before["url"] != after["url"],
    }, browser=browser)
    return 0


if __name__ == "__main__":
    import nodriver as uc
    uc.loop().run_until_complete(main())
