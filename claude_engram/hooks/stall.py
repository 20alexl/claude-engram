"""
No-progress detection: strikes that count EFFECT, not activity.

``/goal``'s own stall rule stops a loop after several turns with no tool
use. The overnight failure that matters is the other one: a run that uses
tools every turn and changes nothing -- nine turns of ``cat`` on a file that
is not going to change (the reference case, 2026-09-09, $3.68). So the unit
here is the assistant TURN, closed at the Stop hook, and a turn is judged by
what it changed:

* good     -- a file changed (Edit/Write/MultiEdit/NotebookEdit succeeded, a
              mutating shell command ran, or the git working tree differs
              from the last reading), a test's pass/fail status flipped, a
              commit landed, or work was delegated to an agent.
* no-effect -- tools were used and none of that happened.
* neutral  -- no tools at all (a plain answer; ``/goal``'s territory), the
              turn parked on a wait primitive (Monitor, ScheduleWakeup,
              a cron, a task-output wait), or it only ran tests that were
              not a repeat of the last run (verification). Parking is the
              healthy pattern when a goal waits on scheduled work; a long
              suite or three different benches in a row is not a stall.
              The same test command with the same verdict again IS one.

Turns, not time: a four-hour foreground command is one turn.

Neutral turns are transparent: they touch neither streak.

The ladder (design/AUTONOMY-PLAN.md §6A): ``STALL_TURNS`` consecutive
no-effect turns = one strike; the strike text is staged and delivered at
the next injection point (a Stop hook cannot add context). Strike 1 is a
warning. Strike 2 re-injects the latest checkpoint and the rules and asks
for a bearings check. Strike 3 is the cap; in autonomy mode it becomes the
halt (Phase 6), here it is the loudest warning. Strikes DECAY, they do not
reset: ``DECAY_GOOD_TURNS`` consecutive good turns remove one strike,
repeatedly, down to zero. A hard reset would let one edited line wipe a
pattern of stalls; no decay would halt an eight-hour run over three stalls
spread across it.

Every increment and decrement is an event with the turn number, kept in the
session state for the run report.

Tool accounting arrives from two places and is idempotent: PostToolBatch
(every call in the batch, no matcher needed) and the PostToolUse handlers
for Edit/Write and Bash (a fallback for settings that predate the batch
hook). The turn closes at Stop.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import time
from typing import Any, Optional

STALL_TURNS = 3  # consecutive no-effect turns per strike
DECAY_GOOD_TURNS = 5  # K: consecutive good turns that remove one strike
STRIKE_CAP = 3
EVENTS_KEEP = 60
_GIT_TIMEOUT = 4.0

EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
DELEGATE_TOOLS = frozenset({"Agent", "Task", "Workflow"})
PARK_TOOLS = frozenset(
    {
        "Monitor",
        "ScheduleWakeup",
        "CronCreate",
        "TaskOutput",
        "AskUserQuestion",
        "SendMessage",
        "RemoteTrigger",
    }
)
# Engram's own durable writes: a checkpoint, a logged decision or mistake, a
# remembered fact. Not file progress on the project, but not circling either.
RECORD_TOOLS = frozenset(
    {
        "mcp__claude-engram__context",
        "mcp__claude-engram__memory",
        "mcp__claude-engram__work",
        "mcp__claude-engram__convention",
    }
)

_MUTATING_FIRST_WORDS = frozenset(
    {
        "mv",
        "cp",
        "rm",
        "trash",
        "mkdir",
        "rmdir",
        "touch",
        "ln",
        "chmod",
        "chown",
        "patch",
        "tee",
        "dd",
        "unzip",
        "tar",
        "install",
        "rsync",
        "truncate",
        "shred",
    }
)
_MUTATING_GIT = frozenset(
    {
        "commit",
        "checkout",
        "switch",
        "stash",
        "merge",
        "rebase",
        "apply",
        "cherry-pick",
        "reset",
        "restore",
        "mv",
        "rm",
        "add",
        "revert",
        "tag",
        "branch",
        "pull",
        "fetch",
        "clone",
        "worktree",
        "am",
    }
)
_INSTALLERS = re.compile(
    r"^(?:pip3?|uv|poetry|npm|pnpm|yarn|cargo|go|apt(?:-get)?|brew|choco|winget)\s+"
    r"(?:install|add|remove|uninstall|update|upgrade|build|sync|i)\b"
)
_SED_INPLACE = re.compile(r"^sed\s+(?:-\S*\s+)*-i\b|^sed\s+(?:-\S*\s+)*--in-place\b")
_SCRIPT_RUN = re.compile(
    r"^(?:[\w.\\/-]*python[\w.]*(?:\.exe)?|node|ruby|perl|bash|sh|pwsh|powershell(?:\.exe)?)\s+"
    r"(?!-c\b|-m\s+(?:pytest|unittest)\b)"
)
_REDIRECT = re.compile(r"(?<![0-9&])>>?\s*(?!&|/dev/null|\$null\b|NUL\b)\S")
_NOISE_REDIRECTS = re.compile(r"\d?>\s*&\s*\d|\d?>\s*(?:/dev/null|\$null|NUL)\b|&>\s*(?:/dev/null|\$null|NUL)\b")
_SEGMENT = re.compile(r"&&|\|\||;|\n|\|(?!\|)")
# Engram operations that read rather than write (context/memory/work/convention).
_READ_OP = re.compile(
    r"^(?:recall|search|list|get|restore|status|query|check|show|read|find)$"
    r"|(?:^|_)(?:restore|list|get|recall|search|check|status)$"
)


# ---------------------------------------------------------------------------
# Classification of a single tool call
# ---------------------------------------------------------------------------


def _first_word(segment: str) -> str:
    seg = segment.strip()
    # Strip env assignments and a leading sudo.
    while True:
        m = re.match(r"^(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+|sudo\s+)", seg)
        if not m:
            break
        seg = seg[m.end() :]
    return (re.split(r"\s+", seg, maxsplit=1)[0] if seg else "").lower()


def bash_mutates(command: str) -> bool:
    """Does this shell command plausibly change files? A heuristic on the
    command text: redirections to a real path, in-place sed, file utilities,
    mutating git subcommands, package installs, and running a script file.
    ``cat``, ``grep``, ``ls``, ``git status``, ``python -c`` and test runs
    do not count."""
    if not command:
        return False
    cmd = _NOISE_REDIRECTS.sub(" ", command)
    if _REDIRECT.search(cmd):
        return True
    for seg in _SEGMENT.split(cmd):
        seg = seg.strip()
        if not seg:
            continue
        low = seg.lower()
        fw = _first_word(seg)
        if fw in _MUTATING_FIRST_WORDS:
            return True
        if fw == "sed" and _SED_INPLACE.search(low):
            return True
        if fw == "git":
            parts = re.split(r"\s+", low)
            sub = next((p for p in parts[1:] if not p.startswith("-")), "")
            if sub in _MUTATING_GIT:
                return True
        if _INSTALLERS.search(low):
            return True
        if _SCRIPT_RUN.search(low) and not _looks_like_test(low):
            return True
    return False


_RUNNERS = re.compile(
    r"^(?:pytest|py\.test|unittest|jest|mocha|vitest|tox|nox|cargo\s+test|go\s+test|"
    r"make\s+test|npm\s+(?:run\s+)?test|pnpm\s+test|yarn\s+test|dotnet\s+test|ctest)\b"
)
_PY_TEST = re.compile(
    r"^[\w.\\/-]*python[\w.]*(?:\.exe)?\s+(?:-m\s+(?:pytest|unittest)\b|"
    r"\S*(?:tests?[\\/]\S*\.py|bench_\w+\.py|test_\w+\.py|\w+_test\.py)\b)"
)


def _looks_like_test(low: str) -> bool:
    """Is this a test INVOCATION? Judged on what runs, never on what a read
    mentions: `cat goal-test/out.txt` is not a test, `python tests/x.py` is."""
    for seg in _SEGMENT.split(low):
        seg = seg.strip()
        while True:
            m = re.match(r"^(?:[a-z_][a-z0-9_]*=\S*\s+|sudo\s+)", seg)
            if not m:
                break
            seg = seg[m.end() :]
        if _RUNNERS.search(seg) or _PY_TEST.search(seg):
            return True
    return False


def _response_text(resp: Any) -> str:
    if isinstance(resp, dict):
        parts = [str(resp.get(k, "")) for k in ("stdout", "stderr", "text", "output")]
        return "\n".join(p for p in parts if p)
    if isinstance(resp, list):
        return "\n".join(_response_text(r) for r in resp)
    return str(resp or "")


def _response_failed(resp: Any) -> bool:
    if isinstance(resp, dict):
        if resp.get("is_error") or resp.get("isError"):
            return True
        if resp.get("interrupted"):
            return True
    return False


def test_outcome(command: str, response: Any) -> Optional[bool]:
    """True/False when the command was a test run with a readable verdict,
    else None. Mirrors the shapes the bash handler already recognises."""
    low = (command or "").lower()
    if not _looks_like_test(low):
        return None
    text = _response_text(response)
    tail = text[-2000:]
    if re.search(r"\bALL PASS\b", tail):
        return True
    m_fail = re.search(r"\b(\d+)\s+(?:failed|errors?)\b", tail)
    if m_fail and int(m_fail.group(1)) > 0:
        return False
    if re.search(r"\b(?:FAILED|FAIL)\b", tail) and not re.search(r"\b0 failed\b", tail):
        return False
    if re.search(r"\b\d+\s+passed\b|\bOK\b|\[PASS\]", tail):
        return True
    return None


def classify_tool(name: str, tool_input: Any, response: Any) -> str:
    """One of ``file``, ``test``, ``commit``, ``delegate``, ``record``,
    ``park``, ``none``. ``test`` means a test run with a verdict; whether the
    status CHANGED is decided at the turn level against the last status."""
    name = name or ""
    ti = tool_input if isinstance(tool_input, dict) else {}
    if name in EDIT_TOOLS:
        return "none" if _response_failed(response) else "file"
    if name in DELEGATE_TOOLS:
        return "delegate"
    if name in PARK_TOOLS:
        return "park"
    if name in RECORD_TOOLS:
        op = str(ti.get("operation") or ti.get("action") or "").lower()
        if op and _READ_OP.search(op):
            return "none"
        return "record"
    if name in ("Bash", "PowerShell"):
        cmd = str(ti.get("command") or "")
        if ti.get("run_in_background"):
            return "park"
        if _response_failed(response):
            return "none"
        if _looks_like_test(cmd.lower()):
            return "test"
        if re.search(r"\bgit\s+commit\b", cmd):
            return "commit"
        if bash_mutates(cmd):
            return "file"
        return "none"
    if name.startswith("mcp__") and re.search(r"(create|write|set|update|delete|edit|insert|upload|import|rename|move)", name.lower()):
        return "none" if _response_failed(response) else "file"
    return "none"


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


def stall_state(state: dict) -> dict:
    st = state.get("stall")
    if not isinstance(st, dict):
        st = {}
        state["stall"] = st
    st.setdefault("strikes", 0)
    st.setdefault("max_strikes", 0)
    st.setdefault("good_streak", 0)
    st.setdefault("noeffect_streak", 0)
    st.setdefault("last_change_at", 0.0)
    st.setdefault("turns", {"good": 0, "noeffect": 0, "neutral": 0})
    st.setdefault("events", [])
    st.setdefault("pending", None)
    st.setdefault("tree_fingerprint", None)
    st.setdefault("last_test_passed", None)
    st.setdefault("turn", _fresh_turn())
    return st


def _fresh_turn() -> dict:
    return {"tools": 0, "effects": [], "parked": False, "delegated": False, "test_passed": None}


def note_tool(state: dict, name: str, tool_input: Any = None, response: Any = None) -> str:
    """Account one tool call to the open turn. Returns the class."""
    st = stall_state(state)
    turn = st["turn"]
    turn["tools"] = int(turn.get("tools", 0)) + 1
    kind = classify_tool(name, tool_input, response)
    if kind == "park":
        turn["parked"] = True
    elif kind == "delegate":
        turn["delegated"] = True
        turn.setdefault("effects", []).append("delegate")
    elif kind == "test":
        cmd = str((tool_input or {}).get("command") or "") if isinstance(tool_input, dict) else ""
        passed = test_outcome(cmd, response)
        turn["test_passed"] = passed
        turn.setdefault("test_runs", []).append([" ".join(cmd.split())[:300], passed])
    elif kind in ("file", "commit", "record"):
        turn.setdefault("effects", []).append(kind)
    return kind


def note_batch(state: dict, tool_calls: list) -> int:
    """PostToolBatch: account every call in the batch. Returns the count."""
    n = 0
    for call in tool_calls or []:
        if not isinstance(call, dict):
            continue
        note_tool(state, str(call.get("tool_name") or ""), call.get("tool_input"), call.get("tool_response"))
        n += 1
    return n


def tree_fingerprint(project_dir: str) -> Optional[str]:
    """A cheap digest of the git working tree: HEAD plus the porcelain status.
    Only consulted on turns that otherwise look effect-free, so its cost is
    paid on the suspect path, not the healthy one."""
    if not project_dir or not os.path.isdir(project_dir):
        return None
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
        if head.returncode != 0:
            return None
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
        if status.returncode != 0:
            return None
        h = hashlib.sha1()
        h.update(head.stdout.strip().encode())
        h.update(status.stdout.encode("utf-8", "replace"))
        return h.hexdigest()
    except Exception:
        return None


def _event(st: dict, turn_no: int, kind: str, reason: str) -> None:
    ev = {"turn": int(turn_no), "kind": kind, "strikes": int(st["strikes"]), "at": time.time(), "reason": reason}
    st["events"] = (st.get("events") or [])[-(EVENTS_KEEP - 1) :] + [ev]


def _env_int(name: str, default: int) -> int:
    try:
        v = int(os.environ.get(name, "") or default)
        return v if v > 0 else default
    except ValueError:
        return default


def close_turn(state: dict, turn_no: int, project_dir: str = "", fingerprint=tree_fingerprint) -> str:
    """Stop hook: judge the turn that just ended and advance the ladder.
    Returns the turn's class (``good``, ``noeffect``, ``neutral``)."""
    st = stall_state(state)
    turn = st.get("turn") or _fresh_turn()
    st["turn"] = _fresh_turn()
    if isinstance(st.get("halted"), dict):
        # The ladder is done its job; turns after the halt (denied calls,
        # the closing notification) are not more strikes.
        st["turns"]["neutral"] = int(st["turns"].get("neutral", 0)) + 1
        return "halted"
    stall_turns = _env_int("CLAUDE_ENGRAM_STALL_TURNS", STALL_TURNS)
    decay_k = _env_int("CLAUDE_ENGRAM_STALL_DECAY", DECAY_GOOD_TURNS)
    cap = _env_int("CLAUDE_ENGRAM_STRIKE_CAP", STRIKE_CAP)

    if int(turn.get("tools", 0)) == 0 or turn.get("parked"):
        st["turns"]["neutral"] = int(st["turns"].get("neutral", 0)) + 1
        return "neutral"

    effects = list(turn.get("effects") or [])
    # A test run is progress when the status flipped. Otherwise it is
    # verification, which is neither progress nor circling -- unless it is
    # the SAME command with the SAME verdict as the last run, which is the
    # re-run-and-hope pattern and counts like any other no-effect turn. So a
    # long suite, or three different benches in three turns, never strike.
    tp = turn.get("test_passed")
    runs = [tuple(r) for r in (turn.get("test_runs") or []) if isinstance(r, (list, tuple)) and len(r) == 2]
    verification = False
    if runs:
        if tp is not None and st.get("last_test_passed") != tp:
            effects.append("test-status")
        if tp is not None:
            st["last_test_passed"] = tp
        last_key = st.get("last_test_key")
        last_key = tuple(last_key) if isinstance(last_key, (list, tuple)) else None
        if any(r != last_key for r in runs):
            verification = True
        st["last_test_key"] = list(runs[-1])
    if not effects and verification:
        st["turns"]["neutral"] = int(st["turns"].get("neutral", 0)) + 1
        return "neutral"

    if not effects:
        fp = fingerprint(project_dir) if callable(fingerprint) else None
        if fp is not None:
            prev = st.get("tree_fingerprint")
            st["tree_fingerprint"] = fp
            if prev is not None and prev != fp:
                effects.append("tree")
    else:
        # The tree moved under a flagged effect; the next reading starts fresh.
        st["tree_fingerprint"] = None

    if effects:
        st["turns"]["good"] = int(st["turns"].get("good", 0)) + 1
        st["good_streak"] = int(st.get("good_streak", 0)) + 1
        st["noeffect_streak"] = 0
        st["last_change_at"] = time.time()
        st["last_effects"] = effects[:6]
        if st["strikes"] > 0 and st["good_streak"] >= decay_k:
            st["strikes"] = int(st["strikes"]) - 1
            st["good_streak"] = 0
            _event(st, turn_no, "decay", f"{decay_k} good turns")
        return "good"

    st["turns"]["noeffect"] = int(st["turns"].get("noeffect", 0)) + 1
    st["noeffect_streak"] = int(st.get("noeffect_streak", 0)) + 1
    st["good_streak"] = 0
    if st["noeffect_streak"] >= stall_turns:
        st["noeffect_streak"] = 0
        st["strikes"] = min(cap, int(st["strikes"]) + 1)
        st["max_strikes"] = max(int(st.get("max_strikes", 0)), st["strikes"])
        _event(st, turn_no, "strike", f"{stall_turns} turns without effect")
        st["pending"] = {"strike": st["strikes"], "at": time.time(), "turns": stall_turns, "turn": int(turn_no)}
    return "noeffect"


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


