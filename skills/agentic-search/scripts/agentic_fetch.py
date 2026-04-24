#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "httpx>=0.28.0",
#   "tenacity>=8.0.0",
# ]
# ///
"""agentic_fetch — full-fidelity URL → Markdown extraction.

Four engines are available:

- **auto** (default): Tavily Extract → Firecrawl Scrape fallback chain.
  Faithful to upstream GrokSearch `web_fetch` (`server.py:339-377`).
  Grok is NOT automatically added to the chain to preserve upstream parity.
- **tavily**: Only Tavily Extract.
- **firecrawl**: Only Firecrawl Scrape (with progressive waitFor retries).
- **grok**: Only Grok via `FETCH_PROMPT` (LLM-mediated 100%-fidelity markdown).
  Ports upstream `grok_provider.fetch()` (dead code in upstream but a real capability).

Output: Markdown text to stdout. On total failure, prints `error: ...` to stderr
and exits 1. Stdout contract is unchanged from v1 — provenance (which engine
succeeded) is surfaced to stderr via `GROK_DEBUG=true` only.

CLI:
    python agentic_fetch.py --url "https://..." [--engine auto|tavily|firecrawl|grok]

Env vars:
    auto / tavily:     TAVILY_API_KEY required
    auto / firecrawl:  FIRECRAWL_API_KEY required (for fallback step in auto)
    grok:              GROK_API_URL + GROK_API_KEY required
    Optional:          GROK_MODEL, GROK_DEBUG

See ../references/fetch-fidelity.md and ../references/provider-quirks.md.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Optional

import httpx

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from _http import (  # noqa: E402
    debug,
    firecrawl_api_key,
    firecrawl_api_url,
    grok_responses_call,
    retry_max_attempts,
    tavily_api_key,
    tavily_api_url,
)
from _prompts import FETCH_PROMPT  # noqa: E402


ENGINES = ("auto", "tavily", "firecrawl", "grok")


async def _tavily_extract(url: str) -> Optional[str]:
    api_key = tavily_api_key()
    if not api_key:
        debug("tavily extract skipped: TAVILY_API_KEY not set")
        return None
    endpoint = f"{tavily_api_url().rstrip('/')}/extract"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {"urls": [url], "format": "markdown"}
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(endpoint, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results") or []
            if results:
                content = results[0].get("raw_content", "") or ""
                if content.strip():
                    return content
            debug("tavily extract returned empty content")
            return None
    except Exception as e:
        debug(f"tavily extract failed: {e}")
        return None


async def _firecrawl_scrape(url: str) -> Optional[str]:
    api_key = firecrawl_api_key()
    if not api_key:
        debug("firecrawl scrape skipped: FIRECRAWL_API_KEY not set")
        return None
    endpoint = f"{firecrawl_api_url().rstrip('/')}/scrape"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    max_retries = retry_max_attempts()
    for attempt in range(max_retries):
        body = {
            "url": url,
            "formats": ["markdown"],
            "timeout": 60000,
            "waitFor": (attempt + 1) * 1500,  # 1.5s, 3s, 4.5s
        }
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                resp = await client.post(endpoint, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()
                markdown = (data.get("data") or {}).get("markdown", "") or ""
                if markdown.strip():
                    return markdown
                debug(f"firecrawl scrape returned empty markdown, attempt {attempt + 1}/{max_retries}")
        except Exception as e:
            debug(f"firecrawl scrape failed: {e}")
            return None
    return None


async def _grok_fetch(url: str) -> Optional[str]:
    """Grok-mediated full-page markdown extraction via xAI Responses API.

    Uses the same FETCH_PROMPT (the Chinese "Web Content Fetcher" persona with
    100% fidelity guarantee) and the same user-message composition as upstream
    GrokSearch (URL + CN instruction suffix). Search mode is "on" so Grok
    actually browses the URL via the web_search tool rather than confabulating
    page content. Returns the Grok-generated markdown string or None on failure.

    Annotations are discarded — fetch returns just the markdown text to stdout.
    """
    try:
        text, _annotations = await grok_responses_call(
            instructions=FETCH_PROMPT,
            user_content=url + "\n获取该网页内容并返回其结构化Markdown格式",
            enable_search=True,
            search_mode="on",
        )
    except SystemExit as e:
        debug(f"grok fetch skipped: {e}")
        return None
    except Exception as e:
        debug(f"grok fetch failed: {e}")
        return None
    return text if text and text.strip() else None


async def fetch_url(url: str, engine: str = "auto") -> tuple[Optional[str], Optional[str]]:
    """Fetch a URL's content as markdown via the chosen engine.

    Returns ``(markdown, engine_used)`` or ``(None, None)`` on total failure.

    Public helper — also imported by `agentic_search.py` for `--auto-fetch-top`
    to avoid duplicating the engine routing logic.

    Engine routing:
        auto:      Tavily Extract → Firecrawl Scrape (default, upstream-faithful)
        tavily:    only Tavily Extract
        firecrawl: only Firecrawl Scrape
        grok:      only Grok via FETCH_PROMPT
    """
    if engine not in ENGINES:
        raise ValueError(f"invalid engine {engine!r}; must be one of {ENGINES}")

    debug(f"fetch_url: engine={engine} url={url}")

    if engine == "tavily":
        result = await _tavily_extract(url)
        return (result, "tavily") if result else (None, None)

    if engine == "firecrawl":
        result = await _firecrawl_scrape(url)
        return (result, "firecrawl") if result else (None, None)

    if engine == "grok":
        result = await _grok_fetch(url)
        return (result, "grok") if result else (None, None)

    # engine == "auto" — Tavily → Firecrawl chain (unchanged from v1)
    result = await _tavily_extract(url)
    if result:
        return result, "tavily"
    debug("tavily failed or unavailable, trying firecrawl")
    result = await _firecrawl_scrape(url)
    if result:
        return result, "firecrawl"
    return None, None


# Backwards-compat alias — older callers may still import `fetch`
fetch = fetch_url


def main() -> int:
    parser = argparse.ArgumentParser(
        description="agentic_fetch — full-fidelity URL → Markdown extraction."
    )
    parser.add_argument("--url", required=True, help="HTTP/HTTPS URL to fetch.")
    parser.add_argument(
        "--engine",
        default="auto",
        choices=ENGINES,
        help="Extraction engine: 'auto' (Tavily→Firecrawl, default), 'tavily', 'firecrawl', or 'grok'.",
    )
    args = parser.parse_args()

    if not args.url.startswith(("http://", "https://")):
        print("error: --url must start with http:// or https://", file=sys.stderr)
        return 1

    try:
        markdown, engine_used = asyncio.run(fetch_url(args.url, args.engine))
    except Exception as e:
        print(f"error: unexpected: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    if markdown is None:
        if args.engine == "auto":
            if not tavily_api_key() and not firecrawl_api_key():
                print(
                    "error: neither TAVILY_API_KEY nor FIRECRAWL_API_KEY is set; cannot fetch",
                    file=sys.stderr,
                )
            else:
                print("error: all extraction providers failed to return content", file=sys.stderr)
        else:
            print(
                f"error: engine '{args.engine}' failed to return content (check API key and network)",
                file=sys.stderr,
            )
        return 1

    debug(f"fetch succeeded via {engine_used}, {len(markdown)} chars")
    sys.stdout.write(markdown)
    if not markdown.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
