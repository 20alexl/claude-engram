"""
Thin hook client — the process Claude Code actually spawns per hook event.

Run with ``python -S`` (skip site initialization): this file imports only
stdlib modules by hand, so a hook costs interpreter start + one TCP round
trip to the scorer/hook daemon (~30-60ms) instead of the full engram import
chain (~220ms). When the daemon is down, unsupported, or anything at all
goes wrong, it falls back to running the real handler in-process — same
behavior, original cost — and fire-and-forgets a daemon (re)start for the
next call.

Invoked by path, not as a module (``-S`` leaves site-packages off sys.path);
the repo root is derived from __file__ for the fallback import.
"""

import json
import os
import socket
import sys
import threading
import time

# Events the daemon serves. Lifecycle events (session start/end, stop,
# compaction) always run in-process — they spawn miners/servers and are rare.
DAEMON_EVENTS = {
    "pre_edit_json",
    "post_edit_json",
    "bash_json",
    "prompt_json",
    "pre_read_json",
    "tool_failure_json",
}

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _storage_dir() -> str:
    override = os.environ.get("CLAUDE_ENGRAM_DIR", "")
    if override:
        return os.path.expanduser(override)
    return os.path.join(os.path.expanduser("~"), ".claude_engram")


def _read_stdin(timeout_secs: float = 0.5) -> str:
    """Same contract as remind._read_stdin_with_timeout: one payload, or ""."""
    result = {"data": ""}

    def _read():
        try:
            result["data"] = sys.stdin.read()
        except Exception:
            pass

    t = threading.Thread(target=_read, daemon=True)
    t.start()
    t.join(timeout=timeout_secs)
    return result["data"]


_DEBUG = os.environ.get("CLAUDE_ENGRAM_HOOK_DEBUG", "")


def _dbg(msg: str) -> None:
    if _DEBUG:
        sys.stderr.write(f"[hook_client] {msg}\n")


def _try_daemon(hook_type: str, payload: str) -> bool:
    """One TCP round trip. True = response printed; False = use the fallback."""
    port_file = os.path.join(_storage_dir(), "scorer_port")
    try:
        with open(port_file) as f:
            port = int(f.read().strip())
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.25)
        sock.connect(("127.0.0.1", port))
        sock.settimeout(1.5)  # handlers are ~5-30ms warm; headroom, not budget
        request = {
            "hook_event": hook_type,
            "stdin": payload,
            "env": {
                "CLAUDE_PROJECT_DIR": os.environ.get("CLAUDE_PROJECT_DIR", "")
            },
        }
        sock.sendall((json.dumps(request) + "\n").encode("utf-8"))
        data = b""
        while b"\n" not in data:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
        sock.close()
        response = json.loads(data.decode("utf-8").strip())
        if "output" not in response:
            _dbg(f"daemon error response: {str(response)[:120]}")
            return False  # old server / error — run the real handler instead
        out = response["output"]
        if out:
            sys.stdout.write(out)
            sys.stdout.flush()
        _dbg("served by daemon")
        return True
    except Exception as e:
        _dbg(f"daemon unreachable: {type(e).__name__}: {e}")
        return False


def _run_fallback(hook_type: str, payload: str) -> None:
    """Run the real handler in this process (repo on sys.path; site skipped
    by -S doesn't matter for an editable/source install)."""
    sys.path.insert(0, _REPO_ROOT)
    try:
        from claude_engram.hooks import remind

        remind._stdin_cache = payload
        remind.main()
    except SystemExit:
        pass
    except Exception:
        pass


def _nudge_daemon() -> None:
    """Fire-and-forget daemon start so the NEXT hook call is fast. After the
    fallback has produced its output, so the only cost is this spawn.

    A 30s-TTL marker keeps a burst of falling-back hooks from spawning a
    pile of servers (each would load the model; last one wins PORT_FILE)."""
    marker = os.path.join(_storage_dir(), "scorer_starting")
    try:
        if os.path.exists(marker) and time.time() - os.path.getmtime(marker) < 30:
            return
        with open(marker, "w") as f:
            f.write(str(time.time()))
    except Exception:
        pass
    try:
        import subprocess

        kwargs = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(
            [sys.executable, "-m", "claude_engram.hooks.scorer_server"],
            cwd=_REPO_ROOT,
            **kwargs,
        )
    except Exception:
        pass


def main() -> None:
    hook_type = sys.argv[1] if len(sys.argv) > 1 else ""
    if not hook_type:
        return
    payload = _read_stdin()

    if hook_type in DAEMON_EVENTS and _try_daemon(hook_type, payload):
        return

    _run_fallback(hook_type, payload)
    if hook_type in DAEMON_EVENTS:
        _nudge_daemon()


if __name__ == "__main__":
    main()