def _since(st: dict) -> str:
    t = float(st.get("last_change_at") or 0.0)
    if not t:
        return "no change recorded this session"
    mins = (time.time() - t) / 60.0
    return f"last change {mins:.0f} min ago" if mins >= 1 else "last change under a minute ago"


def strike_text(strike: int, turns: int, st: dict, bearings: Optional[list[str]] = None) -> str:
    cap = _env_int("CLAUDE_ENGRAM_STRIKE_CAP", STRIKE_CAP)
    decay_k = _env_int("CLAUDE_ENGRAM_STALL_DECAY", DECAY_GOOD_TURNS)
    head = f"<engram-stall>Strike {strike} of {cap}: {turns} turns with tool use and no effect"
    head += f" -- no file changed, no test status changed, nothing committed ({_since(st)})."
    if strike <= 1:
        body = (
            " If this is research, fine; say what you are looking for. If you are "
            "re-reading or re-running the same thing waiting for it to change, stop: "
            "name what is blocking, and either change your approach or park on a "
            "wait primitive (Monitor / ScheduleWakeup) instead of polling."
        )
    elif strike < cap:
        body = (
            " Bearings check before the next tool call: (1) what is the task, (2) what "
            "was the last thing that actually changed, (3) what has been blocking since, "
            "(4) what different action closes the gap. Answer in one line each, then act "
            "on (4). The checkpoint and rules follow."
        )
    else:
        body = (
            " This is the cap. In autonomy mode the next no-effect run halts the session "
            "and writes the run report. State the blocker plainly, bank a "
            "context(checkpoint_save), and either take a different action or stop."
        )
    tail = f" Strikes decay: {decay_k} consecutive turns with real effect remove one.</engram-stall>"
    text = head + body + tail
    if bearings and strike >= 2:
        text += "\n" + "\n".join(bearings)
    return text


