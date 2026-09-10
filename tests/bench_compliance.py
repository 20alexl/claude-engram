"""
Benchmark: the compliance trail (hooks/compliance.py) -- rules with
hand-written detectors matched against tool calls, and the pack's own.

What must hold:
  1. Detector shape: normalized, validated; a broken regex is refused with
     a reason and reported as BROKEN, never silently ignored.
  2. Matching: a command regex sees only shell tools; path globs see edits
     (absolute paths included); tools-only and input-regex detectors work.
  3. The pack's detectors catch the commands their rules name (recursive
     delete, hard reset, force-push, DROP, kill by image name, push, pull
     request, outbound POST) and leave ordinary reads and fetches alone.
  4. Rules in scope: every active rule, inherited ones included; archived
     entries and non-rules excluded; detector health per rule.
  5. Recording: deduped by tool_use_id; verdict from permission_mode
     (unattended / prompted / plan); subagent calls flagged; capped.
  6. The injected text names the rule, what matched, and the mode.
  7. Store: add_rule persists a detector; a similar existing rule adopts a
     detector it lacked; set_detector sets, clears, and refuses non-rules.
  8. Pack seeding: pack rules land with their detectors; a project's own
     covering rule adopts the pack detector; marker version 4.
  9. Opt-out: env and .engram/config.json.
 10. End to end through the real PreToolUse hook entry point: a matching
     command yields additionalContext before it runs, is recorded once,
     and the run report renders the section.
 11. Source guards: install registers the shell PreToolUse hook and the
     daemon serves it; the run report renders the section.

Run: venv/Scripts/python.exe tests/bench_compliance.py
"""

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


def _pm(entries):
    return {"entries": entries}


def test_shape(c):
    print("detector shape:")
    check("empty is None", c.normalize_detector({}) is None and c.normalize_detector(None) is None)
    check("note alone is None", c.normalize_detector({"note": "x"}) is None)
    d = c.normalize_detector({"tools": "Bash", "command": " rm ", "note": "n"})
    check("string tools become a list; command stripped", d == {"tools": ["Bash"], "command": "rm", "note": "n"})
    compiled, err = c.compile_detector({"tools": ["Bash"], "command": "rm (-r"})
    check("a broken regex is refused with a reason", compiled is None and "regex" in err)
    compiled, err = c.compile_detector({"paths": ["design/**"]})
    check("paths-only compiles", compiled is not None and err == "")
    compiled, err = c.compile_detector({"tools": ["Agent"]})
    check("tools-only compiles", compiled is not None and err == "")


def test_matching(c):
    print("matching:")
    cmd, _ = c.compile_detector({"tools": ["Bash", "PowerShell"], "command": r"\brm\s+-rf\b"})
    check("command regex matches a Bash call", c.call_matches(cmd, "Bash", {"command": "rm -rf build"}) is not None)
    check("...case-insensitive", c.call_matches(cmd, "Bash", {"command": "RM -RF build"}) is not None)
    check("...and a PowerShell call", c.call_matches(cmd, "PowerShell", {"command": "rm -rf build"}) is not None)
    check("...not an Edit", c.call_matches(cmd, "Edit", {"file_path": "rm -rf"}) is None)
    check("...not a different command", c.call_matches(cmd, "Bash", {"command": "ls -la"}) is None)
    anyshell, _ = c.compile_detector({"command": r"git push"})
    check("no tools list = any shell tool", c.call_matches(anyshell, "PowerShell", {"command": "git push"}) is not None)
    check("...but a command regex never sees a non-shell tool", c.call_matches(anyshell, "mcp__x__y", {"command": "git push"}) is None)
    paths, _ = c.compile_detector({"paths": ["design/**", "*.pem"]})
    check("path glob matches a relative edit", c.call_matches(paths, "Edit", {"file_path": "design/plan.md"}) is not None)
    check("path glob matches an absolute edit", c.call_matches(paths, "Write", {"file_path": "E:/ws/proj/design/plan.md"}) is not None)
    check("path glob matches a Windows path", c.call_matches(paths, "Write", {"file_path": r"E:\ws\proj\design\plan.md"}) is not None)
    check("basename glob matches", c.call_matches(paths, "Edit", {"file_path": "/etc/keys/server.pem"}) is not None)
    check("path glob leaves other files alone", c.call_matches(paths, "Edit", {"file_path": "src/app.py"}) is None)
    check("path glob ignores a Bash call", c.call_matches(paths, "Bash", {"command": "cat design/plan.md"}) is None)
    tools, _ = c.compile_detector({"tools": ["Agent", "Workflow"]})
    check("tools-only matches the tool name", c.call_matches(tools, "Workflow", {"script": "x"}) == "tool Workflow")
    check("...and nothing else", c.call_matches(tools, "Bash", {"command": "x"}) is None)
    inp, _ = c.compile_detector({"tools": ["mcp__claude_ai_Gmail__send"], "input": r"@"})
    check("input regex sees the tool input JSON", c.call_matches(inp, "mcp__claude_ai_Gmail__send", {"to": "a@b.c"}) is not None)


