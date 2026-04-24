# Provider configuration

Read this only when configuring keys, changing providers, or debugging provider
behavior. Keep routine search/fetch usage in `SKILL.md`.

## Environment

| Variable | Default | Used by | Notes |
|---|---:|---|---|
| `GROK_API_URL` | none | search, fetch:grok, extract, rank | xAI base URL, usually `https://api.x.ai/v1`; the script appends `/responses`. |
| `GROK_API_KEY` | none | search, fetch:grok, extract, rank | Required for every Grok call. |
| `GROK_MODEL` | `grok-4-1-fast-reasoning` | search, fetch:grok, extract, rank | `--model` overrides this per call. |
| `TAVILY_API_KEY` | none | search extras, fetch:auto/tavily, map | `agentic_map` requires it. |
| `TAVILY_API_URL` | `https://api.tavily.com` | Tavily calls | Override only for a proxy/self-hosted endpoint. |
| `FIRECRAWL_API_KEY` | none | search extras, fetch:auto/firecrawl | Firecrawl is skipped when absent. |
| `FIRECRAWL_API_URL` | `https://api.firecrawl.dev/v2` | Firecrawl calls | Keep the `/v2` suffix. |
| `GROK_DEBUG` | `false` | all scripts | `true`, `1`, or `yes` logs diagnostics to stderr. |

Retry tuning is optional: `GROK_RETRY_MAX_ATTEMPTS=3`,
`GROK_RETRY_MULTIPLIER=1`, `GROK_RETRY_MAX_WAIT=10`.

## Grok behavior

- Uses xAI Responses API: `POST {GROK_API_URL}/responses`.
- The default model is `grok-4-1-fast-reasoning`.
- `agentic_search` sends `web_search` and `x_search`.
- `agentic_fetch --engine grok` and `agentic_extract` send `web_search`.
- `agentic_rank` sends no search tools; it reranks the existing source list.
- Do not send `reasoning_effort` or `reasoning` for `grok-4-1-fast-*`.
  xAI documents that these models reason automatically and reject that setting.

Minimal request shape:

```json
{
  "model": "grok-4-1-fast-reasoning",
  "instructions": "<system prompt>",
  "input": [{"role": "user", "content": "<request>"}],
  "tools": [{"type": "web_search"}],
  "stream": true
}
```

Legacy `/chat/completions` live-search behavior is not part of this skill.
xAI moved live search to Responses API tools; do not reintroduce
`search_parameters`.

## Fetch and extra-source behavior

`agentic_fetch --engine auto` is a chain:

```text
Tavily extract -> Firecrawl scrape -> error
```

Grok is available only when explicitly selected with `--engine grok`.

`agentic_search --extra-sources N` always runs Grok first. Extra sources are
added only when Tavily or Firecrawl keys exist. When both keys exist, Firecrawl
gets the full extra-source budget because it is better for broad URL discovery.

## Debugging

- Set `GROK_DEBUG=true` to log provider decisions to stderr while keeping
  stdout parseable.
- Retryable statuses are `408`, `429`, `500`, `502`, `503`, `504`.
- `Retry-After` is honored on `429`; otherwise retries use exponential backoff.
- If Grok returns text but no citation annotations, the script reports provider
  `grok` rather than `grok-web-search`; treat that as ungrounded until fetched.

Official behavior references:

- xAI Reasoning: https://docs.x.ai/developers/model-capabilities/text/reasoning
- xAI Responses API: https://docs.x.ai/developers/model-capabilities/text/generate-text
