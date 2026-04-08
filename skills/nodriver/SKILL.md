---
name: nodriver-browser
description: Drive a persistent Chromium tab across turn boundaries — navigate, snapshot the DOM with stable refs, click/type interactively, scrape pages that need login or JS. Auto-starts a stealth headless browser daemon on first use; the same tab survives between every script call so the model can run a real look→think→act loop. Falls through anti-bot detection that blocks WebFetch.
---

# nodriver-browser

A persistent, headless Chromium that **stays alive between Claude's turns**. Built on `nodriver` (CDP-direct, no Selenium, no `navigator.webdriver`). Every script attaches to the same long-running browser, performs one action, exits — the browser and its tab keep going.

**Core invariant: ONE daemon, ONE persistent tab (`tabs[0]`).** Every script reports `tabs_open` in its output. If you ever see `tabs_open > 1`, treat it as a real signal that something opened a stray tab — read the warning and act on it.

## When to use this skill

- The page **needs JavaScript** to render (SPA, infinite scroll, lazy load)
- WebFetch is blocked by **anti-bot** systems (Cloudflare, DataDome, Imperva, hCaptcha)
- The task requires **interaction**: clicking buttons, filling forms, multi-step flows, dropdown selection
- You need **session state** across multiple actions (logged-in scraping, multi-page checkout, OAuth flows)
- You need **visual proof** of a page (screenshot) for debugging or reporting

## When NOT to use this skill

- **Static HTML** that loads fully on first GET → use `WebFetch`
- **One-shot search query** → use `WebSearch` (or grok-search skill if it exists)
- **A JSON API endpoint** → use `curl` via Bash, you don't need a browser at all
- **A single quick scrape with no interactivity** → consider a one-off Python script, not this skill

This skill spawns a Chromium process (~150-200 MB RAM) that stays alive until you explicitly stop it. Worth it for interactive flows; overkill for one URL.

## Quick start

Scripts live in `scripts/` next to this SKILL.md — resolve paths relative to the skill root.

```bash
# 1. Navigate (auto-starts daemon on first call — no manual start needed)
scripts/nav.py https://news.ycombinator.com

# 2. Snapshot the page — gives you text + numbered refs for every interactive element
scripts/snapshot.py

# 3. Click something by ref id from the snapshot
scripts/click.py r17

# 4. Read state any time — it's the same tab as before, even from a fresh process
scripts/state.py

# 5. When done with the session, stop the daemon (frees ~190 MB)
scripts/stop_daemon.py
```

## Script reference

All scripts return JSON to stdout. Every script (except daemon control) appends `tabs_open: N` and emits a `warning` field if `N > 1`.

### Daemon control (no nodriver needed — fast)

| Script | Purpose | Output |
|---|---|---|
| `start_daemon.py` | Idempotent start. No-op if already running. | `{ok, pid, port, already_running}` |
| `stop_daemon.py` | Kill daemon, clean PID file + stale singleton locks. | `{ok, stopped}` |
| `status.py` | Daemon health + tab list. | `{alive, pid, process: {uptime_s, rss_kb}, tabs: [...]}` |

### Navigation & state

| Script | Args | Purpose |
|---|---|---|
| `nav.py` | `URL` | Navigate the persistent tab. Returns the new URL/title/scroll. |
| `state.py` | — | Cheap status read of the current tab. No DOM mutation. |
| `back.py` | — | `history.back()` |
| `forward.py` | — | `history.forward()` |
| `reload.py` | — | `location.reload()` |

### Interaction (the look-think-act primitives)

| Script | Args | Purpose |
|---|---|---|
| `snapshot.py` | — | Full page text + numbered interactive refs. **Writes refs to `/tmp/nodriver-skill/refs.json`** so click/type/press can resolve them. |
| `click.py` | `REF` | Click element by ref id from latest snapshot. |
| `type.py` | `REF TEXT` | Clear field and type. Dispatches `input`+`change` so React/Vue notice. |
| `press.py` | `KEY` or `REF KEY` | Send keyboard event (Enter, Tab, Escape, ArrowDown, single chars, ...). |
| `scroll.py` | `up\|down\|top\|bottom\|N` | Scroll viewport (N is pixels). |
| `wait.py` | `SELECTOR [--text] [--timeout N]` | Block until selector exists (or text appears with `--text`). Default 30s. |
| `eval.py` | `JS_EXPR` | Escape hatch: arbitrary JS expression. Multi-statement → wrap in IIFE. |

### Tab visibility & hygiene

| Script | Args | Purpose |
|---|---|---|
| `tabs.py` | — | List ALL open tabs (index, url, title, target_id). Use this to see what's actually open. |
| `close_tab.py` | `INDEX` | Close one tab by 0-indexed position. Refuses to close index 0. |
| `cleanup.py` | — | Close every tab except `tabs[0]`. The "reset stray tabs" button. |

### Misc

| Script | Args | Purpose |
|---|---|---|
| `screenshot.py` | `[PATH] [--full]` | PNG of viewport (or full scrollable page with `--full`). Default path `/tmp/nodriver-skill/last.png`. |

## The snapshot/refs model

`snapshot.py` is the single most important script. It does three things:

1. Walks the DOM for every interactive element (`a[href]`, `button`, `input`, `select`, `textarea`, `[role=button]`, `[contenteditable]`, `[onclick]`, ...)
2. Assigns each a stable ref id `r1`, `r2`, ... and **mutates the DOM** by setting `data-nd-ref="rN"` on each. This gives a stable CSS selector (`[data-nd-ref="r17"]`) that survives subsequent queries.
3. Writes the `{ref: selector}` map to `/tmp/nodriver-skill/refs.json` so `click.py` / `type.py` / `press.py` can look refs up.

