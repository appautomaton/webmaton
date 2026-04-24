---
name: html-to-markdown
description: Convert a URL or HTML into clean Markdown with metadata using markmaton. Handles browser capture for JS-heavy pages and deterministic HTML-to-Markdown conversion in one skill.
---

# HTML to Markdown

## Composes with

- **Called by** — `RECIPES.md` `parse-jd` recipe (step 1). Any capture-a-web-page task in the workspace prefers this over built-in `WebFetch`.
- **Wraps** — nodriver (CDP-based headless browser capture for JS-heavy pages, with Playwright Chromium discovery) and markmaton (HTML→Markdown with main-content extraction, metadata, and link/image inventory). See `references/integration-patterns.md` for browser-vs-fetch guidance.
- **Outputs** — JSON envelope by default (markdown body + metadata + links + images + quality signals). Use `--output-format markdown` when only the raw Markdown body is needed.

Converts a URL or HTML into clean Markdown plus metadata, links, images, and quality signals.

## From a URL

Capture the page and convert in one pipeline:

```bash
uv run --script scripts/capture_html.py <url> \
  | uv run --script scripts/markmaton_convert.py --from-capture --output-format json
```

The capture script outputs a JSON envelope by default. `--from-capture` reads it and extracts `html`, `url`, `final_url`, and `content_type` automatically — no context lost, URL typed once.

- Add `--wait-selector <css>` or `--wait-text <string>` to the capture step for pages that need a readiness signal.
- Prefer a simple fetch over browser capture for static articles, wikis, and server-rendered docs.

## From HTML

```bash
uv run --script scripts/markmaton_convert.py --html-file page.html \
  --url <url> --output-format json
```

Or from stdin:

```bash
echo "$html" | uv run --script scripts/markmaton_convert.py --url <url>
```

Pass `--url` when available — it improves link resolution and canonical metadata.

## Key defaults

- Output: `json`. Use `--output-format markdown` for raw Markdown only.
- Main-content extraction: on. Use `--full-content` to disable.
- Capture: always headless. Timeout `10s`, override with `--timeout`.
- Browser discovery: user's Chrome → user's Chromium → Playwright's Chromium.

## References

Read only when needed:

- `references/usage.md` — full CLI reference for both scripts
- `references/integration-patterns.md` — browser vs fetch guidance, contracts, parser defaults
