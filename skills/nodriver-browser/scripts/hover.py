#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = ["nodriver"]
# ///
"""
Hover over an element by ref. Usage: hover.py REF

Moves the mouse to the element's center via CDP Input.dispatchMouseEvent,
triggering CSS :hover and dispatching mouseover/mouseenter JS events.
Useful for revealing dropdown menus, tooltips, and hover-dependent UI.
"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("UV_LINK_MODE", "copy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from runner import attach, get_persistent_tab, js, output, pop_launch_mode, REFS_FILE  # noqa: E402


async def main() -> int:
    try:
        mode, args = pop_launch_mode(sys.argv[1:])
    except ValueError as e:
        print(json.dumps({"error": str(e)}, indent=2))
        return 2
    if len(args) < 1:
        print('{"error": "usage: hover.py [--headed|--headless] REF"}')
        return 2
    ref = args[0]

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

    # Get bounding box center.
    bbox = await js(tab, f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {{ x: r.x + r.width / 2, y: r.y + r.height / 2 }};
        }})()
    """)
    if not bbox:
        await output({"error": f"ref {ref} no longer in DOM", "hint": "re-run snapshot.py"}, browser=browser)
        return 1

    cx, cy = bbox["x"], bbox["y"]

    # CDP mouse move — triggers CSS :hover.
    import nodriver.cdp.input_ as cdp_input
    await tab.send(cdp_input.dispatch_mouse_event(type_="mouseMoved", x=cx, y=cy))

    # JS events for frameworks listening on mouseover/mouseenter.
    await js(tab, f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            el.dispatchEvent(new MouseEvent('mouseover', {{bubbles: true, clientX: {cx}, clientY: {cy}}}));
            el.dispatchEvent(new MouseEvent('mouseenter', {{bubbles: false, clientX: {cx}, clientY: {cy}}}));
        }})()
    """)

    await tab.wait(0.3)

    await output({"ref": ref, "selector": selector, "position": {"x": cx, "y": cy}}, browser=browser)
    return 0


if __name__ == "__main__":
    import nodriver as uc
    uc.loop().run_until_complete(main())
