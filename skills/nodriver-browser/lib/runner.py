"""
runner.py — shared library for the nodriver-browser skill.

Provides:
  • find_chrome()       — discovery + cache
  • is_daemon_alive()   — port-based liveness check
  • pop_launch_mode()   — parse leading browser launch flags
  • ensure_daemon()     — atomic singleton start/adopt (fcntl.flock)
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
  • Browser mode defaults to headless. Use a leading --headed script flag or
    NODRIVER_SKILL_MODE=headed when spawning a visible browser.
  • Profile defaults to the isolated skill profile. Use --user-profile or
    NODRIVER_SKILL_PROFILE=user to launch against the user's Chrome profile.
  • Chrome sandbox stays enabled by default. Use --no-sandbox or
    NODRIVER_CHROME_NO_SANDBOX=1 only in constrained environments that cannot
    run Chrome's OS sandbox, such as PRoot/container/root setups.
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
MODE_FILE = STATE_DIR / "mode"
PROFILE_FILE = STATE_DIR / "profile.json"
SANDBOX_FILE = STATE_DIR / "sandbox"
REFS_FILE = STATE_DIR / "refs.json"
PERSISTENT_TAB_FILE = STATE_DIR / "persistent_tab_id"

CACHE_DIR = Path.home() / ".cache" / "nodriver-skill"
PROFILE_DIR = CACHE_DIR / "profile"

DAEMON_BOOT_TIMEOUT_S = 6.0
DAEMON_POLL_INTERVAL_S = 0.1
ALIVE_HTTP_TIMEOUT_S = 0.5

# Singleton-lock files Chromium leaves in the profile dir; safe to remove
# when we know there's no live process holding them.
STALE_LOCKS = ("SingletonLock", "SingletonCookie", "SingletonSocket")
VALID_LAUNCH_MODES = {"headless", "headed"}
VALID_PROFILE_MODES = {"skill", "user"}


def _ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)


def _normalize_launch_mode(mode: str) -> str:
    value = mode.strip().lower()
    aliases = {
        "headful": "headed",
        "visible": "headed",
        "gui": "headed",
    }
    value = aliases.get(value, value)
    if value not in VALID_LAUNCH_MODES:
        raise ValueError(
            "launch mode must be 'headless' or 'headed' "
            "(or use --headless / --headed)"
        )
    return value


def default_launch_mode() -> str:
    """Default mode used only when spawning a fresh daemon."""
    return _normalize_launch_mode(os.environ.get("NODRIVER_SKILL_MODE", "headless"))


def pop_launch_mode(args: list[str]) -> tuple[str | None, list[str]]:
    """
    Consume leading global browser launch flags from a script argv tail.

    Returns (requested_mode, remaining_args). requested_mode is None when the
    caller did not explicitly ask for a mode; in that case an existing daemon is
    accepted as-is, and a new daemon uses default_launch_mode().

    Profile flags are applied to this process through environment variables so
    existing script call sites only need to pass the requested mode to attach().
    """
    rest = list(args)
    mode: str | None = None
    profile: str | None = None
    while rest:
        flag = rest[0]
        if flag in ("--headed", "--headless"):
            rest.pop(0)
            requested = "headed" if flag == "--headed" else "headless"
            if mode is not None and mode != requested:
                raise ValueError("choose only one of --headed or --headless")
            mode = requested
            continue
        if flag in ("--user-profile", "--skill-profile"):
            rest.pop(0)
            requested_profile = "user" if flag == "--user-profile" else "skill"
            if profile is not None and profile != requested_profile:
                raise ValueError("choose only one of --user-profile or --skill-profile")
            profile = requested_profile
            os.environ["NODRIVER_SKILL_PROFILE"] = requested_profile
            os.environ["NODRIVER_SKILL_PROFILE_EXPLICIT"] = "1"
            continue
        if flag == "--profile-directory":
            rest.pop(0)
            if not rest:
                raise ValueError("--profile-directory requires a Chrome profile name")
            if profile == "skill":
                raise ValueError("--profile-directory requires --user-profile")
            profile = "user"
            os.environ["NODRIVER_CHROME_PROFILE_DIRECTORY"] = rest.pop(0)
            os.environ["NODRIVER_SKILL_PROFILE"] = "user"
            os.environ["NODRIVER_SKILL_PROFILE_EXPLICIT"] = "1"
            continue
        if flag == "--user-data-dir":
            rest.pop(0)
            if not rest:
                raise ValueError("--user-data-dir requires a path")
            if profile == "skill":
                raise ValueError("--user-data-dir requires --user-profile")
            profile = "user"
            os.environ["NODRIVER_CHROME_USER_DATA_DIR"] = rest.pop(0)
            os.environ["NODRIVER_SKILL_PROFILE"] = "user"
            os.environ["NODRIVER_SKILL_PROFILE_EXPLICIT"] = "1"
            continue
        if flag == "--no-sandbox":
            rest.pop(0)
            os.environ["NODRIVER_CHROME_NO_SANDBOX"] = "1"
            os.environ["NODRIVER_CHROME_NO_SANDBOX_EXPLICIT"] = "1"
            continue
        break
    return mode, rest


def _normalize_profile_mode(mode: str) -> str:
    value = mode.strip().lower()
    aliases = {
        "isolated": "skill",
        "chrome": "user",
        "default": "user",
        "user-profile": "user",
    }
    value = aliases.get(value, value)
    if value not in VALID_PROFILE_MODES:
        raise ValueError("profile mode must be 'skill' or 'user'")
    return value


def _chrome_user_data_dir() -> Path:
    env_dir = os.environ.get("NODRIVER_CHROME_USER_DATA_DIR")
    if env_dir:
        return Path(env_dir).expanduser()

    system = platform.system()
    if system == "Darwin":
        cands = [
            Path.home() / "Library/Application Support/Google/Chrome",
            Path.home() / "Library/Application Support/Chromium",
        ]
    elif system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData/Local"
        cands = [
            base / "Google/Chrome/User Data",
            base / "Chromium/User Data",
        ]
    else:
        cands = [
            Path.home() / ".config/google-chrome",
            Path.home() / ".config/chromium",
        ]

    for c in cands:
        if c.exists():
            return c
    return cands[0]


def _profile_mode_explicit() -> bool:
    return (
        "NODRIVER_SKILL_PROFILE" in os.environ
        or "NODRIVER_SKILL_PROFILE_EXPLICIT" in os.environ
        or "NODRIVER_CHROME_USER_DATA_DIR" in os.environ
        or "NODRIVER_CHROME_PROFILE_DIRECTORY" in os.environ
    )


def launch_profile() -> dict:
    default_profile = "user" if (
        "NODRIVER_CHROME_USER_DATA_DIR" in os.environ
        or "NODRIVER_CHROME_PROFILE_DIRECTORY" in os.environ
    ) else "skill"
    mode = _normalize_profile_mode(os.environ.get("NODRIVER_SKILL_PROFILE", default_profile))
    if mode == "skill":
        return {
            "mode": "skill",
            "user_data_dir": str(PROFILE_DIR),
            "profile_directory": None,
        }

    user_data_dir = _chrome_user_data_dir()
    profile_directory = os.environ.get("NODRIVER_CHROME_PROFILE_DIRECTORY", "Default")
    return {
        "mode": "user",
        "user_data_dir": str(user_data_dir),
        "profile_directory": profile_directory,
    }


def _env_bool(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def launch_no_sandbox() -> bool:
    return _env_bool("NODRIVER_CHROME_NO_SANDBOX")


def _no_sandbox_explicit() -> bool:
    return (
        "NODRIVER_CHROME_NO_SANDBOX" in os.environ
        or "NODRIVER_CHROME_NO_SANDBOX_EXPLICIT" in os.environ
    )


# ─────────────────────────────────────────────────────── chrome discovery ──

def _candidate_paths() -> list[Path]:
    """Build the ordered candidate list — first match wins."""
    cands: list[Path] = []

    # 1. Explicit env var
    env_path = os.environ.get("CHROMIUM_PATH") or os.environ.get("CHROME_PATH")
    if env_path:
        cands.append(Path(env_path))

    # 2. PATH — prefer Chrome over Chromium
    for name in ("google-chrome", "google-chrome-stable", "chrome",
                 "chromium", "chromium-browser"):
        p = shutil.which(name)
        if p:
            cands.append(Path(p))

    # 3. Standard system paths per OS
    system = platform.system()
    if system == "Linux":
        cands += [
            Path("/usr/bin/google-chrome"),
            Path("/usr/bin/google-chrome-stable"),
            Path("/opt/google/chrome/chrome"),
            Path("/usr/bin/chromium"),
            Path("/usr/bin/chromium-browser"),
            Path("/snap/bin/chromium"),
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

    return cands


def find_chrome() -> str:
    """
    Locate a usable chromium-family binary.

    Search order:
      1. CHROMIUM_PATH / CHROME_PATH environment variables
      2. PATH binaries (Chrome first, then Chromium)
      3. Standard OS install paths
      4. Playwright Chromium cache

    Raises FileNotFoundError with install instructions if nothing found.
    """
    for c in _candidate_paths():
        try:
            if c.exists() and os.access(c, os.X_OK):
                return str(c)
        except OSError:
            continue

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
        pid = int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return None
    return pid if pid > 0 else None


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _process_cmdline(pid: int) -> str | None:
    """Best-effort process command line, using /proc first and ps as fallback."""
    if pid <= 0:
        return None
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        return raw.replace(b"\0", b" ").decode("utf-8", "ignore").strip()
    except (FileNotFoundError, PermissionError, OSError):
        pass

    try:
        proc = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=0.5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _cmdline_is_chrome(cmdline: str) -> bool:
    lower = cmdline.lower()
    return "chrome" in lower or "chromium" in lower


def _cmdline_is_chrome_debug_daemon(cmdline: str, port: int = PORT) -> bool:
    return _cmdline_is_chrome(cmdline) and f"--remote-debugging-port={port}" in cmdline


def _process_is_chrome(pid: int) -> bool:
    """Best-effort check that PID's cmdline points at a chromium binary."""
    cmdline = _process_cmdline(pid)
    return bool(cmdline and _cmdline_is_chrome(cmdline))


