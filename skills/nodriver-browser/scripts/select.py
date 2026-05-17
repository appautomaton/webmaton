#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = ["nodriver"]
# ///
"""
Select an option from a <select> dropdown by ref. Usage:

    select.py REF "visible text or value"
    select.py REF --index N

Matches by option.value first, then option.textContent (case-insensitive trim).
Dispatches input + change events so frameworks notice.
"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("UV_LINK_MODE", "copy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from runner import attach, get_persistent_tab, js, output, pop_launch_mode, REFS_FILE  # noqa: E402


SELECT_JS = r"""
(sel, match, byIndex) => {
    const el = document.querySelector(sel);
    if (!el) return { ok: false, error: 'not found' };
    if (el.tagName !== 'SELECT') return { ok: false, error: 'not a <select> element' };
    const opts = Array.from(el.options);
    let idx = -1;
    if (byIndex !== null) {
        idx = byIndex;
    } else {
        idx = opts.findIndex(o => o.value === match);
        if (idx < 0) idx = opts.findIndex(o => o.textContent.trim().toLowerCase() === match.toLowerCase());
    }
    if (idx < 0 || idx >= opts.length) {
        return { ok: false, error: 'no matching option', available: opts.slice(0, 20).map(o => ({ value: o.value, text: o.textContent.trim() })) };
    }
    const proto = Object.getPrototypeOf(el);
    const setter = Object.getOwnPropertyDescriptor(proto, 'selectedIndex')?.set;
    if (setter) setter.call(el, idx); else el.selectedIndex = idx;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return { ok: true, selected_value: opts[idx].value, selected_text: opts[idx].textContent.trim(), index: idx };
}
"""


async def main() -> int:
    try:
        mode, args = pop_launch_mode(sys.argv[1:])
    except ValueError as e:
        print(json.dumps({"error": str(e)}, indent=2))
        return 2
    if len(args) < 2:
        print('{"error": "usage: select.py [--headed|--headless] REF VALUE  or  REF --index N"}')
        return 2

    ref = args[0]
    by_index = None
    match = None
    if args[1] == "--index":
        if len(args) < 3:
            print('{"error": "--index requires a number"}')
            return 2
        by_index = int(args[2])
    else:
        match = args[1]

    if not REFS_FILE.exists():
        print(json.dumps({"error": "no snapshot yet — run snapshot.py first"}))
        return 1
    refs = json.loads(REFS_FILE.read_text())
    selector = refs.get(ref)
    if not selector:
        print(json.dumps({"error": f"ref {ref!r} not in last snapshot"}))
        return 1

    browser = await attach(mode=mode)
    tab = await get_persistent_tab(browser)

    expr = f"({SELECT_JS})({json.dumps(selector)}, {json.dumps(match)}, {json.dumps(by_index)})"
    result = await js(tab, expr)

    await output({"ref": ref, "selector": selector, **(result or {})}, browser=browser)
    return 0 if (result and result.get("ok")) else 1


if __name__ == "__main__":
    import nodriver as uc
    uc.loop().run_until_complete(main())
