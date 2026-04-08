"""
runner.py — shared library for the nodriver-browser skill.

Provides:
  • find_chrome()       — discovery + cache
  • is_daemon_alive()   — port-based liveness check
  • ensure_daemon()     — atomic singleton start (fcntl.flock)
  • stop_daemon()       — kill + clean
  • attach()            — async, returns nodriver Browser attached to the daemon
  • get_persistent_tab(), list_tabs(), tab_count(), cleanup_extra_tabs()
  • js(), output()      — small async helpers used by every script

Design notes:
  • nodriver is imported lazily inside async helpers, so daemon-control
    scripts (start/stop/status) don't pay the import cost.
  • ALL paths and constants live here. Scripts must not hardcode them.
  • Port can be overridden with NODRIVER_SKILL_PORT for users who already
    have something on 9222.
"""

from __future__ import annotations

import errno
import fcntl
import glob
import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ───────────────────────────────────────────────────────────── constants ──

PORT = int(os.environ.get("NODRIVER_SKILL_PORT", "9222"))

STATE_DIR = Path("/tmp/nodriver-skill")
PID_FILE = STATE_DIR / "pid"
LOCK_FILE = STATE_DIR / "start.lock"
LOG_FILE = STATE_DIR / "daemon.log"
REFS_FILE = STATE_DIR / "refs.json"
PERSISTENT_TAB_FILE = STATE_DIR / "persistent_tab_id"

CACHE_DIR = Path.home() / ".cache" / "nodriver-skill"
PROFILE_DIR = CACHE_DIR / "profile"
CHROME_PATH_CACHE = CACHE_DIR / "chrome_path"

DAEMON_BOOT_TIMEOUT_S = 6.0
DAEMON_POLL_INTERVAL_S = 0.1
ALIVE_HTTP_TIMEOUT_S = 0.5

# Singleton-lock files Chromium leaves in the profile dir; safe to remove
# when we know there's no live process holding them.
STALE_LOCKS = ("SingletonLock", "SingletonCookie", "SingletonSocket")


def _ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────── chrome discovery ──

def _candidate_paths() -> list[Path]:
    """Build the ordered candidate list — first match wins."""
    cands: list[Path] = []

    # 1. Explicit env var
    env_path = os.environ.get("CHROMIUM_PATH") or os.environ.get("CHROME_PATH")
    if env_path:
        cands.append(Path(env_path))

    # 2. PATH
    for name in ("chromium", "google-chrome", "chromium-browser",
                 "chrome", "google-chrome-stable"):
        p = shutil.which(name)
        if p:
            cands.append(Path(p))

    # 3. Standard system paths per OS
    system = platform.system()
    if system == "Linux":
        cands += [
            Path("/usr/bin/chromium"),
            Path("/usr/bin/chromium-browser"),
            Path("/usr/bin/google-chrome"),
            Path("/usr/bin/google-chrome-stable"),
            Path("/snap/bin/chromium"),
            Path("/opt/google/chrome/chrome"),
        ]
    elif system == "Darwin":
        cands += [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        ]
    elif system == "Windows":
        cands += [
            Path(r"C:/Program Files/Google/Chrome/Application/chrome.exe"),
            Path(r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
        ]

    # 4. Playwright cache — pick newest by version number
    pw_pattern = str(Path.home() / ".cache" / "ms-playwright" /
                     "chromium-*" / "chrome-linux" / "chrome")
    pw_matches = sorted(
        glob.glob(pw_pattern),
        key=lambda p: int(Path(p).parts[-3].split("-")[1])
        if Path(p).parts[-3].split("-")[1].isdigit() else 0,
        reverse=True,
    )
    cands += [Path(p) for p in pw_matches]

    # 5. Puppeteer cache
    pt_pattern = str(Path.home() / ".cache" / "puppeteer" / "chrome" /
                     "*" / "chrome-linux*" / "chrome")
    cands += [Path(p) for p in sorted(glob.glob(pt_pattern), reverse=True)]

    return cands


def find_chrome() -> str:
    """
    Locate a usable chromium-family binary. Result is cached to disk so
    we don't re-search on every script invocation.

    Raises FileNotFoundError with install instructions if nothing found.
    """
    _ensure_dirs()

    # Use cached value if it still exists.
    if CHROME_PATH_CACHE.exists():
        cached = CHROME_PATH_CACHE.read_text().strip()
        if cached and Path(cached).exists() and os.access(cached, os.X_OK):
            return cached

    for c in _candidate_paths():
        try:
            if c.exists() and os.access(c, os.X_OK):
                CHROME_PATH_CACHE.write_text(str(c))
                return str(c)
        except OSError:
            continue

    # Last-ditch: ask nodriver itself
    try:
        from nodriver.core.config import find_chrome_executable
        p = find_chrome_executable()
        if p:
            CHROME_PATH_CACHE.write_text(str(p))
            return str(p)
    except Exception:
        pass

    raise FileNotFoundError(
        "No chromium binary found. Install one of:\n"
        "  • apt install chromium      (Debian/Ubuntu)\n"
        "  • brew install --cask chromium  (macOS)\n"
        "  • npx playwright install chromium\n"
        "Or set CHROMIUM_PATH=/path/to/chrome"
    )


# ──────────────────────────────────────────────────────── daemon liveness ──

def is_daemon_alive(port: int = PORT) -> bool:
    """
    Authoritative liveness check: GET /json/version on the debug port.
    Returns True only on a 200 with a valid Chrome `Browser` field.
    """
    url = f"http://127.0.0.1:{port}/json/version"
    try:
        with urllib.request.urlopen(url, timeout=ALIVE_HTTP_TIMEOUT_S) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read())
            return isinstance(data.get("Browser"), str)
    except (urllib.error.URLError, socket.timeout, ConnectionError,
            json.JSONDecodeError, OSError):
        return False