def nudge(state: dict, bearings: Optional[list[str]] = None) -> tuple[str, bool]:
    """Deliver a staged strike once. Returns (text, state_changed)."""
    st = stall_state(state)
    p = st.get("pending")
    if not isinstance(p, dict):
        return "", False
    st["pending"] = None
    return strike_text(int(p.get("strike", 1)), int(p.get("turns", STALL_TURNS)), st, bearings), True


# ---------------------------------------------------------------------------
# The halt (autonomy mode only)
# ---------------------------------------------------------------------------
#
# At the cap, in autonomy mode, engram STARVES the run: PreToolUse denies
# every tool call. A deny ends the turn; with no tool use, /goal's own stall
# rule ("no tool use for several turns") closes the loop and leaves the goal
# set. Engram never answers the Stop hook -- hooks merge most-restrictive, so
# a /goal block would out-vote it anyway. Two calls stay allowed so the model
# can leave a record: engram's checkpoint_save and PushNotification.

# ToolSearch stays open too: on the newest models PushNotification is a
# deferred tool whose schema must be loaded before it can be called (seen on
# the first live halt run, 2026-09-10).
HALT_ALLOWED_TOOLS = frozenset({"PushNotification", "mcp__claude-engram__context", "ToolSearch"})


def autonomy_on(state: Optional[dict] = None) -> bool:
    """Autonomy mode: an in-session `/engram run` is running (session state,
    hooks/autorun.py), or CLAUDE_ENGRAM_AUTONOMY=1 in the environment (the
    headless launcher, or a person arming a session by hand)."""
    from claude_engram.hooks.autorun import env_or_state_autonomy

    return env_or_state_autonomy(state)


