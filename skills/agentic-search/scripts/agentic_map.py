#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "httpx>=0.28.0",
#   "tenacity>=8.0.0",
# ]
# ///
"""agentic_map — discover URLs under a site root via Tavily Map.

Traverses a site like a graph, returning a structured list of discovered URLs.
Use natural-language `--instructions` to filter (e.g., "only API reference
pages"). Tunable depth/breadth/limit/timeout.

Output: JSON `{base_url, results, response_time}` to stdout. On error, prints
`error: ...` to stderr and exits 1.

CLI:
    python agentic_map.py --url "https://docs.example.com" \\
        [--instructions "only docs"] [--max-depth 2] [--max-breadth 30] \\
        [--limit 100] [--timeout 150]

Env vars: TAVILY_API_KEY (required), TAVILY_API_URL (optional).
See ../references/provider-quirks.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import httpx

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from _http import debug, tavily_api_key, tavily_api_url  # noqa: E402


async def map_site(
    url: str,
    instructions: str,
    max_depth: int,
    max_breadth: int,
    limit: int,
    timeout: int,
) -> dict:
    api_key = tavily_api_key()
    if not api_key:
        raise SystemExit("error: TAVILY_API_KEY is not set; agentic_map requires it")

    endpoint = f"{tavily_api_url().rstrip('/')}/map"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body: dict = {
        "url": url,
        "max_depth": max_depth,
        "max_breadth": max_breadth,
        "limit": limit,
        "timeout": timeout,
    }
    if instructions:
        body["instructions"] = instructions

    debug(f"map request: url={url} depth={max_depth} breadth={max_breadth} limit={limit}")

    try:
        async with httpx.AsyncClient(timeout=float(timeout + 10)) as client:
            resp = await client.post(endpoint, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            return {
                "base_url": data.get("base_url", "") or "",
                "results": data.get("results", []) or [],
                "response_time": data.get("response_time", 0),
            }
    except httpx.TimeoutException:
        raise SystemExit(f"error: map timed out after {timeout}s")
    except httpx.HTTPStatusError as e:
        raise SystemExit(f"error: HTTP {e.response.status_code}: {e.response.text[:200]}")
    except Exception as e:
        raise SystemExit(f"error: {type(e).__name__}: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="agentic_map — discover URLs under a site root via Tavily Map."
    )
    parser.add_argument("--url", required=True, help="Root URL to begin mapping.")
    parser.add_argument(
        "--instructions",
        default="",
        help="Natural-language filter (e.g., 'only documentation pages').",
    )
    parser.add_argument("--max-depth", type=int, default=1, help="Traversal depth (1-5). Default 1.")
    parser.add_argument(
        "--max-breadth", type=int, default=20, help="Max links per page (1-500). Default 20."
    )
    parser.add_argument("--limit", type=int, default=50, help="Total link cap (1-500). Default 50.")
    parser.add_argument(
        "--timeout", type=int, default=150, help="Server-side timeout in seconds (10-150). Default 150."
    )
    args = parser.parse_args()

    if not args.url.startswith(("http://", "https://")):
        print("error: --url must start with http:// or https://", file=sys.stderr)
        return 1

    try:
        result = asyncio.run(
            map_site(
                args.url,
                args.instructions,
                args.max_depth,
                args.max_breadth,
                args.limit,
                args.timeout,
            )
        )
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 1
    except Exception as e:
        print(f"error: unexpected: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
