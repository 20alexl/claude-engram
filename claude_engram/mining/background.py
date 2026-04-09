"""
Background Miner — subprocess spawner for session log processing.

Heavy mining can't happen in hooks (1-2s timeout). This module spawns
a detached background process that runs after the hook returns.

Follows the same pattern as scorer_server.py: subprocess.Popen with
CREATE_NO_WINDOW on Windows, start_new_session on Unix.
"""

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path


LOCK_FILE = Path("~/.claude_engram/mining.lock").expanduser()
STATUS_FILE = Path("~/.claude_engram/mining_status.json").expanduser()


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with given PID is still running."""
    try:
        if platform.system() == "Windows":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except (OSError, PermissionError):
        return False


def is_mining_running() -> bool:
    """Check if a mining process is currently running."""
    if not LOCK_FILE.exists():
        return False
    try:
        pid = int(LOCK_FILE.read_text().strip())
        if _is_pid_alive(pid):
            return True
        # Stale lock
        LOCK_FILE.unlink(missing_ok=True)
        return False
    except (ValueError, OSError):
        LOCK_FILE.unlink(missing_ok=True)
        return False


def get_mining_status() -> dict:
    """Get current mining status."""
    if not STATUS_FILE.exists():
        return {"status": "idle"}
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"status": "unknown"}


def _write_status(status: dict):
    """Write mining status atomically."""
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(status), encoding="utf-8")
    tmp.replace(STATUS_FILE)


def _acquire_lock() -> bool:
    """Try to acquire the mining lock. Returns True if acquired."""
    if is_mining_running():
        return False
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(str(os.getpid()))
    return True


def _release_lock():
    """Release the mining lock."""
    LOCK_FILE.unlink(missing_ok=True)


def start_mining_background(
    project_path: str,
    mode: str = "post_session",
    engram_storage_dir: str = "~/.claude_engram",
) -> bool:
    """
    Spawn a background mining process. Fire-and-forget.

    Args:
        project_path: The project directory to mine sessions for
        mode: Mining mode:
            - "post_session": Index + extract from current session (default)
            - "index_only": Just update session index (fast)
            - "bootstrap": Full historical mining (all sessions)
            - "embed": Generate/update search embeddings
            - "full": Everything including pattern detection
        engram_storage_dir: Engram storage directory

    Returns:
        True if process was spawned, False if mining already running.
    """
    if is_mining_running():
        return False

    try:
        kwargs = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if platform.system() == "Windows":
            CREATE_NO_WINDOW = 0x08000000
            kwargs["creationflags"] = CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True

        subprocess.Popen(
            [
                sys.executable, "-m", "claude_engram.mining.background",
                "--project", project_path,
                "--mode", mode,
                "--storage", engram_storage_dir,
            ],
            **kwargs,
        )
        return True
    except Exception:
        return False


# ── Background worker entry point ────────────────────────────────────────

def run_mining(project_path: str, mode: str, engram_storage_dir: str):
    """
    Main mining worker. Runs in a background subprocess.

    Called by __main__ block below.
    """
    if not _acquire_lock():
        return

    try:
        _write_status({
            "status": "running",
            "project": project_path,
            "mode": mode,
            "started": time.time(),
            "phase": "indexing",
        })

        # Phase 1: Build/update session index
        from claude_engram.mining.session_index import build_project_index
        index = build_project_index(project_path, engram_storage_dir)

        if not index:
            _write_status({
                "status": "completed",
                "project": project_path,
                "mode": mode,
                "result": "no sessions found",
                "completed": time.time(),
            })
            return

        sessions_count = index.get_session_count()
        messages_count = index.get_total_messages()

        # Phase 2: Run extractors (if mode supports it)
        extraction_count = 0
        if mode in ("post_session", "bootstrap", "full"):
            _write_status({
                "status": "running",
                "project": project_path,
                "mode": mode,
                "started": time.time(),
                "phase": "extracting",
                "sessions_indexed": sessions_count,
            })

            try:
                from claude_engram.mining.extractors import run_extraction_pipeline
                extraction_count = run_extraction_pipeline(
                    project_path, index, engram_storage_dir
                )
            except ImportError:
                pass  # extractors not built yet (Phase 2)

        # Phase 3: Generate embeddings (if mode supports it)
        if mode in ("embed", "bootstrap", "full"):
            _write_status({
                "status": "running",
                "project": project_path,
                "mode": mode,
                "started": time.time(),
                "phase": "embedding",
            })

            try:
                from claude_engram.mining.search import build_session_embeddings
                build_session_embeddings(project_path, index, engram_storage_dir)
            except ImportError:
                pass  # search not built yet (Phase 3)

        # Phase 4: Pattern detection (if mode supports it)
        if mode in ("bootstrap", "full"):
            try:
                from claude_engram.mining.patterns import detect_all_patterns
                detect_all_patterns(project_path, index, engram_storage_dir)
            except ImportError:
                pass  # patterns not built yet (Phase 4)

        _write_status({
            "status": "completed",
            "project": project_path,
            "mode": mode,
            "sessions_indexed": sessions_count,
            "total_messages": messages_count,
            "extractions": extraction_count,
            "completed": time.time(),
        })

    except Exception as e:
        _write_status({
            "status": "error",
            "project": project_path,
            "mode": mode,
            "error": str(e),
            "completed": time.time(),
        })
    finally:
        _release_lock()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Claude Engram session miner")
    parser.add_argument("--project", required=True, help="Project path")
    parser.add_argument("--mode", default="post_session", help="Mining mode")
    parser.add_argument("--storage", default="~/.claude_engram", help="Storage dir")
    args = parser.parse_args()

    run_mining(args.project, args.mode, args.storage)
