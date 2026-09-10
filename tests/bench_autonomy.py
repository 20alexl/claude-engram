"""
Benchmark: autonomy mode -- the halt, the alerts, the launcher.

What must hold:
  1. The halt arms only in autonomy mode (CLAUDE_ENGRAM_AUTONOMY), only at
     the strike cap, once; release resets strikes and is an event.
  2. Halted, PreToolUse denies every tool with a reason that names the
     release command, except PushNotification and engram's checkpoint call.
  3. Arming the halt sends an alert; with no alert command it is recorded
     as not sent, never lost.
  4. alerts.send runs the owner's command with {message} (or on stdin),
     records sent/not, never raises.
  5. StopFailure in autonomy mode alerts; Notification (needs input,
     permission prompt, idle) alerts in autonomy mode and is silent otherwise.
  6. The CLI: status prints the summary; release lifts the halt.
  7. The launcher: window by model, 75% compaction point, the prompt shape
     (goal line, task, park hint), the env it sets and strips, the command
     shape for a fresh run and a resume, the resume decision.
  8. --dry-run prints the plan and launches nothing.
  9. End to end with a fake `claude`: a usage-limit exit with a known reset
     sleeps, resumes the same session, ends on exit 0, writes the report and
     the manifest, and records the paused/done alerts.
 10. Source guards and the report sections (HALTED line, Alerts table).

Run: venv/Scripts/python.exe tests/bench_autonomy.py
"""

import json
import os
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


def _clean():
    for k in ("CLAUDE_ENGRAM_AUTONOMY", "CLAUDE_ENGRAM_STALL_TURNS", "CLAUDE_ENGRAM_STRIKE_CAP",
              "CLAUDE_ENGRAM_STALL_DECAY", "CLAUDE_ENGRAM_ALERT_COMMAND", "CLAUDE_ENGRAM_RESUME_SLACK"):
        os.environ.pop(k, None)


def _no_fp(_):
    return None


def _cat_turn(st, state, i):
    st.note_tool(state, "Bash", {"command": "cat f"}, {"stdout": ""})
    st.close_turn(state, i, "", fingerprint=_no_fp)


def test_halt_arming(st):
    print("the halt arms only in autonomy mode, at the cap, once:")
    _clean()
    state = {}
    for i in range(1, 10):
        _cat_turn(st, state, i)
    check("three strikes without autonomy", st.stall_state(state)["strikes"] == 3)
    check("no halt outside autonomy mode", st.maybe_halt(state, 9) is False and st.halted(state) is None)
    os.environ["CLAUDE_ENGRAM_AUTONOMY"] = "1"
    check("autonomy_on reads the env", st.autonomy_on())
    check("halt arms at the cap", st.maybe_halt(state, 9) is True)
    h = st.halted(state)
    check("halted record carries turn and strikes", h is not None and h["turn"] == 9 and h["strikes"] == 3 and h["denied"] == 0)
    check("halt is an event", st.stall_state(state)["events"][-1]["kind"] == "halt")
    check("arming twice is a no-op", st.maybe_halt(state, 10) is False)
    state2 = {}
    for i in range(1, 6):
        _cat_turn(st, state2, i)
    check("below the cap, no halt even in autonomy mode", st.maybe_halt(state2, 5) is False)
    print("texts:")
    r = st.deny_reason(state, "Read")
    check("deny reason names the release command and the two open calls", "stall release" in r and "checkpoint_save" in r and "PushNotification" in r and "Denied: Read" in r)
    t = st.halt_text(state, "abc-123")
    check("halt text gives the order: checkpoint, then notify, then stop", t.index("checkpoint_save") < t.index("PushNotification") and "Session abc-123" in t)
    st.note_denied(state)
    check("denials are counted", st.halted(state)["denied"] == 1)
    check("ToolSearch, PushNotification and the checkpoint call stay open", {"ToolSearch", "PushNotification", "mcp__claude-engram__context"} <= set(st.HALT_ALLOWED_TOOLS))
    ev_before = len(st.stall_state(state)["events"])
    _cat_turn(st, state, 10)
    check("turns after the halt are not more strikes", st.stall_state(state)["events"][-1]["kind"] != "strike" or len(st.stall_state(state)["events"]) == ev_before)
    st.note_tool(state, "Bash", {"command": "cat f"}, {"stdout": ""})
    check("close_turn reports halted", st.close_turn(state, 11, "", fingerprint=_no_fp) == "halted")
    print("release:")
    check("release lifts the halt", st.release(state, "bench") is True and st.halted(state) is None)
    check("...resets strikes", st.stall_state(state)["strikes"] == 0)
    check("...and is an event", st.stall_state(state)["events"][-1]["kind"] == "release")
    check("release on a non-halted session is False", st.release(state) is False)
    s = st.summary(state)
    check("summary carries autonomy and halted", s["autonomy"] is True and s["halted"] is None)
    _clean()


