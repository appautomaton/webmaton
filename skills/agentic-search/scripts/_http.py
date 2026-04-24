"""Shared HTTP utilities for agentic-search scripts.

Provides:
- Async retry wrapper with Retry-After header parsing.
- Env var helpers for config (mirroring upstream GrokSearch v1.9.2 surface).
- Debug logging to stderr (gated by GROK_DEBUG).

Pure stdlib + httpx + tenacity. No fastmcp, no pydantic, no upstream package.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)
from tenacity.wait import wait_base


# ---------- dotenv loader (no python-dotenv dependency) ----------

_DOTENV_FILENAME = ".env.search.local"


def _load_dotenv() -> Optional[Path]:
    """Walk up from this file's directory looking for .env.search.local and
    load KEY=value pairs into os.environ. Existing env vars take precedence,
    so shell exports always win over file values. Returns the loaded path
    (for debug logging) or None if no file was found."""
    here = Path(__file__).resolve().parent
    candidates = [here] + list(here.parents)[:6]  # cap walk depth
    for parent in candidates:
        candidate = parent / _DOTENV_FILENAME
        if not candidate.is_file():
            continue
        try:
            for raw in candidate.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                # strip surrounding quotes (single or double) if matched
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                if key and key not in os.environ:
                    os.environ[key] = value
        except OSError:
            return None
        return candidate
    return None


_LOADED_DOTENV = _load_dotenv()


# ---------- env / config ----------

RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def env_str(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.getenv(name)
    return val if val is not None else default


def env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.lower() in ("true", "1", "yes")


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def debug_enabled() -> bool:
    return env_bool("GROK_DEBUG", False)


def debug(msg: str) -> None:
    if debug_enabled():
        print(f"[agentic-search] {msg}", file=sys.stderr, flush=True)


def _emit_dotenv_debug_once() -> None:
    if debug_enabled() and _LOADED_DOTENV is not None:
        # Print once at first debug call so we know which file was sourced.
        print(f"[agentic-search] loaded dotenv: {_LOADED_DOTENV}", file=sys.stderr, flush=True)


_emit_dotenv_debug_once()


def retry_max_attempts() -> int:
    return env_int("GROK_RETRY_MAX_ATTEMPTS", 3)


def retry_multiplier() -> float:
    return env_float("GROK_RETRY_MULTIPLIER", 1.0)


def retry_max_wait() -> int:
    return env_int("GROK_RETRY_MAX_WAIT", 10)


# ---------- Grok config ----------

def grok_api_url() -> str:
    url = env_str("GROK_API_URL")
    if not url:
        raise SystemExit(
            "error: GROK_API_URL is not set. "
            "Set it to your OpenAI-compatible endpoint (e.g. https://api.x.ai/v1)."
        )
    return url


def grok_api_key() -> str:
    key = env_str("GROK_API_KEY")
    if not key:
        raise SystemExit("error: GROK_API_KEY is not set.")
    return key


def grok_model(override: Optional[str] = None) -> str:
    model = override or env_str("GROK_MODEL") or "grok-4-1-fast-reasoning"
    # OpenRouter requires :online suffix for live web access
    try:
        url = grok_api_url()
    except SystemExit:
        return model
    if "openrouter" in url and ":online" not in model:
        return f"{model}:online"
    return model


# ---------- Tavily config ----------

def tavily_api_url() -> str:
    return env_str("TAVILY_API_URL", "https://api.tavily.com") or "https://api.tavily.com"


def tavily_api_key() -> Optional[str]:
    return env_str("TAVILY_API_KEY")


# ---------- Firecrawl config ----------

def firecrawl_api_url() -> str:
    return env_str("FIRECRAWL_API_URL", "https://api.firecrawl.dev/v2") or "https://api.firecrawl.dev/v2"


def firecrawl_api_key() -> Optional[str]:
    return env_str("FIRECRAWL_API_KEY")


# ---------- retry strategy ----------

def is_retryable_exception(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS_CODES
    return False


class WaitWithRetryAfter(wait_base):
    """Honor Retry-After on 429s, otherwise exponential backoff with a flat
    +3s bump on RemoteProtocolError to give the connection time to recover."""

    def __init__(self, multiplier: float, max_wait: int):
        self._base_wait = wait_random_exponential(multiplier=multiplier, max=max_wait)
        self._protocol_error_base = 3.0

    def __call__(self, retry_state):
        if retry_state.outcome and retry_state.outcome.failed:
            exc = retry_state.outcome.exception()
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                retry_after = self._parse_retry_after(exc.response)
                if retry_after is not None:
                    return retry_after
            if isinstance(exc, httpx.RemoteProtocolError):
                return self._base_wait(retry_state) + self._protocol_error_base
        return self._base_wait(retry_state)

    @staticmethod
    def _parse_retry_after(response: httpx.Response) -> Optional[float]:
        header = response.headers.get("Retry-After")
        if not header:
            return None
        header = header.strip()
        if header.isdigit():
            return float(header)
        try:
            retry_dt = parsedate_to_datetime(header)
            if retry_dt.tzinfo is None:
                retry_dt = retry_dt.replace(tzinfo=timezone.utc)
            delay = (retry_dt - datetime.now(timezone.utc)).total_seconds()
            return max(0.0, delay)
        except (TypeError, ValueError):
            return None


def make_retrying() -> AsyncRetrying:
    return AsyncRetrying(
        stop=stop_after_attempt(retry_max_attempts() + 1),
        wait=WaitWithRetryAfter(retry_multiplier(), retry_max_wait()),
        retry=retry_if_exception(is_retryable_exception),
        reraise=True,
    )


# ---------- xAI Responses API (v3 — primary Grok call path) ----------
#
# As of January 2026, xAI deprecated the `search_parameters` field on the
# `/v1/chat/completions` endpoint and migrated live web search to the new
# `/v1/responses` endpoint with server-side `web_search` and `x_search` tools.
# All Grok-mediated scripts in this skill (search, fetch, extract, rank)
# call into `grok_responses_call` below to get real grounded citations.
#
# Docs: https://docs.x.ai/docs/guides/live-search
#       https://docs.x.ai/docs/guides/tools/search-tools


async def parse_responses_streaming(
    response: httpx.Response,
) -> tuple[str, list[dict]]:
    """Parse xAI Responses API SSE stream.

    Returns (accumulated_text, annotations).

    Each SSE line is `data: {"type": "<event>", ...}`. Event types handled:
        response.created                      → ignored (start marker)
        response.output_item.added            → ignored (item begin)
        response.output_text.delta            → append `delta` field to text
        response.output_text.annotation.added → append `annotation` to citations
        response.completed                    → terminal (normal exit)
        response.incomplete                   → terminal (capped/cut off)
        response.failed                       → terminal (raise httpx.HTTPError)
        all other types                       → ignored (forward-compat)

    Falls back to non-streaming JSON parse if no events parse — some proxies
    buffer the full body into one chunk. The fallback walks the standard
    Responses API response shape: output[].content[].text + annotations[].

    Mirrors xAI's documented streaming envelope (which itself mirrors OpenAI's
    Responses API streaming events). On `response.failed`, raises httpx.HTTPError
    so the caller's `make_retrying()` loop can decide whether to retry.
    """
    content = ""
    annotations: list[dict] = []
    saw_event = False
    full_body: list[str] = []

    async for line in response.aiter_lines():
        line = line.strip()
        if not line:
            continue
        full_body.append(line)
        if not line.startswith("data:"):
            continue
        payload = line[5:].lstrip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue

        event_type = event.get("type", "")
        saw_event = True

        if event_type == "response.output_text.delta":
            delta = event.get("delta")
            if isinstance(delta, str):
                content += delta
            continue

        if event_type == "response.output_text.annotation.added":
            ann = event.get("annotation")
            if isinstance(ann, dict):
                annotations.append(ann)
            continue

        if event_type in ("response.completed", "response.incomplete"):
            # Terminal events; loop will end naturally as the stream closes
            continue

        if event_type == "response.failed":
            err = event.get("error") or {}
            err_msg = err.get("message") if isinstance(err, dict) else str(err)
            raise httpx.HTTPError(f"xAI Responses API stream failed: {err_msg}")

        # Other event types (response.created, response.output_item.added,
        # response.content_part.added/done, etc.) are ignored — we don't need
        # them for text+citation extraction. Forward-compat by design.

    # Fallback: no SSE events parsed (proxy buffered body, or non-streaming
    # response was returned despite stream=true). Walk the documented response
    # envelope: {output: [{type, content: [{type: "output_text", text, annotations}]}]}.
    if not saw_event and full_body:
        try:
            data = json.loads("".join(full_body))
        except json.JSONDecodeError:
            return content, annotations
        if not isinstance(data, dict):
            return content, annotations
        for item in data.get("output", []) or []:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for part in item.get("content", []) or []:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "output_text":
                    text = part.get("text")
                    if isinstance(text, str):
                        content += text
                    for ann in part.get("annotations", []) or []:
                        if isinstance(ann, dict):
                            annotations.append(ann)

    return content, annotations


# Recognized auxiliary fields on annotation objects, copied through into our
# normalized source dict shape. The `url` field is required; everything else
# is optional. We deliberately accept multiple synonyms for the same concept
# (e.g. snippet/summary/description) so we're robust to xAI/OpenAI naming drift.
_ANNOTATION_FIELD_ALIASES = {
    "title": "title",
    "snippet": "description",
    "summary": "description",
    "description": "description",
    "source": "source",
    "published_date": "published_date",
    "publishedAt": "published_date",
    "date": "published_date",
}


def normalize_responses_annotations(annotations: list[dict]) -> list[dict]:
    """Convert Responses API annotation objects to our standard source dict shape.

    Permissive parser:
      - Skips entries that aren't dicts
      - Skips entries without a `url` field starting with http(s)://
      - Strips trailing punctuation from URLs (matches `_extract_unique_urls`)
      - Dedupes by URL across the input list (first-seen wins)
      - Copies recognized auxiliary fields via `_ANNOTATION_FIELD_ALIASES`
      - Tags every result with `provider="grok-web-search"` so downstream
        logic can distinguish native Grok citations from Tavily/Firecrawl extras

    Returns a list of `{url, title?, description?, source?, published_date?, provider}`
    dicts. Output schema matches the upstream `_normalize_sources` shape so
    downstream merging/dedupe code is unchanged.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for ann in annotations or []:
        if not isinstance(ann, dict):
            continue
        url = ann.get("url")
        if not isinstance(url, str):
            continue
        url = url.strip().rstrip(".,;:!?")
        if not url.startswith(("http://", "https://")):
            continue
        if url in seen:
            continue
        seen.add(url)
        rec: dict = {"url": url, "provider": "grok-web-search"}
        for src_key, dst_key in _ANNOTATION_FIELD_ALIASES.items():
            v = ann.get(src_key)
            if isinstance(v, str) and v.strip():
                rec[dst_key] = v.strip()
        out.append(rec)
    return out