def maybe_halt(state: dict, turn_no: int) -> bool:
    """After close_turn: at the cap, in autonomy mode, arm the halt. Returns
    True when the halt was armed this call."""
    if not autonomy_on(state):
        return False
    st = stall_state(state)
    cap = _env_int("CLAUDE_ENGRAM_STRIKE_CAP", STRIKE_CAP)
    if int(st.get("strikes", 0)) < cap or st.get("halted"):
        return False
    st["halted"] = {"at": time.time(), "turn": int(turn_no), "strikes": int(st["strikes"]), "denied": 0}
    _event(st, turn_no, "halt", f"strike cap {cap} in autonomy mode")
    return True


def halted(state: dict) -> Optional[dict]:
    h = stall_state(state).get("halted")
    return h if isinstance(h, dict) else None


def release(state: dict, reason: str = "released") -> bool:
    """Lift the halt (CLI, or a person at the terminal). Strikes reset to
    zero: a release is a human judgment that the run may continue."""
    st = stall_state(state)
    if not st.get("halted"):
        return False
    _event(st, int(st["halted"].get("turn", 0)), "release", reason)
    st["halted"] = None
    st["strikes"] = 0
    st["noeffect_streak"] = 0
    st["good_streak"] = 0
    return True


def deny_reason(state: dict, tool_name: str) -> str:
    h = halted(state) or {}
    return (
        f"engram halt: {h.get('strikes', STRIKE_CAP)} strikes -- no file, test or commit changed "
        f"for {h.get('strikes', STRIKE_CAP) * _env_int('CLAUDE_ENGRAM_STALL_TURNS', STALL_TURNS)} turns "
        f"(halted at turn {h.get('turn', '?')}). Every tool call is denied until a person releases "
        f"the run (`python -m claude_engram.hooks.stall release <session_id>`). Do this now, in order: "
        f"FIRST context(checkpoint_save) -- the task, the last real change, what has been blocking, "
        f"what a person must decide; it is the record they will read. THEN PushNotification with one "
        f"line under 200 characters. Then stop. Nothing else is allowed. Denied: {tool_name}."
    )


