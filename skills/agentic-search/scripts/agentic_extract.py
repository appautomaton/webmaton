#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "httpx>=0.28.0",
#   "tenacity>=8.0.0",
# ]
# ///
"""agentic_extract — LLM-mediated "read this URL and give me verbatim quotes".

Ports upstream GrokSearch `GrokSearchProvider.describe_url()` (grok.py:236-257),
which is defined upstream but never wired to an MCP tool. It asks Grok to read
a URL and return exactly two labeled sections:

    Title: <page title>
    Extracts: <quote 1> | <quote 2> | ... (2-4 verbatim fragments)

The LLM is instructed to be "a copy-paste machine" — no paraphrasing, no
interpretation, just the author's original words.

**When to use this vs agentic_fetch:**
- `agentic_fetch`: when you want the *full* page contents (academic paper,
  docs, source code). Tavily/Firecrawl/Grok engines for 100% fidelity markdown.
- `agentic_extract`: when you want to know *what's on a page in the author's
  own words* — a title plus 2–4 key quotes. Much cheaper and smaller output.

Output: JSON `{url, title, extracts: [str, ...], model}` to stdout. On total
failure, prints `{"error": ...}` and exits 1.

CLI:
    python agentic_extract.py --url "https://..." [--session-id S]

If `--session-id` is provided, the extract result is also appended to that
session's JSON on disk under an `extracted_pages` list (for composable
workflows like `agentic_search → agentic_extract --session-id S`).

Env vars: GROK_API_URL, GROK_API_KEY (required); GROK_MODEL, GROK_DEBUG (optional).
See ../references/extract-and-rank.md and ../references/provider-quirks.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Optional

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from _http import (  # noqa: E402
    debug,
    grok_model,
    grok_responses_call,
)
from _prompts import URL_DESCRIBE_PROMPT  # noqa: E402
from _session import read_session, write_session  # noqa: E402


async def describe_url(url: str, model_override: Optional[str] = None) -> dict:
    """LLM-mediated URL → title + verbatim quotes via xAI Responses API.

    Returns a dict with:
        url: the input URL
        title: extracted page title (falls back to the URL if Grok omits it)
        extracts: list of 2-4 verbatim quote strings (may be empty on parse failure)
        model: the effective model id used

    Search mode is "on" so Grok actually browses the URL via web_search rather
    than confabulating content from training data. Annotations are returned by
    the helper but discarded here — describe_url's contract is title+extracts,
    not citations.
    """
    model = grok_model(model_override)
    debug(f"describe_url: model={model} url={url}")

    result_text, _annotations = await grok_responses_call(
        instructions=URL_DESCRIBE_PROMPT,
        user_content=url,
        model=model_override,
        enable_search=True,
        search_mode="on",
    )

    # Parse the upstream-format response:
    #   Title: <title>
    #   Extracts: "quote 1" | "quote 2" | ...
    # Mirrors upstream grok.py:251-256 parsing loop, but splits the extracts
    # line on ` | ` so the caller gets a list instead of a single string.
    title = url
    extracts_raw = ""
    for line in (result_text or "").strip().splitlines():
        stripped = line.strip()
        if stripped.startswith("Title:"):
            candidate = stripped[6:].strip()
            if candidate:
                title = candidate
        elif stripped.startswith("Extracts:"):
            extracts_raw = stripped[9:].strip()

    # Split extracts on ' | ' (the separator the prompt instructs Grok to use).
    # Strip surrounding quotes per-fragment — Grok wraps quotes around each.
    extracts: list[str] = []
    if extracts_raw:
        for frag in extracts_raw.split(" | "):
            frag = frag.strip()
            if len(frag) >= 2 and frag[0] == frag[-1] and frag[0] in ('"', "'"):
                frag = frag[1:-1].strip()
            if frag:
                extracts.append(frag)

    return {
        "url": url,
        "title": title,
        "extracts": extracts,
        "model": model,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="agentic_extract — LLM-mediated URL → title + verbatim quotes."
    )
    parser.add_argument("--url", required=True, help="HTTP/HTTPS URL to extract.")
    parser.add_argument("--model", default="", help="Override GROK_MODEL for this call only.")
    parser.add_argument(
        "--session-id",
        default="",
        help="Optional session id. If set, the extract is appended to the session's 'extracted_pages' list.",
    )
    args = parser.parse_args()

    if not args.url.startswith(("http://", "https://")):
        print(
            json.dumps({"error": "--url must start with http:// or https://"}),
            file=sys.stderr,
        )
        return 1

    try:
        result = asyncio.run(describe_url(args.url, args.model or None))
    except SystemExit as e:
        print(json.dumps({"error": str(e) if e.code != 0 else "configuration error"}))
        return 1
    except Exception as e:
        print(json.dumps({"error": f"unexpected: {type(e).__name__}: {e}"}))
        return 1

    # Optionally merge into an existing session
    if args.session_id:
        session = read_session(args.session_id)
        if session is not None:
            extracted = session.get("extracted_pages") or []
            extracted.append(result)
            session["extracted_pages"] = extracted
            try:
                write_session(args.session_id, session)
                debug(f"appended extract to session {args.session_id}")
            except Exception as e:
                debug(f"failed to update session {args.session_id}: {e}")
        else:
            debug(f"session {args.session_id} not found; skipping append")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
