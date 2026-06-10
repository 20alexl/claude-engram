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
                sys.executable,
                "-m",
                "claude_engram.mining.background",
                "--project",
                project_path,
                "--mode",
                mode,
                "--storage",
                engram_storage_dir,
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

    started = time.time()
    current_phase = "indexing"
    # Per-phase failures are isolated and recorded here instead of aborting the
    # remaining phases: a runtime error in extraction must not silently kill
    # patterns/cleanup/code-index for the run (the old blocks caught only
    # ImportError, so any other exception did exactly that).
    phase_errors: dict[str, str] = {}

    def _phase_status(phase: str, **extra):
        nonlocal current_phase
        current_phase = phase
        _write_status(
            {
                "status": "running",
                "project": project_path,
                "mode": mode,
                "started": started,
                "phase": phase,
                **extra,
            }
        )

    try:
        _phase_status("indexing")

        # Phase 1: Build/update session index. Not isolated: every later phase
        # consumes the index, so there is nothing useful to continue with.
        from claude_engram.mining.session_index import build_project_index

        index = build_project_index(project_path, engram_storage_dir)

        if not index:
            _write_status(
                {
                    "status": "completed",
                    "project": project_path,
                    "mode": mode,
                    "result": {"sessions": 0, "messages": 0, "extractions": 0},
                    "completed": time.time(),
                }
            )
            return

        sessions_count = index.get_session_count()
        messages_count = index.get_total_messages()

        # Phase 2: Run extractors (if mode supports it)
        extraction_count = 0
        if mode in ("post_session", "bootstrap", "full"):
            _phase_status("extracting", sessions_indexed=sessions_count)
            try:
                from claude_engram.mining.extractors import run_extraction_pipeline

                extraction_count = run_extraction_pipeline(
                    project_path, index, engram_storage_dir
                )
            except ImportError:
                pass  # optional dependency missing -- expected, not an error
            except Exception as e:
                phase_errors["extracting"] = str(e)[:200]

        # Phase 3: Generate embeddings (incremental -- skips already-embedded
        # sessions, so it is cheap to refresh every session end)
        if mode in ("post_session", "embed", "bootstrap", "full"):
            _phase_status("embedding")
            try:
                from claude_engram.mining.search import build_session_embeddings

                build_session_embeddings(project_path, index, engram_storage_dir)
            except ImportError:
                pass  # search/embedding deps not installed
            except Exception as e:
                phase_errors["embedding"] = str(e)[:200]

        # Phase 4: Pattern detection -- run every session end so the session-start
        # "recurring errors / struggles" banner stays current instead of frozen at
        # the one-time bootstrap (cheap: aggregates the already-built index)
        if mode in ("post_session", "bootstrap", "full"):
            _phase_status("patterns")
            try:
                from claude_engram.mining.patterns import detect_all_patterns

                detect_all_patterns(project_path, index, engram_storage_dir)
            except ImportError:
                pass
            except Exception as e:
                phase_errors["patterns"] = str(e)[:200]

        # Phase 5: Auto-cleanup (dedup + broken removal) AND keep memory
        # embeddings fresh. embed_all_memories is incremental (only new entries),
        # so hybrid_search "just works" without a manual embed_all — fixing the
        # stale embeddings.npy. Both reuse one store; embedding has its own try
        # so a cleanup failure never blocks it.
        if mode in ("post_session", "bootstrap", "full"):
            _phase_status("memory_maintenance")
            try:
                from claude_engram.tools.memory import MemoryStore

                store = MemoryStore(storage_dir=engram_storage_dir)
                try:
                    store.cleanup_memories(project_path, dry_run=False)
                except Exception as e:
                    phase_errors["memory_cleanup"] = str(e)[:200]
                try:
                    store.embed_all_memories(project_path)
                except Exception as e:
                    phase_errors["memory_embedding"] = str(e)[:200]
            except Exception as e:
                phase_errors["memory_maintenance"] = str(e)[:200]

        # Phase 6: Code index (per-project symbol table) -- the substrate for
        # pre-edit import/export verification + blast-radius. Incremental,
        # mtime-keyed, ast-only, scoped to one project (cheap every session end).
        if mode in ("post_session", "bootstrap", "full"):
            _phase_status("code_index")
            try:
                from claude_engram.mining.code_index import build_code_index
                from claude_engram.hooks.paths import get_project_memory_dir

                build_code_index(project_path, get_project_memory_dir(project_path))
            except Exception as e:
                phase_errors["code_index"] = str(e)[:200]

        final = {
            "status": "completed",
            "project": project_path,
            "mode": mode,
            "result": {
                "sessions": sessions_count,
                "messages": messages_count,
                "extractions": extraction_count,
            },
            "completed": time.time(),
        }
        if phase_errors:
            final["phase_errors"] = phase_errors
        _write_status(final)

    except Exception as e:
        status = {
            "status": "error",
            "project": project_path,
            "mode": mode,
            "phase": current_phase,
            "error": str(e),
            "completed": time.time(),
        }
        if phase_errors:
            status["phase_errors"] = phase_errors
        _write_status(status)
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
