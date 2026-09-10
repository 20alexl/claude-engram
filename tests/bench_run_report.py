"""
Benchmark: the run report (claude_engram/run_report.py).

One auditable artifact per session, assembled only from what hooks captured
and what the transcript says. Nothing self-reported by the model.

What must hold:
  1. collect() reads the per-session state (files + edit counts, tests,
     prompts, the run block) and the transcript (model, branch, timestamps,
     /goal text, tool errors, compact_boundary sizes) into one dict.
  2. Compactions come from the transcript's compactMetadata (verified real
     shape) and are joined in order with what PostCompact restored.
  3. This session's checkpoints are listed, deliberate vs auto, by session_id;
     another session's entries are not.
  4. Errors are grouped by normalized signature, recurrences counted, and
     matched against the miner's known recurring errors.
  5. What is not measured is listed, never silently dropped.
  6. render_md() produces the sections; write_report() writes .md + .json
     under <project>/.engram/runs/<date>-<session8>.
  7. substantial() gates the automatic write.
  8. Source guards: SessionEnd writes it, PostCompact pins the restored entry,
     Stop counts turns, manual ring entries carry session_id, the MCP op exists.

Run: venv/Scripts/python.exe tests/bench_run_report.py
"""

import json
import os
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


def _msg(mtype, ts, **kw):
    d = {"type": mtype, "timestamp": ts, "sessionId": kw.pop("sid", "S1"), "gitBranch": "feat/x"}
    d.update(kw)
    return d