def _process_owns_debug_port(pid: int | None, port: int = PORT) -> bool:
    if pid is None or not _process_alive(pid):
        return False
    cmdline = _process_cmdline(pid)
    return bool(cmdline and _cmdline_is_chrome_debug_daemon(cmdline, port))


def _process_launch_mode(pid: int | None) -> str | None:
    """Best-effort mode detection for live daemons we did not start."""
    if pid is None:
        return None
    cmdline = _process_cmdline(pid)
    if not cmdline:
        return None
    if "--headless" in cmdline:
        return "headless"
    if _cmdline_is_chrome(cmdline):
        return "headed"
    return None


def running_launch_mode() -> str | None:
    try:
        mode = _normalize_launch_mode(MODE_FILE.read_text().strip())
        return mode
    except (FileNotFoundError, OSError, ValueError):
        pass
    return _process_launch_mode(_read_pid())


def running_profile() -> dict | None:
    try:
        data = json.loads(PROFILE_FILE.read_text())
        user_data_dir = data.get("user_data_dir")
        if not isinstance(user_data_dir, str) or not user_data_dir:
            return None
        mode = _normalize_profile_mode(data.get("mode", "skill"))
        profile_directory = data.get("profile_directory")
        if profile_directory is not None and not isinstance(profile_directory, str):
            profile_directory = None
        return {
            "mode": mode,
            "user_data_dir": user_data_dir,
            "profile_directory": profile_directory,
        }
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        return None


