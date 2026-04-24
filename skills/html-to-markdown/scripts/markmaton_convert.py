#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "markmaton",
# ]
# ///

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from markmaton import ConvertOptions, ConvertRequest, convert_html


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="html-to-markdown")
    parser.add_argument("--html-file", type=Path, help="Path to an HTML file")
    parser.add_argument("--url", help="Source URL used as parsing context")
    parser.add_argument("--final-url", help="Final URL after redirects")
    parser.add_argument("--content-type", help="Optional content type hint")
    parser.add_argument(
        "--from-capture",
        action="store_true",
        help="Read a capture JSON envelope from stdin instead of raw HTML",
    )
    parser.add_argument(
        "--output-format",
        choices=("json", "markdown"),
        default="json",
        help="Choose between full JSON output or markdown only",
    )
    parser.add_argument(
        "--full-content",
        action="store_true",
        help="Disable main-content-only cleaning",
    )
    parser.add_argument(
        "--include-selector",
        action="append",
        default=[],
        help="CSS selector to force-include before conversion",
    )
    parser.add_argument(
        "--exclude-selector",
        action="append",
        default=[],
        help="CSS selector to remove before conversion",
    )
    return parser


def _read_capture_envelope(
    args: argparse.Namespace,
) -> tuple[str, str | None, str | None, str | None]:
    """Read a capture JSON envelope from stdin. CLI flags override envelope values."""
    envelope = json.loads(sys.stdin.read())
    html = envelope.get("html", "")
    url = args.url or envelope.get("url")
    final_url = args.final_url or envelope.get("final_url")
    content_type = args.content_type or envelope.get("content_type")
    return html, url, final_url, content_type


def _read_html(path: Path | None) -> str:
    if path is None:
        return sys.stdin.read()
    return path.read_text(encoding="utf-8")


def main(
    argv: list[str] | None = None,
    *,
    stdout: Any | None = None,
    stderr: Any | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    try:
        if args.from_capture:
            html, url, final_url, content_type = _read_capture_envelope(args)
        else:
            html = _read_html(args.html_file)
            url = args.url
            final_url = args.final_url
            content_type = args.content_type

        response = convert_html(
            ConvertRequest(
                html=html,
                url=url,
                final_url=final_url,
                content_type=content_type,
                options=ConvertOptions(
                    only_main_content=not args.full_content,
                    include_selectors=list(args.include_selector),
                    exclude_selectors=list(args.exclude_selector),
                ),
            )
        )
    except Exception as exc:
        stderr.write(f"conversion failed: {exc}\n")
        return 1

    if args.output_format == "markdown":
        stdout.write(response.markdown)
        if response.markdown and not response.markdown.endswith("\n"):
            stdout.write("\n")
        return 0

    stdout.write(
        json.dumps(
            {
                "markdown": response.markdown,
                "html_clean": response.html_clean,
                "metadata": response.metadata.__dict__,
                "links": response.links,
                "images": response.images,
                "quality": response.quality.__dict__,
            },
            ensure_ascii=False,
        )
    )
    stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
