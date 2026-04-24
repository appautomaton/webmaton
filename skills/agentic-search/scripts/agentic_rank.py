#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "httpx>=0.28.0",
#   "tenacity>=8.0.0",
# ]
# ///
"""agentic_rank — rerank a list of sources by relevance to a refined query.

Ports upstream GrokSearch `GrokSearchProvider.rank_sources()` (grok.py:259-288),
which is defined upstream but never wired to an MCP tool. It takes a numbered
source list, asks Grok to output the numbers reordered by relevance to a query,
and returns the sources in the new order (with missing indices filled at the
end — robust to partial model outputs).

**Typical workflow**:
    # 1. Run a broad search
    uv run scripts/agentic_search.py --query "best agentic AI frameworks" > /tmp/search.json
    SID=$(python -c "import json; print(json.load(open('/tmp/search.json'))['session_id'])")

    # 2. Rerank by a more specific lens
    uv run scripts/agentic_rank.py --query "production-ready open source" --session-id "$SID"

The rerank mutates the session's sources list in place so subsequent scripts
(`agentic_get_sources`, `agentic_search --auto-fetch-top`) see the new order.

Two input modes:
    --session-id S            Read sources from session cache, rerank, write back.
    --sources-json -          Read a JSON list of sources from stdin (ad-hoc mode).

Output: JSON `{ordered_sources, model, session_id?}` to stdout.

Env vars: GROK_API_URL, GROK_API_KEY (required); GROK_MODEL, GROK_DEBUG (optional).
See ../references/extract-and-rank.md.
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
from _prompts import RANK_SOURCES_PROMPT  # noqa: E402
from _session import read_session, write_session  # noqa: E402


def _format_sources_for_ranking(sources: list[dict]) -> str:
    """Format sources as a numbered list for the Grok prompt.

    Format (one per line, 1-indexed):
        1. [Title] - URL
           description (if any)
        2. ...
    """
    lines = []
    for i, src in enumerate(sources, start=1):
        url = src.get("url", "") or ""
        title = src.get("title") or "Untitled"
        lines.append(f"{i}. [{title}] - {url}")
        desc = src.get("description") or ""
        if desc:
            lines.append(f"   {desc[:200]}")
    return "\n".join(lines)


async def rank_sources(query: str, sources: list[dict], model_override: Optional[str] = None) -> dict:
    """Rerank a list of sources by relevance to a refined query via xAI Responses API.

    Returns a dict:
        ordered_sources: [...]  (same dicts, new order)
        model: effective model id
        original_count: int

    **Search is disabled** for this call (`enable_search=False`). Ranking is
    pure reasoning over a given list of sources — no new web information is
    needed, and disabling search saves cost and latency. The Responses API
    helper omits both the `web_search` tool and the `search_parameters` field
    when `enable_search=False`.

    Mirrors upstream's 'fill missing indices' tail logic so partial model
    outputs degrade gracefully (unranked indices get appended at the end).
    """
    if not sources:
        return {"ordered_sources": [], "model": grok_model(model_override), "original_count": 0}

    model = grok_model(model_override)
    total = len(sources)
    sources_text = _format_sources_for_ranking(sources)

    debug(f"rank_sources: model={model} total={total} (search disabled)")

    result_text, _annotations = await grok_responses_call(
        instructions=RANK_SOURCES_PROMPT,
        user_content=f"Query: {query}\n\n{sources_text}",
        model=model_override,
        enable_search=False,
    )

    # Parse the response: space-separated integers, dedupe, validate range.
    # Mirrors upstream grok.py:274-287 byte-for-byte.
    order: list[int] = []
    seen: set[int] = set()
    for token in (result_text or "").strip().split():
        try:
            n = int(token)
            if 1 <= n <= total and n not in seen:
                seen.add(n)
                order.append(n)
        except ValueError:
            continue
    # Fill any missing indices at the end
    for i in range(1, total + 1):
        if i not in seen:
            order.append(i)

    # Reorder the original sources list (1-indexed → 0-indexed)
    ordered = [sources[n - 1] for n in order]

    return {
        "ordered_sources": ordered,
        "model": model,
        "original_count": total,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="agentic_rank — rerank a source list by relevance to a refined query."
    )
    parser.add_argument("--query", required=True, help="The refined query to rank sources against.")
    parser.add_argument("--model", default="", help="Override GROK_MODEL for this call only.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--session-id",
        default="",
        help="Session id from a previous agentic_search call. Sources are loaded from the session cache and the reranked order is written back.",
    )
    group.add_argument(
        "--sources-json",
        default="",
        help="Read a JSON list of sources from this file, or '-' for stdin.",
    )
    args = parser.parse_args()

    # Load sources
    sources: list[dict]
    session_data: Optional[dict] = None

    if args.session_id:
        session_data = read_session(args.session_id)
        if session_data is None:
            print(
                json.dumps({"error": f"session {args.session_id} not found or expired"}),
                file=sys.stderr,
            )
            return 1
        sources = session_data.get("sources") or []
    else:
        try:
            if args.sources_json == "-":
                raw = sys.stdin.read()
            else:
                raw = __import__("pathlib").Path(args.sources_json).read_text(encoding="utf-8")
            sources = json.loads(raw)
            if not isinstance(sources, list):
                raise ValueError("sources JSON must be a list")
        except Exception as e:
            print(
                json.dumps({"error": f"failed to read sources JSON: {type(e).__name__}: {e}"}),
                file=sys.stderr,
            )
            return 1

    if not sources:
        print(json.dumps({"error": "no sources to rank"}), file=sys.stderr)
        return 1

    # Run the rank
    try:
        result = asyncio.run(rank_sources(args.query, sources, args.model or None))
    except SystemExit as e:
        print(json.dumps({"error": str(e) if e.code != 0 else "configuration error"}))
        return 1
    except Exception as e:
        print(json.dumps({"error": f"unexpected: {type(e).__name__}: {e}"}))
        return 1

    # If invoked via session_id, write the reranked sources back to the session
    if args.session_id and session_data is not None:
        session_data["sources"] = result["ordered_sources"]
        # Preserve sources_count (still the same count, just reordered)
        session_data["sources_count"] = len(result["ordered_sources"])
        session_data["ranked_by_query"] = args.query
        try:
            write_session(args.session_id, session_data)
            result["session_id"] = args.session_id
            debug(f"wrote reranked sources back to session {args.session_id}")
        except Exception as e:
            debug(f"failed to write back to session: {e}")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