def running_no_sandbox() -> bool | None:
    try:
        value = SANDBOX_FILE.read_text().strip()
        if value == "disabled":
            return True
        if value == "enabled":
            return False
    except (FileNotFoundError, OSError):
        pass

    pid = _read_pid()
    if pid is None:
        return None
    cmdline = _process_cmdline(pid)
    if not cmdline:
        return None
    if "--no-sandbox" in cmdline:
        return True
    if _cmdline_is_chrome(cmdline):
        return False
    return None


def _atomic_write_pid(pid: int) -> None:
    if pid <= 0:
        raise ValueError("refusing to write invalid daemon PID")
    tmp = PID_FILE.with_suffix(".tmp")
    tmp.write_text(str(pid))
    tmp.replace(PID_FILE)


def _atomic_write_mode(mode: str) -> None:
    tmp = MODE_FILE.with_suffix(".tmp")
    tmp.write_text(mode)
    tmp.replace(MODE_FILE)


def _atomic_write_profile(profile: dict) -> None:
    tmp = PROFILE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(profile, indent=2, sort_keys=True))
    tmp.replace(PROFILE_FILE)


def _atomic_write_sandbox(disabled: bool) -> None:
    tmp = SANDBOX_FILE.with_suffix(".tmp")
    tmp.write_text("disabled" if disabled else "enabled")
    tmp.replace(SANDBOX_FILE)