def _writer_script(tmp):
    p = tmp / "alert_sink.py"
    p.write_text(
        "import sys\n"
        "msg = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()\n"
        "open(sys.argv[2] if len(sys.argv) > 2 else r'%s', 'a', encoding='utf-8').write(msg.strip() + '\\n')\n" % str(tmp / "alerts.log").replace("\\", "\\\\"),
        encoding="utf-8",
    )
    return p


def test_alerts(al, tmp):
    print("alerts:")
    _clean()
    state = {}
    rec = al.send("hello", str(tmp), kind="test", state=state)
    check("no command: recorded, not sent", rec["sent"] is False and "no alert_command" in rec["detail"] and state["alerts"][0]["kind"] == "test")
    script = _writer_script(tmp)
    log = tmp / "alerts.log"
    os.environ["CLAUDE_ENGRAM_ALERT_COMMAND"] = f'"{sys.executable}" "{script}" {{message}}'
    rec = al.send("  run 1234 halted:  no progress 3x ", str(tmp), kind="halt", state=state)
    check("command with {message} runs and is marked sent", rec["sent"] is True and rec["detail"] == "ok")
    check("message is collapsed and delivered", log.read_text(encoding="utf-8").strip().endswith("run 1234 halted: no progress 3x"))
    os.environ["CLAUDE_ENGRAM_ALERT_COMMAND"] = f'"{sys.executable}" "{script}"'
    rec = al.send("via stdin", str(tmp), kind="x", state=state)
    check("command without a placeholder gets the message on stdin", rec["sent"] and "via stdin" in log.read_text(encoding="utf-8"))
    os.environ["CLAUDE_ENGRAM_ALERT_COMMAND"] = f'"{sys.executable}" -c "import sys; sys.exit(3)"'
    rec = al.send("fails", str(tmp), kind="x", state=state)
    check("a failing command is recorded as not sent", rec["sent"] is False)
    check("messages are capped at 200 chars", len(al.send("x" * 500, str(tmp), state=state)["message"]) == 200)
    os.environ.pop("CLAUDE_ENGRAM_ALERT_COMMAND", None)
    proj = tmp / "cfg-proj"
    (proj / ".engram").mkdir(parents=True, exist_ok=True)
    (proj / ".engram" / "config.json").write_text(json.dumps({"alert_command": f'"{sys.executable}" "{script}" {{message}}'}), encoding="utf-8")
    check("the command can come from .engram/config.json", al.alert_command(str(proj)).startswith('"'))
    check("summary lists the records", len(al.summary(state)) == 5)
    _clean()


def _hook(hook_type, payload, env):
    return subprocess.run(
        [sys.executable, "-m", "claude_engram.hooks.remind", hook_type],
        input=json.dumps(payload), capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=120,
    )


