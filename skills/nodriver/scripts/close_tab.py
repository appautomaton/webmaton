#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["nodriver"]
# ///
"""
Close a single tab by its 0-indexed position. Refuses to close index 0
(the persistent tab) — use stop_daemon.py for a full reset instead.

Usage: close_tab.py 2
"""
import asyncio
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("UV_LINK_MODE", "copy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from runner import (  # noqa: E402
    attach, _refresh_targets, _page_tabs, _persistent_target_id, output,
)


async def main() -> int:
    if len(sys.argv) < 2:
        print('{"error": "usage: close_tab.py INDEX"}')
        return 2
    try:
        index = int(sys.argv[1])
    except ValueError:
        print('{"error": "INDEX must be an integer"}')
        return 2

    browser = await attach()
    await _refresh_targets(browser)
    tabs = _page_tabs(browser)
    if index < 0 or index >= len(tabs):
        await output({
            "error": f"index {index} out of range (have {len(tabs)} tabs)",
            "valid_range": [0, len(tabs) - 1] if tabs else [],
        }, browser=browser)
        return 1

    target = tabs[index]
    target_id = getattr(target, "target_id", None)
    pinned = _persistent_target_id()
    if target_id == pinned:
        await output({
            "error": f"refusing to close the persistent tab (target_id={target_id}). "
                     f"Use stop_daemon.py to reset everything.",
            "index": index,
        }, browser=browser)
        return 1

    closed_url = getattr(target, "url", None)
    try:
        await target.close()
    except Exception as e:
        await output({"error": f"close failed: {e}"}, browser=browser)
        return 1

    # Wait for nodriver to receive Target.targetDestroyed before tab_count.
    await asyncio.sleep(0.25)
    await output({
        "closed_index": index,
        "closed_url": closed_url,
        "closed_target_id": target_id,
    }, browser=browser)
    return 0


if __name__ == "__main__":
    import nodriver as uc
    uc.loop().run_until_complete(main())
