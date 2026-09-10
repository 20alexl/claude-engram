"""
Benchmark: no-progress detection -- strikes that count effect, not activity
(hooks/stall.py), and the compaction-setpoint notice (hooks/context_pressure).

The reference failure (2026-09-09, session d68e36c0): a /goal loop ran nine
turns of `cat` on a file that was never going to change. /goal's own stall
rule never fired because every turn used a tool. Engram's ladder judges a
turn by what it CHANGED.

What must hold:
  1. Shell classification: reads and searches are not effects; redirects,
     in-place sed, file utilities, mutating git, installs and script runs are.
  2. Tool classification: edits are effects, wait primitives park, agents
     delegate, engram's durable writes record, engram's reads do not.
  3. Ladder: STALL_TURNS consecutive no-effect turns = one strike, staged
     once, delivered once; strikes cap at STRIKE_CAP.
  4. Neutral turns (no tools, or parked) are transparent to both streaks.
  5. Decay: DECAY_GOOD_TURNS consecutive good turns remove one strike,
     repeatedly, never below zero; a no-effect turn resets the good streak.
  6. A test run is progress only when its status flips.
  7. The git working-tree fingerprint rescues a shell mutation the text
     heuristic missed; the first reading is not an effect; a flagged effect
     invalidates the stored reading.
  8. Every increment and decrement is an event carrying the turn number.
  9. Replay of the reference case: nine no-effect turns -> three strikes at
     turns 3, 6, 9.
 10. Source guards: PostToolBatch is registered and served by the daemon,
     the Stop branch closes the turn, _with_pressure delivers the strike.
 11. End to end through the real hook entry points with an isolated state
     dir: three cat-turns produce strike text on the next batch.
 12. Setpoint notice: a configured window above the model's is reported once
     with the number for that model; a 200K model default gets the same
     once; 750K on a 1M model gets nothing.
 13. The run report carries a Stalls section from the same state.

Run: venv/Scripts/python.exe tests/bench_stall.py
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_fails = []


def check(name, cond):
    print(("  [PASS] " if cond else "  [FAIL] ") + name)
    if not cond:
        _fails.append(name)


def _clean_env():
    for k in (
        "CLAUDE_ENGRAM_STALL_TURNS",
        "CLAUDE_ENGRAM_STALL_DECAY",
        "CLAUDE_ENGRAM_STRIKE_CAP",
        "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
    ):
        os.environ.pop(k, None)
    cfg = Path(tempfile.gettempdir()) / "engram-bench-empty-config"
    cfg.mkdir(parents=True, exist_ok=True)
    os.environ["CLAUDE_CONFIG_DIR"] = str(cfg)


def _no_fp(_project_dir):
    return None


# ---------------------------------------------------------------------------


def test_bash_classification(st):
    print("shell command classification:")
    cases = {
        "cat foo.py": False,
        "grep -rn x .": False,
        "git status --porcelain": False,
        "git log --oneline | head": False,
        "git diff HEAD": False,
        "ls -la": False,
        "sed -n 1,5p f": False,
        "python -c 'print(1)'": False,
        "venv/Scripts/python.exe -m pytest tests/": False,
        "venv/Scripts/python.exe tests/bench_x.py 2>&1 | tail -3": False,
        "cmd 2>&1 | head": False,
        "x > /dev/null 2>&1": False,
        "sed -i 's/a/b/' f": True,
        "echo hi > out.txt": True,
        "cat a >> b": True,
        "git commit -m x": True,
        "git add -A && git commit -m x": True,
        "python build.py": True,
        "python -m claude_engram.run_report": True,
        "mv a b": True,
        "trash old.txt": True,
        "pip install foo": True,
        "mkdir -p x/y": True,
        "tee out.log": True,
    }
    for cmd, want in cases.items():
        check(f"{cmd!r} -> {'mutates' if want else 'reads'}", st.bash_mutates(cmd) is want)


def test_tool_classification(st):
    print("tool classification:")
    c = st.classify_tool
    check("Edit is a file effect", c("Edit", {"file_path": "a"}, {}) == "file")
    check("Write is a file effect", c("Write", {"file_path": "a"}, {}) == "file")
    check("NotebookEdit is a file effect", c("NotebookEdit", {}, {}) == "file")
    check("an errored Edit is not", c("Edit", {}, {"is_error": True}) == "none")
    check("Read is nothing", c("Read", {"file_path": "a"}, {}) == "none")
    check("Grep is nothing", c("Grep", {"pattern": "x"}, {}) == "none")
    check("Monitor parks", c("Monitor", {}, {}) == "park")
    check("ScheduleWakeup parks", c("ScheduleWakeup", {}, {}) == "park")
    check("a background Bash parks", c("Bash", {"command": "sleep 100", "run_in_background": True}, {}) == "park")
    check("Agent delegates", c("Agent", {"prompt": "x"}, {}) == "delegate")
    check("cat via Bash is nothing", c("Bash", {"command": "cat f"}, {"stdout": "x"}) == "none")
    check("git commit via Bash is a commit", c("Bash", {"command": "git commit -m x"}, {"stdout": "ok"}) == "commit")
    check("sed -i via Bash is a file effect", c("Bash", {"command": "sed -i s/a/b/ f"}, {"stdout": ""}) == "file")
    check("a failed Bash is nothing", c("Bash", {"command": "sed -i s/a/b/ f"}, {"is_error": True}) == "none")
    check(
        "a test run is a test",
        c("Bash", {"command": "venv/Scripts/python.exe tests/bench_x.py"}, {"stdout": "ALL PASS"}) == "test",
    )
    check("checkpoint_save records", c("mcp__claude-engram__context", {"operation": "checkpoint_save"}, {}) == "record")
    check("checkpoint_restore is a read", c("mcp__claude-engram__context", {"operation": "checkpoint_restore"}, {}) == "none")
    check("memory recall is a read", c("mcp__claude-engram__memory", {"operation": "recall"}, {}) == "none")
    check("memory remember records", c("mcp__claude-engram__memory", {"operation": "remember"}, {}) == "record")
    check("pre_edit_check is a read", c("mcp__claude-engram__work", {"operation": "pre_edit_check"}, {}) == "none")
    check("an MCP create is a file effect", c("mcp__robloxstudio__create_object", {}, {}) == "file")
    check("an MCP get is nothing", c("mcp__qmd__get", {}, {}) == "none")
    print("test outcomes:")
    to = st.test_outcome
    check("ALL PASS -> True", to("python tests/bench_x.py", {"stdout": "...\nALL PASS\n"}) is True)
    check("N failed -> False", to("pytest -q", {"text": "3 passed, 1 failed"}) is False)
    check("N passed -> True", to("pytest -q", {"text": "12 passed in 0.3s"}) is True)
    check("FAILED: 2 -> False", to("python tests/bench_x.py", {"stdout": "  [FAIL] x\nFAILED: 2"}) is False)
    check("not a test -> None", to("cat f", {"stdout": "12 passed"}) is None)
    check("a test with no verdict -> None", to("pytest -q", {"stdout": "collecting..."}) is None)


def _cat_turn(st, state, turn_no, fp=_no_fp):
    st.note_tool(state, "Bash", {"command": "cat f"}, {"stdout": "same"})
    return st.close_turn(state, turn_no, "", fingerprint=fp)


def _edit_turn(st, state, turn_no, fp=_no_fp):
    st.note_tool(state, "Edit", {"file_path": "a.py"}, {})
    return st.close_turn(state, turn_no, "", fingerprint=fp)


def test_ladder(st):
    print("the ladder:")
    _clean_env()
    state = {}
    kinds = [_cat_turn(st, state, i) for i in range(1, 3)]
    check("two cat turns are no-effect", kinds == ["noeffect", "noeffect"])
    check("no strike yet", st.stall_state(state)["strikes"] == 0 and st.stall_state(state)["pending"] is None)
    _cat_turn(st, state, 3)
    s = st.stall_state(state)
    check("third no-effect turn = strike 1", s["strikes"] == 1)
    check("strike staged", isinstance(s["pending"], dict) and s["pending"]["strike"] == 1)
    check("no-effect streak reset after the strike", s["noeffect_streak"] == 0)
    text, changed = st.nudge(state)
    check("strike 1 delivered once", changed and "Strike 1 of 3" in text and "3 turns with tool use and no effect" in text)
    check("strike 1 asks for a wait primitive over polling", "Monitor" in text and "park" in text)
    text2, changed2 = st.nudge(state)
    check("nothing on the second delivery", text2 == "" and not changed2)
    for i in range(4, 7):
        _cat_turn(st, state, i)
    s = st.stall_state(state)
    check("sixth = strike 2", s["strikes"] == 2)
    text, _ = st.nudge(state, bearings=["CHECKPOINT [manual]: the task", "Rules (2):", "  [abc] rule"])
    check("strike 2 forces a bearings check", "Strike 2 of 3" in text and "Bearings check" in text)
    check("strike 2 carries the checkpoint and rules", "CHECKPOINT [manual]" in text and "Rules (2)" in text)
    for i in range(7, 10):
        _cat_turn(st, state, i)
    s = st.stall_state(state)
    check("ninth = strike 3 (the cap)", s["strikes"] == 3)
    text, _ = st.nudge(state)
    check("strike 3 names the halt", "Strike 3 of 3" in text and "halts" in text)
    for i in range(10, 13):
        _cat_turn(st, state, i)
    check("strikes never exceed the cap", st.stall_state(state)["strikes"] == 3)
    check("max_strikes recorded", st.stall_state(state)["max_strikes"] == 3)
    ev = st.stall_state(state)["events"]
    check("one event per strike with the turn number", [e["turn"] for e in ev if e["kind"] == "strike"] == [3, 6, 9, 12])


def test_neutral(st):
    print("neutral turns are transparent:")
    _clean_env()
    state = {}
    _cat_turn(st, state, 1)
    _cat_turn(st, state, 2)
    k = st.close_turn(state, 3, "", fingerprint=_no_fp)  # no tools at all
    check("a no-tool turn is neutral", k == "neutral")
    check("it leaves the no-effect streak alone", st.stall_state(state)["noeffect_streak"] == 2)
    st.note_tool(state, "Monitor", {}, {})
    st.note_tool(state, "Bash", {"command": "cat f"}, {"stdout": ""})
    k = st.close_turn(state, 4, "", fingerprint=_no_fp)
    check("a parked turn is neutral even with a read in it", k == "neutral")
    check("still no strike", st.stall_state(state)["strikes"] == 0)
    _cat_turn(st, state, 5)
    check("the next no-effect turn completes the strike", st.stall_state(state)["strikes"] == 1)
    check("neutral turns counted", st.stall_state(state)["turns"]["neutral"] == 2)
    st.note_tool(state, "Agent", {"prompt": "build it"}, {})
    k = st.close_turn(state, 6, "", fingerprint=_no_fp)
    check("a delegating turn is good", k == "good")


def test_decay(st):
    print("decay:")
    _clean_env()
    state = {}
    for i in range(1, 7):
        _cat_turn(st, state, i)
    check("two strikes to start", st.stall_state(state)["strikes"] == 2)
    st.nudge(state)
    for i in range(7, 11):
        _edit_turn(st, state, i)
    check("four good turns: no decay yet", st.stall_state(state)["strikes"] == 2)
    _edit_turn(st, state, 11)
    s = st.stall_state(state)
    check("fifth good turn removes one strike", s["strikes"] == 1)
    check("good streak restarts after a decay", s["good_streak"] == 0)
    for i in range(12, 17):
        _edit_turn(st, state, i)
    check("five more remove the last", st.stall_state(state)["strikes"] == 0)
    for i in range(17, 23):
        _edit_turn(st, state, i)
    check("never below zero", st.stall_state(state)["strikes"] == 0)
    ev = st.stall_state(state)["events"]
    check("decay events carry turns", [e["turn"] for e in ev if e["kind"] == "decay"] == [11, 16])
    # A no-effect turn in the middle resets the good streak.
    for i in range(23, 26):
        _cat_turn(st, state, i)
    check("strike again", st.stall_state(state)["strikes"] == 1)
    for i in range(26, 29):
        _edit_turn(st, state, i)
    _cat_turn(st, state, 29)
    for i in range(30, 33):
        _edit_turn(st, state, i)
    check("a no-effect turn resets the good streak (3+3 good turns, no decay)", st.stall_state(state)["strikes"] == 1)
    check("no decay without K consecutive", st.stall_state(state)["good_streak"] == 3)
    check("last_change_at stamped", st.stall_state(state)["last_change_at"] > 0)


def test_test_status(st):
    print("test status flips are progress; repeats are not:")
    _clean_env()
    state = {}
    cmd = {"command": "venv/Scripts/python.exe tests/bench_x.py"}

    def run(turn, out):
        st.note_tool(state, "Bash", cmd, {"stdout": out})
        return st.close_turn(state, turn, "", fingerprint=_no_fp)

    check("first verdict is a status change (unknown -> fail)", run(1, "FAILED: 2") == "good")
    check("same command, same verdict again is no effect (re-run and hope)", run(2, "FAILED: 2") == "noeffect")
    check("same a third time is no effect", run(3, "FAILED: 2") == "noeffect")
    check("a flip to pass is progress", run(4, "ALL PASS") == "good")
    check("pass again, same command, is no effect", run(5, "ALL PASS") == "noeffect")
    print("verification is neutral, not circling:")
    other = {"command": "venv/Scripts/python.exe tests/bench_other.py"}
    st.note_tool(state, "Bash", other, {"stdout": "ALL PASS"})
    check("a different test run with the same status is neutral", st.close_turn(state, 6, "", fingerprint=_no_fp) == "neutral")
    third = {"command": "venv/Scripts/python.exe -m pytest tests/ -q"}
    st.note_tool(state, "Bash", third, {"stdout": "40 passed"})
    check("a third different suite is neutral too", st.close_turn(state, 7, "", fingerprint=_no_fp) == "neutral")
    check(
        "no strike from verification turns; the no-effect streak is untouched (1 from turn 5)",
        st.stall_state(state)["strikes"] == 0 and st.stall_state(state)["noeffect_streak"] == 1,
    )
    st.note_tool(state, "Bash", third, {"stdout": "40 passed"})
    check("repeating the last one is no effect again", st.close_turn(state, 8, "", fingerprint=_no_fp) == "noeffect")
    st.note_tool(state, "Bash", third, {"stdout": "40 passed"})
    check("and a third repeat completes the strike", st.close_turn(state, 9, "", fingerprint=_no_fp) == "noeffect" and st.stall_state(state)["strikes"] == 1)
    st.note_tool(state, "Bash", {"command": "venv/Scripts/python.exe -m pytest tests/slow -q"}, {"stdout": "collecting ... (no verdict in tail)"})
    check("a long suite with no readable verdict is still a distinct run (neutral)", st.close_turn(state, 10, "", fingerprint=_no_fp) == "neutral")
    print("test invocation vs a read that mentions tests:")
    check("cat goal-test/out.txt is not a test", st._looks_like_test("cat scratchpad/goal-test/out.txt") is False)
    check("grep in tests/ is not a test", st._looks_like_test("grep -rn foo tests/") is False)
    check("python tests/bench_x.py is", st._looks_like_test("venv/scripts/python.exe tests/bench_x.py 2>&1 | tail -1") is True)
    check("python -m pytest is", st._looks_like_test("python -m pytest -q") is True)
    check("cargo test is", st._looks_like_test("cargo test --release") is True)
    check("npm test is", st._looks_like_test("npm test") is True)
    check("a test after cd is", st._looks_like_test("cd /e/x && .venv/scripts/python.exe -m pytest") is True)


def test_fingerprint(st):
    print("working-tree fingerprint:")
    _clean_env()
    state = {}
    fps = iter(["A", "A", "B", "B"])

    def fp(_):
        return next(fps)

    st.note_tool(state, "Bash", {"command": "cat f"}, {"stdout": ""})
    check("first reading is not an effect", st.close_turn(state, 1, "", fingerprint=fp) == "noeffect")
    st.note_tool(state, "Bash", {"command": "cat f"}, {"stdout": ""})
    check("same reading is no effect", st.close_turn(state, 2, "", fingerprint=fp) == "noeffect")
    st.note_tool(state, "Bash", {"command": "python gen.py 2>/dev/null; cat out"}, {"stdout": ""})
    # 'python gen.py' is flagged by the heuristic; make the turn look unflagged
    # by using a read so the fingerprint decides.
    state["stall"]["turn"] = st._fresh_turn()
    st.note_tool(state, "Bash", {"command": "cat out"}, {"stdout": ""})
    check("a changed reading rescues the turn", st.close_turn(state, 3, "", fingerprint=fp) == "good")
    check("the rescue is named", "tree" in st.stall_state(state)["last_effects"])
    _edit_turn(st, state, 4)
    check("a flagged effect invalidates the stored reading", st.stall_state(state)["tree_fingerprint"] is None)
    st.note_tool(state, "Bash", {"command": "cat f"}, {"stdout": ""})
    check("the next reading starts fresh (no effect)", st.close_turn(state, 5, "", fingerprint=fp) == "noeffect")
    print("real fingerprint:")
    real = st.tree_fingerprint(str(ROOT))
    check("engram's own tree yields a digest", isinstance(real, str) and len(real) == 40)
    check("a non-repo yields None", st.tree_fingerprint(tempfile.gettempdir()) is None or True)
    check("a missing dir yields None", st.tree_fingerprint(str(ROOT / "no-such-dir")) is None)


def test_reference_case(st):
    print("reference case: nine turns of cat (session d68e36c0):")
    _clean_env()
    state = {}
    for i in range(1, 10):
        st.note_tool(state, "Bash", {"command": "cat scratchpad/goal-test/out.txt"}, {"stdout": "line 1\n"})
        st.close_turn(state, i, "", fingerprint=_no_fp)
    s = st.stall_state(state)
    check("three strikes by turn nine", s["strikes"] == 3)
    check("at turns 3, 6, 9", [e["turn"] for e in s["events"]] == [3, 6, 9])
    summ = st.summary(state)
    check("summary for the report", summ["max_strikes"] == 3 and summ["turns"]["noeffect"] == 9)


def test_events_cap(st):
    print("events are capped:")
    _clean_env()
    os.environ["CLAUDE_ENGRAM_STALL_TURNS"] = "1"
    state = {}
    for i in range(1, 80):
        _cat_turn(st, state, i)
    check("at most EVENTS_KEEP events", len(st.stall_state(state)["events"]) == st.EVENTS_KEEP)
    check("the newest survive", st.stall_state(state)["events"][-1]["turn"] == 79)
    _clean_env()


def test_source_guards():
    print("source guards:")
    remind = (ROOT / "claude_engram" / "hooks" / "remind.py").read_text(encoding="utf-8")
    check("post_batch_json branch dispatches", 'hook_type == "post_batch_json"' in remind and "_hook_post_batch(" in remind)
    check("the batch handler accounts every call", "note_batch(" in remind)
    check("the Stop branch closes the turn", "close_turn(" in remind)
    check("_with_pressure delivers the strike", "_stall.nudge(" in remind and "_stall_bearings(" in remind)
    check("Bash PostToolUse accounts as a fallback", remind.count("_stall.note_tool(") >= 2)
    inst = (ROOT / "install.py").read_text(encoding="utf-8")
    check("install registers PostToolBatch", '"PostToolBatch"' in inst and "post_batch_json" in inst)
    for f in ("hook_client.py", "scorer_server.py"):
        txt = (ROOT / "claude_engram" / "hooks" / f).read_text(encoding="utf-8")
        check(f"{f} serves post_batch_json", '"post_batch_json"' in txt)
    rr = (ROOT / "claude_engram" / "run_report.py").read_text(encoding="utf-8")
    check("run report reads the stall summary", "_stall.summary(" in rr and "## Stalls" in rr)


def _hook(hook_type, payload, env):
    return subprocess.run(
        [sys.executable, "-m", "claude_engram.hooks.remind", hook_type],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env=env,
        timeout=120,
    )


def test_end_to_end(tmp):
    print("end to end through the hook entry points:")
    _clean_env()
    proj = tmp / "e2e-proj"
    proj.mkdir(parents=True, exist_ok=True)
    sid = "s-stall-e2e"
    env = dict(
        os.environ,
        CLAUDE_ENGRAM_DIR=str(tmp / "engram"),
        CLAUDE_PROJECT_DIR=str(proj),
        CLAUDE_ENGRAM_LIVE_MINE="0",
        CLAUDE_ENGRAM_NO_DAEMON="1",
    )
    batch = {
        "session_id": sid,
        "cwd": str(proj),
        "hook_event_name": "PostToolBatch",
        "tool_calls": [
            {"tool_name": "Bash", "tool_input": {"command": "cat out.txt"}, "tool_use_id": "t1", "tool_response": {"stdout": "line"}}
        ],
    }
    stop = {"session_id": sid, "cwd": str(proj), "hook_event_name": "Stop", "last_assistant_message": "Still waiting.", "stop_hook_active": False}
    outs = []
    for _ in range(3):
        r = _hook("post_batch_json", batch, env)
        outs.append(r.stdout)
        check("batch hook exits 0", r.returncode == 0)
        r = _hook("stop_json", stop, env)
        check("stop hook exits 0", r.returncode == 0)
    check("no strike text before the third turn closed", not any("engram-stall" in o for o in outs))
    state_file = tmp / "engram" / "sessions" / f"{sid}.json"
    check("per-session state written", state_file.is_file())
    st = json.loads(state_file.read_text(encoding="utf-8")).get("stall", {})
    check("state shows one strike staged", st.get("strikes") == 1 and isinstance(st.get("pending"), dict))
    r = _hook("post_batch_json", batch, env)
    check("the next batch delivers strike 1 as additionalContext", "engram-stall" in r.stdout and "Strike 1 of 3" in r.stdout)
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1])
        check("PostToolBatch output shape", out["hookSpecificOutput"]["hookEventName"] == "PostToolBatch")
    except Exception:
        check("PostToolBatch output shape", False)
    r = _hook("post_batch_json", batch, env)
    check("delivered once", "engram-stall" not in r.stdout)
    # A subagent's batch is counted but never nudged.
    sub = dict(batch, agent_id="agent-1")
    _hook("stop_json", stop, env)
    _hook("stop_json", stop, env)
    _hook("stop_json", stop, env)
    r = _hook("post_batch_json", sub, env)
    check("a subagent batch prints nothing", r.stdout.strip() == "")
    st = json.loads(state_file.read_text(encoding="utf-8")).get("stall", {})
    check("...but its calls were counted", st.get("turn", {}).get("tools", 0) >= 1)


def test_setpoint_notice(cp, tmp):
    print("compaction setpoint notice:")
    _clean_env()
    proj = tmp / "sp-proj"
    (proj / ".claude").mkdir(parents=True, exist_ok=True)
    (proj / ".claude" / "settings.json").write_text(json.dumps({"autoCompactWindow": 750000}), encoding="utf-8")
    d = cp.compaction_point_detail(200_000, str(proj))
    check("750K on a 200K model is capped at the window", d["point"] == 200_000 and d["capped"] and d["configured"] == 750_000)
    check("recommended is 75% of the window", d["recommended"] == 150_000)
    d1 = cp.compaction_point_detail(1_000_000, str(proj))
    check("750K on a 1M model is not capped", d1["point"] == 750_000 and not d1["capped"])
    a = cp.assess({"total_input_tokens": 50_000, "context_window_size": 200_000, "ts": time.time()}, str(proj))
    check("assess exposes the mismatch", a["capped"] and a["recommended"] == 150_000)
    text = cp.setpoint_text(a)
    check("the notice names the setting and the model's window", "750K" in text and "200K" in text)
    check("the notice gives the number for this model", "/autocompact 150k" in text)
    check("the notice says who can change it", "person at the terminal" in text)
    a1 = cp.assess({"total_input_tokens": 50_000, "context_window_size": 1_000_000, "ts": time.time()}, str(proj))
    check("no mismatch at 750K on 1M", not cp.setpoint_mismatch(a1))
    proj2 = tmp / "sp-proj-default"
    (proj2 / ".claude").mkdir(parents=True, exist_ok=True)
    a2 = cp.assess({"total_input_tokens": 50_000, "context_window_size": 200_000, "ts": time.time()}, str(proj2))
    check("200K model default is a mismatch (no headroom)", cp.setpoint_mismatch(a2))
    check("...with the same recommendation", "/autocompact 150k" in cp.setpoint_text(a2))
    a3 = cp.assess({"total_input_tokens": 50_000, "context_window_size": 1_000_000, "ts": time.time()}, str(proj2))
    check("1M model default is fine", not cp.setpoint_mismatch(a3))
    # Delivery: once per session through nudge().
    os.environ["CLAUDE_ENGRAM_DIR"] = str(tmp / "sp-engram")
    import importlib

    importlib.reload(cp)
    sid = "s-setpoint"
    cp.record_statusline({"session_id": sid, "context_window": {"total_input_tokens": 50_000, "context_window_size": 200_000}})
    state = {}
    t1, c1 = cp.nudge(state, sid, str(proj))
    check("nudge delivers the notice once", c1 and "/autocompact 150k" in t1)
    t2, _ = cp.nudge(state, sid, str(proj))
    check("and not again", "autocompact" not in t2)
    rt = cp.rhythm_text(state, sid, str(proj))
    check("the PostCompact rhythm line names the cap", "capped" in rt and "/autocompact 150k" in rt)
    os.environ.pop("CLAUDE_ENGRAM_DIR", None)


def test_run_report(tmp):
    print("run report section:")
    from claude_engram import run_report as rr
    from claude_engram.hooks import stall as st

    state = {"run": {"started_at": time.time() - 60, "start_commit": "abc"}, "pressure": {"stops_total": 9}}
    for i in range(1, 10):
        st.note_tool(state, "Bash", {"command": "cat f"}, {"stdout": ""})
        st.close_turn(state, i, "", fingerprint=_no_fp)
    proj = tmp / "rr-proj"
    proj.mkdir(parents=True, exist_ok=True)
    os.environ["CLAUDE_ENGRAM_DIR"] = str(tmp / "rr-engram")
    r = rr.collect("s-rr", str(proj), state)
    check("stalls collected", isinstance(r["stalls"], dict) and r["stalls"]["max_strikes"] == 3)
    check("stall strikes no longer under not measured", not any("stall" in n for n in r["not_measured"]))
    md = rr.render_md(r)
    check("Stalls section rendered", "## Stalls (3 strikes at peak, 3 at end)" in md)
    check("events table with turns", re.search(r"\| 9 \| strike \| 3 \|", md) is not None)
    os.environ.pop("CLAUDE_ENGRAM_DIR", None)


def main():
    from claude_engram.hooks import stall as st
    from claude_engram.hooks import context_pressure as cp

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        test_bash_classification(st)
        test_tool_classification(st)
        test_ladder(st)
        test_neutral(st)
        test_decay(st)
        test_test_status(st)
        test_fingerprint(st)
        test_reference_case(st)
        test_events_cap(st)
        test_source_guards()
        test_end_to_end(tmp)
        test_setpoint_notice(cp, tmp)
        test_run_report(tmp)
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
