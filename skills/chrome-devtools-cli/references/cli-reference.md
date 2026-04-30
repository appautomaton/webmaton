# CLI Reference

Use this as a map, not as a substitute for `chrome-devtools <command> --help`.

## How The CLI Runs

`chrome-devtools` is a client for a background `chrome-devtools-mcp` daemon. On Linux/macOS it uses a Unix socket; on Windows it uses a named pipe.

- First real action auto-starts the daemon and browser if needed.
- Later commands reuse the same browser state.
- `start`, `status`, and `stop` are for setup and troubleshooting.
- `chrome-devtools start` forwards supported launch options such as `--headless`, `--userDataDir`, `--browserUrl`, `--channel`, `--proxyServer`, `--usageStatistics`, and `--slim`.

## Navigation And Page State

```bash
chrome-devtools list_pages
chrome-devtools new_page "https://example.com"
chrome-devtools select_page 1
chrome-devtools close_page 1
chrome-devtools navigate_page --url "https://example.com"
chrome-devtools navigate_page --type "back"
chrome-devtools navigate_page --type "forward"
chrome-devtools navigate_page --type "reload" --ignoreCache=true
chrome-devtools wait_for "Loaded"
chrome-devtools resize_page 1280 720
```

## Snapshot-Based Interaction

```bash
chrome-devtools take_snapshot
chrome-devtools take_snapshot --verbose=true --filePath snapshot.txt
chrome-devtools click "1_3"
chrome-devtools click "1_3" --includeSnapshot=true
chrome-devtools fill "1_5" "text"
chrome-devtools fill_form '[{"uid":"1_5","value":"text"}]'
chrome-devtools hover "1_7"
chrome-devtools drag "1_8" "1_9"
chrome-devtools press_key "Enter"
chrome-devtools type_text "hello" --submitKey "Enter"
chrome-devtools upload_file "1_10" "./file.txt"
chrome-devtools handle_dialog accept
```

The UID shape varies by snapshot. Treat examples such as `1_3` as placeholders.

## Runtime Debugging

```bash
chrome-devtools evaluate_script "() => document.title"
chrome-devtools evaluate_script "(node) => node.innerText" --args 1_4
chrome-devtools list_console_messages
chrome-devtools list_console_messages --types error
chrome-devtools get_console_message 1
chrome-devtools list_network_requests
chrome-devtools list_network_requests --resourceTypes Fetch
chrome-devtools get_network_request --reqid 1 --requestFilePath req.md --responseFilePath res.md
chrome-devtools take_screenshot --filePath page.png
chrome-devtools take_screenshot --uid "1_4" --filePath element.png
```

## Emulation, Audits, And Performance

```bash
chrome-devtools emulate --viewport "390x844"
chrome-devtools emulate --colorScheme "dark"
chrome-devtools emulate --networkConditions "Offline"
chrome-devtools emulate --cpuThrottlingRate 4
chrome-devtools lighthouse_audit --mode "navigation"
chrome-devtools lighthouse_audit --mode "snapshot" --device "mobile"
chrome-devtools performance_start_trace --reload=true --autoStop=true
chrome-devtools performance_start_trace --reload=true --autoStop=false --filePath trace.json.gz
chrome-devtools performance_stop_trace --filePath trace.json
chrome-devtools performance_analyze_insight "1" "LCPBreakdown"
chrome-devtools take_memory_snapshot "./snap.heapsnapshot"
```

Navigate to the target URL before starting a trace when `--reload` or `--autoStop` is enabled.

## Output And Troubleshooting

```bash
chrome-devtools take_snapshot --output-format=json
chrome-devtools status
chrome-devtools start --headless=true
chrome-devtools start --browserUrl http://127.0.0.1:9222
chrome-devtools stop
```

If actions fail because no daemon/browser is reachable, run `status`, then use `start --help` to choose launch flags. Stop the daemon when switching profiles, channels, or connection targets.
