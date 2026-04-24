#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["nodriver"]
# ///
"""Daemon health check + tab list. Returns JSON."""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("UV_LINK_MODE", "copy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from runner import (  # noqa: E402
    PID_FILE, PORT, is_daemon_alive, _read_pid, _process_alive,
    attach, list_tabs, output,
)


def _proc_info(pid: int) -> dict:
    info: dict = {"pid": pid}
    # /proc/<pid>/stat for uptime, /proc/<pid>/status for RSS
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().split()
        # Field 22 (0-indexed 21): starttime in clock ticks since boot
        starttime_ticks = int(stat[21])
        clk_tck = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        with open("/proc/uptime") as f:
            system_uptime = float(f.read().split()[0])
        proc_uptime_s = system_uptime - (starttime_ticks / clk_tck)
        # In containerized/PRoot environments the clock can jump, producing
        # negative or absurd values. Only report if it looks sensible.
        if 0 <= proc_uptime_s < 365 * 24 * 3600:
            info["uptime_s"] = round(proc_uptime_s, 1)
    except Exception:
        pass
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                info["rss_kb"] = int(line.split()[1])
                break
    except Exception:
        pass
    return info


async def main() -> int:
    alive = is_daemon_alive()
    pid = _read_pid()
    payload: dict = {
        "alive": alive,
        "port": PORT,
        "pid_file": str(PID_FILE),
        "pid": pid,
    }
    if pid is not None and _process_alive(pid):
        payload["process"] = _proc_info(pid)

    if not alive:
        print(json.dumps(payload, indent=2))
        return 0

    # Daemon is up — also fetch the tab list.
    browser = await attach()
    payload["tabs"] = await list_tabs(browser)
    await output(payload, browser=browser)
    return 0


if __name__ == "__main__":
    import nodriver as uc
    uc.loop().run_until_complete(main())
