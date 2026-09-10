"""
The /goal bracket: engram around Claude Code's own goal loop.

The user's rule (2026-09-10): "that's the reason we tested /goal. We should
use it." The native loop is the loop -- a session-scoped Stop hook, an
evaluator that reads the transcript, verdicts recorded as ``goal_status``
attachments, restored on resume. A goal is set only by typing ``/goal``:
no flag, setting, hook output or tool call can set one, and the model
cannot type a slash command. So engram does not run a loop of its own.
It WATCHES the transcript for the goal and brackets it:

* ``scan_goal(transcript_path)`` reads the transcript tail for the verified
  record shapes: the sentinel (``goal_status`` with ``sentinel: true`` and
  the condition) when a goal is set; a verdict (``goal_status`` with
  ``met``/``reason``, ``failed: true`` when judged impossible) after each
  evaluation; a met goal auto-clears; ``/goal clear|stop|off|reset|none|
  cancel`` arrives as a ``<command-name>/goal</command-name>`` user record.
  (All observed on a headless Sonnet run, Claude Code 2.1.268.)
* ``observe(state, ...)`` at Stop, UserPromptSubmit and SessionEnd keeps
  ``run.auto`` in the session state in step with the goal: ``running``
  from the sentinel; ``met`` / ``failed`` / ``cleared`` from the transcript;
  ``halted`` from the strike cap; ``capped`` from the turn cap, which arms
  the same halt (engram cannot end a /goal loop -- hooks merge
  most-restrictive -- so the cap starves it and the alert asks a person to
  ``/goal clear``). While the run is running, autonomy mode is on
  (``stall.autonomy_on(state)``): halt, alerts, unattended = deny.
* At the start engram stages one directive for the next injection point:
  the park hint (a not-met verdict re-prompts at once and starves cron
  unless the model parks on Monitor/ScheduleWakeup), the checkpoint rhythm,
  the deny note. Each end sends one alert and writes the run report.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Optional

DEFAULT_TURN_CAP = 150
TAIL_BYTES = 2_000_000
CLEAR_WORDS = frozenset({"clear", "stop", "off", "reset", "none", "cancel"})

RUNNING = "running"
ENDED = ("met", "failed", "cleared", "capped", "halted", "stopped")

_ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)


def _run(state: dict) -> dict:
    r = state.get("run")
    if not isinstance(r, dict):
        r = {}
        state["run"] = r
    return r


def auto(state: dict) -> Optional[dict]:
    a = _run(state).get("auto")
    return a if isinstance(a, dict) else None


def running(state: dict) -> bool:
    a = auto(state)
    return bool(a and a.get("status") == RUNNING)


def turn_cap(project_dir: str = "") -> int:
    """`.engram/config.json` goal_turn_cap, or CLAUDE_ENGRAM_GOAL_TURN_CAP."""
    raw = os.environ.get("CLAUDE_ENGRAM_GOAL_TURN_CAP", "").strip()
    if raw:
        try:
            n = int(raw)
            if n > 0:
                return n
        except ValueError:
            pass
    try:
        from claude_engram import project_config

        n = int(project_config.load(project_dir).get("goal_turn_cap") or 0)
        if n > 0:
            return n
    except Exception:
        pass
    return DEFAULT_TURN_CAP


# ---------------------------------------------------------------------------
# The transcript: where the goal lives
# ---------------------------------------------------------------------------


def _tail_lines(path: str, tail_bytes: int = TAIL_BYTES) -> list[bytes]:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > tail_bytes:
                fh.seek(size - tail_bytes)
                fh.readline()  # drop the partial line
            data = fh.read()
    except Exception:
        return []
    return data.splitlines()


def scan_goal(transcript_path: str, tail_bytes: int = TAIL_BYTES) -> dict:
    """The goal as the transcript tells it. ``active`` is the sentinel with no
    end after it; ``ended`` is met / failed / cleared for the LAST goal seen."""
    out: dict[str, Any] = {
        "seen": False,
        "active": False,
        "condition": "",
        "set_at": "",
        "ended": None,
        "verdicts": 0,
        "last_reason": "",
        "last_met": None,
    }
    if not transcript_path or not os.path.isfile(transcript_path):
        return out
    for raw in _tail_lines(transcript_path, tail_bytes):
        if b'"goal_status"' not in raw and b"<command-name>/goal</command-name>" not in raw:
            continue
        try:
            rec = json.loads(raw)
        except Exception:
            continue
        att = rec.get("attachment")
        if isinstance(att, dict) and att.get("type") == "goal_status":
            if att.get("sentinel"):
                out.update(
                    seen=True,
                    active=True,
                    condition=str(att.get("condition") or ""),
                    set_at=str(rec.get("timestamp") or ""),
                    ended=None,
                    verdicts=0,
                    last_reason="",
                    last_met=None,
                )
                continue
            if not out["seen"]:
                # A verdict with no sentinel in the tail: the goal was set
                # before the window. Treat it as seen and active.
                out.update(seen=True, active=True, condition=str(att.get("condition") or out["condition"]))
            out["verdicts"] = int(out["verdicts"]) + 1
            out["last_reason"] = str(att.get("reason") or "")[:300]
            out["last_met"] = bool(att.get("met"))
            if att.get("met"):
                out["active"], out["ended"] = False, "met"
            elif att.get("failed"):
                out["active"], out["ended"] = False, "failed"
            continue
        if rec.get("type") == "user":
            content = (rec.get("message") or {}).get("content")
            text = content if isinstance(content, str) else json.dumps(content or "")
            if "<command-name>/goal</command-name>" not in text:
                continue
            m = _ARGS_RE.search(text)
            args = (m.group(1) if m else "").strip().lower()
            if args in CLEAR_WORDS and out["seen"] and out["active"]:
                out["active"], out["ended"] = False, "cleared"
    return out


# ---------------------------------------------------------------------------
# The run record
# ---------------------------------------------------------------------------


def _start(state: dict, scan: dict, project_dir: str) -> dict:
    a = {
        "goal": " ".join(str(scan.get("condition") or "").split())[:500],
        "set_at": str(scan.get("set_at") or ""),
        "started_at": time.time(),
        "status": RUNNING,
        "why": "",
        "turns": 0,
        "max_turns": turn_cap(project_dir),
        "verdicts": 0,
        "project": project_dir or "",
        "source": "goal",
        "pending_text": True,  # the directive, delivered once by _with_pressure
    }
    r = _run(state)
    r["auto"] = a
    r["goal"] = a["goal"]  # every checkpoint carries it (repo_state.goal_for_session)
    return a


def stop(state: dict, status: str = "stopped", why: str = "") -> dict:
    a = auto(state)
    if not a or a.get("status") != RUNNING:
        return {"ok": False, "why": "no run is running"}
    a["status"] = status if status in ENDED else "stopped"
    a["why"] = str(why or "")[:300]
    a["ended_at"] = time.time()
    return {"ok": True, "auto": a}


def observe(
    state: dict,
    transcript_path: str,
    project_dir: str = "",
    turn: bool = False,
) -> Optional[dict]:
    """Bring ``run.auto`` in step with the transcript's goal. ``turn=True``
    at Stop counts the turn. Returns ``{"event": "started"|"ended", "auto":
    a}`` when the status changed, else None. The caller saves the state,
    sends the alert and writes the report."""
    tp = transcript_path or str(_run(state).get("transcript_path") or "")
    scan = scan_goal(tp)
    a = auto(state)
    if a and a.get("status") == RUNNING:
        if turn:
            a["turns"] = int(a.get("turns", 0)) + 1
        a["verdicts"] = int(scan.get("verdicts") or 0)
        if scan.get("last_reason"):
            a["last_reason"] = scan["last_reason"]
        _stall = state.get("stall")
        st: dict = _stall if isinstance(_stall, dict) else {}
        halted = st.get("halted")
        if isinstance(halted, dict):
            if halted.get("reason") == "turn cap":
                stop(state, "capped", f"turn cap {a.get('max_turns')} reached; halted until /goal clear")
            else:
                stop(state, "halted", f"strike cap at turn {halted.get('turn')}")
            return {"event": "ended", "auto": a}
        if scan.get("seen") and scan.get("set_at") and scan["set_at"] != a.get("set_at") and scan.get("active"):
            # A new goal replaced ours without a recorded end.
            stop(state, "cleared", "replaced by a new /goal")
            new = _start(state, scan, project_dir)
            if turn:
                new["turns"] = 1
            return {"event": "started", "auto": new, "replaced": a}
        if scan.get("ended"):
            stop(state, str(scan["ended"]), scan.get("last_reason") or f"goal {scan['ended']}")
            return {"event": "ended", "auto": a}
        if turn and int(a["turns"]) >= int(a.get("max_turns") or DEFAULT_TURN_CAP):
            # Engram cannot end a /goal loop; the halt starves it and the
            # alert asks a person to /goal clear.
            from claude_engram.hooks import stall as _stall_mod

            sst = _stall_mod.stall_state(state)
            if not sst.get("halted"):
                sst["halted"] = {
                    "at": time.time(),
                    "turn": int(a["turns"]),
                    "strikes": int(sst.get("strikes", 0)),
                    "denied": 0,
                    "reason": "turn cap",
                }
                _stall_mod._event(sst, int(a["turns"]), "halt", f"turn cap {a['max_turns']} under /goal")
                sst["pending_halt"] = True
            stop(state, "capped", f"turn cap {a.get('max_turns')} reached; halted until /goal clear")
            return {"event": "ended", "auto": a}
        return None
    if scan.get("active") and scan.get("seen"):
        if a and a.get("set_at") and a["set_at"] == scan.get("set_at"):
            return None  # the same goal, already ended in our record
        new = _start(state, scan, project_dir)
        if turn:
            new["turns"] = 1  # the Stop that first saw the goal is its first turn
        return {"event": "started", "auto": new}
    return None


def take_pending_text(state: dict) -> str:
    """The directive, once, at the first injection point after the start."""
    a = auto(state)
    if not a or not a.get("pending_text"):
        return ""
    a["pending_text"] = False
    return directive(a)


def directive(a: dict) -> str:
    return (
        "<engram-goal>Goal active and bracketed by engram: "
        f"{str(a.get('goal', ''))[:200]}. Autonomy mode is on for the goal's life: three no-effect "
        "strikes halt every tool, ask-first rules refuse their commands, alerts go out, the turn cap is "
        f"{a.get('max_turns')} (then the halt, until a person types /goal clear). Work in units that end "
        "with a deliberate context(checkpoint_save); the goal is stamped into each one. When you are "
        "waiting on anything, park on Monitor or ScheduleWakeup instead of polling: a not-met verdict "
        "re-prompts at once and starves scheduled work unless you park. The evaluator reads only what "
        "you surface in the conversation, so print the evidence (test output, file contents) before "
        "you stop.</engram-goal>"
    )


def end_alert_text(a: dict, session_id: str) -> str:
    sid = (session_id or "")[:8]
    st = a.get("status")
    goal = str(a.get("goal", ""))[:80]
    if st == "met":
        return f"goal met in session {sid} after {a.get('turns')} turns: {goal}"
    if st == "failed":
        return f"goal judged impossible in session {sid} after {a.get('turns')} turns: {goal}"
    if st == "cleared":
        return f"goal cleared in session {sid} after {a.get('turns')} turns: {goal}"
    if st == "capped":
        return (
            f"goal run {sid} hit its turn cap ({a.get('max_turns')}) unmet; every tool is denied until "
            "a person types /goal clear and runs python -m claude_engram.hooks.stall release"
        )
    if st == "halted":
        return f"goal run {sid} halted: no progress; release with python -m claude_engram.hooks.stall release, or /goal clear"
    return f"goal run {sid} {st}: {a.get('why', '')[:100]}"


def summary(state: dict) -> Optional[dict]:
    a = auto(state)
    if not a:
        return None
    out = {k: v for k, v in a.items() if k != "pending_text"}
    if out.get("started_at") and out.get("ended_at"):
        out["duration_s"] = round(float(out["ended_at"]) - float(out["started_at"]))
    return out


def env_or_state_autonomy(state: Optional[dict]) -> bool:
    if os.environ.get("CLAUDE_ENGRAM_AUTONOMY", "").strip().lower() in ("1", "on", "true", "yes"):
        return True
    return bool(state) and running(state)  # type: ignore[arg-type]
