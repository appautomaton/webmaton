#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["nodriver"]
# ///
"""
Type text into an input/textarea/contenteditable by ref. Usage: type.py REF TEXT

The field is cleared first, then the text is set, then `input` and `change`
events are dispatched so frameworks (React/Vue/etc.) notice. For
contenteditable elements, innerText is set instead of value.

Use press.py for individual key events (Enter, Tab, ...).
"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("UV_LINK_MODE", "copy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from runner import attach, get_persistent_tab, js, output, REFS_FILE  # noqa: E402


TYPE_JS = r"""
(sel, text) => {
    const el = document.querySelector(sel);
    if (!el) return { ok: false, error: 'not found' };
    el.focus();
    if (el.isContentEditable) {
        el.innerText = text;
        el.dispatchEvent(new InputEvent('input', { bubbles: true }));
        return { ok: true, kind: 'contenteditable', value: el.innerText };
    }
    if ('value' in el) {
        // Use the prototype setter so React's synthetic event system sees it.
        const proto = Object.getPrototypeOf(el);
        const setter = Object.getOwnPropertyDescriptor(proto, 'value') &&
                       Object.getOwnPropertyDescriptor(proto, 'value').set;
        if (setter) setter.call(el, text); else el.value = text;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return { ok: true, kind: el.tagName.toLowerCase(), value: el.value };
    }
    return { ok: false, error: 'element has no value or contenteditable' };
}
"""


async def main() -> int:
    if len(sys.argv) < 3:
        print('{"error": "usage: type.py REF TEXT"}')
        return 2
    ref, text = sys.argv[1], sys.argv[2]

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
    # Inject the helper, then call it. We can't pass arguments to evaluate()
    # cleanly, so we inline both via JSON-encoded literals.
    expr = f"({TYPE_JS})({json.dumps(selector)}, {json.dumps(text)})"
    result = await js(tab, expr)

    await output({"ref": ref, "selector": selector, **(result or {})},
                 browser=browser)
    return 0 if (result and result.get("ok")) else 1


if __name__ == "__main__":
    import nodriver as uc
    uc.loop().run_until_complete(main())
