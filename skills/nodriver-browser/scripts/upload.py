#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = ["nodriver"]
# ///
"""
Set files on a <input type="file"> element by ref. Usage: upload.py REF FILE [FILE...]

The ref must point to an <input type="file"> from the latest snapshot.
Files must be absolute paths to existing local files.
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
    if len(args) < 2:
        print('{"error": "usage: upload.py [--headed|--headless] REF FILE [FILE...]"}')
        return 2
    ref = args[0]
    files = [str(Path(f).resolve()) for f in args[1:]]

    # Validate files exist.
    for f in files:
        if not Path(f).is_file():
            print(json.dumps({"error": f"file not found: {f}"}, indent=2))
            return 1

    if not REFS_FILE.exists():
        print(json.dumps({"error": "no snapshot yet — run snapshot.py first"}, indent=2))
        return 1

    refs = json.loads(REFS_FILE.read_text())
    selector = refs.get(ref)
    if not selector:
        print(json.dumps({"error": f"ref {ref!r} not in last snapshot"}, indent=2))
        return 1

    browser = await attach(mode=mode)
    tab = await get_persistent_tab(browser)

    # Get a JS remote object id for the element.
    resp = await tab.send(
        __import__("nodriver").cdp.runtime.evaluate(
            expression=f"document.querySelector({json.dumps(selector)})",
            return_by_value=False,
        )
    )
    remote_obj = resp[0] if isinstance(resp, tuple) else resp
    if not remote_obj or not remote_obj.object_id:
        await output({"error": f"ref {ref} no longer in DOM", "hint": "re-run snapshot.py"}, browser=browser)
        return 1

    # Verify it's a file input.
    is_file_input = await js(tab, f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            return el && el.tagName === 'INPUT' && el.type === 'file';
        }})()
    """)
    if not is_file_input:
        await output({"error": f"ref {ref} is not an <input type='file'>", "selector": selector}, browser=browser)
        return 1

    # Set files via CDP.
    import nodriver.cdp.dom as cdp_dom
    await tab.send(cdp_dom.set_file_input_files(files=files, object_id=remote_obj.object_id))

    # Dispatch change event so frameworks pick it up.
    await js(tab, f"document.querySelector({json.dumps(selector)}).dispatchEvent(new Event('change', {{bubbles: true}}))")

    await output({"ref": ref, "files": files, "count": len(files)}, browser=browser)
    return 0


if __name__ == "__main__":
    import nodriver as uc
    uc.loop().run_until_complete(main())