# ---------- xAI Responses API (v3 — primary Grok call path) ----------
#
# As of January 2026, xAI deprecated the `search_parameters` field on the
# `/v1/chat/completions` endpoint and migrated live web search to the new
# `/v1/responses` endpoint with server-side `web_search` and `x_search` tools.
# All Grok-mediated scripts in this skill (search, fetch, extract, rank)
# call into `grok_responses_call` below to get real grounded citations.
#
# Docs: https://docs.x.ai/docs/guides/live-search
#       https://docs.x.ai/docs/guides/tools/search-tools


async def grok_responses_call(
    *,
    instructions: str,
    user_content: str,
    model: Optional[str] = None,
    enable_search: bool = True,
    search_mode: str = "auto",
    tools: Optional[list[str]] = None,
    allowed_domains: Optional[list[str]] = None,
    excluded_domains: Optional[list[str]] = None,
    timeout_read: float = 120.0,
) -> tuple[str, list[dict]]:
    """POST to xAI Responses API (`/v1/responses`) with streaming.

    Returns ``(text_content, annotations)`` where annotations is the list of
    raw Responses-API annotation objects (use `normalize_responses_annotations`
    to convert into our source-dict shape).

    Single shared helper used by all 4 Grok call sites:
      - agentic_search.py:_grok_search          (tools=["web_search", "x_search"])
      - agentic_fetch.py:_grok_fetch            (tools=["web_search"])
      - agentic_extract.py:describe_url         (tools=["web_search"])
      - agentic_rank.py:rank_sources            (enable_search=False)

    The `instructions` field is the preferred way to set the system prompt
    on the Responses API (cleaner than embedding role=system in input[]).

    Live search tools are specified via the `tools` parameter:
      - `tools=["web_search"]` — search the web and browse pages (default)
      - `tools=["x_search"]` — search X/Twitter posts, users, threads
      - `tools=["web_search", "x_search"]` — both (recommended for research)

    The legacy `search_parameters` field has been deprecated by xAI
    (returns 410 Gone with error: "Live search is deprecated. Please switch
    to the Agent Tools API"), so we use tools exclusively.

    The `search_mode` argument is a soft hint preserved for callers' clarity
    of intent — it does NOT map to a request field anymore.

    Domain filters: `allowed_domains` and `excluded_domains` are mutually
    exclusive per xAI docs. We pass at most one. Both `None` means no filter.

    Auth, retry strategy, base URL, and model resolution all reuse the
    existing helpers in this module — no duplicate config plumbing.
    """
    api_url = grok_api_url()
    api_key = grok_api_key()
    effective_model = grok_model(model)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload: dict = {
        "model": effective_model,
        "instructions": instructions,
        "input": [
            {"role": "user", "content": user_content},
        ],
        "stream": True,
    }

    if enable_search:
        # Build the tools array. Default to web_search only for backward compat.
        if tools is None:
            tools = ["web_search"]
        
        # Validate tool types
        valid_tools = {"web_search", "x_search"}
        for t in tools:
            if t not in valid_tools:
                raise ValueError(f"Invalid tool type: {t}. Valid options: {valid_tools}")
        
        # Build tools payload
        tools_payload = [{"type": t} for t in tools]
        
        # Apply filters only to web_search (xAI requires filters on specific tool)
        if "web_search" in tools and (allowed_domains or excluded_domains):
            if allowed_domains and excluded_domains:
                debug(
                    "grok_responses_call: both allowed_domains and excluded_domains "
                    "set; allowed_domains wins (xAI requires they be mutually exclusive)"
                )
            # Find the web_search tool and add filters
            for tool in tools_payload:
                if tool["type"] == "web_search":
                    if allowed_domains:
                        tool["filters"] = {"allowed_domains": list(allowed_domains)[:5]}
                    elif excluded_domains:
                        tool["filters"] = {"excluded_domains": list(excluded_domains)[:5]}
                    break
        
        payload["tools"] = tools_payload

    debug(
        f"grok_responses_call: model={effective_model} "
        f"search={enable_search} mode={search_mode if enable_search else 'n/a'} "
        f"input_chars={len(user_content)}"
    )

    timeout = httpx.Timeout(connect=6.0, read=timeout_read, write=10.0, pool=None)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        async for attempt in make_retrying():
            with attempt:
                async with client.stream(
                    "POST",
                    f"{api_url.rstrip('/')}/responses",
                    headers=headers,
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    text, annotations = await parse_responses_streaming(response)
                    if annotations:
                        # One-time debug dump of the first annotation shape so
                        # we can refine the field aliases if xAI uses unexpected
                        # field names. Cheap; only fires when GROK_DEBUG=true.
                        debug(f"grok_responses_call: first annotation shape: {annotations[0]}")
                    return text, annotations

    return "", []
