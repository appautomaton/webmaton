#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["nodriver"]
# ///
"""
Snapshot the persistent tab: page text + interactive elements with stable refs.

Writes the {ref: selector} map to /tmp/nodriver-skill/refs.json so subsequent
click.py / type.py / press.py calls can resolve refs into selectors.

Output format:
  {
    "url": "...",
    "title": "...",
    "text": "first 8000 chars of body innerText",
    "refs": [{ref: "r1", tag: "a", name: "...", href: "...", visible: true, ...}, ...],
    "tabs_open": 1
  }
"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("UV_LINK_MODE", "copy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from runner import attach, get_persistent_tab, output, REFS_FILE, STATE_DIR  # noqa: E402
from snapshot import take_snapshot, build_selector_map  # noqa: E402


async def main() -> int:
    browser = await attach()
    tab = await get_persistent_tab(browser)
    snap = await take_snapshot(tab)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    REFS_FILE.write_text(json.dumps(build_selector_map(snap)))

    await output(snap, browser=browser)
    return 0


if __name__ == "__main__":
    import nodriver as uc
    uc.loop().run_until_complete(main())
