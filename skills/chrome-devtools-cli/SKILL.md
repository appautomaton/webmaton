---
name: chrome-devtools-cli
description: "Use when a task needs Chrome DevTools from the shell: automate a live Chrome browser with `chrome-devtools`, inspect accessibility snapshots and UIDs, click/fill/navigate pages, evaluate JavaScript, inspect console and network activity, take screenshots, run Lighthouse, capture performance traces, or connect to an existing debuggable Chrome. This is CLI mode, not MCP client setup."
---

# chrome-devtools-cli

The package is `chrome-devtools-mcp`, but the action CLI is `chrome-devtools`. Use `chrome-devtools <tool> ...` for this skill. Do not use `npx chrome-devtools-mcp@latest` unless you are configuring an MCP server outside this skill.

## Core Workflow

```bash
chrome-devtools new_page "https://example.com"
chrome-devtools take_snapshot
chrome-devtools click "1_3"
chrome-devtools fill "1_5" "search text"
chrome-devtools press_key "Enter"
```

`take_snapshot` returns accessibility-tree UIDs such as `1_3`. Always act on UIDs from the latest snapshot. Re-snapshot after navigation, reloads, or major DOM updates.

## Operating Rules

- Run tools directly; the background daemon starts implicitly on first real action and preserves browser state.
- Do not run `start`, `status`, or `stop` before every action. Use them only for setup, custom launch flags, or troubleshooting.
- Use `chrome-devtools <command> --help` for exact syntax. Output defaults to Markdown; add `--output-format=json` when structured output is useful.
- Prefer snapshots over screenshots for deciding what to click or fill. Use screenshots for visual proof, layout inspection, or reports.
- Use `evaluate_script`, console, and network commands when debugging runtime behavior; use Lighthouse and performance tracing for page-quality/performance work.

## Common Tasks

```bash
chrome-devtools list_pages
chrome-devtools navigate_page --url "https://example.com"
chrome-devtools navigate_page --type "reload" --ignoreCache=true
chrome-devtools evaluate_script "() => document.title"
chrome-devtools list_console_messages --types error
chrome-devtools list_network_requests --pageSize 50
chrome-devtools take_screenshot --filePath page.png
chrome-devtools lighthouse_audit --mode "navigation"
chrome-devtools performance_start_trace --reload=true --autoStop=false --filePath trace.json.gz
chrome-devtools performance_stop_trace
```

For a broader command map, read `references/cli-reference.md`.

## Setup

If this is the first time using the CLI or `chrome-devtools` is missing, read `references/installation.md`. Installation is a one-time prerequisite, not part of the regular workflow.

## References

- `references/cli-reference.md` — command groups, daemon behavior, output modes, and troubleshooting commands
- `references/installation.md` — global install and PATH troubleshooting
