# Fetch fidelity contract

Loaded when you're about to present extracted page content to the user. Tells you what guarantees `agentic_fetch.py` makes (and doesn't).

## What `agentic_fetch` returns

A Markdown string on stdout. The script accepts a `--engine` flag to pick among four routing modes:

- **`auto`** (default): Tavily Extract → Firecrawl Scrape fallback chain. Faithful to upstream GrokSearch `web_fetch`. Grok is NOT auto-added to the chain.
- **`tavily`**: Only Tavily Extract. Fast, structured, good at modern HTML.
- **`firecrawl`**: Only Firecrawl Scrape with progressive `waitFor` retries (1.5s → 3s → 4.5s). Best for JS-heavy SPAs.
- **`grok`**: Only Grok, using the `FETCH_PROMPT` "Web Content Fetcher" persona (100%-fidelity markdown with metadata header). LLM-mediated; last-resort for pages where Tavily and Firecrawl both fail.

If the chosen engine(s) return nothing, the script prints an error starting with `error:` to stderr and exits 1. Provenance (which engine actually succeeded) is logged to stderr only when `GROK_DEBUG=true` — stdout stays pure markdown so pipes and grep workflows are unaffected.

### Engine trade-offs

| Engine | Speed | Fidelity | Handles JS | Cost | Notes |
|---|---|---|---|---|---|
| `tavily` | Fast | High (structured HTML) | Limited | Low | First-choice for static pages and docs |
| `firecrawl` | Medium | High (rendered HTML) | Yes | Medium | Choose when Tavily returns empty or for SPAs |
| `grok` | Slow | LLM-interpreted | N/A (Grok has its own retrieval) | Higher (LLM tokens) | Choose for paywalled pages, when both above fail, or when you want the Chinese "Web Content Fetcher" persona's 100%-fidelity guarantee applied by the model itself |
| `auto` | Fast→Medium | High | Via fallback | Low→Medium | Default. Tries tavily, falls back to firecrawl on empty/error |

## The fidelity guarantee

Both providers aim for **100% content fidelity**. Specifically:

- **No summarization, paraphrasing, rewriting, or "improvement" of the source text.** What's on the page is what comes back.
- **All headings preserved** with their hierarchy (`<h1>` → `#`, `<h2>` → `##`, ...).
- **All formatting preserved**: bold, italic, code blocks (with language tags), inline code, blockquotes, horizontal rules.
- **All lists preserved** including nesting and ordering.
- **Tables preserved** in Markdown table syntax.
- **Links preserved** as `[text](url)`.
- **Images preserved** as `![alt](url)`.
- **Code blocks preserved verbatim** including indentation and language identifier.

## What gets dropped (intentionally)

- `<script>`, `<style>`, `<iframe>`, `<noscript>` tags.
- Ads, tracking pixels, social-share buttons, cookie banners, newsletter popups.
- Navigation chrome (top nav, footer, sidebars) — usually. Provider-dependent.

If the user needs the navigation/footer too, that's a sign you should use raw `curl` + manual parsing instead, not `agentic_fetch`.

## What you can rely on for downstream use

Because of the fidelity guarantee, content from `agentic_fetch` is safe to:

- **Quote verbatim** to the user without checking if it was paraphrased.
- **Search within** for specific terms, version numbers, code snippets.
- **Diff against another version** of the same page.
- **Pass to another tool** that needs the actual page text.

It is NOT safe to assume:
- **Dynamically loaded content captured.** Both providers attempt to wait for JS but heavy SPAs may still return partial content. If a page looks suspiciously short, retry once or fall back.
- **Auth-walled pages work.** Neither provider has your cookies. For paywalled content, this skill won't help.
- **Real-time content is current.** Providers may serve from cache; stale by minutes to hours is possible.

## When NOT to use `agentic_fetch`

- **Quick fact lookup** where summarization is fine → use built-in `WebFetch` (faster, cheaper).
- **Just need the URL list** of a site → use `agentic_map.py` instead, then fetch only the pages you actually need.
- **The user already pasted the content** → don't re-fetch, just use what they gave you.
- **Local files or files you can read with the Read tool** → use Read.

## Presenting fetched content to the user

When you've fetched a page:

1. **State the URL and what you got.** "I fetched <url>; here's the relevant section." Don't pretend you knew it without fetching.
2. **Quote with attribution.** Use blockquotes for verbatim excerpts: `> ...`.
3. **Don't dump the whole thing** unless asked. Pull out the relevant sections; offer to fetch more on request.
4. **Note if extraction looked degraded** — short content for a long page, garbled formatting, missing sections. The user should know if the fidelity guarantee was compromised.
5. **Preserve code blocks exactly** when relaying to the user. Don't re-format them.
