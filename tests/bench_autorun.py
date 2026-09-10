"""
Benchmark: the /goal bracket (hooks/autorun.py) -- engram around Claude
Code's own goal loop. A goal is set only by typing /goal; engram watches the
transcript and keeps the run record in step.

What must hold:
  1. scan_goal reads the verified record shapes (headless Sonnet run,
     Claude Code 2.1.268): the sentinel on set, not-met and met verdicts,
     failed: true, the /goal clear command record, a second goal.
  2. observe: running from the sentinel (autonomy on), turns counted at
     Stop only, met / failed / cleared from the transcript, halted from the
     strike cap, capped from the turn cap -- which arms the halt with its
     reason, since engram cannot end a /goal loop.
  3. The directive is staged once and delivered by _with_pressure.
  4. End to end through the real hooks: a transcript file grows across
     Stops; the manifest at the start, the alert and the report with the
     "Goal run" section at the end; a Stop under a goal is never blocked
     by engram.
  5. The MCP op run_status; the removed ops are gone from the tool
     definitions; the skill hands the person the /goal line.

Run: venv/Scripts/python.exe tests/bench_autorun.py
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_fails = []


def check(name, cond):
    print(("  [PASS] " if cond else "  [FAIL] ") + name)
    if not cond:
        _fails.append(name)


def _clean():
    for k in ("CLAUDE_ENGRAM_AUTONOMY", "CLAUDE_ENGRAM_STALL_TURNS", "CLAUDE_ENGRAM_STRIKE_CAP", "CLAUDE_ENGRAM_ALERT_COMMAND", "CLAUDE_ENGRAM_GOAL_TURN_CAP"):
        os.environ.pop(k, None)


# --- transcript records in the observed shapes -----------------------------

def _ts(i: int) -> str:
    return f"2026-09-10T22:46:{i:02d}.000Z"


def rec_sentinel(cond: str, i: int) -> str:
    return json.dumps({"type": "attachment", "timestamp": _ts(i), "attachment": {"type": "goal_status", "met": False, "sentinel": True, "condition": cond}})


def rec_verdict(cond: str, i: int, met: bool, reason: str = "because", failed: bool = False) -> str:
    att = {"type": "goal_status", "met": met, "condition": cond, "reason": reason, "iterations": 1, "durationMs": 900, "tokens": 1200}
    if failed:
        att["failed"] = True
    return json.dumps({"type": "attachment", "timestamp": _ts(i), "attachment": att})


def rec_command(args: str, i: int) -> str:
    content = f"<command-name>/goal</command-name>\n            <command-message>goal</command-message>\n            <command-args>{args}</command-args>"
    return json.dumps({"type": "user", "timestamp": _ts(i), "message": {"role": "user", "content": content}})


def rec_noise(i: int) -> str:
    return json.dumps({"type": "assistant", "timestamp": _ts(i), "message": {"role": "assistant", "content": [{"type": "text", "text": "working; the goal is near"}]}})


def _write(path: Path, *lines: str) -> str:
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return str(path)


def test_scan(ar, tmp):
    print("scan_goal over the observed record shapes:")
    t = tmp / "t1.jsonl"
    check("no file: nothing seen", ar.scan_goal(str(tmp / "missing.jsonl"))["seen"] is False)
    _write(t, rec_noise(1))
    check("noise only: nothing seen", ar.scan_goal(str(t))["seen"] is False)
    _write(t, rec_noise(1), rec_sentinel("tests pass", 2), rec_noise(3))
    s = ar.scan_goal(str(t))
    check("sentinel: seen, active, condition, set_at", s["seen"] and s["active"] and s["condition"] == "tests pass" and s["set_at"] == _ts(2) and s["ended"] is None)
    _write(t, rec_sentinel("tests pass", 2), rec_verdict("tests pass", 4, False, "no test output yet"))
    s = ar.scan_goal(str(t))
    check("not-met verdict: still active, counted, reason kept", s["active"] and s["verdicts"] == 1 and s["last_reason"] == "no test output yet" and s["last_met"] is False)
    _write(t, rec_sentinel("tests pass", 2), rec_verdict("tests pass", 4, False), rec_verdict("tests pass", 6, True, "pytest exited 0"))
    s = ar.scan_goal(str(t))
    check("met verdict: ended met, not active", s["ended"] == "met" and not s["active"] and s["verdicts"] == 2)
    _write(t, rec_sentinel("fly", 2), rec_verdict("fly", 4, False, "impossible", failed=True))
    s = ar.scan_goal(str(t))
    check("failed: true -> ended failed", s["ended"] == "failed" and not s["active"])
    _write(t, rec_sentinel("tests pass", 2), rec_verdict("tests pass", 4, False), rec_command("clear", 5))
    s = ar.scan_goal(str(t))
    check("/goal clear command record -> ended cleared", s["ended"] == "cleared" and not s["active"])
    for w in ("stop", "off", "reset", "none", "cancel", "CLEAR"):
        _write(t, rec_sentinel("g", 2), rec_command(w, 3))
        if ar.scan_goal(str(t))["ended"] != "cleared":
            check(f"alias {w} clears", False)
            break
    else:
        check("every clear alias clears", True)
    _write(t, rec_command("clear", 1), rec_sentinel("g", 2))
    check("a clear BEFORE the sentinel does not end it", ar.scan_goal(str(t))["active"] is True)
    # A tool_result echoing the command text (a fixture read back) is a list,
    # not a slash command.
    echo = json.dumps({"type": "user", "timestamp": _ts(3), "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "<command-name>/goal</command-name>\n<command-args>clear</command-args>"}]}})
    _write(t, rec_sentinel("g", 2), echo)
    check("a tool_result echoing '/goal clear' does NOT clear the goal", ar.scan_goal(str(t))["active"] is True)
    _write(t, rec_sentinel("first", 2), rec_verdict("first", 3, True), rec_sentinel("second", 5))
    s = ar.scan_goal(str(t))
    check("a second goal after a met first: the last goal is active", s["active"] and s["condition"] == "second" and s["set_at"] == _ts(5) and s["verdicts"] == 0)
    _write(t, rec_command("the file exists", 1), rec_noise(2))
    check("a /goal <condition> command without a sentinel is not a goal (the sentinel is the record)", ar.scan_goal(str(t))["seen"] is False)
    # The tail window: a sentinel outside it, a verdict inside.
    big = tmp / "big.jsonl"
    filler = json.dumps({"type": "assistant", "message": {"content": "x" * 5000}})
    lines = [rec_sentinel("old goal", 1)] + [filler] * 30 + [rec_verdict("old goal", 40, False, "still going")]
    _write(big, *lines)
    s = ar.scan_goal(str(big), tail_bytes=20_000)
    check("a verdict with its sentinel outside the tail still reads as an active goal", s["seen"] and s["active"] and s["condition"] == "old goal")


def test_observe(ar, st, tmp):
    print("observe: the run record follows the goal:")
    _clean()
    t = tmp / "t2.jsonl"
    state: dict = {}
    _write(t, rec_noise(1))
    check("no goal: no event, no run, autonomy off", ar.observe(state, str(t), str(tmp), turn=True) is None and ar.auto(state) is None and not st.autonomy_on(state))
    _write(t, rec_noise(1), rec_sentinel("tests pass", 2))
    ev = ar.observe(state, str(t), str(tmp), turn=False)
    a = ar.auto(state)
    check("sentinel -> started, running, goal recorded, directive pending", ev and ev["event"] == "started" and a["status"] == "running" and a["goal"] == "tests pass" and a["pending_text"] is True)
    check("the goal is where checkpoints read it", state["run"]["goal"] == "tests pass")
    check("autonomy mode is on from the state alone", st.autonomy_on(state))
    check("default cap", a["max_turns"] == ar.DEFAULT_TURN_CAP)
    check("observe without a turn does not count", ar.observe(state, str(t), str(tmp), turn=False) is None and a["turns"] == 0)
    check("a Stop counts a turn", ar.observe(state, str(t), str(tmp), turn=True) is None and a["turns"] == 1)
    d = ar.take_pending_text(state)
    check("the directive is handed out once, with the park hint and the cap", "Goal active" in d and "ScheduleWakeup" in d and "turn cap is 150" in d and ar.take_pending_text(state) == "")
    _write(t, rec_sentinel("tests pass", 2), rec_verdict("tests pass", 4, False, "no output yet"))
    check("a not-met verdict: still running, verdict counted", ar.observe(state, str(t), str(tmp), turn=True) is None and a["verdicts"] == 1 and a["last_reason"] == "no output yet")
    _write(t, rec_sentinel("tests pass", 2), rec_verdict("tests pass", 4, False), rec_verdict("tests pass", 6, True, "pytest exited 0"))
    ev = ar.observe(state, str(t), str(tmp), turn=True)
    check("met verdict -> ended met, autonomy off", ev and ev["event"] == "ended" and a["status"] == "met" and "pytest exited 0" in a["why"] and not st.autonomy_on(state))
    check("after the end the same goal does not restart", ar.observe(state, str(t), str(tmp), turn=True) is None and a["status"] == "met")
    s = ar.summary(state)
    check("summary: duration, no pending flag", s and "duration_s" in s and "pending_text" not in s)
    print("cleared / failed / replaced:")
    state = {}
    _write(t, rec_sentinel("g", 2))
    ar.observe(state, str(t), str(tmp))
    _write(t, rec_sentinel("g", 2), rec_command("clear", 3))
    ev = ar.observe(state, str(t), str(tmp))
    check("/goal clear -> ended cleared", ev and ev["event"] == "ended" and ar.auto(state)["status"] == "cleared")
    state = {}
    _write(t, rec_sentinel("fly", 2))
    ar.observe(state, str(t), str(tmp))
    _write(t, rec_sentinel("fly", 2), rec_verdict("fly", 3, False, "impossible", failed=True))
    check("failed verdict -> ended failed", ar.observe(state, str(t), str(tmp))["event"] == "ended" and ar.auto(state)["status"] == "failed")
    state = {}
    _write(t, rec_sentinel("one", 2))
    ar.observe(state, str(t), str(tmp))
    _write(t, rec_sentinel("one", 2), rec_sentinel("two", 5))
    ev = ar.observe(state, str(t), str(tmp))
    check("a new goal replaces the running one: started again with the new goal", ev and ev["event"] == "started" and ar.auto(state)["goal"] == "two" and ev["replaced"]["status"] == "cleared")
    print("halt and turn cap:")
    state = {"stall": {"halted": {"turn": 4, "strikes": 3, "denied": 0}}}
    _write(t, rec_sentinel("g", 2))
    ar.observe(state, str(t), str(tmp))
    ev = ar.observe(state, str(t), str(tmp), turn=True)
    check("a strike-cap halt ends the run as halted", ev and ev["event"] == "ended" and ar.auto(state)["status"] == "halted")
    os.environ["CLAUDE_ENGRAM_GOAL_TURN_CAP"] = "2"
    state = {}
    _write(t, rec_sentinel("never", 2))
    ar.observe(state, str(t), str(tmp))
    check("cap from the env", ar.auto(state)["max_turns"] == 2)
    check("turn 1: nothing", ar.observe(state, str(t), str(tmp), turn=True) is None)
    ev = ar.observe(state, str(t), str(tmp), turn=True)
    h = st.halted(state)
    check("turn 2: capped, and the halt is armed with its reason", ev and ev["event"] == "ended" and ar.auto(state)["status"] == "capped" and h and h.get("reason") == "turn cap" and state["stall"].get("pending_halt") is True)
    check("the deny reason names the cap and /goal clear", "turn cap" in st.deny_reason(state, "Bash") and "/goal clear" in st.deny_reason(state, "Bash"))
    check("the halt text names the cap", "turn cap" in st.halt_text(state, "s"))
    _clean()
    print("alert texts:")
    for status, needle in (("met", "goal met"), ("failed", "impossible"), ("cleared", "cleared"), ("capped", "/goal clear"), ("halted", "halted")):
        check(f"{status} text", needle in ar.end_alert_text({"status": status, "turns": 3, "goal": "g", "max_turns": 5, "why": ""}, "abcdef12"))
    print("turn cap from the project config:")
    proj = tmp / "cfg-proj"
    (proj / ".engram").mkdir(parents=True, exist_ok=True)
    (proj / ".engram" / "config.json").write_text('{"goal_turn_cap": 7}', encoding="utf-8")
    check("goal_turn_cap read from .engram/config.json", ar.turn_cap(str(proj)) == 7)
    check("default without a file", ar.turn_cap(str(tmp / "nowhere")) == ar.DEFAULT_TURN_CAP)


def _hook(hook_type, payload, env):
    return subprocess.run([sys.executable, "-m", "claude_engram.hooks.remind", hook_type], input=json.dumps(payload),
                          capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=120)


def test_end_to_end(tmp):
    print("end to end through the real hooks:")
    _clean()
    store = tmp / "store-e2e"
    proj = tmp / "proj-e2e"
    proj.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    sink = tmp / "alert_sink.py"
    sink.write_text("import sys\nopen(sys.argv[2],'a',encoding='utf-8').write(sys.argv[1].strip()+'\\n')\n", encoding="utf-8")
    log = tmp / "alerts-e2e.log"
    sid = "s-goal-e2e"
    t = tmp / "transcript-e2e.jsonl"
    env = dict(os.environ, CLAUDE_ENGRAM_DIR=str(store), CLAUDE_PROJECT_DIR=str(proj), CLAUDE_ENGRAM_LIVE_MINE="0",
               CLAUDE_ENGRAM_NO_DAEMON="1", CLAUDE_ENGRAM_ALERT_COMMAND=f'"{py}" "{sink}" {{message}} "{log}"')
    base = {"session_id": sid, "cwd": str(proj), "transcript_path": str(t), "hook_event_name": "Stop", "last_assistant_message": "Working on it.", "stop_hook_active": False}

    def state():
        return json.loads((store / "sessions" / f"{sid}.json").read_text(encoding="utf-8"))

    _write(t, rec_noise(1))
    r0 = _hook("stop_json", base, env)
    check("a stop with no goal: exit 0, nothing blocked, no run", r0.returncode == 0 and "block" not in r0.stdout and not (state().get("run") or {}).get("auto"))
    _write(t, rec_noise(1), rec_sentinel("count reaches three", 2))
    r1 = _hook("stop_json", base, env)
    a = state()["run"]["auto"]
    check("stop under a fresh goal: never blocked by engram, run started, 1 turn", r1.returncode == 0 and "block" not in r1.stdout and a["status"] == "running" and a["turns"] == 1)
    manifests = list((proj / ".engram" / "runs").glob("*.manifest.json"))
    check("the manifest was written at the start (mode goal)", manifests and '"goal"' in manifests[0].read_text(encoding="utf-8") and '"mode": "goal"' in manifests[0].read_text(encoding="utf-8"))
    # The directive rides the next injection point (a PostToolUse Bash here).
    r_b = _hook("bash_json", {"session_id": sid, "cwd": str(proj), "hook_event_name": "PostToolUse", "tool_name": "Bash",
                              "tool_input": {"command": "python -m pytest -q"}, "tool_response": {"stdout": "3 passed", "exit_code": 0}}, env)
    check("the directive was injected once after the start", "<engram-goal>" in r_b.stdout and "ScheduleWakeup" in r_b.stdout)
    check("... and its flag is cleared", state()["run"]["auto"]["pending_text"] is False)
    _write(t, rec_noise(1), rec_sentinel("count reaches three", 2), rec_verdict("count reaches three", 3, False, "not yet"))
    r2 = _hook("stop_json", dict(base, stop_hook_active=True), env)
    check("stop 2 after a not-met verdict: still running, 2 turns, verdict counted", "block" not in r2.stdout and state()["run"]["auto"]["turns"] == 2 and state()["run"]["auto"]["verdicts"] == 1)
    _write(t, rec_noise(1), rec_sentinel("count reaches three", 2), rec_verdict("count reaches three", 3, False), rec_verdict("count reaches three", 5, True, "the count printed 3"))
    r3 = _hook("prompt_json", {"session_id": sid, "cwd": str(proj), "transcript_path": str(t), "hook_event_name": "UserPromptSubmit", "prompt": "thanks"}, env)
    a = state()["run"]["auto"]
    check("the met verdict is picked up at the next prompt: ended met", r3.returncode == 0 and a["status"] == "met" and "printed 3" in a["why"])
    check("the end alert went out", log.exists() and "goal met in session s-goal-e" in log.read_text(encoding="utf-8"))
    reports = list((proj / ".engram" / "runs").glob("*.md"))
    md = reports[0].read_text(encoding="utf-8") if reports else ""
    check("the run report was written with the Goal run section", "## Goal run (met)" in md and "count reaches three" in md and "of the 150 cap" in md)
    r4 = _hook("stop_json", dict(base), env)
    check("after the end, stops stay free and the record stays met", "block" not in r4.stdout and state()["run"]["auto"]["status"] == "met")
    print("SessionEnd closes a run whose verdict landed after the last stop:")
    sid2 = "s-goal-end"
    t2 = tmp / "transcript-end.jsonl"
    env2 = dict(env)
    base2 = dict(base, session_id=sid2, transcript_path=str(t2))
    _write(t2, rec_sentinel("g2", 2))
    _hook("stop_json", base2, env2)
    _write(t2, rec_sentinel("g2", 2), rec_verdict("g2", 4, True, "done"))
    _hook("session_end_json", {"session_id": sid2, "cwd": str(proj), "transcript_path": str(t2), "hook_event_name": "SessionEnd", "reason": "other"}, env2)
    st2 = json.loads((store / "sessions" / f"{sid2}.json").read_text(encoding="utf-8"))
    check("SessionEnd recorded the met end", (st2.get("run") or {}).get("auto", {}).get("status") == "met")


def test_handler(tmp):
    print("MCP op in-process:")
    _clean()
    store = tmp / "store-handler"
    proj = tmp / "proj-handler"
    proj.mkdir(parents=True, exist_ok=True)
    os.environ["CLAUDE_ENGRAM_DIR"] = str(store)
    from claude_engram.hooks import remind, autorun as ar
    from claude_engram.handlers import Handlers

    remind._session_id = "s-handler"
    h = Handlers()

    def call(op, **kw):
        res = asyncio.run(h.handle_session_mine(op, {"project_path": str(proj), **kw}))
        return res[0].text

    t = call("run_status")
    check("run_status with no goal says how a goal starts", "No goal run" in t and "/goal" in t)
    st = remind.load_state()
    tr = tmp / "transcript-handler.jsonl"
    _write(tr, rec_sentinel("tests green", 2))
    ar.observe(st, str(tr), str(proj))
    remind.save_state(st)
    t = call("run_status")
    check("run_status prints the running goal", '"status": "running"' in t and '"goal": "tests green"' in t)
    for op in ("run_start", "run_stop", "run_done"):
        r = call(op, goal="x")
        if "Unknown" not in r and "unknown" not in r and "not" not in r.lower():
            check(f"{op} is gone", False)
            break
    else:
        check("run_start / run_stop / run_done are gone", True)
    os.environ.pop("CLAUDE_ENGRAM_DIR", None)


def test_source_guards():
    print("source guards:")
    remind = (ROOT / "claude_engram" / "hooks" / "remind.py").read_text(encoding="utf-8")
    check("engram never blocks a Stop of its own", "stop_decision(" not in remind and '"decision": "block"' not in remind)
    check("the bracket observes at Stop, UserPromptSubmit and SessionEnd", remind.count("_goal_bracket(") >= 3)
    check("the directive rides _with_pressure", "take_pending_text(" in remind)
    td = (ROOT / "claude_engram" / "tool_definitions_v2.py").read_text(encoding="utf-8")
    check("session_mine keeps run_status only", '"run_status"' in td and not any(f'"{op}"' in td for op in ("run_start", "run_stop", "run_done")))
    skill = (ROOT / "claude_engram" / "skill" / "engram" / "SKILL.md").read_text(encoding="utf-8")
    check("the skill hands the person the /goal line and never a loop of its own", "`/goal <the goal" in skill and "never a loop of your own" in skill and "run_start" not in skill)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    check("README: you type /goal, engram brackets it", "You type `/goal`" in readme and "run_start" not in readme)


def main():
    from claude_engram.hooks import autorun as ar
    from claude_engram.hooks import stall as st

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp = Path(td)
        test_scan(ar, tmp)
        test_observe(ar, st, tmp)
        test_end_to_end(tmp)
        test_handler(tmp)
        test_source_guards()
    print()
    if _fails:
        print(f"FAILED: {len(_fails)}")
        for f in _fails:
            print(f"  - {f}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
