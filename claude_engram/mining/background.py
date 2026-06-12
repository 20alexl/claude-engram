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
            - "live": Mid-session freshness tick — index + extract + embed
              the active session's new tail and refresh the two most recent
              code indexes; skips patterns/memory maintenance (session-end work)
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


def _recent_subprojects(index, root: str, limit: int = 5) -> list[str]:
    """Sub-project roots whose files recent sessions actually edited.

    The root build's file walk prunes nested project-marker dirs, so each
    active sub-project needs its own (incremental, cheap) build — otherwise
    the indexes that pre-edit hooks and deps_map symbol lookup read go stale.
    """
    from claude_engram.hooks.paths import _normalize_path, resolve_project_for_file

    norm_root = _normalize_path(root)

    def _get(meta, key, default):
        if isinstance(meta, dict):
            return meta.get(key, default)
        return getattr(meta, key, default)

    sessions = sorted(
        index.sessions.values(),
        key=lambda m: _get(m, "last_timestamp", ""),
        reverse=True,
    )[:10]
    out: list[str] = []
    for meta in sessions:
        for f in _get(meta, "files_edited", [])[:200]:
            try:
                sub = _normalize_path(resolve_project_for_file(f, norm_root))
            except Exception:
                continue
            if sub and sub != norm_root and sub not in out:
                out.append(sub)
                if len(out) >= limit:
                    return out
    return out


def _recent_session_files(index, sessions: int = 15) -> set:
    """Basenames edited in the most recent sessions — the "active area"
    signal mistake hygiene uses to keep mistakes near current work hot."""
    metas = sorted(
        (m for m in index.sessions.values()),
        key=lambda m: (
            m.get("last_timestamp", "")
            if isinstance(m, dict)
            else getattr(m, "last_timestamp", "")
        ),
        reverse=True,
    )[:sessions]
    out: set = set()
    for meta in metas:
        files = (
            meta.get("files_edited", [])
            if isinstance(meta, dict)
            else getattr(meta, "files_edited", [])
        )
        for f in files:
            try:
                out.add(Path(f).name.lower())
            except Exception:
                continue
    return out


def _schema_canary(index) -> str:
    """Detect a collapse in JSONL recognition rate (a Claude Code log-format
    change would silently degrade everything mining produces). Compares the
    newest sessions against the historical baseline; returns a warning line,
    or "" when healthy or there's not enough data to judge."""
    MIN_LINES = 50  # ignore tiny sessions — their ratios are noise
    MIN_BASELINE_SESSIONS = 5
    RECENT_WINDOW = 3

    sessions = [
        m for m in index.sessions.values() if m.get("line_count", 0) >= MIN_LINES
    ]
    if len(sessions) < MIN_BASELINE_SESSIONS + RECENT_WINDOW:
        return ""
    sessions.sort(key=lambda m: m.get("last_timestamp", ""))
    recent = sessions[-RECENT_WINDOW:]
    baseline = sessions[:-RECENT_WINDOW]

    def rate(group):
        lines = sum(m.get("line_count", 0) for m in group)
        known = sum(m.get("known_type_count", 0) for m in group)
        return (known / lines) if lines else 1.0

    base_rate = rate(baseline)
    recent_rate = rate(recent)
    if base_rate >= 0.8 and recent_rate < 0.5 * base_rate:
        return (
            f"session-log recognition collapsed: {recent_rate:.0%} of recent "
            f"log lines recognized vs {base_rate:.0%} baseline — Claude Code "
            f"may have changed its log format; session mining is degraded "
            f"(update claude-engram or report an issue)"
        )
    return ""


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

        # Phase 2: Run extractors (if mode supports it). "live" runs them
        # too: extraction skips already-seen sessions and re-extracts grown
        # ones, so mid-session runs only pay for the active session's tail.
        extraction_count = 0
        if mode in ("post_session", "bootstrap", "full", "live"):
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

        # Phase 3: Generate embeddings (incremental -- watermarks mean only
        # the new transcript tail embeds, so it is cheap to refresh every
        # session end and every live tick)
        if mode in ("post_session", "embed", "bootstrap", "full", "live"):
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
                # Mistake hygiene: one-off auto-captured mistakes that went
                # stale (3+ weeks, never recurred, away from current work)
                # move to the archive so pre-edit banners keep their signal.
                # Sub-projects hold their own mistake stores — sweep the
                # recently-active ones too.
                try:
                    recent = _recent_session_files(index)
                    # Sweep EVERY registered project, not just recent ones:
                    # dormant projects (an old chappie/V7 store) are exactly
                    # where stale mistakes pile up, and the sweep is a cheap
                    # json pass per project.
                    from claude_engram.hooks.paths import _get_manifest

                    for proj_path in (
                        _get_manifest().get("projects", {}) or {project_path: 1}
                    ):
                        store.archive_stale_mistakes(
                            proj_path, recent_files=recent, dry_run=False
                        )
                except Exception as e:
                    phase_errors["mistake_hygiene"] = str(e)[:200]
                # Curated-lessons bridge: dated entries in lesson files
                # sync as protected "lesson" memories with code-index-joined
                # triggers. STRICTLY opt-in: runs only when config.json
                # sets lessons_globs; no default path ships with the tool.
                try:
                    from claude_engram.mining.lessons import sync_lessons

                    sync_lessons(store, project_path)
                    for sub in _recent_subprojects(index, project_path):
                        sync_lessons(store, sub)
                except Exception as e:
                    phase_errors["lessons"] = str(e)[:200]
                try:
                    store.embed_all_memories(project_path)
                except Exception as e:
                    phase_errors["memory_embedding"] = str(e)[:200]
            except Exception as e:
                phase_errors["memory_maintenance"] = str(e)[:200]
            try:
                # Close the Cap-6 loop: refresh the bounded per-kind
                # multipliers the pre-edit scorer reads.
                from claude_engram.mining.outcomes import write_weights

                write_weights()
            except Exception as e:
                phase_errors["injection_weights"] = str(e)[:200]

        # Phase 6: Code index (per-project symbol table) -- the substrate for
        # pre-edit import/export verification + blast-radius. Incremental,
        # mtime-keyed, ast-only, scoped to one project (cheap every session end).
        if mode in ("post_session", "bootstrap", "full", "live"):
            _phase_status("code_index")
            try:
                from claude_engram.mining.code_index import build_code_index
                from claude_engram.hooks.paths import get_project_memory_dir

                build_code_index(project_path, get_project_memory_dir(project_path))
                # Sub-projects the recent sessions actually edited get their
                # own refresh: the root build's walk prunes nested
                # project-marker dirs, so without this the per-sub-project
                # indexes (read by pre-edit hooks and deps_map symbol lookup)
                # go stale forever in workspace setups. Live ticks sweep only
                # the two most recent (= the active session's projects).
                try:
                    limit = 2 if mode == "live" else 5
                    for sub in _recent_subprojects(index, project_path, limit=limit):
                        build_code_index(sub, get_project_memory_dir(sub))
                except Exception as e:
                    phase_errors["code_index_subprojects"] = str(e)[:200]
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
        try:
            warning = _schema_canary(index)
            if warning:
                final["schema_warning"] = warning
        except Exception:
            pass  # the canary must never break the run it watches
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
