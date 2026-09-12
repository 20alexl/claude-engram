"""
Where the repo and the run stand, for a checkpoint to record and a restore
to compare against.

A restored checkpoint carries the last session's framing. Before acting on
it the model should know how far the repo moved since: commits landed,
files changed, and whether the files the checkpoint names are among them.
That is one git call at save time (the commit) and two at restore time
(bounded, best effort, silent when there is no repo).

The active /goal is the other thing a checkpoint should carry: a resumed
session then reads the condition it is working toward without re-mining
the transcript.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Optional

_GIT_TIMEOUT = 4.0


def _git(args: list[str], cwd: str) -> Optional[str]:
    t0 = time.time()
    outcome = ""
    try:
        r = subprocess.run(
            ["git", "--no-optional-locks", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
        outcome = f"rc={r.returncode}"
        return r.stdout if r.returncode == 0 else None
    except Exception as e:
        outcome = f"{type(e).__name__}: {str(e)[:120]}"
        return None
    finally:
        _trace(f"git {' '.join(args)} cwd={cwd} {outcome} {time.time() - t0:.2f}s")


def _trace(line: str) -> None:
    """Append one line to CLAUDE_ENGRAM_GIT_TRACE when set: a git call that
    times out inside a long-lived process (the MCP server) is invisible
    otherwise -- the caller just sees ''."""
    p = os.environ.get("CLAUDE_ENGRAM_GIT_TRACE", "")
    if not p:
        return
    try:
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%H:%M:%S')} pid={os.getpid()} {line}\n")
    except Exception:
        pass


def head(project_dir: str) -> str:
    """Short HEAD sha, or '' outside a repo."""
    if not project_dir or not Path(project_dir).is_dir():
        return ""
    out = _git(["rev-parse", "--short", "HEAD"], project_dir)
    return (out or "").strip()


def since(commit: str, project_dir: str, files: Optional[list[str]] = None) -> Optional[dict]:
    """How the repo moved since ``commit``:
    {commits, files_changed, touched (checkpoint files among them), missing}.
    None outside a repo or with no commit to compare."""
    if not commit or not project_dir or not Path(project_dir).is_dir():
        return None
    if _git(["cat-file", "-e", f"{commit}^{{commit}}"], project_dir) is None:
        return {"commits": 0, "files_changed": 0, "touched": [], "missing": True}
    count = (_git(["rev-list", "--count", f"{commit}..HEAD"], project_dir) or "0").strip()
    # Every local branch, worktrees included: a checkpoint taken on main
    # said "no commits" while nine sat on three worktree branches
    # (2026-09-12). HEAD's own count is subtracted so the two never overlap.
    everywhere = (_git(["rev-list", "--count", "--branches", "--not", commit], project_dir) or "0").strip()
    names = _git(["diff", "--name-only", f"{commit}..HEAD"], project_dir) or ""
    changed = [n.strip().replace("\\", "/") for n in names.splitlines() if n.strip()]
    touched: list[str] = []
    for f in files or []:
        fp = str(f).replace("\\", "/")
        base = fp.rsplit("/", 1)[-1]
        if any(c == fp or c.endswith("/" + base) or fp.endswith("/" + c) or c == base for c in changed):
            touched.append(base)
    try:
        n = int(count)
    except ValueError:
        n = 0
    try:
        elsewhere = max(0, int(everywhere) - n)
    except ValueError:
        elsewhere = 0
    return {"commits": n, "files_changed": len(changed), "touched": touched, "missing": False, "other_branches": elsewhere}


def since_text(info: Optional[dict]) -> str:
    """One line for a banner, or '' when there is nothing to say."""
    if not info:
        return ""
    if info.get("missing"):
        return "Since this checkpoint: its commit is not in this history (rewritten or another clone)"
    n, f = int(info.get("commits", 0)), int(info.get("files_changed", 0))
    other = int(info.get("other_branches", 0) or 0)
    if not n and not f:
        line = "Since this checkpoint: no commits on this branch"
    else:
        line = f"Since this checkpoint: {n} commit{'s' if n != 1 else ''}, {f} file{'s' if f != 1 else ''} changed"
        if info.get("touched"):
            line += " -- incl. " + ", ".join(info["touched"][:4])
    if other:
        line += f"; {other} commit{'s' if other != 1 else ''} on other local branches (worktrees included)"
    return line


def goal_for_session(state: dict) -> str:
    """The active /goal condition: what the launcher recorded, else the goal
    the session's transcript shows as still open (hooks/autorun.scan_goal:
    a met, failed or cleared goal is not active and is not stamped)."""
    _run = state.get("run")
    run: dict = _run if isinstance(_run, dict) else {}
    goal = str(run.get("goal") or "").strip()
    if goal:
        return goal
    tp = str(run.get("transcript_path") or "")
    if not tp or not Path(tp).is_file():
        return ""
    try:
        from claude_engram.hooks.autorun import scan_goal

        s = scan_goal(tp)
        if not s.get("active"):
            return ""
        return " ".join(str(s.get("condition") or "").split()).strip()
    except Exception:
        return ""