def test_end_to_end_hooks(tmp):
    print("end to end through the hooks (autonomy on, cap 2, one turn per strike):")
    _clean()
    store = tmp / "store-e2e"
    proj = tmp / "proj-e2e"
    proj.mkdir(parents=True, exist_ok=True)
    script = _writer_script(tmp)
    log = tmp / "alerts.log"
    if log.exists():
        log.unlink()
    sid = "s-autonomy-e2e"
    env = dict(os.environ, CLAUDE_ENGRAM_DIR=str(store), CLAUDE_PROJECT_DIR=str(proj), CLAUDE_ENGRAM_LIVE_MINE="0",
               CLAUDE_ENGRAM_AUTONOMY="1", CLAUDE_ENGRAM_STALL_TURNS="1", CLAUDE_ENGRAM_STRIKE_CAP="2")
    batch = {"session_id": sid, "cwd": str(proj), "hook_event_name": "PostToolBatch", "permission_mode": "bypassPermissions",
             "tool_calls": [{"tool_name": "Bash", "tool_input": {"command": "cat out.txt"}, "tool_use_id": "t1", "tool_response": {"stdout": "x"}}]}
    stop = {"session_id": sid, "cwd": str(proj), "hook_event_name": "Stop", "last_assistant_message": "Still waiting.", "stop_hook_active": False}
    state_file = store / "sessions" / f"{sid}.json"

    def st():
        return json.loads(state_file.read_text(encoding="utf-8"))

    _hook("post_batch_json", batch, env); _hook("stop_json", stop, env)
    check("one strike after the first no-effect turn", st()["stall"]["strikes"] == 1 and not st()["stall"].get("halted"))
    r = _hook("pre_tool_json", {"session_id": sid, "cwd": str(proj), "hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": "x"}}, env)
    check("not halted: the catch-all hook prints nothing", r.returncode == 0 and r.stdout.strip() == "")
    _hook("post_batch_json", batch, env); _hook("stop_json", stop, env)
    s = st()
    check("second strike arms the halt", s["stall"]["strikes"] == 2 and isinstance(s["stall"].get("halted"), dict))
    check("the halt alert is recorded as not sent (no command)", any(a["kind"] == "halt" and a["sent"] is False for a in s.get("alerts", [])))
    r = _hook("pre_tool_json", {"session_id": sid, "cwd": str(proj), "hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": "x"}}, env)
    out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    hso = out.get("hookSpecificOutput", {})
    check("halted: Read is denied with the reason", hso.get("permissionDecision") == "deny" and "engram halt" in hso.get("permissionDecisionReason", ""))
    r = _hook("pre_tool_json", {"session_id": sid, "cwd": str(proj), "hook_event_name": "PreToolUse", "tool_name": "mcp__qmd__query", "tool_input": {}}, env)
    check("halted: an MCP tool is denied too", "deny" in r.stdout)
    r = _hook("pre_tool_json", {"session_id": sid, "cwd": str(proj), "hook_event_name": "PreToolUse", "tool_name": "PushNotification", "tool_input": {"message": "m", "status": "proactive"}}, env)
    check("halted: PushNotification stays open", r.stdout.strip() == "")
    r = _hook("pre_tool_json", {"session_id": sid, "cwd": str(proj), "hook_event_name": "PreToolUse", "tool_name": "mcp__claude-engram__context", "tool_input": {"operation": "checkpoint_save"}}, env)
    check("halted: the checkpoint call stays open", r.stdout.strip() == "")
    check("denials counted", st()["stall"]["halted"]["denied"] == 2)
    r = _hook("pre_bash_json", {"session_id": sid, "cwd": str(proj), "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_use_id": "t9", "permission_mode": "bypassPermissions"}, env)
    check("the halt text rides the next injection point once", "engram-halt" in r.stdout and "checkpoint_save" in r.stdout)
    r = _hook("pre_bash_json", {"session_id": sid, "cwd": str(proj), "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_use_id": "t10", "permission_mode": "bypassPermissions"}, env)
    check("...and not again", "engram-halt" not in r.stdout)
    print("alerts through the hooks:")
    env2 = dict(env, CLAUDE_ENGRAM_ALERT_COMMAND=f'"{sys.executable}" "{script}" {{message}}')
    r = _hook("stop_failure_json", {"session_id": sid, "cwd": str(proj), "hook_event_name": "StopFailure", "error_type": "rate_limit", "error": "limit", "permission_mode": "bypassPermissions"}, env2)
    check("StopFailure in autonomy mode alerts", log.exists() and "stopped: rate_limit" in log.read_text(encoding="utf-8"))
    r = _hook("notification_json", {"session_id": sid, "cwd": str(proj), "hook_event_name": "Notification", "notification_type": "permission_prompt", "message": "Allow Bash?"}, env2)
    check("a permission prompt in autonomy mode alerts", "waiting on you: permission_prompt" in log.read_text(encoding="utf-8"))
    r = _hook("notification_json", {"session_id": sid, "cwd": str(proj), "hook_event_name": "Notification", "notification_type": "auth_success"}, env2)
    check("other notification types are silent", "auth_success" not in log.read_text(encoding="utf-8"))
    env3 = dict(env2); env3.pop("CLAUDE_ENGRAM_AUTONOMY", None)
    before = log.read_text(encoding="utf-8")
    _hook("notification_json", {"session_id": sid, "cwd": str(proj), "hook_event_name": "Notification", "notification_type": "agent_needs_input"}, env3)
    check("outside autonomy mode notifications are silent", log.read_text(encoding="utf-8") == before)
    print("the CLI:")
    r = subprocess.run([sys.executable, "-m", "claude_engram.hooks.stall", "status", sid], capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=60)
    check("status prints the halted record", r.returncode == 0 and '"halted"' in r.stdout and '"denied": 2' in r.stdout)
    r = subprocess.run([sys.executable, "-m", "claude_engram.hooks.stall", "release", sid], capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=60)
    check("release lifts it", r.returncode == 0 and "released" in r.stdout and st()["stall"].get("halted") is None and st()["stall"]["strikes"] == 0)
    r = _hook("pre_tool_json", {"session_id": sid, "cwd": str(proj), "hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {}}, env)
    check("after release, tools are allowed again", r.stdout.strip() == "")
    r = subprocess.run([sys.executable, "-m", "claude_engram.hooks.stall", "release", sid], capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=60)
    check("releasing twice says so", r.returncode == 1 and "not halted" in r.stdout)
    print("run report:")
    from claude_engram import run_report as rr

    s = st()
    s["stall"]["halted"] = {"at": time.time(), "turn": 2, "strikes": 2, "denied": 2}
    rep = rr.collect(sid, str(proj), s)
    md = rr.render_md(rep)
    check("HALTED line", "**HALTED** at turn 2" in md and "2 tool call(s) denied" in md)
    check("Alerts table", "## Alerts (" in md and "| halt |" in md and "stopped: rate_limit" in md)
    _clean()


def test_launcher_units(run):
    print("launcher units:")
    _clean()
    check("haiku window 200K", run.model_window("haiku") == 200_000)
    check("default window 1M", run.model_window("") == 1_000_000 and run.model_window("claude-fable-5-1") == 1_000_000)
    check("explicit window wins", run.model_window("haiku", "500k") == 500_000)
    check("75% point", run.compaction_env(1_000_000, 0.75) == 750_000 and run.compaction_env(200_000, 0.75) == 150_000)
    check("point floor 100K", run.compaction_env(120_000, 0.5) == 100_000)
    p = run.build_prompt("done.txt contains ok", "Write ok into done.txt.")
    check("prompt: goal line first, task, park hint", p.startswith("/goal done.txt contains ok") and "Write ok into done.txt." in p and "park on Monitor" in p)
    check("prompt without the hint", "park on Monitor" not in run.build_prompt("g", "t", park_hint=False))
    env = run.build_env({"PATH": "x", "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "old"}, 750_000, "cmd {message}")
    check("env: autonomy, window, msys, alert; nested identity stripped",
          env["CLAUDE_ENGRAM_AUTONOMY"] == "1" and env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "750000" and env["MSYS_NO_PATHCONV"] == "1"
          and env["CLAUDE_ENGRAM_ALERT_COMMAND"] == "cmd {message}" and "CLAUDECODE" not in env and "CLAUDE_CODE_SESSION_ID" not in env and env["PATH"] == "x")
    c = run.build_cmd("/goal x", "sid-1", "bypassPermissions", "sonnet", 40)
    check("fresh command shape", c[:3] == ["claude", "-p", "/goal x"] and "--session-id" in c and c[c.index("--session-id") + 1] == "sid-1"
          and "--output-format" in c and c[c.index("--permission-mode") + 1] == "bypassPermissions" and c[c.index("--model") + 1] == "sonnet" and c[c.index("--max-turns") + 1] == "40")
    c2 = run.build_cmd("Continue.", "sid-1", "bypassPermissions", resume=True)
    check("resume command shape", c2[:4] == ["claude", "-p", "--resume", "sid-1"] and "Continue." in c2 and "--session-id" not in c2 and "--model" not in c2)
    now = 1_000_000.0
    check("no failure: no resume", run.resume_decision({}, 0, 3, now)[0] is False)
    check("non-limit failure: no resume", run.resume_decision({"run": {"last_failure": {"error_type": "overloaded"}}}, 0, 3, now)[0] is False)
    st = {"run": {"last_failure": {"error_type": "rate_limit", "five_hour_resets_at": now + 600}}}
    ok, wait, why = run.resume_decision(st, 0, 3, now)
    check("limit with a reset: resume after reset + slack", ok and 600 <= wait <= 600 + run.RESUME_SLACK_SECS + 1 and "10 min" in why)
    check("budget spent: no resume", run.resume_decision(st, 3, 3, now)[0] is False)
    check("no reset time: no resume", run.resume_decision({"run": {"last_failure": {"error_type": "rate_limit"}}}, 0, 3, now)[0] is False)
    ok, wait, why = run.resume_decision({"run": {"last_failure": {"error_type": "rate_limit", "seven_day_resets_at": now + 3 * 86400}}}, 0, 3, now)
    check("a weekly reset is too long to hold", ok is False and "too long" in why)
    check("result parsing takes the last JSON line", run._parse_result('noise\n{"a":1}\n{"result":"ok","num_turns":3}\n')["num_turns"] == 3)
    check("result parsing tolerates junk", run._parse_result("nothing") == {})


def test_dry_run(tmp):
    print("--dry-run:")
    proj = tmp / "proj-dry"
    proj.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, CLAUDE_ENGRAM_DIR=str(tmp / "store-dry"))
    r = subprocess.run([sys.executable, "-m", "claude_engram.run", "--goal", "x", "--project", str(proj), "--dry-run", "--model", "sonnet"],
                       capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=120)
    check("exits 0 and prints the plan", r.returncode == 0 and "dry run" in r.stdout and "compaction point 750,000" in r.stdout and "window 1,000,000" in r.stdout)
    check("no manifest written", not list((proj / ".engram" / "runs").glob("*")) if (proj / ".engram" / "runs").exists() else True)
    r = subprocess.run([sys.executable, "-m", "claude_engram.run", "--project", str(proj), "--dry-run"], capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=120)
    check("nothing to run without a goal or prompt", r.returncode == 2)


def _fake_claude(tmp):
    """A stand-in for `claude`: first call records a usage-limit failure in
    the session state and exits 1; a --resume call exits 0 with a result."""
    py = tmp / "fake_claude.py"
    py.write_text(
        "import json, os, sys, time\n"
        "args = sys.argv[1:]\n"
        "sid = args[args.index('--session-id') + 1] if '--session-id' in args else args[args.index('--resume') + 1]\n"
        "store = os.environ['CLAUDE_ENGRAM_DIR']\n"
        "p = os.path.join(store, 'sessions', sid + '.json')\n"
        "os.makedirs(os.path.dirname(p), exist_ok=True)\n"
        "st = json.load(open(p)) if os.path.exists(p) else {}\n"
        "assert os.environ.get('CLAUDE_ENGRAM_AUTONOMY') == '1', 'autonomy env missing'\n"
        "assert os.environ.get('CLAUDE_CODE_AUTO_COMPACT_WINDOW') == '750000', 'window env missing'\n"
        "if '--resume' in args:\n"
        "    st.setdefault('run', {})['resumed'] = True\n"
        "    json.dump(st, open(p, 'w'))\n"
        "    print(json.dumps({'session_id': sid, 'result': 'goal met', 'num_turns': 2, 'total_cost_usd': 0.01}))\n"
        "    sys.exit(0)\n"
        "st.setdefault('run', {})['last_failure'] = {'error_type': 'rate_limit', 'error': 'limit', 'at': time.time(), 'five_hour_resets_at': time.time() + 1}\n"
        "st['run']['failures'] = [st['run']['last_failure']]\n"
        "json.dump(st, open(p, 'w'))\n"
        "print(json.dumps({'session_id': sid, 'result': 'limit', 'is_error': True}))\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    return py  # a .py --claude-bin runs under the launcher's interpreter


def test_launcher_end_to_end(tmp):
    print("launcher end to end with a fake claude (limit -> sleep -> resume -> done):")
    _clean()
    proj = tmp / "proj-launch"
    proj.mkdir(parents=True, exist_ok=True)
    store = tmp / "store-launch"
    script = _writer_script(tmp)
    log = tmp / "launch-alerts.log"
    fake = _fake_claude(tmp)
    env = dict(os.environ, CLAUDE_ENGRAM_DIR=str(store), CLAUDE_ENGRAM_RESUME_SLACK="0", CLAUDE_ENGRAM_LIVE_MINE="0")
    r = subprocess.run(
        [sys.executable, "-m", "claude_engram.run", "--goal", "done.txt contains ok", "--project", str(proj),
         "--claude-bin", str(fake), "--session-id", "11111111-2222-4333-8444-555555555555", "--max-turns", "5",
         "--alert-command", f'"{sys.executable}" "{script}" {{message}} "{log}"'],
        capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=300,
    )
    out = r.stdout
    check("launcher exits with claude's final code (0)", r.returncode == 0)
    check("first attempt exited 1 and was diagnosed as a usage limit", "claude exited 1" in out and "usage limit" in out and "resuming (1/3)" in out)
    check("the resume ended on exit 0 with the result's turns and cost", "claude exited 0" in out and "turns 2" in out and "$0.01" in out)
    state = json.loads((store / "sessions" / "11111111-2222-4333-8444-555555555555.json").read_text(encoding="utf-8"))
    check("the same session was resumed", state.get("run", {}).get("resumed") is True)
    manifests = list((proj / ".engram" / "runs").glob("*.manifest.json"))
    check("manifest written", len(manifests) == 1 and json.loads(manifests[0].read_text(encoding="utf-8"))["compaction_point"] == 750_000)
    check("run report written", "report" in out and list((proj / ".engram" / "runs").glob("*-11111111.md")))
    txt = log.read_text(encoding="utf-8") if log.exists() else ""
    check("paused and done alerts went out", "paused: usage limit" in txt and "done (exit 0)" in txt)
    _clean()


def test_source_guards():
    print("source guards:")
    inst = (ROOT / "install.py").read_text(encoding="utf-8")
    check("install registers the catch-all PreToolUse halt hook", "pre_tool_json" in inst and '"matcher": ""' in inst)
    check("install registers Notification", '"Notification"' in inst and "notification_json" in inst)
    for f in ("hook_client.py", "scorer_server.py"):
        check(f"{f} serves pre_tool_json", '"pre_tool_json"' in (ROOT / "claude_engram" / "hooks" / f).read_text(encoding="utf-8"))
    remind = (ROOT / "claude_engram" / "hooks" / "remind.py").read_text(encoding="utf-8")
    check("remind dispatches pre_tool_json and notification_json", 'hook_type == "pre_tool_json"' in remind and 'hook_type == "notification_json"' in remind)
    check("the Stop branch arms the halt and alerts", "maybe_halt(" in remind and 'kind="halt"' in remind)
    check("session start announces autonomy mode", "AUTONOMY MODE" in remind)


def main():
    from claude_engram.hooks import stall as st
    from claude_engram import alerts as al
    from claude_engram import run

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        test_halt_arming(st)
        test_alerts(al, tmp)
        test_end_to_end_hooks(tmp)
        test_launcher_units(run)
        test_dry_run(tmp)
        test_launcher_end_to_end(tmp)
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