def _same_profile(left: dict | None, right: dict | None) -> bool:
    if left is None or right is None:
        return False
    return (
        Path(left["user_data_dir"]).expanduser()
        == Path(right["user_data_dir"]).expanduser()
        and left.get("profile_directory") == right.get("profile_directory")
    )


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


def ensure_daemon(mode: str | None = None) -> int | None:
    """
    Idempotent + race-free: guarantee exactly one Chromium daemon is running
    on PORT, and return its PID when safely known. Safe to call from
    concurrent processes.

    If mode is explicit and a daemon already exists in the opposite mode, the
    caller must stop it first; a running browser cannot be made headed/headless
    in place.
    """
    _ensure_dirs()
    requested_mode = _normalize_launch_mode(mode) if mode is not None else None
    requested_profile = launch_profile()
    profile_explicit = _profile_mode_explicit()
    requested_no_sandbox = launch_no_sandbox()
    no_sandbox_explicit = _no_sandbox_explicit()

    with _StartLock():
        # Re-check inside the lock — someone else may have just started it.
        if is_daemon_alive():
            pid = _read_pid()
            if not _process_owns_debug_port(pid):
                # Adopt: alive but no usable PID file (e.g. survived state wipe).
                pid = _find_chrome_pid_on_port()
                if pid is not None:
                    _atomic_write_pid(pid)
            current_mode = running_launch_mode()
            if requested_mode is not None:
                if current_mode is None:
                    raise RuntimeError(
                        f"daemon is already running on port {PORT}, but its mode is unknown; "
                        f"run stop_daemon.py before starting {requested_mode} mode"
                    )
                if requested_mode != current_mode:
                    raise RuntimeError(
                        f"daemon is already running in {current_mode} mode on port {PORT}; "
                        f"run stop_daemon.py before starting {requested_mode} mode"
                    )
            current_profile = running_profile()
            if profile_explicit:
                if current_profile is None:
                    raise RuntimeError(
                        "daemon is already running, but its profile is unknown; "
                        "run stop_daemon.py before changing profiles"
                    )
                if not _same_profile(requested_profile, current_profile):
                    raise RuntimeError(
                        "daemon is already running with "
                        f"{current_profile['mode']} profile at {current_profile['user_data_dir']}; "
                        "run stop_daemon.py before changing profiles"
                    )
            current_no_sandbox = running_no_sandbox()
            if no_sandbox_explicit:
                if current_no_sandbox is None:
                    raise RuntimeError(
                        "daemon is already running, but its sandbox setting is unknown; "
                        "run stop_daemon.py before changing sandbox flags"
                    )
                if requested_no_sandbox != current_no_sandbox:
                    current = "disabled" if current_no_sandbox else "enabled"
                    requested = "disabled" if requested_no_sandbox else "enabled"
                    raise RuntimeError(
                        f"daemon is already running with Chrome sandbox {current}; "
                        f"run stop_daemon.py before starting with sandbox {requested}"
                    )
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
        launch_mode = requested_mode or default_launch_mode()
        launch_profile_spec = requested_profile
        user_data_dir = Path(launch_profile_spec["user_data_dir"]).expanduser()
        if launch_profile_spec["mode"] == "user" and not user_data_dir.exists():
            raise FileNotFoundError(
                f"Chrome user data dir does not exist: {user_data_dir}. "
                "Use --user-data-dir PATH or --skill-profile."
            )

        chrome = find_chrome()
        launch_args = [
            chrome,
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-default-apps",
            "--disable-extensions",
            "--disable-sync",
            "--mute-audio",
            f"--remote-debugging-port={PORT}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={user_data_dir}",
        ]
        if launch_mode == "headless":
            launch_args.insert(1, "--headless=new")
        if requested_no_sandbox:
            launch_args.insert(1, "--no-sandbox")
        if launch_profile_spec.get("profile_directory"):
            launch_args.append(f"--profile-directory={launch_profile_spec['profile_directory']}")

        log_fp = open(LOG_FILE, "ab")
        proc = subprocess.Popen(
            launch_args,
            stdout=log_fp,
            stderr=log_fp,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # detach from our process group
            close_fds=True,
        )
        _atomic_write_pid(proc.pid)
        _atomic_write_mode(launch_mode)
        _atomic_write_sandbox(requested_no_sandbox)
        _atomic_write_profile({
            **launch_profile_spec,
            "user_data_dir": str(user_data_dir),
        })

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
        try:
            MODE_FILE.unlink()
        except FileNotFoundError:
            pass
        try:
            PROFILE_FILE.unlink()
        except FileNotFoundError:
            pass
        try:
            SANDBOX_FILE.unlink()
        except FileNotFoundError:
            pass
        raise RuntimeError(
            f"chromium failed to come up within {DAEMON_BOOT_TIMEOUT_S}s. "
            f"See {LOG_FILE} for details."
        )