def test_pack_detectors(c):
    print("the pack's detectors:")
    from claude_engram import default_pack as dp

    d, err = c.compile_detector(dp.DESTRUCTIVE_DETECTOR)
    check("destructive detector compiles", d is not None and not err)
    yes = [
        "rm -rf build", "rm old.txt", "sudo rm -r /tmp/x", "git reset --hard HEAD~1", "git push --force origin main",
        "git push -f", "git clean -fdx", "git branch -D feature", "Remove-Item -Recurse -Force .\\out",
        "rmdir /s /q build", "psql -c 'DROP TABLE users'", "taskkill /IM python.exe", "pkill -f train",
        "kill -9 1234", "dd if=/dev/zero of=/dev/sda",
    ]
    no = ["ls -la", "cat file", "git status", "git rm --cached secrets.txt", "trash old.txt", "grep -rn rm .",
          "npm run build", "git push", "python -m pytest", "echo remove", "git diff HEAD", "rm --help"]
    for s in yes:
        check(f"destructive: {s!r}", c.call_matches(d, "Bash", {"command": s}) is not None)
    for s in no:
        check(f"not destructive: {s!r}", c.call_matches(d, "Bash", {"command": s}) is None)
    k, _ = c.compile_detector(dp.KILL_BY_NAME_DETECTOR)
    for s in ["taskkill /IM python.exe /F", "Stop-Process -Name node", "pkill -f train.py", "killall node"]:
        check(f"kill by name: {s!r}", c.call_matches(k, "Bash", {"command": s}) is not None)
    for s in ["taskkill /PID 1234", "kill 1234", "Stop-Process -Id 42", "ps aux | grep python"]:
        check(f"not by name: {s!r}", c.call_matches(k, "Bash", {"command": s}) is None)
    o, _ = c.compile_detector(dp.OUTBOUND_DETECTOR)
    for s in ["git push", "git push origin main", "gh pr create --fill", "gh pr comment 12 --body x",
              "npm publish", "curl -X POST https://api.x/y -d '{}'", "docker push img"]:
        check(f"outbound: {s!r}", c.call_matches(o, "Bash", {"command": s}) is not None)
    for s in ["git fetch", "git pull", "gh pr view 12", "gh pr list", "curl https://x/y", "git commit -m x", "git log"]:
        check(f"not outbound: {s!r}", c.call_matches(o, "Bash", {"command": s}) is None)


def test_rules_in_scope(c):
    print("rules in scope:")
    pm = _pm([
        {"id": "r1", "category": "rule", "content": "No rm", "detector": {"tools": ["Bash"], "command": r"\brm\b"}},
        {"id": "r2", "category": "rule", "content": "Be direct"},
        {"id": "r3", "category": "rule", "content": "Broken", "detector": {"command": "("}},
        {"id": "r4", "category": "rule", "content": "Archived", "archived_at": 1.0, "detector": {"command": "x"}},
        {"id": "m1", "category": "mistake", "content": "not a rule", "detector": {"command": "x"}},
        {"id": "r1", "category": "rule", "content": "No rm (inherited twice)", "detector": {"command": "rm"}},
    ])
    rules = c.rules_with_detectors(pm)
    ids = [r["id"] for r in rules]
    check("active rules only, once each", ids == ["r1", "r2", "r3"])
    by = {r["id"]: r for r in rules}
    check("a detector compiles", by["r1"]["compiled"] is not None and by["r1"]["error"] == "")
    check("an advisory rule has no detector", by["r2"]["detector"] is None and by["r2"]["error"] == "")
    check("a broken detector is reported, not dropped", by["r3"]["compiled"] is None and "regex" in by["r3"]["error"])
    hits = c.match_call(rules, "Bash", {"command": "rm -rf x"})
    check("match_call returns the hit with rule text", len(hits) == 1 and hits[0]["rule_id"] == "r1" and "rm" in hits[0]["what"])
    check("no hit for a clean call", c.match_call(rules, "Bash", {"command": "ls"}) == [])


