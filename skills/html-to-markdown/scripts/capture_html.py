#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "nodriver",
# ]
# ///

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Callable


def _playwright_candidates(version_dir: Path) -> list[Path]:
    """Yield Playwright Chromium binary paths for the current platform."""
    if sys.platform == "darwin":
        # Apple Silicon then Intel
        return [
            version_dir / "chrome-mac-arm64" / "Chromium.app" / "Contents" / "MacOS" / "Chromium",
            version_dir / "chrome-mac" / "Chromium.app" / "Contents" / "MacOS" / "Chromium",
        ]
    if os.name == "nt":
        return [version_dir / "chrome-win" / "chrome.exe"]
    # Linux: new layout then old
    return [
        version_dir / "chrome-linux64" / "chrome",
        version_dir / "chrome-linux" / "chrome",
    ]


def find_chrome() -> str:
    """Find Chrome or Chromium. Order: env var, user's Chrome, user's Chromium, Playwright cache."""

    # Explicit override via env var
    for var in ("CHROME_PATH", "CHROMIUM_PATH"):
        if path := os.environ.get(var):
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path

    # User's Chrome — PATH then platform-specific
    for name in ("google-chrome", "google-chrome-stable", "chrome"):
        if path := shutil.which(name):
            return path

    if sys.platform == "darwin":
        mac_chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if os.path.isfile(mac_chrome):
            return mac_chrome
    elif sys.platform == "linux":
        for p in ("/opt/google/chrome/chrome",):
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p

    # User's Chromium — PATH then platform-specific
    for name in ("chromium", "chromium-browser"):
        if path := shutil.which(name):
            return path

    if sys.platform == "darwin":
        mac_chromium = "/Applications/Chromium.app/Contents/MacOS/Chromium"
        if os.path.isfile(mac_chromium):
            return mac_chromium

    # Playwright cache — newest version first
    if os.name == "nt":
        pw_cache = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    else:
        pw_cache = Path.home() / ".cache" / "ms-playwright"
    if pw_cache.is_dir():
        for d in sorted(pw_cache.glob("chromium-*"), reverse=True):
            for binary in _playwright_candidates(d):
                if binary.is_file():
                    return str(binary)

    raise FileNotFoundError(
        "No Chrome or Chromium found. "
        "Set CHROME_PATH or CHROMIUM_PATH, install Chrome, "
        "or run: playwright install chromium"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="html-to-markdown-capture")
    parser.add_argument("url", help="URL to capture in a headless browser")
    parser.add_argument(
        "--wait-selector",
        help="CSS selector to wait for before capture",
    )
    parser.add_argument(
        "--wait-text",
        help="Visible text to wait for before capture",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Maximum seconds to wait for body and optional readiness signals",
    )
    parser.add_argument(
        "--output-format",
        choices=("json", "html"),
        default="json",
        help="Emit a JSON capture envelope or raw HTML only",
    )
    return parser


async def js(tab: Any, expr: str) -> Any:
    raw = await tab.evaluate(f"JSON.stringify({expr})")
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


async def wait_for_capture_ready(
    tab: Any,
    *,
    wait_selector: str | None,
    wait_text: str | None,
    timeout: float,
) -> None:
    body = await tab.select("body", timeout=timeout)
    if body is None:
        raise RuntimeError("timed out waiting for the page body")

    if wait_selector:
        target = await tab.select(wait_selector, timeout=timeout)
        if target is None:
            raise RuntimeError(
                f"timed out waiting for selector: {wait_selector}"
            )

    if wait_text:
        try:
            target = await tab.find(wait_text, timeout=timeout, best_match=True)
        except TypeError:
            target = await tab.find(wait_text, timeout=timeout)
        if target is None:
            raise RuntimeError(f"timed out waiting for text: {wait_text}")

    await asyncio.sleep(0.5)


async def capture_once(
    url: str,
    *,
    wait_selector: str | None,
    wait_text: str | None,
    timeout: float,
) -> dict[str, Any]:
    import nodriver as uc

    browser = None
    try:
        chrome_path = find_chrome()
        browser = await uc.start(
            headless=True,
            browser_executable_path=chrome_path,
            browser_args=["--use-mock-keychain"],
        )
        tab = await browser.get(url)
        await wait_for_capture_ready(
            tab,
            wait_selector=wait_selector,
            wait_text=wait_text,
            timeout=timeout,
        )
        html = await tab.get_content()
        page_state = await js(
            tab,
            """(() => ({
                final_url: location.href,
                title: document.title || null,
                content_type: document.contentType || null
            }))()""",
        )

        final_url = url
        title = None
        content_type = None
        if isinstance(page_state, dict):
            final_url = page_state.get("final_url") or url
            title = page_state.get("title")
            content_type = page_state.get("content_type")

        return {
            "html": html or "",
            "url": url,
            "final_url": final_url,
            "content_type": content_type,
            "title": title,
            "rendered": True,
        }
    finally:
        if browser is not None:
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    with contextlib.redirect_stderr(io.StringIO()):
                        browser.stop()
            except Exception:
                pass


def capture_page(
    url: str,
    *,
    wait_selector: str | None,
    wait_text: str | None,
    timeout: float,
) -> dict[str, Any]:
    import nodriver as uc

    return uc.loop().run_until_complete(
        capture_once(
            url,
            wait_selector=wait_selector,
            wait_text=wait_text,
            timeout=timeout,
        )
    )


def render_output(payload: dict[str, Any], output_format: str) -> str:
    if output_format == "html":
        return payload["html"]
    return json.dumps(payload, ensure_ascii=False)


def main(
    argv: list[str] | None = None,
    *,
    capture_impl: Callable[..., dict[str, Any]] | None = None,
    stdout: Any | None = None,
    stderr: Any | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    capture = capture_impl or capture_page
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    try:
        payload = capture(
            args.url,
            wait_selector=args.wait_selector,
            wait_text=args.wait_text,
            timeout=args.timeout,
        )
    except Exception as exc:
        stderr.write(f"capture failed for {args.url}: {exc}\n")
        return 1

    stdout.write(render_output(payload, args.output_format))
    if args.output_format == "html":
        if payload["html"] and not payload["html"].endswith("\n"):
            stdout.write("\n")
    else:
        stdout.write("\n")
    return 0


if __name__ == "__main__":
    _stdout = sys.stdout
    _stderr = sys.stderr
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    raise SystemExit(main(stdout=_stdout, stderr=_stderr))
