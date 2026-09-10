"""
Benchmark: /engram run inside the session (hooks/autorun.py) -- engram's
own loop, like /goal or /loop, invoked by the person or by Claude.

What must hold:
  1. start / stop / declare_done / summary over the session state; a
     running run arms autonomy mode (stall.autonomy_on(state)) and is
     replaced only after run_stop.
  2. stop_decision: while the check fails it BLOCKS the stop with the
     directive as the next prompt (goal, check exit and tail, turn count,
     the park hint); it ends the run on check exit 0 (met), the turn cap
     (capped), a halt (halted); without a check only run_done ends it
     (self-declared).
  3. run_check: exit code and output tail; a missing command is an error,
     a timeout is reported, never raises.
  4. End to end through the real Stop hook: a run armed in the state file,
     a check that passes on its third call -> two blocks then a clean stop,
     the end alert recorded, the run report written with the section.
  5. The MCP handler ops (run_start / run_status / run_done / run_stop)
     in-process, and the manifest they write.
  6. Source guards and the docs' claim that the launcher is for cron only.

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
    for k in ("CLAUDE_ENGRAM_AUTONOMY", "CLAUDE_ENGRAM_STALL_TURNS", "CLAUDE_ENGRAM_STRIKE_CAP", "CLAUDE_ENGRAM_ALERT_COMMAND"):
        os.environ.pop(k, None)


def test_state(ar, st):
    print("state machine:")
    _clean()
    state = {}
    check("no run: not running, autonomy off", not ar.running(state) and not st.autonomy_on(state))
    r = ar.start(state, "  tests pass  ", "pytest -q", 20, "/p")
    check("start arms the run", r["ok"] and ar.running(state) and state["run"]["auto"]["goal"] == "tests pass" and state["run"]["auto"]["max_turns"] == 20)
    check("the goal is also where checkpoints read it", state["run"]["goal"] == "tests pass")
    check("a running run arms autonomy mode from the state alone", st.autonomy_on(state))
    check("a second start is refused", ar.start(state, "other", "", 5, "/p")["ok"] is False)
    check("start needs a goal", ar.start({}, "   ", "", 5, "/p")["ok"] is False)
    check("default cap", ar.start({}, "g", "", 0, "/p")["auto"]["max_turns"] == ar.DEFAULT_MAX_TURNS)
    r = ar.declare_done(state, "green")
    check("declare with a check only records; the check decides", r["ok"] and ar.running(state) and state["run"]["auto"]["declared"]["evidence"] == "green")
    r = ar.stop(state, "stopped", "person")
    check("stop ends it and autonomy goes off", r["ok"] and not ar.running(state) and state["run"]["auto"]["status"] == "stopped" and not st.autonomy_on(state))
    check("stop twice is refused", ar.stop(state)["ok"] is False)
    check("after a stop a new run may start", ar.start(state, "again", "", 5, "/p")["ok"])
    r = ar.declare_done(state, "I say so")
    check("declare without a check ends the run as self-declared", r["ok"] and state["run"]["auto"]["status"] == "done" and state["run"]["auto"]["self_declared"] is True)
    s = ar.summary(state)
    check("summary carries duration", s is not None and "duration_s" in s)
    os.environ["CLAUDE_ENGRAM_AUTONOMY"] = "1"
    check("the env var still arms autonomy (headless launcher)", st.autonomy_on({}))
    _clean()


def test_check(ar, tmp):
    print("run_check:")
    py = sys.executable
    ok = ar.run_check(f'"{py}" -c "print(\'fine\')"', str(tmp))
    check("exit 0 with the output tail", ok["rc"] == 0 and ok["out"] == "fine")
    bad = ar.run_check(f'"{py}" -c "import sys; print(\'2 failed\'); sys.exit(1)"', str(tmp))
    check("non-zero exit with the tail", bad["rc"] == 1 and "2 failed" in bad["out"])
    check("no command is an error, not a pass", ar.run_check("", str(tmp))["error"] == "no check command" and ar.run_check("", str(tmp))["rc"] is None)
    ar.CHECK_TIMEOUT = 1.0
    slow = ar.run_check(f'"{py}" -c "import time; time.sleep(5)"', str(tmp))
    check("a timeout is reported", "timed out" in slow["error"] and slow["rc"] is None)
    ar.CHECK_TIMEOUT = 120.0


def test_stop_decision(ar, tmp):
    print("stop_decision:")
    _clean()
    py = sys.executable
    counter = tmp / "count.txt"
    counter.write_text("0", encoding="utf-8")
    # A check that passes on its third call.
    script = tmp / "check3.py"
    script.write_text(
        "import sys\np=sys.argv[1]\nn=int(open(p).read())+1\nopen(p,'w').write(str(n))\nprint('call', n)\nsys.exit(0 if n>=3 else 1)\n",
        encoding="utf-8",
    )
    cmd = f'"{py}" "{script}" "{counter}"'
    state = {}
    ar.start(state, "done.txt has ok", cmd, 10, str(tmp))
    d1 = ar.stop_decision(state, str(tmp))
    check("first stop: blocked with the directive", d1 is not None and d1["decision"] == "block" and "Goal: done.txt has ok" in d1["reason"] and "exited 1" in d1["reason"] and "turn 1 of 10" in d1["reason"])
    check("the directive carries the park hint and the deny note", "ScheduleWakeup" in d1["reason"] and "ask first" in d1["reason"])
    d2 = ar.stop_decision(state, str(tmp))
    check("second stop: still blocked, turn 2", d2 is not None and "turn 2 of 10" in d2["reason"] and "call 2" in d2["reason"])
    d3 = ar.stop_decision(state, str(tmp))
    check("third stop: the check passes, the turn may end, status met", d3 is None and state["run"]["auto"]["status"] == "met" and state["run"]["auto"]["turns"] == 3)
    check("last check recorded", state["run"]["auto"]["last_check"]["rc"] == 0)
    check("after the end, no more decisions", ar.stop_decision(state, str(tmp)) is None)
    print("turn cap:")
    state = {}
    ar.start(state, "never", f'"{py}" -c "import sys; sys.exit(1)"', 2, str(tmp))
    check("turn 1 blocks", ar.stop_decision(state, str(tmp)) is not None)
    check("turn 2 hits the cap: not blocked, status capped", ar.stop_decision(state, str(tmp)) is None and state["run"]["auto"]["status"] == "capped")
    print("halt:")
    state = {"stall": {"halted": {"turn": 4, "strikes": 3, "denied": 0}}}
    ar.start(state, "g", f'"{py}" -c "import sys; sys.exit(1)"', 10, str(tmp))
    check("a halted session ends the run as halted, no block", ar.stop_decision(state, str(tmp)) is None and state["run"]["auto"]["status"] == "halted")
    print("no check:")
    state = {}
    ar.start(state, "g", "", 3, str(tmp))
    d = ar.stop_decision(state, str(tmp))
    check("without a check the stop is blocked and the directive asks for run_done", d is not None and "run_done" in d["reason"])
    ar.declare_done(state, "proof")
    check("run_done ends it (self-declared)", ar.stop_decision(state, str(tmp)) is None and state["run"]["auto"]["status"] == "done")
    print("alert texts:")
    for status, needle in (("met", "met its goal"), ("done", "self-declared"), ("capped", "turn cap"), ("halted", "halted"), ("stopped", "stopped")):
        check(f"{status} text", needle in ar.end_alert_text({"status": status, "turns": 3, "goal": "g", "max_turns": 5, "why": "stopped"}, "abcdef12"))


def _hook(hook_type, payload, env):
    return subprocess.run([sys.executable, "-m", "claude_engram.hooks.remind", hook_type], input=json.dumps(payload),
                          capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=120)


def test_end_to_end(tmp):
    print("end to end through the Stop hook:")
    _clean()
    store = tmp / "store-e2e"
    proj = tmp / "proj-e2e"
    proj.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    counter = tmp / "count-e2e.txt"
    counter.write_text("0", encoding="utf-8")
    script = tmp / "check3e.py"
    script.write_text(
        "import sys\np=sys.argv[1]\nn=int(open(p).read())+1\nopen(p,'w').write(str(n))\nprint('call', n)\nsys.exit(0 if n>=3 else 1)\n",
        encoding="utf-8",
    )
    sink = tmp / "alert_sink.py"
    sink.write_text("import sys\nopen(sys.argv[2],'a',encoding='utf-8').write(sys.argv[1].strip()+'\\n')\n", encoding="utf-8")
    log = tmp / "alerts-e2e.log"
    sid = "s-autorun-e2e"
    env = dict(os.environ, CLAUDE_ENGRAM_DIR=str(store), CLAUDE_PROJECT_DIR=str(proj), CLAUDE_ENGRAM_LIVE_MINE="0",
               CLAUDE_ENGRAM_ALERT_COMMAND=f'"{py}" "{sink}" {{message}} "{log}"')
    # Arm the run in the state file the way the MCP op does.
    from claude_engram.hooks import remind, autorun as ar

    os.environ["CLAUDE_ENGRAM_DIR"] = str(store)
    remind._session_id = sid
    st = remind.load_state()
    ar.start(st, "count reaches three", f'"{py}" "{script}" "{counter}"', 10, str(proj))
    remind.save_state(st)
    stop = {"session_id": sid, "cwd": str(proj), "hook_event_name": "Stop", "last_assistant_message": "Working on it.", "stop_hook_active": False}
    r1 = _hook("stop_json", stop, env)
    out1 = json.loads(r1.stdout.strip().splitlines()[-1]) if r1.stdout.strip() else {}
    check("stop 1: the hook blocks with the directive", r1.returncode == 0 and out1.get("decision") == "block" and "Goal: count reaches three" in out1.get("reason", ""))
    r2 = _hook("stop_json", dict(stop, stop_hook_active=True), env)
    out2 = json.loads(r2.stdout.strip().splitlines()[-1]) if r2.stdout.strip() else {}
    check("stop 2: still blocked (stop_hook_active does not end a running run)", out2.get("decision") == "block" and "turn 2 of 10" in out2.get("reason", ""))
    r3 = _hook("stop_json", dict(stop, stop_hook_active=True), env)
    check("stop 3: the check passes, the stop is not blocked", r3.returncode == 0 and "block" not in r3.stdout)
    state = json.loads((store / "sessions" / f"{sid}.json").read_text(encoding="utf-8"))
    a = state["run"]["auto"]
    check("state: met after 3 turns", a["status"] == "met" and a["turns"] == 3)
    check("the end alert went out", log.exists() and "met its goal after 3 turns" in log.read_text(encoding="utf-8"))
    reports = list((proj / ".engram" / "runs").glob("*.md"))
    check("the run report was written at the end", bool(reports))
    md = reports[0].read_text(encoding="utf-8") if reports else ""
    check("with the Engram run section", "## Engram run (met)" in md and "count reaches three" in md and "Turns:** 3 of 10" in md)
    r4 = _hook("stop_json", stop, env)
    check("after the end, stops are free", "block" not in r4.stdout)
    os.environ.pop("CLAUDE_ENGRAM_DIR", None)


def test_handler(tmp):
    print("MCP ops in-process:")
    _clean()
    store = tmp / "store-handler"
    proj = tmp / "proj-handler"
    proj.mkdir(parents=True, exist_ok=True)
    os.environ["CLAUDE_ENGRAM_DIR"] = str(store)
    from claude_engram.hooks import remind
    from claude_engram.handlers import Handlers

    remind._session_id = "s-handler"
    h = Handlers()

    def call(op, **kw):
        res = asyncio.run(h.handle_session_mine(op, {"project_path": str(proj), **kw}))
        return res[0].text

    t = call("run_start", goal="tests green", check="pytest -q", max_turns=7)
    check("run_start arms and explains the ends", "Run armed" in t and "pytest -q" in t and "7 turns" in t)
    check("the manifest was written (mode in-session)", any('"in-session"' in p.read_text(encoding="utf-8") for p in (proj / ".engram" / "runs").glob("*.manifest.json")))
    t = call("run_start", goal="again")
    check("a second run_start is refused", "already running" in t)
    t = call("run_status")
    check("run_status prints the run", '"status": "running"' in t and '"goal": "tests green"' in t)
    t = call("run_done", evidence="all green")
    check("run_done with a check only records", "check command decides" in t)
    t = call("run_stop", evidence="enough")
    check("run_stop ends it", "Run stopped" in t)
    check("run_status after: stopped", '"status": "stopped"' in call("run_status"))
    t = call("run_start", goal="no check here")
    t = call("run_done", evidence="I looked")
    check("run_done without a check ends it as self-declared", "self-declared" in t)
    os.environ.pop("CLAUDE_ENGRAM_DIR", None)


def test_source_guards():
    print("source guards:")
    remind = (ROOT / "claude_engram" / "hooks" / "remind.py").read_text(encoding="utf-8")
    check("the Stop branch runs the loop and prints the block", "_ar.stop_decision(" in remind and "print(json_module.dumps(_block))" in remind)
    check("autonomy_on takes the state everywhere it matters", remind.count("autonomy_on(state)") + remind.count("autonomy_on(load_state())") >= 3)
    td = (ROOT / "claude_engram" / "tool_definitions_v2.py").read_text(encoding="utf-8")
    check("session_mine exposes run_start/run_stop/run_done/run_status", all(f'"{op}"' in td for op in ("run_start", "run_stop", "run_done", "run_status")))
    skill = (ROOT / "claude_engram" / "skill" / "engram" / "SKILL.md").read_text(encoding="utf-8")
    check("the skill's /engram run is in-session via run_start", "session_mine(run_start" in skill and "like `/goal` or `/loop`" in skill)


def main():
    from claude_engram.hooks import autorun as ar
    from claude_engram.hooks import stall as st

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        test_state(ar, st)
        test_check(ar, tmp)
        test_stop_decision(ar, tmp)
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