def test_recording(c):
    print("recording:")
    pm = _pm([
        {"id": "r1", "category": "rule", "content": "No rm", "detector": {"tools": ["Bash"], "command": r"\brm\b", "note": "rm"}},
        {"id": "r3", "category": "rule", "content": "Broken", "detector": {"command": "("}},
        {"id": "r2", "category": "rule", "content": "Advisory"},
    ])
    rules = c.rules_with_detectors(pm)
    state = {}
    hits = c.match_call(rules, "Bash", {"command": "rm -rf x"})
    new = c.record(state, rules, hits, "Bash", {"command": "rm -rf x"}, tool_use_id="t1", turn=4, permission_mode="bypassPermissions")
    check("a match is recorded with the turn", len(new) == 1 and new[0]["turn"] == 4)
    check("bypass mode is unattended", new[0]["verdict"] == "unattended")
    again = c.record(state, rules, hits, "Bash", {"command": "rm -rf x"}, tool_use_id="t1", turn=4, permission_mode="bypassPermissions")
    check("the same tool_use_id is not recorded twice", again == [] and len(state["compliance"]["matches"]) == 1)
    new2 = c.record(state, rules, hits, "Bash", {"command": "rm -rf x"}, tool_use_id="t2", turn=5, permission_mode="default")
    check("default mode is prompted", new2[0]["verdict"] == "prompted")
    new3 = c.record(state, rules, hits, "Bash", {"command": "rm -rf x"}, tool_use_id="t3", turn=6, permission_mode="plan")
    check("plan mode is plan", new3[0]["verdict"] == "plan")
    new4 = c.record(state, rules, hits, "Bash", {"command": "rm -rf x"}, tool_use_id="t4", turn=6, permission_mode="auto", agent_id="a1")
    check("auto mode is unattended and a subagent call is flagged", new4[0]["verdict"] == "unattended" and new4[0]["subagent"])
    h = state["compliance"]["health"]
    check("health: hits counted on the matching rule", h["r1"]["hits"] == 4 and h["r1"]["ok"])
    check("health: the broken detector is marked", h["r3"]["ok"] is False and "regex" in h["r3"]["error"])
    check("health: advisory rules have no entry", "r2" not in h)
    print("summary:")
    s = c.summary(state, pm)
    check("counts", s["with_detector"] == 2 and s["advisory"] == 1 and s["broken"] == 1)
    check("verdict tallies", s["unattended"] == 2 and s["prompted"] == 1 and len(s["matches"]) == 4)
    for i in range(c.MATCHES_KEEP + 20):
        c.record(state, rules, hits, "Bash", {"command": "rm x"}, tool_use_id=f"x{i}", turn=7, permission_mode="default")
    check("matches are capped", len(state["compliance"]["matches"]) == c.MATCHES_KEEP)
    print("injected text:")
    t = c.rule_text(hits, "bypassPermissions")
    check("names the rule and what matched", "[r1] No rm" in t and "command ~" in t)
    check("unattended wording", "no person approves" in t)
    t2 = c.rule_text(hits, "default")
    check("prompted wording", "permission prompt" in t2)
    check("nothing to inject for no hits", c.rule_text([], "default") == "")