def _write_transcript(path: Path, sid: str):
    t0 = "2026-09-09T10:00:00Z"
    lines = [
        _msg("user", t0, sid=sid, message={"role": "user", "content": "<command-name>/goal</command-name>\n<command-message>goal</command-message>\n<command-args>make all benches pass or stop after 20 turns</command-args>"}),
        # The verified shape from a real /goal run (2.1.267): sentinel on set,
        # then one goal_status attachment per evaluator verdict.
        {"type": "attachment", "timestamp": "2026-09-09T10:00:01Z", "sessionId": sid, "attachment": {"type": "goal_status", "met": False, "sentinel": True, "condition": "make all benches pass or stop after 20 turns"}},
        {"type": "attachment", "timestamp": "2026-09-09T10:30:00Z", "sessionId": sid, "attachment": {"type": "goal_status", "met": False, "condition": "make all benches pass or stop after 20 turns", "reason": "Two benches still fail.", "iterations": 1, "durationMs": 4000, "tokens": 900}},
        {"type": "attachment", "timestamp": "2026-09-09T11:58:00Z", "sessionId": sid, "attachment": {"type": "goal_status", "met": True, "condition": "make all benches pass or stop after 20 turns", "reason": "All benches pass in the transcript.", "iterations": 2, "durationMs": 5000, "tokens": 1200}},
        _msg("user", "2026-09-09T10:00:05Z", sid=sid, message={"role": "user", "content": "start"}),
        _msg("assistant", "2026-09-09T10:00:10Z", sid=sid, message={"role": "assistant", "model": "claude-fable-5-1", "content": [{"type": "text", "text": "working"}, {"type": "tool_use", "id": "e1", "name": "Edit", "input": {"file_path": "E:\\ws\\proj\\a.py"}}, {"type": "tool_use", "id": "e2", "name": "Write", "input": {"file_path": "E:/ws/proj/c.py"}}]}),
        _msg("assistant", "2026-09-09T10:00:12Z", sid=sid, message={"role": "assistant", "model": "<synthetic>", "content": [{"type": "text", "text": "injected"}]}),
        _msg("assistant", "2026-09-09T10:00:14Z", sid=sid, message={"role": "assistant", "model": "claude-fable-5-1", "content": [{"type": "tool_use", "id": "c1", "name": "CronCreate", "input": {"cron": "*/2 * * * *", "prompt": "append", "recurring": True}}, {"type": "tool_use", "id": "w1", "name": "ScheduleWakeup", "input": {"delaySeconds": 120, "prompt": "x"}}, {"type": "tool_use", "id": "w2", "name": "ScheduleWakeup", "input": {"stop": True}}, {"type": "tool_use", "id": "c2", "name": "CronDelete", "input": {"id": "c1"}}]}),
        _msg("user", "2026-09-09T10:01:00Z", sid=sid, message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "ModuleNotFoundError: No module named 'foo'"}]}),
        _msg("user", "2026-09-09T10:02:00Z", sid=sid, message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t2", "is_error": True, "content": "ModuleNotFoundError: No module named 'foo'"}]}),
        _msg("user", "2026-09-09T10:03:00Z", sid=sid, toolUseResult="Error: File does not exist.", message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t3", "is_error": True, "content": "Error: File does not exist."}]}),
        {"type": "system", "subtype": "compact_boundary", "timestamp": "2026-09-09T11:00:00Z", "sessionId": sid, "content": "Conversation compacted", "compactMetadata": {"trigger": "auto", "preTokens": 489107, "postTokens": 28251, "cumulativeDroppedTokens": 460856, "durationMs": 120559}},
        _msg("assistant", "2026-09-09T11:00:30Z", sid=sid, message={"role": "assistant", "model": "claude-fable-5-1", "content": [{"type": "text", "text": "continuing"}]}),
        _msg("user", "2026-09-09T11:30:00Z", sid="OTHER", message={"role": "user", "content": "not this session"}),
        _msg("assistant", "2026-09-09T12:00:00Z", sid=sid, message={"role": "assistant", "model": "claude-fable-5-1", "content": [{"type": "text", "text": "Phase 1 done."}]}),
    ]
    path.write_text("\n".join(json.dumps(l) for l in lines) + "\n", encoding="utf-8")


def main():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        os.environ["CLAUDE_ENGRAM_DIR"] = str(tmp)
        from claude_engram.hooks import remind
        from claude_engram.hooks import context_pressure as cp
        from claude_engram import run_report as rr
        from claude_engram import handoff_store as hs

        sid = "sess-1234-abcd"
        project = tmp / "proj"
        project.mkdir()
        transcript = tmp / "transcript.jsonl"
        _write_transcript(transcript, sid)

        # Ring: one manual + one auto for this session, one manual for another.
        ring_dir = tmp / "projects" / "hash1"
        remind._project_hash_dir = lambda p: ring_dir
        remind._global_handoff_dir = lambda: tmp / "checkpoints"
        remind._handoff_candidate_dirs = lambda p="": [ring_dir, tmp / "checkpoints"]
        hs.write_handoff({"kind": "manual", "created": time.time() - 3000, "summary": "step 1 banked", "task_id": "task_1", "session_id": sid, "next_steps": ["x"]}, [ring_dir])
        hs.write_handoff({"kind": "auto", "created": time.time() - 100, "summary": "Session stopped. 2 files edited.", "session_id": sid, "files_in_progress": ["a.py"], "decisions": ["d"]}, [ring_dir])
        hs.write_handoff({"kind": "manual", "created": time.time() - 50, "summary": "someone else's", "task_id": "task_9", "session_id": "OTHER"}, [ring_dir])
        (ring_dir / "patterns.json").write_text(json.dumps({"recurring_errors": [{"error_type": "ModuleNotFoundError", "session_count": 4}]}), encoding="utf-8")

        started = time.time() - 7200
        state: dict = {
            "last_session_start": started,
            "prompts_this_session": 3,
            "files_edited_this_session": ["E:/ws/proj/a.py", "E:/ws/proj/b.py"],
            "loop": {
                "edit_counts": {"E:/ws/proj/a.py": 4, "e:/ws/proj/B.py": 1},
                "test_results": [
                    {"timestamp": started + 10, "passed": False},
                    {"timestamp": started + 500, "passed": True},
                ],
            },
            "test_runs_this_session": 2,
            "last_test_passed": True,
            "run": {"start_commit": "abc1234", "permission_mode": "auto", "transcript_path": str(transcript)},
        }
        cp.note_stop(state, "Working.")
        cp.note_stop(state, "More.")
        cp.note_compaction(state)
        cp.note_restored(state, {"kind": "manual", "task_id": "task_1", "summary": "step 1 banked"})
        # The hook record sits 20 s after the transcript's boundary (real
        # ordering: the boundary is written, then PostCompact runs).
        state["pressure"]["compactions"][0]["at"] = rr._parse_iso("2026-09-09T11:00:20Z")
        cp.record_statusline({"session_id": sid, "model": {"id": "claude-fable-5-1", "display_name": "Fable 5.1"}, "context_window": {"total_input_tokens": 300000, "context_window_size": 1000000}, "cost": {"total_cost_usd": 4.2}})

        print("collect():")
        r = rr.collect(sid, str(project), state)
        check("run_id = date + session8", r["run_id"].endswith("-sess-123") and r["run_id"][:4] == "2026")
        check("goal text from the goal_status sentinel", r["goal_text"] == "make all benches pass or stop after 20 turns" and r["goal_set_at"] == "2026-09-09T10:00:01Z")
        vs = r["goal_verdicts"]
        check("two evaluator verdicts parsed (sentinel excluded)", len(vs) == 2 and vs[0]["met"] is False and vs[1]["met"] is True)
        check("verdict carries reason, iterations, duration, tokens", vs[1]["reason"].startswith("All benches") and vs[1]["iterations"] == 2 and vs[1]["duration_ms"] == 5000 and vs[1]["tokens"] == 1200)
        check("goal outcome = met", r["goal_outcome"] == "met")
        check("verdicts are no longer listed as not measured", not any("verdict" in n for n in r["not_measured"]))
        check("model from the transcript", r["model"] == "claude-fable-5-1" and r["models"] == ["claude-fable-5-1"])
        check("branch: transcript's when the project has no git", r["branch"] == "feat/x")
        check("permission mode + start commit from the run block", r["permission_mode"] == "auto" and r["start_commit"] == "abc1234")
        check("turns from Stop count", r["turns"] == 2)
        check("prompts from state", r["prompts"] == 3)
        check("wall time from session start", 7100 <= r["wall_seconds"] <= 7300)
        check("final tokens + cost from the mirror", r["tokens"]["final_input"] == 300000 and r["tokens"]["cost_usd"] == 4.2)
        c = r["compactions"]
        check("one compaction from compact_boundary", len(c) == 1 and c[0]["trigger"] == "auto")
        check("compaction sizes from compactMetadata", c[0]["pre_tokens"] == 489107 and c[0]["post_tokens"] == 28251)
        check("compaction joined with what PostCompact restored", (c[0].get("restored") or {}).get("task_id") == "task_1")
        f = r["files"]
        check("files = transcript edits UNION hook state (a, b from state; c only in transcript)", sorted(x["path"][-4:] for x in f) == ["a.py", "b.py", "c.py"])
        check("per-file counts: hook counter wins when larger, case-insensitive join", {x["path"][-4:]: x["edits"] for x in f} == {"a.py": 4, "b.py": 1, "c.py": 1})
        check("files sorted by edits desc", f[0]["path"].endswith("a.py"))
        check("<synthetic> is not a model", "<synthetic>" not in r["models"])
        check("scheduled work counted (cron created/deleted, wakeups excluding stop)", r["scheduled"] == {"cron_created": 1, "cron_deleted": 1, "wakeups": 1})
        check("scheduled line rendered", "**Scheduled work:** cron jobs created 1, deleted 1, self-paced wakeups 1" in rr.render_md(r))
        t = r["tests"]
        check("tests: runs, first fail, last pass, failing runs", t["runs"] == 2 and t["first"] is False and t["last"] is True and t["failures"] == 1)
        e = r["errors"]
        check("errors counted from is_error blocks + error toolUseResult", e["count"] == 3)
        check("errors grouped: 2 distinct, 1 recurring", e["distinct"] == 2 and e["recurring"] == 1)
        top = e["top"][0]
        check("recurring error on top with count 2", top["count"] == 2 and "ModuleNotFoundError" in top["text"])
        check("known-before matched against patterns.json", top["known_before"] is True)
        check("unknown error flagged known_before=False", e["top"][1]["known_before"] is False)
        cps = r["checkpoints"]
        # Autos contend only for the latest pointer (0.8.5), so the per-turn
        # auto is not retained once a manual promotes over it; the deliberate
        # one is the record. Another session's entry must never appear.
        check("this session's deliberate checkpoint listed", any(x["task_id"] == "task_1" and x["kind"] == "manual" for x in cps))
        check("another session's checkpoint excluded", all(x["task_id"] != "task_9" for x in cps))
        check("deliberate count", r["checkpoint_counts"]["deliberate"] == 1)
        check("stalls and compliance measured from state; no phase left under not measured", isinstance(r["stalls"], dict) and isinstance(r["compliance"], dict) and not [n for n in r["not_measured"] if "Phase" in n])

        print("render + write:")
        md = rr.render_md(r)
        for sect in ("# Run ", "## Compactions (1)", "## Files touched (3)", "## Tests", "## Errors (3;", "## Checkpoints (1 deliberate,", "## Not measured"):
            check(f"section {sect!r}", sect in md)
        check("goal line rendered with outcome", "**Goal:** make all benches pass" in md and "**met**" in md)
        check("goal section with the verdict table", "## Goal (2 evaluator verdicts)" in md and "| yes | 2 | All benches pass" in md)
        check("compaction row shows sizes and restore", "489K → 28K" in md and "manual task_1" in md)
        p = rr.write_report(sid, str(project), state)
        check("write_report returns the .md path", p is not None and p.suffix == ".md")
        check("written under <project>/.engram/runs/", p is not None and p.parent == project / ".engram" / "runs")
        js = p.with_suffix(".json") if p else None
        check(".json sibling written and parses", js is not None and js.is_file() and json.loads(js.read_text(encoding="utf-8"))["schema"] == rr.SCHEMA)
        check("rewrite is idempotent (same path)", rr.write_report(sid, str(project), state) == p)

        print("transcript lookup and the time join:")
        # A session started from a workspace root lives under THAT projects
        # dir; find it by session id, not by project.
        from claude_engram.mining import jsonl_reader as jr

        fake_projects = tmp / "claude_projects"
        (fake_projects / "E--workspace").mkdir(parents=True)
        (fake_projects / "E--workspace" / f"{sid}.jsonl").write_bytes(transcript.read_bytes())
        orig_root = jr._get_claude_projects_dir
        jr._get_claude_projects_dir = lambda: fake_projects
        try:
            found = rr.find_transcript(sid, str(tmp / "elsewhere"), "")
            check("transcript found by session id under any projects dir", found is not None and found.name == f"{sid}.jsonl")
            check("hook-recorded path wins when present", rr.find_transcript(sid, str(project), str(transcript)) == transcript)
        finally:
            jr._get_claude_projects_dir = orig_root
        # Join by time: a hook record 2 minutes from the transcript boundary
        # attaches; one an hour away does not, whatever the order.
        st2: dict = {
            "run": {"transcript_path": str(transcript), "started_at": started},
            "pressure": {
                "compactions": [
                    {"at": rr._parse_iso("2026-09-09T09:00:00Z"), "restored": {"kind": "auto", "task_id": "far"}},
                    {"at": rr._parse_iso("2026-09-09T11:02:00Z"), "restored": {"kind": "manual", "task_id": "near"}},
                ]
            },
        }
        r3 = rr.collect(sid, str(project), st2)
        check("compaction joined to the NEAREST hook record by time", (r3["compactions"][0].get("restored") or {}).get("task_id") == "near")
        check("run.started_at beats last_session_start", r3["started_at"] == rr._iso(started))

        print("compaction-triggered SessionStart keeps the session's accumulators:")
        remind._session_id = "s-cont"
        remind.save_state({"files_edited_this_session": ["a.py", "b.py"], "prompts_this_session": 7, "run": {"started_at": 1.0, "start_commit": "abc"}})
        remind.mark_session_started(str(project), source="compact")
        st3 = remind.load_state()
        check("files kept across compaction", st3.get("files_edited_this_session") == ["a.py", "b.py"])
        check("prompt count kept across compaction", st3.get("prompts_this_session") == 7)
        check("run block kept (started_at, start_commit)", st3["run"]["started_at"] == 1.0 and st3["run"]["start_commit"] == "abc")
        remind.mark_session_started(str(project), source="resume")
        check("resume keeps them too (state is per session id)", remind.load_state().get("files_edited_this_session") == ["a.py", "b.py"])
        remind.mark_session_started(str(project), source="startup")
        check("a fresh startup still resets", remind.load_state().get("files_edited_this_session") == [])
        remind._session_id = sid

        print("no transcript, no mirror:")
        bare_state: dict = {"last_session_start": time.time() - 10, "files_edited_this_session": ["x.py"]}
        r2 = rr.collect("nosess", str(project), bare_state)
        check("still collects", r2["files"][0]["path"] == "x.py")
        check("names the missing sources", any("transcript" in n for n in r2["not_measured"]) and any("mirror" in n for n in r2["not_measured"]))
        check("no goal -> empty goal fields", r2["goal_text"] is None and r2["goal_verdicts"] == [] and r2["goal_outcome"] == "")
        # A goal set but never judged (session died) is said plainly.
        tr_unjudged = tmp / "unjudged.jsonl"
        tr_unjudged.write_text(json.dumps({"type": "attachment", "timestamp": "2026-09-09T10:00:01Z", "sessionId": "u1", "attachment": {"type": "goal_status", "met": False, "sentinel": True, "condition": "finish it"}}) + "\n", encoding="utf-8")
        r4 = rr.collect("u1", str(project), {"last_session_start": time.time() - 5, "run": {"transcript_path": str(tr_unjudged)}})
        check("goal with no verdict -> 'set, no verdict recorded'", r4["goal_outcome"] == "set, no verdict recorded")
        # Judged impossible: the verified "failed entry" shape.
        tr_failed = tmp / "failed.jsonl"
        tr_failed.write_text(
            json.dumps({"type": "attachment", "timestamp": "2026-09-09T10:00:01Z", "sessionId": "f1", "attachment": {"type": "goal_status", "met": False, "sentinel": True, "condition": "prove 2 is odd"}}) + "\n"
            + json.dumps({"type": "attachment", "timestamp": "2026-09-09T10:01:00Z", "sessionId": "f1", "attachment": {"type": "goal_status", "met": False, "failed": True, "condition": "prove 2 is odd", "reason": "2 is even; the assistant refused to fabricate a proof.", "iterations": 1, "durationMs": 54988, "tokens": 3574}}) + "\n",
            encoding="utf-8",
        )
        r5 = rr.collect("f1", str(project), {"last_session_start": time.time() - 5, "run": {"transcript_path": str(tr_failed)}})
        check("failed verdict -> outcome 'failed'", r5["goal_outcome"] == "failed" and r5["goal_verdicts"][0]["flags"] == {"failed": True})
        check("failed verdict rendered", "| failed | 1 | 2 is even" in rr.render_md(r5))

        print("gate:")
        check("edits make a session substantial", rr.substantial({"files_edited_this_session": ["a"]}))
        check("a compaction makes it substantial", rr.substantial({"pressure": {"cycle": 1}}))
        check("five prompts make it substantial", rr.substantial({"prompts_this_session": 5}))
        check("an empty session is not", not rr.substantial({"prompts_this_session": 2}))
        check("a goal makes it substantial even with no edits (Bash-written files)", rr.substantial({"run": {"transcript_path": str(transcript)}}))
        check("a test run makes it substantial", rr.substantial({"test_runs_this_session": 1}))
        check("three real turns make it substantial (a Bash-only /loop session)", rr.substantial({"pressure": {"stops_total": 3}}))
        check("two turns do not", not rr.substantial({"pressure": {"stops_total": 2}}))
        check("goal_seen is false on a transcript without one", not rr.goal_seen(str(tmp / "nope.jsonl")))

        print("CLI:")
        import subprocess

        env = dict(os.environ, CLAUDE_ENGRAM_DIR=str(tmp))
        remind._session_id = sid
        remind.save_state(state)
        res = subprocess.run([sys.executable, "-m", "claude_engram.run_report", "--session", sid, "--project", str(project), "--stdout"], capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=60)
        check("CLI --stdout renders", res.returncode == 0 and "# Run " in res.stdout)
        res = subprocess.run([sys.executable, "-m", "claude_engram.run_report"], capture_output=True, text=True, cwd=str(ROOT), env=dict(env, CLAUDE_CODE_SESSION_ID=""), timeout=60)
        check("CLI without a session id prints usage", res.returncode == 2)

        print("source guards:")
        remind_src = (ROOT / "claude_engram" / "hooks" / "remind.py").read_text(encoding="utf-8")
        check("SessionEnd writes the report", "_rr.write_report(" in remind_src and "_rr.substantial(state)" in remind_src)
        check("PostCompact pins the restored entry", "_cp2.note_restored(" in remind_src)
        check("SessionStart records permission mode + transcript + source", "permission_mode=_perm," in remind_src and "transcript_path=_transcript," in remind_src and 'source=str(source or "startup")' in remind_src)
        guard_src = (ROOT / "claude_engram" / "tools" / "context_guard.py").read_text(encoding="utf-8")
        check("manual ring entries carry session_id", 'checkpoint_data["session_id"] = _sid' in guard_src)
        defs = (ROOT / "claude_engram" / "tool_definitions_v2.py").read_text(encoding="utf-8")
        handlers = (ROOT / "claude_engram" / "handlers.py").read_text(encoding="utf-8")
        check("session_mine(run_report) is advertised and dispatched", '"run_report"' in defs and 'operation == "run_report"' in handlers)

    print()
    if _fails:
        print(f"FAILED: {len(_fails)}")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