def halt_text(state: dict, session_id: str = "") -> str:
    """Injected once when the halt arms: what to do with the two open calls."""
    h = halted(state) or {}
    sid = f" Session {session_id}." if session_id else ""
    return (
        f"<engram-halt>HALTED at strike {h.get('strikes', STRIKE_CAP)} (turn {h.get('turn', '?')}): "
        "tool use without effect for the whole ladder, in autonomy mode. From here every tool call "
        "is denied except two. Do these, in order, then stop: (1) context(checkpoint_save) with the "
        "task, what the last real change was, what has been blocking since, and what a person should "
        "decide; (2) PushNotification with one line under 200 characters: what stalled and what you "
        f"need. Then end the turn with no further tool calls.{sid}</engram-halt>"
    )


def note_denied(state: dict) -> None:
    h = halted(state)
    if h is not None:
        h["denied"] = int(h.get("denied", 0)) + 1


def summary(state: dict) -> dict:
    """For the run report."""
    st = stall_state(state)
    return {
        "strikes_now": int(st.get("strikes", 0)),
        "max_strikes": int(st.get("max_strikes", 0)),
        "turns": dict(st.get("turns") or {}),
        "events": list(st.get("events") or []),
        "last_change_at": float(st.get("last_change_at") or 0.0),
        "last_effects": list(st.get("last_effects") or []),
        "halted": dict(st["halted"]) if isinstance(st.get("halted"), dict) else None,
        "autonomy": autonomy_on(state),
    }


# ---------------------------------------------------------------------------
# CLI: python -m claude_engram.hooks.stall status|release <session_id>
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    import json
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2 or args[0] not in ("status", "release"):
        print("usage: python -m claude_engram.hooks.stall status|release <session_id>")
        return 2
    op, sid = args[0], args[1]
    from claude_engram.hooks import remind

    remind._session_id = sid
    state = remind.load_state()
    if op == "status":
        print(json.dumps(summary(state), indent=2, default=str))
        return 0
    if release(state, reason=f"released by {os.environ.get('USERNAME') or os.environ.get('USER') or 'operator'} via CLI"):
        remind.save_state(state)
        print(f"released: session {sid} may use tools again (strikes reset)")
        return 0
    print(f"session {sid} was not halted")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
