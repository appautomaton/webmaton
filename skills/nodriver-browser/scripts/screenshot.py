#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["nodriver"]
# ///
"""
Capture a PNG of the persistent tab.

Usage:  screenshot.py                       — saves to /tmp/nodriver-skill/last.png
        screenshot.py /path/to/out.png      — custom path
        screenshot.py --full /tmp/full.png  — full scrollable page (not just viewport)
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("UV_LINK_MODE", "copy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from runner import attach, get_persistent_tab, output, STATE_DIR  # noqa: E402


async def main() -> int:
    args = sys.argv[1:]
    full_page = "--full" in args
    args = [a for a in args if a != "--full"]
    out_path = Path(args[0]) if args else (STATE_DIR / "last.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    browser = await attach()
    tab = await get_persistent_tab(browser)

    # nodriver's save_screenshot returns the path it actually used
    saved = await tab.save_screenshot(filename=str(out_path), full_page=full_page)
    saved_path = Path(saved if saved else out_path)
    size = saved_path.stat().st_size if saved_path.exists() else 0

    await output({
        "path": str(saved_path),
        "size_bytes": size,
        "full_page": full_page,
    }, browser=browser)
    return 0


if __name__ == "__main__":
    import nodriver as uc
    uc.loop().run_until_complete(main())
