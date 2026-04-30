# CLI Reference

Use this as a map, not as a substitute for `playwright-cli <command> --help`.

## Session Lifecycle

```bash
playwright-cli open [url]
playwright-cli open [url] --browser=chrome|firefox|webkit|msedge
playwright-cli open [url] --headed
playwright-cli open [url] --persistent
playwright-cli open [url] --profile=/path/to/profile
playwright-cli attach --cdp=chrome
playwright-cli attach --cdp=http://127.0.0.1:9222
playwright-cli attach --extension=chrome
playwright-cli list
playwright-cli close
playwright-cli close-all
playwright-cli kill-all
playwright-cli delete-data
```

Use `-s=<session>` before the command to isolate concurrent sessions:

```bash
playwright-cli -s=auth open https://app.example.com --persistent
playwright-cli -s=auth snapshot
playwright-cli -s=auth close
```

## Inspect And Act

```bash
playwright-cli snapshot
playwright-cli snapshot e34
playwright-cli snapshot "#main" --depth=4
playwright-cli click e15
playwright-cli dblclick e15
playwright-cli fill e5 "text"
playwright-cli fill e5 "text" --submit
playwright-cli type "text"
playwright-cli type "text" --submit
playwright-cli press Enter
playwright-cli hover e4
playwright-cli drag e2 e8
playwright-cli select e9 "option-value"
playwright-cli check e12
playwright-cli uncheck e12
playwright-cli upload ./document.pdf
playwright-cli eval "document.title"
playwright-cli eval "el => el.getAttribute('data-testid')" e5
```

Refs come from the latest snapshot. If the page navigated or re-rendered, snapshot again.

## Navigation, Tabs, And Output

```bash
playwright-cli goto https://example.com
playwright-cli go-back
playwright-cli go-forward
playwright-cli reload
playwright-cli tab-list
playwright-cli tab-new https://example.com/other
playwright-cli tab-select 0
playwright-cli tab-close 1
playwright-cli screenshot --filename=page.png
playwright-cli pdf --filename=page.pdf
playwright-cli --raw eval "document.title"
```

Use `--json` only if `playwright-cli --help` shows it in the installed version.

## Debugging, Network, And Storage

```bash
playwright-cli console
playwright-cli console warning
playwright-cli network
playwright-cli network --filter="/api/.*" --request-headers --request-body
playwright-cli network-state-set offline
playwright-cli network-state-set online
playwright-cli run-code "async page => await page.context().clearCookies()"
playwright-cli state-save auth.json
playwright-cli state-load auth.json
playwright-cli cookie-list
playwright-cli localstorage-list
playwright-cli sessionstorage-list
playwright-cli tracing-start
playwright-cli tracing-stop
playwright-cli video-start demo.webm
playwright-cli video-chapter "Step" --description="Context" --duration=2000
playwright-cli video-stop
```

## Version-Sensitive Commands

Recent releases may add commands such as `highlight`, `generate-locator`, `drop`, `detach`, `snapshot --boxes`, and global `--json`. Check `playwright-cli --version` and command help before using them.