def test_store(tmp):
    print("store:")
    os.environ["CLAUDE_ENGRAM_DIR"] = str(tmp / "store")
    from claude_engram.tools.memory import MemoryStore

    proj = str(tmp / "proj-store")
    Path(proj).mkdir(parents=True, exist_ok=True)
    s = MemoryStore(str(tmp / "store"))
    s.remember_project(proj, summary="x")
    ok, msg = s.add_rule(proj, "Never push without asking", reason="bench", detector={"command": r"git push"})
    check("add_rule with a detector", ok)
    rid = msg.split("id=")[-1].strip()
    fresh = MemoryStore(str(tmp / "store"))
    r = next(x for x in fresh.get_rules(proj) if x.id == rid)
    check("the detector persisted", r.detector == {"command": r"git push"})
    ok, msg = s.add_rule(proj, "Never push without asking", reason="bench")
    check("a duplicate without a detector is still refused", not ok)
    ok2, msg2 = s.add_rule(proj, "Never force-push to main", reason="bench")
    check("a plain rule lands without a detector", ok2)
    rid2 = msg2.split("id=")[-1].strip()
    ok3, msg3 = s.add_rule(proj, "Never force-push to main", reason="bench", detector={"command": "--force"})
    check("a similar rule adopts the detector it lacked", (not ok3) and "detector attached" in msg3)
    r2 = next(x for x in MemoryStore(str(tmp / "store")).get_rules(proj) if x.id == rid2)
    check("...and it persisted", r2.detector == {"command": "--force"})
    ok, _ = s.set_detector(proj, rid2, {"command": "push --force", "note": "n"})
    check("set_detector replaces", ok and (next(x for x in s.get_rules(proj) if x.id == rid2).detector or {}).get("note") == "n")
    ok, _ = s.set_detector(proj, rid2, None)
    check("set_detector clears", ok and next(x for x in s.get_rules(proj) if x.id == rid2).detector is None)
    s.remember_project(proj, summary="x")
    from claude_engram.tools.memory import MemoryEntry

    p = s.get_project(proj)
    assert p is not None
    p.entries.append(MemoryEntry(id="note1", content="a note", category="note"))
    ok, msg = s.set_detector(proj, "note1", {"command": "x"})
    check("set_detector refuses a non-rule", not ok and "not a rule" in msg)
    ok, msg = s.set_detector(proj, "nope", {"command": "x"})
    check("set_detector reports an unknown id", not ok and "not found" in msg)


def test_pack_seed(tmp):
    print("pack seeding:")
    os.environ["CLAUDE_ENGRAM_DIR"] = str(tmp / "store2")
    from claude_engram import default_pack as dp
    from claude_engram.tools.memory import MemoryStore

    proj = tmp / "proj-seed"
    (proj / ".git").mkdir(parents=True, exist_ok=True)
    (proj / "CLAUDE.md").write_text("# x\n", encoding="utf-8")
    s = MemoryStore(str(tmp / "store2"))
    s.remember_project(str(proj), summary="seed")
    ok, msg = s.add_rule(str(proj), "Don't run destructive commands without asking. trash > rm.", reason="mine")
    check("the project has its own destructive rule, no detector", ok)
    own_id = msg.split("id=")[-1].strip()
    rep = dp.seed_rules(str(proj))
    check("seed ran", not rep.get("already_seeded"))
    rules = {r.id: r for r in MemoryStore(str(tmp / "store2")).get_rules(str(proj))}
    check("the own rule adopted the pack detector", (rules[own_id].detector or {}).get("note", "").startswith("destructive"))
    check("...and it is listed as attached", own_id in rep.get("detectors_attached", []))
    kill = [r for r in rules.values() if "image name" in r.content]
    check("the pack's kill-by-name rule landed with its detector", kill and kill[0].detector is not None)
    outbound = [r for r in rules.values() if "leaves the machine" in r.content]
    check("the workflow outbound rule landed with its detector", outbound and outbound[0].detector is not None)
    plain = [r for r in rules.values() if "Search first" in r.content]
    check("a rule with nothing to watch has no detector", plain and plain[0].detector is None)
    mp = dp._marker_path(str(proj))
    marker = json.loads(mp.read_text(encoding="utf-8")) if mp and mp.is_file() else {}
    check("marker at the current pack version (>= 4, detectors)", marker.get("version") == dp.PACK_VERSION >= 4)
    rep2 = dp.seed_rules(str(proj))
    check("a second seed is a no-op", rep2.get("already_seeded") is True)


