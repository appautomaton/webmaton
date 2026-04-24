#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "httpx>=0.28.0",
#   "tenacity>=8.0.0",
# ]
# ///
"""agentic_search — deep web research via Grok + optional Tavily/Firecrawl fusion.

Calls Grok's chat-completions endpoint with a discipline-loaded system prompt,
optionally fans out to Tavily and/or Firecrawl in parallel for supplementary
sources, parses citations out of Grok's free-form answer, dedupes sources by
URL, and prints a JSON object to stdout.

Output schema:
    {
        "content": str,                 # Grok's answer with sources stripped
        "sources": [                    # deduped, ordered: grok first, then extras
            {"url": str, "title"?: str, "description"?: str, "provider"?: str},
            ...
        ],
        "sources_count": int,
        "model": str                    # the effective model used
    }

On configuration error, prints {"error": "..."} and exits 1.

CLI:
    python agentic_search.py --query "..." [--platform "..."] [--model "..."] [--extra-sources N]

Env vars: GROK_API_URL, GROK_API_KEY (required); GROK_MODEL, TAVILY_API_KEY,
FIRECRAWL_API_KEY (optional). See ../references/provider-quirks.md.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

# Allow running this file directly: `python scripts/agentic_search.py`
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from _http import (  # noqa: E402
    debug,
    firecrawl_api_key,
    firecrawl_api_url,
    grok_model,
    grok_responses_call,
    normalize_responses_annotations,
    tavily_api_key,
    tavily_api_url,
)
from _prompts import SEARCH_PROMPT  # noqa: E402
from _session import (  # noqa: E402
    new_session_id,
    prune_sessions,
    write_session,
)


# ---------- time-context heuristic ----------

_CN_TIME_KEYWORDS = (
    "当前", "现在", "今天", "明天", "昨天",
    "本周", "上周", "下周", "这周",
    "本月", "上月", "下月", "这个月",
    "今年", "去年", "明年",
    "最新", "最近", "近期", "刚刚", "刚才",
    "实时", "即时", "目前",
)
_EN_TIME_KEYWORDS = (
    "current", "now", "today", "tomorrow", "yesterday",
    "this week", "last week", "next week",
    "this month", "last month", "next month",
    "this year", "last year", "next year",
    "latest", "recent", "recently", "just now",
    "real-time", "realtime", "up-to-date",
)
_CN_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


def _needs_time_context(query: str) -> bool:
    if any(kw in query for kw in _CN_TIME_KEYWORDS):
        return True
    lower = query.lower()
    return any(kw in lower for kw in _EN_TIME_KEYWORDS)


def _local_time_block() -> str:
    try:
        local_tz = datetime.now().astimezone().tzinfo
        local_now = datetime.now(local_tz)
    except Exception:
        local_now = datetime.now(timezone.utc)
    weekday = _CN_WEEKDAYS[local_now.weekday()]
    return (
        f"[Current Time Context]\n"
        f"- Date: {local_now.strftime('%Y-%m-%d')} ({weekday})\n"
        f"- Time: {local_now.strftime('%H:%M:%S')}\n"
        f"- Timezone: {local_now.tzname() or 'Local'}\n"
    )


# ---------- Grok call (xAI Responses API with native web search) ----------

async def _grok_search(
    query: str, platform: str, model: Optional[str]
) -> tuple[str, list[dict]]:
    """Call Grok via the xAI Responses API with web_search enabled.

    Returns ``(text_content, raw_annotations)``. Raw annotations are
    Responses-API citation objects; pass them through
    `normalize_responses_annotations` to convert to source dicts.

    Time-context injection (CN/EN keyword detection) and platform-focus
    suffix are preserved verbatim from v1/v2 — they're prompt-discipline
    decisions, not API-shape decisions.
    """
    user_content = ""
    if _needs_time_context(query):
        user_content += _local_time_block() + "\n"
    user_content += query
    if platform:
        user_content += (
            f"\n\nYou should search the web for the information you need, "
            f"and focus on these platform: {platform}\n"
        )

    return await grok_responses_call(
        instructions=SEARCH_PROMPT,
        user_content=user_content,
        model=model,
        enable_search=True,
        search_mode="auto",
        tools=["web_search", "x_search"],  # Use both web and X search for research
    )


# ---------- Tavily / Firecrawl supplementary search ----------

async def _tavily_search(query: str, max_results: int) -> Optional[list[dict]]:
    api_key = tavily_api_key()
    if not api_key or max_results <= 0:
        return None
    endpoint = f"{tavily_api_url().rstrip('/')}/search"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "query": query,
        "max_results": max_results,
        "search_depth": "advanced",
        "include_raw_content": False,
        "include_answer": False,
    }
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(endpoint, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results") or []
            return [
                {
                    "title": r.get("title", "") or "",
                    "url": r.get("url", "") or "",
                    "content": r.get("content", "") or "",
                    "score": r.get("score", 0),
                }
                for r in results
            ] or None
    except Exception as e:
        debug(f"tavily search failed: {e}")
        return None


async def _firecrawl_search(query: str, limit: int) -> Optional[list[dict]]:
    api_key = firecrawl_api_key()
    if not api_key or limit <= 0:
        return None
    endpoint = f"{firecrawl_api_url().rstrip('/')}/search"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {"query": query, "limit": limit}
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(endpoint, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            results = (data.get("data") or {}).get("web") or []
            return [
                {
                    "title": r.get("title", "") or "",
                    "url": r.get("url", "") or "",
                    "description": r.get("description", "") or "",
                }
                for r in results
            ] or None
    except Exception as e:
        debug(f"firecrawl search failed: {e}")
        return None


# ---------- source extraction (port of upstream sources.py) ----------

_URL_PATTERN = re.compile(r'https?://[^\s<>"\'`，。、；：！？》）】\)]+')
_MD_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
_SOURCES_HEADING_PATTERN = re.compile(
    r"(?im)^"
    r"(?:#{1,6}\s*)?"
    r"(?:\*\*|__)?\s*"
    r"(sources?|references?|citations?|信源|参考资料|参考|引用|来源列表|来源)"
    r"\s*(?:\*\*|__)?"
    r"(?:\s*[（(][^)\n]*[)）])?"
    r"\s*[:：]?\s*$"
)
_SOURCES_FUNCTION_PATTERN = re.compile(
    r"(?im)(^|\n)\s*(sources|source|citations|citation|references|reference|citation_card|source_cards|source_card)\s*\("
)

# v2: parser for inline `(\`citation_card\`: Author, "Title," Source, Year, URL, description)`
# parentheticals that Grok uses mid-sentence. Reuses _URL_PATTERN for URL extraction.
_CITATION_CARD_PATTERN = re.compile(
    r"\(\s*`?citation_card`?\s*:\s*([^)]+?)\s*\)",
    re.IGNORECASE | re.DOTALL,
)
_QUOTED_TITLE_PATTERN = re.compile(r'"([^"]+?)"')
_YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")

# v2.1: matches fenced code blocks of any language tag (or none). Captures the
# language tag as group 1 and the body as group 2. Used by
# _parse_fenced_citation_blocks below.
#
# In real grok-4-1-fast-reasoning output we've observed at least three citation
# fence variants, ALL of which this regex catches:
#   ```json\n{"url":..., "title":...}\n```                    (JSON dict)
#   ```\n{"url":..., "title":...}\n```                        (JSON, no lang)
#   ```citation_card\nurl: ...\ntitle: "..."\nsummary: ...```  (YAML-ish kv)
_FENCED_BLOCK_PATTERN = re.compile(
    r"```(\w*)\s*\n?(.*?)\n?```",
    re.DOTALL,
)


def _extract_unique_urls(text: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for m in _URL_PATTERN.finditer(text or ""):
        url = m.group().rstrip(".,;:!?")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _normalize_sources(data: Any) -> list[dict]:
    items: list[Any]
    if isinstance(data, (list, tuple)):
        items = list(data)
    elif isinstance(data, dict):
        items = [data]
    else:
        items = [data]

    out: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, str):
            for url in _extract_unique_urls(item):
                if url not in seen:
                    seen.add(url)
                    out.append({"url": url})
            continue
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            title, url = item[0], item[1]
            if isinstance(url, str) and url.startswith(("http://", "https://")) and url not in seen:
                seen.add(url)
                rec: dict = {"url": url}
                if isinstance(title, str) and title.strip():
                    rec["title"] = title.strip()
                out.append(rec)
            continue
        if isinstance(item, dict):
            url = item.get("url") or item.get("href") or item.get("link")
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                continue
            if url in seen:
                continue
            seen.add(url)
            rec = {"url": url}
            title = item.get("title") or item.get("name") or item.get("label")
            if isinstance(title, str) and title.strip():
                rec["title"] = title.strip()
            desc = item.get("description") or item.get("snippet") or item.get("content")
            if isinstance(desc, str) and desc.strip():
                rec["description"] = desc.strip()
            out.append(rec)
    return out


# v2.1: known citation field keys, used to slice key:value bodies regardless
# of whether they're newline-separated or all on one line. Word-boundary anchored
# so titles containing tokens like "Reasoning:" don't match (case-insensitive).
_CITATION_KEY_PATTERN = re.compile(
    r"\b(title|author|authors|url|date|year|section|snippet|summary|description|published|publisher|source|venue)\s*:\s*",
    re.IGNORECASE,
)


def _parse_keyvalue_citation_body(body: str) -> Optional[dict]:
    """Parse a key:value citation block body into a dict.

    Used by `_parse_fenced_citation_blocks` when `json.loads` fails on the
    body. Handles both newline-separated AND single-line layouts that Grok
    emits — sliced by known field-key positions, not by `\\n`.

    Strips surrounding quotes from values. Returns None if no `url` key is
    found or no recognized fields parse.

    Multi-line example:
        title: "What is a 'harness' in agent benchmarks?"
        author: Nathan Lambert
        url: https://www.interconnects.ai/p/what-is-a-harness-in-agent-benchmarks
        date: 2024-10-15
        summary: Defines harness as ...

    Single-line example (also seen in real Grok output):
        title: "Harnesses" author: Stanford CRFM url: https://crfm.stanford.edu/helm/latest/ date: 2024 section: Harness Definition
    """
    matches = list(_CITATION_KEY_PATTERN.finditer(body))
    if not matches:
        return None

    result: dict = {}
    for i, m in enumerate(matches):
        key = m.group(1).lower()
        value_start = m.end()
        value_end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        value = body[value_start:value_end].strip()
        # Strip trailing comma/semicolon noise that may bleed in from
        # comma-separated layouts
        value = value.rstrip(",;").strip()
        # Strip surrounding matched quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1].strip()
        if value:
            # Last value wins on duplicate keys (rare; usually a malformed citation)
            result[key] = value

    if "url" not in result:
        return None
    return result


def _parse_fenced_citation_blocks(text: str) -> list[dict]:
    """Parse fenced code blocks containing citation records, in either JSON
    dict form OR YAML-ish `key: value` form.

    v2.1: handles the formats `grok-4-1-fast-reasoning` actually uses in real
    output. Three observed variants are all caught:

        ```json
        {"url": "...", "title": "...", "snippet": "..."}
        ```

        ```
        {"url": "...", "title": "..."}
        ```

        ```citation_card
        title: "..."
        author: ...
        url: ...
        date: 2024-10-15
        summary: ...
        ```

    For each fenced block:
      1. Pre-filter on the cheap substring `url` — skip blocks that obviously
         can't be citations (e.g. code examples).
      2. Try `json.loads(body)` first; on success, treat result as dict or list of dicts.
      3. On JSON failure, try the line-based key:value parser.
      4. Extract a normalized record with these field aliases:
            url                   -> url (required, must start with http(s)://)
            title                 -> title
            author / authors      -> author
            year (or date's YYYY) -> year
            snippet / summary
              / description       -> description
            citation_id           -> dropped (Grok-internal)
      5. Dedupe by URL across the entire input.

    Output schema matches `_parse_citation_cards` so downstream consumers
    don't need to know which extractor produced a record.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for m in _FENCED_BLOCK_PATTERN.finditer(text or ""):
        body = m.group(2).strip()
        if not body or "url" not in body:
            continue  # cheap pre-filter — skip non-citation code blocks

        # Try JSON first; fall back to key:value parser.
        items: list[dict] = []
        try:
            data = json.loads(body)
            if isinstance(data, list):
                items = [d for d in data if isinstance(d, dict)]
            elif isinstance(data, dict):
                items = [data]
        except (json.JSONDecodeError, ValueError):
            kv = _parse_keyvalue_citation_body(body)
            if kv is not None:
                items = [kv]

        for item in items:
            url = item.get("url")
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                continue
            url = url.rstrip(".,;:!?")
            if url in seen:
                continue
            seen.add(url)

            rec: dict = {"url": url}

            # title
            title = item.get("title")
            if isinstance(title, str) and title.strip():
                rec["title"] = title.strip()

            # author / authors
            author = item.get("author") or item.get("authors")
            if isinstance(author, str) and author.strip():
                rec["author"] = author.strip()
            elif isinstance(author, list) and author:
                rec["author"] = ", ".join(str(a) for a in author if a)

            # year directly, or year from a date string like "2024-10-15"
            year = item.get("year")
            if isinstance(year, str) and year.strip():
                rec["year"] = year.strip()
            elif isinstance(year, int):
                rec["year"] = str(year)
            else:
                date = item.get("date")
                if isinstance(date, str):
                    ym = _YEAR_PATTERN.search(date)
                    if ym:
                        rec["year"] = ym.group()

            # description: snippet | summary | description
            for k in ("snippet", "summary", "description"):
                v = item.get(k)
                if isinstance(v, str) and v.strip():
                    rec["description"] = v.strip()
                    break

            out.append(rec)
    return out


# Backwards-compat alias — earlier v2.1 plan referred to it as JSON-only.
_parse_json_citation_blocks = _parse_fenced_citation_blocks


def _parse_citation_cards(text: str) -> list[dict]:
    r"""Parse Grok's inline `(\`citation_card\`: Author, "Title," Source, Year, URL, description)`
    annotations into rich source dicts.

    Returns a list of `{url, title?, author?, year?, description?}` dicts.
    Best-effort: any field that can't be parsed is omitted (never None).
    Dedupes by URL across the input. Robust to missing fields and to the
    backtick-wrapped vs bare `citation_card` variants.

    v2 deviation from upstream GrokSearch — upstream's `sources.py` only
    parses citation_card as a top-level function call (pattern 1 in
    `split_answer_and_sources`), not as inline parentheticals. This parser
    catches the inline form Grok actually emits in v2 model output.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for m in _CITATION_CARD_PATTERN.finditer(text or ""):
        inner = m.group(1).strip()

        # URL — required; if absent, skip this annotation
        url_match = _URL_PATTERN.search(inner)
        if not url_match:
            continue
        url = url_match.group().rstrip(".,;:!?")
        if url in seen:
            continue
        seen.add(url)
        rec: dict = {"url": url}

        # Title — first quoted string
        title_match = _QUOTED_TITLE_PATTERN.search(inner)
        if title_match:
            title = title_match.group(1).strip().rstrip(",").strip()
            if title:
                rec["title"] = title

        # Year — first 4-digit year-like token (matches the standalone year
        # before the URL most of the time; falls back to year inside the URL
        # path if no standalone year is present)
        year_match = _YEAR_PATTERN.search(inner)
        if year_match:
            rec["year"] = year_match.group()

        # Author — text before the first comma, if it's not the URL or
        # the (already-extracted) title
        first_comma = inner.find(",")
        if first_comma > 0:
            author_candidate = inner[:first_comma].strip()
            if (
                author_candidate
                and "http" not in author_candidate
                and author_candidate != rec.get("title", "")
                and not _YEAR_PATTERN.fullmatch(author_candidate)
            ):
                rec["author"] = author_candidate

        # Description — text after the URL up to the closing paren
        url_end = url_match.end()
        tail = inner[url_end:].strip()
        # Strip leading punctuation/comma noise
        while tail and tail[0] in ",;:.- ":
            tail = tail[1:]
        if tail:
            rec["description"] = tail.strip()

        out.append(rec)
    return out


def _extract_sources_from_text(text: str) -> list[dict]:
    r"""Harvest sources from free-form text using a four-tier extraction order.

    Tiers, richest first (each one's URLs win over the next, deduped by URL):
        1. Fenced JSON citation blocks  (v2.1) — `_parse_json_citation_blocks`
           handles ```json {"url":...,"title":...,"snippet":...} ``` blocks,
           which is the format `grok-4-1-fast-reasoning` actually emits.
        2. citation_card parentheticals  (v2)  — `_parse_citation_cards`
           handles `(\`citation_card\`: Author, "Title," ..., URL, desc)`.
        3. Markdown links                (v1)  — `[anchor](url)`. Only `title`
           field populated (the link's anchor text).
        4. Bare URLs                     (v1)  — no metadata.
    """
    sources: list[dict] = []
    seen: set[str] = set()

    # Tier 1 (v2.1): fenced citation blocks (JSON or YAML-ish key:value form)
    for rec in _parse_fenced_citation_blocks(text or ""):
        url = rec["url"]
        if url not in seen:
            seen.add(url)
            sources.append(rec)

    # Tier 2 (v2): citation_card parentheticals
    for rec in _parse_citation_cards(text or ""):
        url = rec["url"]
        if url in seen:
            continue
        seen.add(url)
        sources.append(rec)

    # Tier 3 (v1): markdown links (poorer metadata: just title)
    for title, url in _MD_LINK_PATTERN.findall(text or ""):
        url = (url or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        title = (title or "").strip()
        sources.append({"title": title, "url": url} if title else {"url": url})

    # Finally bare URLs (no metadata)
    for url in _extract_unique_urls(text or ""):
        if url in seen:
            continue
        seen.add(url)
        sources.append({"url": url})

    return sources


def _parse_sources_payload(payload: str) -> list[dict]:
    payload = (payload or "").strip().rstrip(";")
    if not payload:
        return []
    data: Any = None
    try:
        data = json.loads(payload)
    except Exception:
        try:
            data = ast.literal_eval(payload)
        except Exception:
            data = None
    if data is None:
        return _extract_sources_from_text(payload)
    if isinstance(data, dict):
        for key in ("sources", "citations", "references", "urls"):
            if key in data:
                return _normalize_sources(data[key])
        return _normalize_sources(data)
    return _normalize_sources(data)


def _extract_balanced_call(text: str, open_idx: int) -> Optional[tuple[int, str]]:
    if open_idx < 0 or open_idx >= len(text) or text[open_idx] != "(":
        return None
    depth = 1
    in_string: Optional[str] = None
    escape = False
    for idx in range(open_idx + 1, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == in_string:
                in_string = None
            continue
        if ch in ("'", '"'):
            in_string = ch
            continue
        if ch == "(":
            depth += 1
            continue
        if ch == ")":
            depth -= 1
            if depth == 0:
                if text[idx + 1:].strip():
                    return None
                return idx, text[open_idx + 1: idx]
    return None


def _split_function_call(text: str) -> Optional[tuple[str, list[dict]]]:
    matches = list(_SOURCES_FUNCTION_PATTERN.finditer(text))
    if not matches:
        return None
    for m in reversed(matches):
        open_idx = m.end() - 1
        extracted = _extract_balanced_call(text, open_idx)
        if not extracted:
            continue
        _, args_text = extracted
        sources = _parse_sources_payload(args_text)
        if not sources:
            continue
        return text[: m.start()].rstrip(), sources
    return None


def _split_heading(text: str) -> Optional[tuple[str, list[dict]]]:
    matches = list(_SOURCES_HEADING_PATTERN.finditer(text))
    if not matches:
        return None
    for m in reversed(matches):
        sources = _extract_sources_from_text(text[m.start():])
        if sources:
            return text[: m.start()].rstrip(), sources
    return None


def _split_details_block(text: str) -> Optional[tuple[str, list[dict]]]:
    lower = text.lower()
    close_idx = lower.rfind("</details>")
    if close_idx == -1:
        return None
    if text[close_idx + len("</details>"):].strip():
        return None
    open_idx = lower.rfind("<details", 0, close_idx)
    if open_idx == -1:
        return None
    block = text[open_idx: close_idx + len("</details>")]
    sources = _extract_sources_from_text(block)
    if len(sources) < 2:
        return None
    return text[:open_idx].rstrip(), sources


def _is_link_only_line(line: str) -> bool:
    stripped = re.sub(r"^\s*(?:[-*]|\d+\.)\s*", "", line).strip()
    if not stripped:
        return False
    if stripped.startswith(("http://", "https://")):
        return True
    return bool(_MD_LINK_PATTERN.search(stripped))


def _split_tail_links(text: str) -> Optional[tuple[str, list[dict]]]:
    lines = text.splitlines()
    if not lines:
        return None
    idx = len(lines) - 1
    while idx >= 0 and not lines[idx].strip():
        idx -= 1
    if idx < 0:
        return None
    tail_end = idx
    link_count = 0
    while idx >= 0:
        line = lines[idx].strip()
        if not line:
            idx -= 1
            continue
        if not _is_link_only_line(line):
            break
        link_count += 1
        idx -= 1
    if link_count < 2:
        return None
    tail_start = idx + 1
    block = "\n".join(lines[tail_start: tail_end + 1])
    sources = _extract_sources_from_text(block)
    if not sources:
        return None
    return "\n".join(lines[:tail_start]).rstrip(), sources


def split_answer_and_sources(text: str) -> tuple[str, list[dict]]:
    raw = (text or "").strip()
    if not raw:
        return "", []
    for splitter in (_split_function_call, _split_heading, _split_details_block, _split_tail_links):
        result = splitter(raw)
        if result:
            return result
    # v1 deviation from upstream GrokSearch: when none of the four upstream
    # patterns match (e.g. Grok inlined citations as `(citation_card: ..., URL)`
    # annotations mid-sentence), fall back to harvesting any inline URLs from
    # the answer body without modifying it. Reuses _extract_sources_from_text.
    inline_sources = _extract_sources_from_text(raw)
    return raw, inline_sources


def _merge_sources(*lists: list[dict]) -> list[dict]:
    seen: set[str] = set()
    merged: list[dict] = []
    for sources in lists:
        for item in sources or []:
            url = (item or {}).get("url")
            if not isinstance(url, str) or not url.strip():
                continue
            url = url.strip()
            if url in seen:
                continue
            seen.add(url)
            merged.append(item)
    return merged


def _extras_to_sources(
    tavily: Optional[list[dict]], firecrawl: Optional[list[dict]]
) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    # Firecrawl first to match upstream's preference (Firecrawl is breadth-prioritized)
    for r in firecrawl or []:
        url = (r.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        item: dict = {"url": url, "provider": "firecrawl"}
        if r.get("title"):
            item["title"] = r["title"].strip()
        if r.get("description"):
            item["description"] = r["description"].strip()
        out.append(item)
    for r in tavily or []:
        url = (r.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        item = {"url": url, "provider": "tavily"}
        if r.get("title"):
            item["title"] = r["title"].strip()
        if r.get("content"):
            item["description"] = r["content"].strip()
        out.append(item)
    return out


# ---------- main ----------

async def run(
    query: str,
    platform: str,
    model_override: Optional[str],
    extra_sources: int,
    auto_fetch_top: int = 0,
) -> dict:
    session_id = new_session_id()
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    model = grok_model(model_override)

    providers_used: list[str] = []
    providers_failed: list[str] = []

    # Allocation matches upstream server.py:153-164:
    # If both keys present, Firecrawl takes 100% of N (it's breadth-prioritized).
    has_tavily = bool(tavily_api_key())
    has_firecrawl = bool(firecrawl_api_key())
    firecrawl_count = 0
    tavily_count = 0
    if extra_sources > 0:
        if has_firecrawl and has_tavily:
            firecrawl_count = extra_sources
            tavily_count = 0
        elif has_firecrawl:
            firecrawl_count = extra_sources
        elif has_tavily:
            tavily_count = extra_sources

    async def safe_grok() -> tuple[str, list[dict]]:
        try:
            return await _grok_search(query, platform, model)
        except Exception as e:
            debug(f"grok search failed: {e}")
            return "", []

    coros: list = [safe_grok()]
    if tavily_count > 0:
        coros.append(_tavily_search(query, tavily_count))
    if firecrawl_count > 0:
        coros.append(_firecrawl_search(query, firecrawl_count))

    gathered = await asyncio.gather(*coros)
    grok_result_pair = gathered[0] or ("", [])
    grok_result: str = grok_result_pair[0] or ""
    grok_annotations: list[dict] = grok_result_pair[1] or []
    idx = 1
    tavily_results = None
    firecrawl_results = None
    if tavily_count > 0:
        tavily_results = gathered[idx]
        idx += 1
    if firecrawl_count > 0:
        firecrawl_results = gathered[idx]

    # Track providers_used / providers_failed based on result content.
    # v3: distinguish "grok" (text only, no native search citations) from
    # "grok-web-search" (text AND structured annotations from Responses API
    # web_search tool). When annotations are present, native live search ran;
    # when absent, Grok answered from training data only and we fell back to
    # heuristic citation extraction.
    if grok_result.strip():
        if grok_annotations:
            providers_used.append("grok-web-search")
        else:
            providers_used.append("grok")
    else:
        providers_failed.append("grok")
    if tavily_count > 0:
        if tavily_results:
            providers_used.append("tavily")
        else:
            providers_failed.append("tavily")
    if firecrawl_count > 0:
        if firecrawl_results:
            providers_used.append("firecrawl")
        else:
            providers_failed.append("firecrawl")

    # v3: prefer native annotations from the Responses API. They're real,
    # structured citations from Grok's actual web_search call — no
    # confabulation, no URL invention, no parsing heuristics needed.
    # If annotations is empty (rare: only when search_mode produced none, or
    # when grok_responses_call fell back to a non-streaming response that
    # didn't include annotations), fall through to the v1/v2/v2.1 heuristic
    # citation extraction chain as a safety net.
    native_sources = normalize_responses_annotations(grok_annotations)
    if native_sources:
        answer = grok_result
        grok_sources = native_sources
        debug(f"grok annotations: {len(native_sources)} native sources extracted")
    else:
        answer, grok_sources = split_answer_and_sources(grok_result)
        if grok_result.strip():
            debug(
                f"grok annotations empty; fell back to heuristic citation parser "
                f"(found {len(grok_sources)} sources)"
            )

    extras = _extras_to_sources(tavily_results, firecrawl_results)
    merged = _merge_sources(grok_sources, extras)

    # Auto-fetch-top: parallel fetch of the top N source URLs via the default
    # fetch chain (Tavily → Firecrawl). Grok is NOT used here to keep bulk
    # fetch fast and upstream-faithful. Imported locally to avoid a circular
    # import at module load.
    fetched_pages: list[dict] = []
    if auto_fetch_top > 0 and merged:
        try:
            from agentic_fetch import fetch_url  # noqa: WPS433 — intentional lazy import
        except ImportError as e:
            debug(f"auto-fetch-top: could not import agentic_fetch.fetch_url: {e}")
        else:
            top_urls = [
                s["url"] for s in merged[:auto_fetch_top] if isinstance(s.get("url"), str)
            ]
            debug(f"auto-fetch-top: fetching {len(top_urls)} pages in parallel")

            async def _fetch_one(u: str) -> dict:
                md, engine = await fetch_url(u, engine="auto")
                return {
                    "url": u,
                    "engine": engine or "none",
                    "markdown": md or "",
                    "ok": bool(md),
                }

            fetched_pages = list(await asyncio.gather(*(_fetch_one(u) for u in top_urls)))

    result = {
        "session_id": session_id,
        "created_at": created_at,
        "model": model,
        "query": query,
        "platform": platform,
        "extra_sources": extra_sources,
        "content": answer,
        "sources": merged,
        "sources_count": len(merged),
        "providers_used": providers_used,
        "providers_failed": providers_failed,
    }
    if fetched_pages:
        result["fetched_pages"] = fetched_pages

    # Persist the session to disk cache so downstream scripts (agentic_rank,
    # agentic_get_sources, agentic_extract --session-id) can compose on it.
    try:
        write_session(session_id, result)
        pruned = prune_sessions()
        if pruned:
            debug(f"pruned {pruned} old sessions")
    except Exception as e:
        debug(f"session cache write failed: {e}")

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="agentic_search — Grok-primary deep web search with optional Tavily/Firecrawl fusion."
    )
    parser.add_argument("--query", required=True, help="Natural-language search query.")
    parser.add_argument("--platform", default="", help="Optional platform focus (e.g., 'GitHub', 'Reddit').")
    parser.add_argument("--model", default="", help="Override GROK_MODEL for this call only.")
    parser.add_argument(
        "--extra-sources",
        type=int,
        default=0,
        help="Number of supplementary results from Tavily/Firecrawl. 0 disables.",
    )
    parser.add_argument(
        "--auto-fetch-top",
        type=int,
        default=0,
        help="After the search, fetch the top N source URLs in parallel via Tavily→Firecrawl and include their markdown in the output under 'fetched_pages'. 0 disables.",
    )
    args = parser.parse_args()

    try:
        result = asyncio.run(
            run(
                args.query,
                args.platform,
                args.model or None,
                args.extra_sources,
                auto_fetch_top=args.auto_fetch_top,
            )
        )
    except SystemExit as e:
        # Config errors raised from _http
        msg = str(e) if e.code != 0 else "configuration error"
        print(json.dumps({"error": msg}, ensure_ascii=False))
        return 1
    except Exception as e:
        print(json.dumps({"error": f"unexpected: {type(e).__name__}: {e}"}, ensure_ascii=False))
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
