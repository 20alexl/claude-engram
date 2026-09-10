"""
``/engram run`` inside the session: engram's own loop, like /goal or /loop.

The user's rule: it works in Claude Code like normal, invoked like normal,
by the person or by Claude itself. No second process. So:

* ``start(state, goal, check, ...)`` arms a run in the SESSION STATE (the
  MCP op ``session_mine(run_start)`` calls it; the skill's ``/engram run``
  tells the model to). Autonomy mode (halt, alerts, unattended = deny) is
  on while the run is running -- ``stall.autonomy_on(state)`` reads it.
* The Stop hook is the loop. While the run is running and its check has
  not passed, the hook answers ``{"decision": "block", "reason": ...}``
  and the reason is the next prompt (the documented loop primitive;
  ralph-loop is the precedent). Engram never judges a natural-language
  goal: the CHECK COMMAND is the truth (exit 0 = met). Without a check,
  the run ends only when the model declares it done through
  ``session_mine(run_done, evidence=...)`` -- recorded as self-declared,
  and the report says so.
* It ends on: the check passing (met), the model's declaration (done,
  self-declared), the turn cap (capped), the strike-cap halt (halted),
  or a person's ``run_stop`` / ``/engram stop`` (stopped). Each end sends
  one alert and writes the run report.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any, Optional

DEFAULT_MAX_TURNS = 150
CHECK_TIMEOUT = 120.0
OUT_KEEP = 400

RUNNING = "running"
ENDED = ("met", "done", "capped", "halted", "stopped", "failed")


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


def start(state: dict, goal: str, check: str = "", max_turns: int = DEFAULT_MAX_TURNS, project_dir: str = "") -> dict:
    """Arm a run. A running run is replaced only by run_stop first."""
    if running(state):
        return {"ok": False, "why": "a run is already running; run_stop first", "auto": auto(state)}
    goal = " ".join(str(goal or "").split())[:500]
    if not goal:
        return {"ok": False, "why": "a run needs a goal"}
    a = {
        "goal": goal,
        "check": str(check or "").strip()[:500],
        "max_turns": int(max_turns) if max_turns and int(max_turns) > 0 else DEFAULT_MAX_TURNS,
        "turns": 0,
        "started_at": time.time(),
        "status": RUNNING,
        "why": "",
        "self_declared": False,
        "last_check": None,
        "project": project_dir or "",
    }
    r = _run(state)
    r["auto"] = a
    r["goal"] = goal  # every checkpoint carries it (repo_state.goal_for_session)
    return {"ok": True, "auto": a}


def stop(state: dict, status: str = "stopped", why: str = "") -> dict:
    a = auto(state)
    if not a or a.get("status") != RUNNING:
        return {"ok": False, "why": "no run is running"}
    a["status"] = status if status in ENDED else "stopped"
    a["why"] = str(why or "")[:300]
    a["ended_at"] = time.time()
    return {"ok": True, "auto": a}


def declare_done(state: dict, evidence: str = "") -> dict:
    """The model says the goal is met. With a check, the check decides at
    the next Stop; without one this is the end, and the report says the
    claim was self-declared."""
    a = auto(state)
    if not a or a.get("status") != RUNNING:
        return {"ok": False, "why": "no run is running"}
    a["declared"] = {"at": time.time(), "evidence": str(evidence or "")[:500]}
    if a.get("check"):
        return {"ok": True, "note": "recorded; the check command decides at the next stop", "auto": a}
    a["self_declared"] = True
    stop(state, "done", "declared by the model (no check command)")
    return {"ok": True, "auto": a}


def run_check(check: str, project_dir: str) -> dict:
    """Run the check command; exit 0 = met. Output tail kept for the report."""
    rec: dict[str, Any] = {"at": time.time(), "rc": None, "out": "", "error": ""}
    if not check:
        rec["error"] = "no check command"
        return rec
    try:
        r = subprocess.run(
            check,
            shell=True,
            cwd=project_dir or None,
            capture_output=True,
            text=True,
            timeout=CHECK_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
        rec["rc"] = int(r.returncode)
        rec["out"] = ((r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")).strip()[-OUT_KEEP:]
    except subprocess.TimeoutExpired:
        rec["error"] = f"check timed out after {CHECK_TIMEOUT:.0f}s"
    except Exception as e:
        rec["error"] = str(e)[:200]
    return rec


def directive(a: dict, last_check: Optional[dict]) -> str:
    """The next prompt while the run continues."""
    lines = [f"[engram run, turn {a.get('turns', 0)} of {a.get('max_turns')}] Goal: {a.get('goal')}"]
    if a.get("check"):
        if last_check and last_check.get("rc") is not None:
            tail = (last_check.get("out") or "").strip().replace("\n", " | ")[-200:]
            lines.append(f"Check `{a['check']}` exited {last_check['rc']}" + (f": {tail}" if tail else ""))
        elif last_check and last_check.get("error"):
            lines.append(f"Check `{a['check']}` could not run: {last_check['error']}")
        lines.append("The run ends when the check exits 0. Do the next unit of work toward it.")
    else:
        lines.append(
            "No check command: when the goal is genuinely met, call session_mine(run_done, evidence=...) "
            "with what proves it; that ends the run and is recorded as self-declared."
        )
    lines.append(
        "Checkpoint before declaring a step done. If you are waiting on something, park on Monitor or "
        "ScheduleWakeup rather than polling; tool use without effect strikes. A rule with a detector that "
        "says ask first refuses the call in this run: record what you need and continue with allowed work."
    )
    return "\n".join(lines)


def stop_decision(state: dict, project_dir: str) -> Optional[dict]:
    """Called at Stop after the turn is closed and the halt considered.
    Returns the block JSON to print, or None when the turn may end. Mutates
    the run: turn count, last check, status."""
    a = auto(state)
    if not a or a.get("status") != RUNNING:
        return None
    a["turns"] = int(a.get("turns", 0)) + 1
    _stall = state.get("stall")
    stall: dict = _stall if isinstance(_stall, dict) else {}
    halted = stall.get("halted")
    if isinstance(halted, dict):
        stop(state, "halted", f"strike cap at turn {halted.get('turn')}")
        return None
    if a.get("check"):
        rec = run_check(a["check"], a.get("project") or project_dir)
        a["last_check"] = rec
        if rec.get("rc") == 0:
            stop(state, "met", "check exited 0")
            return None
    if int(a["turns"]) >= int(a.get("max_turns", DEFAULT_MAX_TURNS)):
        stop(state, "capped", f"turn cap {a.get('max_turns')} reached")
        return None
    return {"decision": "block", "reason": directive(a, a.get("last_check"))}


def end_alert_text(a: dict, session_id: str) -> str:
    sid = (session_id or "")[:8]
    st = a.get("status")
    if st == "met":
        return f"engram run {sid} met its goal after {a.get('turns')} turns: {a.get('goal', '')[:80]}"
    if st == "done":
        return f"engram run {sid} declared done (self-declared, no check) after {a.get('turns')} turns"
    if st == "capped":
        return f"engram run {sid} hit its turn cap ({a.get('max_turns')}) with the goal not met"
    if st == "halted":
        return f"engram run {sid} halted: no progress; release with python -m claude_engram.hooks.stall release"
    return f"engram run {sid} {st}: {a.get('why', '')[:100]}"


def summary(state: dict) -> Optional[dict]:
    a = auto(state)
    if not a:
        return None
    out = dict(a)
    if out.get("started_at") and out.get("ended_at"):
        out["duration_s"] = round(float(out["ended_at"]) - float(out["started_at"]))
    return out


def env_or_state_autonomy(state: Optional[dict]) -> bool:
    if os.environ.get("CLAUDE_ENGRAM_AUTONOMY", "").strip().lower() in ("1", "on", "true", "yes"):
        return True
    return bool(state) and running(state)  # type: ignore[arg-type]
