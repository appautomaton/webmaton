#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["nodriver"]
# ///
"""
Send a keyboard key event to the focused element (or the page).

Usage:  press.py Enter
        press.py Tab
        press.py Escape
        press.py ArrowDown
        press.py r17 Enter      # focus REF first, then press

Common keys: Enter, Tab, Escape, Backspace, Delete, ArrowUp/Down/Left/Right,
PageUp, PageDown, Home, End. Single characters also work: press.py "a".
"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("UV_LINK_MODE", "copy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from runner import attach, get_persistent_tab, js, output, REFS_FILE  # noqa: E402


KEY_JS = r"""
(sel, key) => {
    let target = document.activeElement || document.body;
    if (sel) {
        const el = document.querySelector(sel);
        if (!el) return { ok: false, error: 'ref not found' };
        el.focus();
        target = el;
    }
    // Map name → KeyboardEvent code
    const codeMap = {
        Enter: 'Enter', Tab: 'Tab', Escape: 'Escape', Backspace: 'Backspace',
        Delete: 'Delete', ArrowUp: 'ArrowUp', ArrowDown: 'ArrowDown',
        ArrowLeft: 'ArrowLeft', ArrowRight: 'ArrowRight',
        PageUp: 'PageUp', PageDown: 'PageDown', Home: 'Home', End: 'End',
        Space: 'Space', ' ': 'Space',
    };
    const code = codeMap[key] || (key.length === 1 ? 'Key' + key.toUpperCase() : key);
    const opts = { key, code, bubbles: true, cancelable: true };
    target.dispatchEvent(new KeyboardEvent('keydown', opts));
    target.dispatchEvent(new KeyboardEvent('keypress', opts));
    target.dispatchEvent(new KeyboardEvent('keyup', opts));
    return { ok: true, key, code, target_tag: target.tagName.toLowerCase() };
}
"""


async def main() -> int:
    if len(sys.argv) < 2:
        print('{"error": "usage: press.py KEY  OR  press.py REF KEY"}')
        return 2

    if len(sys.argv) == 2:
        ref, key = None, sys.argv[1]
        selector = None
    else:
        ref, key = sys.argv[1], sys.argv[2]
        if not REFS_FILE.exists():
            print(json.dumps({"error": "run snapshot.py first"}, indent=2))
            return 1
        refs = json.loads(REFS_FILE.read_text())
        selector = refs.get(ref)
        if not selector:
            print(json.dumps({"error": f"unknown ref {ref!r}"}, indent=2))
            return 1

    browser = await attach()
    tab = await get_persistent_tab(browser)
    expr = f"({KEY_JS})({json.dumps(selector)}, {json.dumps(key)})"
    result = await js(tab, expr)
    # Brief settle for any handler-driven navigation.
    await tab.wait(0.5)
    await output({"ref": ref, **(result or {})}, browser=browser)
    return 0


if __name__ == "__main__":
    import nodriver as uc
    uc.loop().run_until_complete(main())