def test_opt_out(c, tmp):
    print("opt-out:")
    proj = tmp / "proj-opt"
    (proj / ".engram").mkdir(parents=True, exist_ok=True)
    os.environ.pop("CLAUDE_ENGRAM_COMPLIANCE", None)
    check("on by default", c.enabled(str(proj)))
    (proj / ".engram" / "config.json").write_text(json.dumps({"compliance": False}), encoding="utf-8")
    check("config turns it off", not c.enabled(str(proj)))
    os.environ["CLAUDE_ENGRAM_COMPLIANCE"] = "on"
    check("env overrides config", c.enabled(str(proj)))
    os.environ["CLAUDE_ENGRAM_COMPLIANCE"] = "off"
    check("env off", not c.enabled(str(proj)))
    os.environ.pop("CLAUDE_ENGRAM_COMPLIANCE", None)


def _hook(hook_type, payload, env):
    return subprocess.run(
        [sys.executable, "-m", "claude_engram.hooks.remind", hook_type],
        input=json.dumps(payload), capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=120,
    )


def test_end_to_end(tmp):
    print("end to end through the PreToolUse hook:")
    store = tmp / "store-e2e"
    proj = tmp / "proj-e2e"
    proj.mkdir(parents=True, exist_ok=True)
    os.environ["CLAUDE_ENGRAM_DIR"] = str(store)
    from claude_engram.tools.memory import MemoryStore

    s = MemoryStore(str(store))
    s.remember_project(str(proj), summary="e2e")
    ok, msg = s.add_rule(str(proj), "No recursive deletes without asking", reason="bench",
                         detector={"tools": ["Bash"], "command": r"\brm\s+-rf\b", "note": "rm -rf"})
    check("rule with detector seeded", ok)
    rid = msg.split("id=")[-1].strip()
    sid = "s-compliance-e2e"
    env = dict(os.environ, CLAUDE_ENGRAM_DIR=str(store), CLAUDE_PROJECT_DIR=str(proj), CLAUDE_ENGRAM_LIVE_MINE="0")
    base = {"session_id": sid, "cwd": str(proj), "hook_event_name": "PreToolUse", "tool_name": "Bash", "permission_mode": "bypassPermissions"}
    r = _hook("pre_bash_json", dict(base, tool_use_id="tu1", tool_input={"command": "rm -rf build"}), env)
    check("hook exits 0", r.returncode == 0)
    check("additionalContext carries the rule before the command runs", "engram-rule" in r.stdout and rid in r.stdout and "no person approves" in r.stdout)
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1])
        check("PreToolUse output shape", out["hookSpecificOutput"]["hookEventName"] == "PreToolUse" and "permissionDecision" not in out["hookSpecificOutput"])
    except Exception:
        check("PreToolUse output shape", False)
    r = _hook("pre_bash_json", dict(base, tool_use_id="tu2", tool_input={"command": "cat build/log.txt"}), env)
    check("a clean command injects nothing", "engram-rule" not in r.stdout)
    r = _hook("pre_bash_json", dict(base, tool_use_id="tu1", tool_input={"command": "rm -rf build"}), env)
    state = json.loads((store / "sessions" / f"{sid}.json").read_text(encoding="utf-8"))
    matches = state.get("compliance", {}).get("matches", [])
    check("recorded once per tool_use_id", len(matches) == 1 and matches[0]["verdict"] == "unattended")
    batch = {"session_id": sid, "cwd": str(proj), "hook_event_name": "PostToolBatch", "permission_mode": "bypassPermissions",
             "tool_calls": [{"tool_name": "Bash", "tool_input": {"command": "rm -rf build"}, "tool_use_id": "tu1", "tool_response": {"stdout": ""}},
                            {"tool_name": "Bash", "tool_input": {"command": "rm -rf other"}, "tool_use_id": "tu9", "tool_response": {"stdout": ""}}]}
    r = _hook("post_batch_json", batch, env)
    state = json.loads((store / "sessions" / f"{sid}.json").read_text(encoding="utf-8"))
    matches = state.get("compliance", {}).get("matches", [])
    check("the batch hook dedupes the PreToolUse match and records the one it had not seen", [m["tool_use_id"] for m in matches] == ["tu1", "tu9"])
    sub = dict(base, tool_use_id="tu3", agent_id="agent-1", tool_input={"command": "rm -rf sub"})
    r = _hook("pre_bash_json", sub, env)
    check("a subagent's call is recorded but not nudged", r.stdout.strip() == "")
    state = json.loads((store / "sessions" / f"{sid}.json").read_text(encoding="utf-8"))
    check("...flagged as a subagent's", any(m.get("subagent") for m in state["compliance"]["matches"]))
    print("run report:")
    from claude_engram import run_report as rr

    rep = rr.collect(sid, str(proj), state)
    check("compliance collected", isinstance(rep["compliance"], dict) and rep["compliance"]["with_detector"] == 1)
    md = rr.render_md(rep)
    check("section rendered", "## Rules compliance (1 with a detector, 0 advisory, 0 broken)" in md)
    check("matches table with the verdict", "| unattended |" in md and "rm -rf build" in md)
    check("nothing left under not measured for compliance", "rules compliance" not in md.split("## Not measured")[-1])
    os.environ.pop("CLAUDE_ENGRAM_DIR", None)


