# Extract and rank

Loaded when composing a multi-step workflow: `agentic_extract` for quote-mining, `agentic_rank` for source reordering, or both chained after a search.

## `agentic_extract` vs `agentic_fetch`

| | `agentic_extract` | `agentic_fetch` |
|---|---|---|
| **Output** | Title + 2–4 verbatim quotes (JSON) | Full page as Markdown |
| **Engine** | Grok (`search_mode=on`) — LLM browses the URL | Tavily → Firecrawl chain (no LLM) |
| **Cost** | Low — just a prompt + short structured output | Medium — full content retrieval |
| **Use when** | You want the author's own words on a source | You need the full page for reading, diffing, or downstream tools |

Use `agentic_extract` first to decide whether a source is worth fetching in full. If the quotes confirm relevance, follow up with `agentic_fetch`.

## When to use `agentic_rank`

Run `agentic_rank` after `agentic_search` when:

- The broad search returned many sources (≥ 5) and you want to prioritise before fetching.
- The user has narrowed their question — use the refined angle as the `--query` to rerank.
- You want the session's source list reordered before handing `session_id` to `agentic_extract` or `agentic_get_sources`.

Skip `agentic_rank` for small result sets (< 5 sources) — the LLM overhead isn't worth it.

## Composable workflow

```
agentic_search --query "broad question" → session_id
     │
     ├─→ agentic_rank --session-id S --query "refined lens"   (optional; mutates session in place)
     │
     ├─→ agentic_extract --session-id S --url <top URL>       (append quotes to session)
     │
     └─→ agentic_fetch --url <top URL>                        (full page if quotes confirmed relevance)
```

`session_id` is the connective tissue. Each script that accepts `--session-id` reads from and writes back to the same disk-cached JSON — so the session accumulates results across steps.

## Rank mutates the session

`agentic_rank --session-id S` rewrites the `sources` list in the session JSON. Subsequent `agentic_get_sources --session-id S` and `agentic_extract --session-id S` see the new order. This is irreversible — if you want to preserve the original order, copy the session JSON out first via `agentic_get_sources --session-id S > backup.json`.

## `agentic_rank` without a session

Pass a raw source list via `--sources-json -` (stdin) for ad-hoc reranking without a prior search:

```bash
echo '[{"url": "https://a.com", "title": "A"}, {"url": "https://b.com", "title": "B"}]' \
  | uv run scripts/agentic_rank.py --query "production-ready open source" --sources-json -
```

Output does not include `session_id` in this mode.