Example output:
```json
{
  "url": "https://example.com/login",
  "title": "Sign in",
  "text": "Sign in to your account...",
  "refs": [
    { "ref": "r1", "tag": "input", "type": "email", "name": "Email address", "visible": true, "bbox": [120, 200, 400, 40] },
    { "ref": "r2", "tag": "input", "type": "password", "name": "Password", ... },
    { "ref": "r3", "tag": "button", "type": "submit", "name": "Sign in", ... }
  ],
  "tabs_open": 1
}
```

To act on it:
```bash
scripts/type.py r1 "user@example.com"
scripts/type.py r2 "hunter2"
scripts/click.py r3
```

**Refs go stale on navigation or significant SPA re-render.** If `click.py` returns `"ref no longer in DOM"`, just re-run `snapshot.py` and try again.

## Daemon lifecycle

The daemon is **singleton-enforced via `fcntl.flock`** on `/tmp/nodriver-skill/start.lock`. Five concurrent script invocations from a cold start will only ever spawn one Chromium.

- **Auto-start**: First call to any interaction script (nav, state, snapshot, ...) auto-starts the daemon if it's not running. You don't need to call `start_daemon.py` first unless you want to verify it manually.
- **Persists**: The daemon runs with `start_new_session=True` so it survives the parent script exit. It will stay alive across all your turn boundaries until explicit shutdown.
- **Explicit stop**: `stop_daemon.py` SIGTERMs the daemon, then SIGKILLs after 2s if needed, cleans the PID file and stale singleton locks. Run this at the end of any session that started the daemon.
- **Port**: 9222 by default. Override with `NODRIVER_SKILL_PORT=9223` if something else holds 9222.
- **Profile**: `~/.cache/nodriver-skill/profile/` (cookies, localStorage, IndexedDB, etc.). Persists across daemon restarts.

## Tab hygiene (READ THIS)

This skill runs Chromium **headlessly** — there is no visible window. You cannot see stray tabs unless you ask for them. **Some sites open new tabs you didn't ask for**: `target="_blank"` links, `window.open()` calls, popup ads, OAuth redirects.

The contract is **one tab**. If `tabs_open > 1` in any script's output (and the `warning` field is set):

```bash
scripts/tabs.py            # see what's actually open
scripts/cleanup.py         # close everything except tabs[0]
# OR for surgical removal:
scripts/close_tab.py 2     # close just the tab at index 2
```

Don't ignore the warning. Tabs accumulate. 30 stale tabs = ~2 GB of RAM and a confused state machine.

## Footguns

- **Refs go stale on re-render.** SPAs that re-mount components on route change will lose `data-nd-ref` attributes. Re-run `snapshot.py` after every navigation or significant action.
- **Concurrent navigations on the same tab race.** Multiple processes can attach simultaneously, but two `nav.py` calls to different URLs at the same time will fight. Serialize them.
- **Daemon outlives the session.** If you forget `stop_daemon.py`, Chromium keeps running — silently eating ~190 MB of RAM until you explicitly stop it or reboot. Stop it when you're done.
- **`wait.py` polls every 250ms.** Don't use it for sub-second timing-sensitive stuff.
- **`type.py` clears the field first.** If you need to append, read the existing value with `eval.py` first.
- **`eval.py` takes ONE expression**, not statements. Multi-statement code: `eval.py '(() => { let x = 1; x++; return x; })()'`.
- **The persistent profile can grow.** A heavily-used profile easily hits a few hundred MB. Periodically delete `~/.cache/nodriver-skill/profile/Default/Cache/` between sessions.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `daemon won't start` | Chrome binary missing | Set `CHROMIUM_PATH=/path/to/chrome` or `apt install chromium` |
| `port 9222 in use by a non-CDP process` | Another tool holds 9222 | `NODRIVER_SKILL_PORT=9223 ./scripts/start_daemon.py` |
| `PID is a chromium process but isn't responding` | Crashed daemon left a zombie | `./scripts/stop_daemon.py` to clean up, then retry |
| `no snapshot yet — run snapshot.py first` | `click.py` called without prior snapshot | Run `snapshot.py` first |
| `ref no longer in DOM` | Page navigated/re-rendered | Re-run `snapshot.py`, get the new ref |
| `tabs_open: 5, warning: ...` | Site opened popups/new tabs | `cleanup.py` closes everything except tabs[0] |
| `Installed N packages` log noise on first run | uv resolving deps for the inline script | Normal — only happens once per skill version |
| Hardlink errors during install | PRoot/container without hardlink support | Already mitigated: `UV_LINK_MODE=copy` is set automatically |
| Daemon won't die after `stop_daemon.py` | Stale PID file, real PID lives elsewhere | `pkill -f remote-debugging-port=9222` (CAREFUL: this also kills other CDP browsers) |

## Verifying it works

```bash
scripts/stop_daemon.py                                    # clean state
scripts/nav.py https://example.com                        # cold-start auto-spawns daemon
scripts/state.py                                          # SAME tab, fresh process
scripts/snapshot.py | head -20                            # see refs
scripts/eval.py "document.title"                          # escape hatch
scripts/screenshot.py /tmp/test.png && ls -la /tmp/test.png
scripts/status.py                                         # uptime + tab list
scripts/stop_daemon.py                                    # done
```

If the second call (`state.py`) reports the same URL as `nav.py` set, the persistent-tab invariant is working — every other script can rely on it.