def _port_bound(port: int = PORT) -> bool:
    """True if SOMETHING accepts TCP on the port (CDP or otherwise)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.2)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except (ConnectionRefusedError, socket.timeout, OSError):
        return False
    finally:
        s.close()


def _read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return None


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _process_is_chrome(pid: int) -> bool:
    """Best-effort check that PID's cmdline points at a chromium binary."""
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", "ignore")
        return "chrome" in cmdline.lower() or "chromium" in cmdline.lower()
    except (FileNotFoundError, PermissionError, OSError):
        return False


def _atomic_write_pid(pid: int) -> None:
    tmp = PID_FILE.with_suffix(".tmp")
    tmp.write_text(str(pid))
    tmp.replace(PID_FILE)


def _clean_stale_locks() -> None:
    for name in STALE_LOCKS:
        p = PROFILE_DIR / name
        try:
            if p.is_symlink() or p.exists():
                p.unlink()
        except OSError:
            pass


# ─────────────────────────────────────────────── singleton daemon control ──

class _StartLock:
    """Context manager wrapping fcntl.flock(LOCK_EX) on LOCK_FILE."""

    def __enter__(self):
        _ensure_dirs()
        self._fd = open(LOCK_FILE, "w")
        fcntl.flock(self._fd.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        try:
            fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
        finally:
            self._fd.close()


def ensure_daemon() -> int:
    """
    Idempotent + race-free: guarantee exactly one Chromium daemon is running
    on PORT, and return its PID. Safe to call from concurrent processes.
    """
    _ensure_dirs()

    with _StartLock():
        # Re-check inside the lock — someone else may have just started it.
        if is_daemon_alive():
            pid = _read_pid()
            if pid is None:
                # Adopt: alive but no PID file (e.g. survived a state wipe).
                _atomic_write_pid(_find_chrome_pid_on_port() or 0)
                pid = _read_pid() or 0
            return pid

        # Port bound but not CDP → alien process. Refuse.
        if _port_bound():
            raise RuntimeError(
                f"port {PORT} is in use by a non-CDP process. "
                f"Free it, or set NODRIVER_SKILL_PORT to a different port."
            )

        # Stale PID file? Either a dead process or an alien live one.
        pid = _read_pid()
        if pid is not None:
            if _process_alive(pid):
                if _process_is_chrome(pid):
                    raise RuntimeError(
                        f"PID {pid} is a chromium process but isn't responding "
                        f"on port {PORT}. Run stop_daemon.py to clean up."
                    )
                raise RuntimeError(
                    f"stale PID file points at live non-chromium PID {pid}. "
                    f"Remove {PID_FILE} manually."
                )
            # dead process → safe to clean and restart
            _clean_stale_locks()
            try:
                PID_FILE.unlink()
            except FileNotFoundError:
                pass

        # Spawn fresh.
        chrome = find_chrome()
        log_fp = open(LOG_FILE, "ab")
        proc = subprocess.Popen(
            [
                chrome,
                "--headless=new",
                "--no-sandbox",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-background-networking",
                "--disable-default-apps",
                "--disable-extensions",
                "--disable-sync",
                "--mute-audio",
                f"--remote-debugging-port={PORT}",
                "--remote-debugging-address=127.0.0.1",
                f"--user-data-dir={PROFILE_DIR}",
            ],
            stdout=log_fp,
            stderr=log_fp,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # detach from our process group
            close_fds=True,
        )
        _atomic_write_pid(proc.pid)

        # Poll for readiness.
        deadline = time.monotonic() + DAEMON_BOOT_TIMEOUT_S
        while time.monotonic() < deadline:
            if is_daemon_alive():
                return proc.pid
            if proc.poll() is not None:
                raise RuntimeError(
                    f"chromium exited prematurely (rc={proc.returncode}). "
                    f"See {LOG_FILE} for details."
                )
            time.sleep(DAEMON_POLL_INTERVAL_S)

        # Timeout — kill and complain.
        try:
            proc.kill()
        except Exception:
            pass
        try:
            PID_FILE.unlink()
        except FileNotFoundError:
            pass
        raise RuntimeError(
            f"chromium failed to come up within {DAEMON_BOOT_TIMEOUT_S}s. "
            f"See {LOG_FILE} for details."
        )


def _find_chrome_pid_on_port() -> int | None:
    """Best-effort: find a chrome PID with our --remote-debugging-port=PORT."""
    try:
        for d in Path("/proc").iterdir():
            if not d.name.isdigit():
                continue
            try:
                cmdline = (d / "cmdline").read_bytes().decode("utf-8", "ignore")
            except (FileNotFoundError, PermissionError, OSError):
                continue
            if f"--remote-debugging-port={PORT}" in cmdline and "chrom" in cmdline.lower():
                return int(d.name)
    except OSError:
        pass
    return None


def _clear_session_state() -> None:
    """Remove ephemeral state that's only valid while a daemon is running."""
    for f in (PID_FILE, PERSISTENT_TAB_FILE, REFS_FILE):
        try:
            f.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def stop_daemon() -> bool:
    """
    Kill the daemon (SIGTERM, then SIGKILL after 2s) and clean up state.
    Returns True if a daemon was running, False if there was nothing to stop.
    """
    with _StartLock():
        pid = _read_pid()
        if pid is None or not _process_alive(pid):
            # Maybe it died but left junk; still clean up.
            _clear_session_state()
            _clean_stale_locks()
            return False

        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

        for _ in range(20):
            if not _process_alive(pid):
                break
            time.sleep(0.1)
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        _clear_session_state()
        _clean_stale_locks()
        return True


# ──────────────────────────────────────────────────────────── nodriver ────

async def attach():
    """
    Attach to the running daemon (auto-starting it if necessary).
    Returns a nodriver Browser instance.
    """
    ensure_daemon()
    import nodriver as uc  # lazy
    config = uc.Config(
        host="127.0.0.1",
        port=PORT,
        browser_executable_path=find_chrome(),  # validated by Config.__init__
    )
    # Tell nodriver this is OUR profile dir, not a temp scratch one — this
    # sets _custom_data_dir=True so deconstruct_browser() skips its rmtree
    # and the noisy "successfully removed temp profile" print at exit.
    config.user_data_dir = str(PROFILE_DIR)
    browser = await uc.Browser.create(config=config)
    await browser.start()
    return browser


async def _refresh_targets(browser) -> None:
    # nodriver renamed/added this method across versions; try both.
    if hasattr(browser, "update_targets"):
        await browser.update_targets()
    elif hasattr(browser, "_update_targets"):
        await browser._update_targets()


def _page_tabs(browser) -> list:
    """
    Return all page-type tabs, deduplicated by target_id.

    nodriver's `browser.tabs` can contain the same target twice (it adds
    the existing target on attach AND on update_targets without dedup).
    We trust the CDP target_id as the unique identity.
    """
    seen: set[str] = set()
    out: list = []
    for t in browser.tabs:
        if getattr(t, "type_", None) != "page":
            continue
        tid = getattr(t, "target_id", None)
        if tid and tid in seen:
            continue
        if tid:
            seen.add(tid)
        out.append(t)
    return out


async def get_persistent_tab(browser):
    """
    Return THE persistent tab — identified by stable target_id, not by list
    position. The id is stored in /tmp/nodriver-skill/persistent_tab_id on
    first call and re-used forever. This is critical: when a stray tab
    appears (window.open, target=_blank, ...), CDP may report the new tab
    at index 0, which would silently swap our persistent tab if we trusted
    list order.

    Fallbacks (in order):
      1. Saved target_id resolves to a live tab → use it
      2. Saved id is gone → use the OLDEST page tab and re-pin to its id
      3. No page tabs exist → open about:blank in-place and pin to it
    """
    await _refresh_targets(browser)
    tabs = _page_tabs(browser)

    # 1. Saved id if it still exists
    if PERSISTENT_TAB_FILE.exists():
        saved_id = PERSISTENT_TAB_FILE.read_text().strip()
        for t in tabs:
            if getattr(t, "target_id", None) == saved_id:
                return t
        # Saved id is stale — fall through to repin

    # 2. Repin: pick the oldest existing tab. browser.tabs preserves
    # discovery order, so the first one we ever saw is generally tabs[0]
    # at fresh-daemon time. (After strays appear, this may not be index 0
    # in CDP order, but as long as we pin once and resolve by id thereafter,
    # we're stable.)
    if tabs:
        chosen = tabs[0]
        target_id = getattr(chosen, "target_id", None)
        if target_id:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            PERSISTENT_TAB_FILE.write_text(target_id)
        return chosen

    # 3. No tabs at all — open one and pin
    await browser.get("about:blank", new_tab=False)
    await _refresh_targets(browser)
    tabs = _page_tabs(browser)
    if not tabs:
        raise RuntimeError("daemon has zero page tabs and could not create one")
    chosen = tabs[0]
    target_id = getattr(chosen, "target_id", None)
    if target_id:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        PERSISTENT_TAB_FILE.write_text(target_id)
    return chosen


def _persistent_target_id() -> str | None:
    if PERSISTENT_TAB_FILE.exists():
        v = PERSISTENT_TAB_FILE.read_text().strip()
        return v or None
    return None


async def list_tabs(browser) -> list[dict]:
    """List every page-type tab with metadata. is_persistent is by target_id."""
    await _refresh_targets(browser)
    tabs = _page_tabs(browser)
    pinned = _persistent_target_id()
    out = []
    for i, t in enumerate(tabs):
        title = None
        try:
            title = await js(t, "document.title")
        except Exception:
            pass
        target_id = getattr(t, "target_id", None)
        out.append({
            "index": i,
            "url": getattr(t, "url", None),
            "title": title,
            "target_id": target_id,
            "is_persistent": (target_id == pinned),
        })
    return out


async def tab_count(browser) -> int:
    """Force a fresh CDP target list before counting."""
    await _refresh_targets(browser)
    return len(_page_tabs(browser))


async def cleanup_extra_tabs(browser) -> int:
    """
    Close every page-type tab except the persistent one (pinned by target_id).
    Returns number of tabs actually closed.

    After closing, waits briefly for nodriver to process Target.targetDestroyed
    events so the next tab_count call sees the post-cleanup state.
    """
    import asyncio
    await _refresh_targets(browser)
    tabs = _page_tabs(browser)
    pinned = _persistent_target_id()

    closed = 0
    for t in tabs:
        if getattr(t, "target_id", None) == pinned:
            continue
        try:
            await t.close()
            closed += 1
        except Exception:
            pass

    # Give nodriver a moment to receive the Target.targetDestroyed events,
    # then refresh so callers see an accurate count.
    if closed:
        await asyncio.sleep(0.25)
        await _refresh_targets(browser)
    return closed


async def js(tab, expr: str):
    """
    Run JS and return plain Python data, not nodriver's CDP RemoteObject
    envelope. Wraps the expression in JSON.stringify so we get a string we
    can json.loads.

    Defensive: if the JS throws OR returns something JSON.stringify can't
    handle (Window object from window.open, DOM nodes, etc.), nodriver
    surfaces an ExceptionDetails object. We coerce that to a string so the
    caller's output() never crashes on json.dumps.
    """
    try:
        raw = await tab.evaluate(f"JSON.stringify({expr})")
    except Exception as e:
        return {"_js_error": f"{type(e).__name__}: {e}"}

    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    if isinstance(raw, (int, float, bool, list, dict)):
        return raw
    # ExceptionDetails or some other CDP wrapper — best-effort string repr.
    return {"_js_unserializable": str(raw)[:500]}


async def output(payload: dict, browser=None) -> None:
    """
    Centralized print. ALWAYS appends `tabs_open` (when browser provided)
    and a `warning` field if more than one tab is open. Every script must
    use this — never bare `print(json.dumps(...))`.
    """
    if browser is not None:
        try:
            n = await tab_count(browser)
            payload["tabs_open"] = n
            if n > 1:
                payload["warning"] = (
                    f"{n} tabs open, expected 1. "
                    f"Run cleanup.py to close stray tabs."
                )
        except Exception as e:
            payload["tabs_open_error"] = str(e)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
