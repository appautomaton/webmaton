---
name: agentic-search
description: "Grok-primary deep research skill for source-backed web work. Use when the task needs current web research, grounded citations, supplementary Tavily/Firecrawl source discovery, high-fidelity page-to-Markdown fetch, Tavily site mapping, verbatim quote extraction, source reranking, or reusable multi-step research sessions. Use as a supplement when ordinary search results feel incomplete, thinly sourced, or need more URLs, quotes, fetched pages, or session composition; not for simple one-off facts."
---

# agentic-search

| # | Script | Intent |
|---|---|---|
| 1 | `scripts/agentic_search.py` | Research a topic — AI-reasoned answer with citations |
| 2 | `scripts/agentic_fetch.py` | Full page → Markdown, no summarization |
| 3 | `scripts/agentic_map.py` | Enumerate URLs under a site (Tavily-only) |
| 4 | `scripts/agentic_extract.py` | Verbatim title + 2–4 quotes from a URL |
| 5 | `scripts/agentic_rank.py` | Rerank session sources by a refined query |
| 6 | `scripts/agentic_get_sources.py` | Retrieve or list cached sessions |

## How to invoke

All scripts use PEP 723 inline deps — always invoke via `uv run`. Allow up to 3 minutes per call.

```bash
uv run scripts/agentic_search.py --query "..." [--extra-sources N] [--auto-fetch-top N] [--platform "..."]
uv run scripts/agentic_fetch.py --url "..." [--engine auto|tavily|firecrawl|grok]
uv run scripts/agentic_map.py --url "..." [--instructions "..."] [--limit N]
uv run scripts/agentic_extract.py --url "..." [--session-id S]
uv run scripts/agentic_rank.py --query "..." --session-id S
uv run scripts/agentic_get_sources.py --list | --session-id S
```

## Session workflow

`agentic_search` generates a `session_id` persisted to disk — the connective tissue for composing steps:

```
agentic_search → session_id
     ├─→ agentic_rank --session-id S --query Q     (rerank in place; mutates session)
     ├─→ agentic_extract --session-id S --url U    (append verbatim quotes)
     └─→ agentic_get_sources --session-id S        (inspect full session)
```

Sessions survive between invocations but may be cleared on OS reboot.

## Operating discipline

Load the relevant reference before composing a non-trivial query — don't load all four upfront.

- **`references/search-discipline.md`** — two-pass methodology, citation contract, time-context heuristic. Read for research tasks.
- **`references/fetch-fidelity.md`** — engine trade-offs, fidelity guarantees, when not to fetch. Read before presenting extracted content.
- **`references/extract-and-rank.md`** — extract vs fetch, when to rank, session composition patterns. Read for multi-step workflows.
- **`references/provider-quirks.md`** — env vars, provider schemas, retry policy, debugging. Read when configuring or debugging.

## Failure modes

- No `GROK_API_KEY` / `GROK_API_URL` → config error on any Grok-using script.
- `agentic_fetch --engine auto` total failure → retry with `--engine grok` or fall back to built-in `WebFetch`.
- `agentic_map` without `TAVILY_API_KEY` → hard exit.
- `agentic_rank --session-id S` session expired → re-run `agentic_search`.
- `sources_count: 0` with non-empty `content` → Grok used training data; check `providers_used` (`grok-web-search` = real citations, `grok` = heuristic fallback).