def test_unattended_deny(c, tmp):
    print("unattended = deny (autonomy mode only):")
    os.environ.pop("CLAUDE_ENGRAM_AUTONOMY", None)
    d = c.normalize_detector({"command": "x", "unattended": "DENY"})
    check("unattended is normalized", d is not None and d["unattended"] == "deny")
    check("an unknown value is dropped", "unattended" not in (c.normalize_detector({"command": "x", "unattended": "maybe"}) or {}))
    compiled, _ = c.compile_detector({"command": "x"})
    check("default policy is record", compiled is not None and compiled["unattended"] == "record")
    from claude_engram import default_pack as dp

    check("the pack's ask-first detectors deny unattended", all(x["unattended"] == "deny" for x in (dp.DESTRUCTIVE_DETECTOR, dp.KILL_BY_NAME_DETECTOR, dp.OUTBOUND_DETECTOR)))
    pm = _pm([{"id": "r1", "category": "rule", "content": "No rm", "detector": {"tools": ["Bash"], "command": r"\brm\b", "unattended": "deny"}},
              {"id": "r2", "category": "rule", "content": "Log pushes", "detector": {"tools": ["Bash"], "command": r"git push"}}])
    rules = c.rules_with_detectors(pm)
    hits = c.match_call(rules, "Bash", {"command": "rm -rf x && git push"})
    check("hits carry the policy", {h["rule_id"]: h["unattended"] for h in hits} == {"r1": "deny", "r2": "record"})
    check("outside autonomy mode nothing is denied, even in bypass mode", c.should_deny(hits, "bypassPermissions") == [])
    os.environ["CLAUDE_ENGRAM_AUTONOMY"] = "1"
    denied = c.should_deny(hits, "bypassPermissions")
    check("in autonomy mode the deny-marked rule refuses, the record-marked one does not", [h["rule_id"] for h in denied] == ["r1"])
    t = c.deny_text(denied)
    check("the reason names the rule and says what to do instead", "refused by rule [r1]" in t and "checkpoint_save" in t and "PushNotification" in t and "Do not work around it" in t)
    os.environ.pop("CLAUDE_ENGRAM_AUTONOMY", None)
    print("seed upgrades an older pack-shaped detector:")
    os.environ["CLAUDE_ENGRAM_DIR"] = str(tmp / "store-upgrade")
    from claude_engram.tools.memory import MemoryStore

    proj = tmp / "proj-upgrade"
    (proj / ".git").mkdir(parents=True, exist_ok=True)
    s = MemoryStore(str(tmp / "store-upgrade"))
    s.remember_project(str(proj), summary="u")
    old = {k: v for k, v in dp.DESTRUCTIVE_DETECTOR.items() if k != "unattended"}
    ok, msg = s.add_rule(str(proj), "Don't run destructive commands without asking. trash > rm.", reason="mine", detector=old)
    rid = msg.split("id=")[-1].strip()
    dp.seed_rules(str(proj))
    r = next(x for x in MemoryStore(str(tmp / "store-upgrade")).get_rules(str(proj)) if x.id == rid)
    check("the existing detector gained unattended=deny and kept its regex", (r.detector or {}).get("unattended") == "deny" and (r.detector or {}).get("command") == old["command"])
    os.environ.pop("CLAUDE_ENGRAM_DIR", None)
    print("end to end: the shell hook refuses in autonomy mode:")
    store = tmp / "store-deny"
    projd = tmp / "proj-deny"
    projd.mkdir(parents=True, exist_ok=True)
    os.environ["CLAUDE_ENGRAM_DIR"] = str(store)
    s2 = MemoryStore(str(store))
    s2.remember_project(str(projd), summary="d")
    s2.add_rule(str(projd), "Never push without asking", reason="bench", detector={"tools": ["Bash"], "command": r"\bgit\s+push\b", "unattended": "deny", "note": "push"})
    sid = "s-deny-e2e"
    base = {"session_id": sid, "cwd": str(projd), "hook_event_name": "PreToolUse", "tool_name": "Bash", "permission_mode": "bypassPermissions", "tool_input": {"command": "git push origin main"}}
    env = dict(os.environ, CLAUDE_ENGRAM_DIR=str(store), CLAUDE_PROJECT_DIR=str(projd), CLAUDE_ENGRAM_LIVE_MINE="0")
    r = _hook("pre_bash_json", dict(base, tool_use_id="d1"), env)
    check("attended (no autonomy): injected, not refused", "engram-rule" in r.stdout and "permissionDecision" not in r.stdout)
    env_a = dict(env, CLAUDE_ENGRAM_AUTONOMY="1")
    r = _hook("pre_bash_json", dict(base, tool_use_id="d2"), env_a)
    out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    hso = out.get("hookSpecificOutput", {})
    check("autonomy: the push is refused with the rule as the reason", hso.get("permissionDecision") == "deny" and "refused by rule" in hso.get("permissionDecisionReason", ""))
    st = json.loads((store / "sessions" / f"{sid}.json").read_text(encoding="utf-8"))
    verdicts = {m["tool_use_id"]: m["verdict"] for m in st["compliance"]["matches"]}
    check("the trail records the permission-mode verdict for the attended call and denied for the refused one", verdicts.get("d1") == "unattended" and verdicts.get("d2") == "denied")
    r = _hook("pre_bash_json", dict(base, tool_use_id="d3", tool_input={"command": "git status"}), env_a)
    check("a clean command in autonomy mode is untouched", r.stdout.strip() == "")
    os.environ.pop("CLAUDE_ENGRAM_DIR", None)