def _find_chrome_pid_on_port_proc(port: int = PORT) -> int | None:
    """Best-effort Linux/ProcFS lookup for a chrome PID on our debug port."""
    try:
        for d in Path("/proc").iterdir():
            if not d.name.isdigit():
                continue
            try:
                raw = (d / "cmdline").read_bytes()
            except (FileNotFoundError, PermissionError, OSError):
                continue
            cmdline = raw.replace(b"\0", b" ").decode("utf-8", "ignore")
            if _cmdline_is_chrome_debug_daemon(cmdline, port):
                return int(d.name)
    except OSError:
        pass
    return None


def _find_chrome_pid_on_port_lsof(port: int = PORT) -> int | None:
    """Best-effort macOS/Unix lookup for a chrome PID listening on the port."""
    if not shutil.which("lsof"):
        return None
    try:
        proc = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.isdigit():
            continue
        pid = int(line)
        if _process_owns_debug_port(pid, port):
            return pid
    return None


def _find_chrome_pid_on_port(port: int = PORT) -> int | None:
    """Best-effort: find a chrome PID with our --remote-debugging-port=PORT."""
    return _find_chrome_pid_on_port_proc(port) or _find_chrome_pid_on_port_lsof(port)


def _resolve_daemon_pid(port: int = PORT) -> int | None:
    pid = _read_pid()
    if _process_owns_debug_port(pid, port):
        return pid
    return _find_chrome_pid_on_port(port)


def _clear_session_state() -> None:
    """Remove ephemeral state that's only valid while a daemon is running."""
    for f in (PID_FILE, MODE_FILE, PROFILE_FILE, SANDBOX_FILE, PERSISTENT_TAB_FILE, REFS_FILE):
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
        alive = is_daemon_alive()
        pid = _resolve_daemon_pid()
        if pid is None:
            _clear_session_state()
            _clean_stale_locks()
            if alive:
                raise RuntimeError(
                    f"Chrome CDP daemon is alive on port {PORT}, but no safe PID "
                    "could be resolved. Refusing to kill an unidentified process."
                )
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

        for _ in range(20):
            if not is_daemon_alive():
                break
            time.sleep(0.1)
        else:
            raise RuntimeError(
                f"sent shutdown signals to PID {pid}, but Chrome CDP is still "
                f"alive on port {PORT}"
            )

        _clear_session_state()
        _clean_stale_locks()
        return True


# ──────────────────────────────────────────────────────────── nodriver ────

async def attach(mode: str | None = None):
    """
    Attach to the running daemon (auto-starting it if necessary).
    Returns a nodriver Browser instance.
    """
    ensure_daemon(mode=mode)
    profile = running_profile() or launch_profile()
    import nodriver as uc  # lazy
    config = uc.Config(
        host="127.0.0.1",
        port=PORT,
        browser_executable_path=find_chrome(),  # validated by Config.__init__
    )
    # Tell nodriver this is OUR profile dir, not a temp scratch one — this
    # sets _custom_data_dir=True so deconstruct_browser() skips its rmtree
    # and the noisy "successfully removed temp profile" print at exit.
    config.user_data_dir = profile["user_data_dir"]
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
