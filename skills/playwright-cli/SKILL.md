---
name: playwright-cli
description: "Use when a task needs Playwright-backed browser automation from the shell: open or attach to browser sessions, inspect snapshots and element refs, click/type/fill forms, debug Playwright tests, inspect console/network/storage, run Playwright snippets, capture screenshots/traces/videos, or generate reliable test code. Prefer for repeatable browser workflows and Playwright test work; not for static HTTP fetches, JSON APIs, or simple web search."
---

# playwright-cli

`playwright-cli` is a token-efficient shell interface to Playwright. It keeps browser state across commands, exposes page snapshots with stable element refs such as `e15`, and prints the Playwright code it ran so the interaction can be converted into tests.

## Core Workflow

```bash
playwright-cli open https://example.com
playwright-cli snapshot
playwright-cli click e15
playwright-cli fill e5 "user@example.com"
playwright-cli press Enter
playwright-cli close
```

Use refs from the latest snapshot by default. Re-run `snapshot` after navigation, major DOM changes, or a failed ref action. Use CSS selectors or Playwright locators only when refs are unavailable or unstable.

## Operating Rules

- Discover exact syntax with `playwright-cli --help` and `playwright-cli <command> --help`; the CLI changes quickly.
- Use `--raw` when piping values into other tools. Use `--json` only if the installed CLI advertises it.
- Use named sessions with `-s=<name>` for concurrent or long-lived work.
- Use `open --persistent` only when disk-persisted cookies/storage are needed.
- Prefer `attach --cdp=chrome`, `attach --cdp=msedge`, or `attach --cdp=http://127.0.0.1:9222` when the task needs an existing browser/session.
- Close sessions when finished. Reserve `close-all` and `kill-all` for cleanup of stale sessions.

## Common Tasks

```bash
playwright-cli open https://example.com --browser=chrome
playwright-cli snapshot --depth=4
playwright-cli screenshot --filename=page.png
playwright-cli console warning
playwright-cli network --filter="/api/.*" --request-headers
playwright-cli run-code "async page => await page.context().grantPermissions(['geolocation'])"
playwright-cli tracing-start
playwright-cli tracing-stop
```

For a broader command map, read `references/cli-reference.md`.

## Playwright Test Debugging

When a Playwright test fails, prefer the CLI debug workflow:

```bash
PLAYWRIGHT_HTML_OPEN=never npx playwright test --debug=cli
# wait for "Debugging Instructions", then attach to the printed session
playwright-cli attach tw-abcdef
```

Keep the test process running while inspecting the paused page. Use snapshots, console/network inspection, and generated Playwright code to identify the fix.

## References

Load only what the task needs:

- `references/cli-reference.md` — command groups, output modes, and version-sensitive features
- `references/playwright-tests.md` — running and debugging Playwright tests
- `references/request-mocking.md` — route mocking and request interception
- `references/running-code.md` — custom Playwright snippets with `run-code`
- `references/session-management.md` — named sessions and cleanup
- `references/storage-state.md` — cookies, localStorage, sessionStorage, auth state
- `references/test-generation.md` — turning CLI output into tests
- `references/tracing.md` — trace capture and inspection
- `references/video-recording.md` — WebM recording and chapter markers
- `references/element-attributes.md` — inspect IDs/classes/data attributes not shown in snapshots