def test_source_guards():
    print("source guards:")
    inst = (ROOT / "install.py").read_text(encoding="utf-8")
    check("install registers PreToolUse Bash|PowerShell", '"Bash|PowerShell"' in inst and "pre_bash_json" in inst)
    for f in ("hook_client.py", "scorer_server.py"):
        check(f"{f} serves pre_bash_json", '"pre_bash_json"' in (ROOT / "claude_engram" / "hooks" / f).read_text(encoding="utf-8"))
    remind = (ROOT / "claude_engram" / "hooks" / "remind.py").read_text(encoding="utf-8")
    check("remind dispatches pre_bash_json", 'hook_type == "pre_bash_json"' in remind and "_hook_pre_bash(" in remind)
    check("the batch hook records compliance too", remind.count("_compliance_check(") >= 2)
    td = (ROOT / "claude_engram" / "tool_definitions_v2.py").read_text(encoding="utf-8")
    check("memory tool exposes set_detector and the detector param", '"set_detector"' in td and '"detector": {' in td)
    rr = (ROOT / "claude_engram" / "run_report.py").read_text(encoding="utf-8")
    check("the run report renders the section", "## Rules compliance" in rr)


def main():
    from claude_engram.hooks import compliance as c

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        test_shape(c)
        test_matching(c)
        test_pack_detectors(c)
        test_rules_in_scope(c)
        test_recording(c)
        test_store(tmp)
        test_pack_seed(tmp)
        test_opt_out(c, tmp)
        test_end_to_end(tmp)
        test_unattended_deny(c, tmp)
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
