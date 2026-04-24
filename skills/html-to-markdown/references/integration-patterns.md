# Integration Patterns

## When to use a real browser

Prefer browser capture for:

- app-shell pages
- commerce pages
- form-heavy pages
- client-side card/list pages
- modern landing pages with substantial hydration
- pages where a simple HTTP fetch does not produce meaningful content

Prefer a simple fetch for:

- static article pages
- wiki pages
- docs pages that are mostly server-rendered
- direct JSON or API endpoints

## Capture contract

`capture_html.py` produces:

- `html` — rendered page HTML
- `url` — the requested URL
- `final_url` — browser location after redirects
- `content_type` — from `document.contentType`
- `title` — from `document.title` (informational)
- `rendered` — always `true` (informational)

## Convert contract

`markmaton_convert.py` accepts:

- HTML content (stdin or `--html-file`)
- optional `url` (improves canonical fallback and absolute link normalization)
- optional `final_url`
- optional `content_type`

## Good defaults

Capture:

- Use default JSON output when piping into conversion with `--from-capture`. This preserves `final_url` and `content_type`.
- Add `--wait-selector` or `--wait-text` only when the page needs a stronger readiness signal than `<body>`.

Convert:

- Start with main-content mode.
- Use `--full-content` only when main-content extraction is clearly too aggressive.
- Use `--include-selector` or `--exclude-selector` only when a page has a stable structural reason for it.
- Do not turn parser usage into site-specific patching unless the task explicitly calls for that.
