# Constrained Environments (PRoot / Container / Root)

Headed mode on systems without a native display server (common in PRoot, Docker, or root-only containers) requires a lightweight virtual display.

## Quick setup: Xvfb

```bash
# Start a virtual display on :99. Use setsid so it survives session boundaries.
setsid Xvfb :99 -screen 0 1280x720x24 -ac >/dev/null 2>&1 &

# Export before every headed daemon launch.
export DISPLAY=:99

# Then use the skill normally.
scripts/start_daemon.py --headed --no-sandbox
```

## Why setsid?

Each `bash` tool invocation is a fresh session. Background processes die when the session ends. `setsid` detaches Xvfb so it persists across turns.

## Cleanup

```bash
pkill -f "Xvfb :99"
```

## See also

- `--no-sandbox` usage is documented in `SKILL.md` under the daemon lifecycle and troubleshooting sections.
