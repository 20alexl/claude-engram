"""
Benchmark: Phase 7 polish -- a checkpoint carries where the repo and the
run stood, and a restore says how far the repo moved since.

What must hold:
  1. repo_state.head / since: a temp git repo; commits and files since a
     commit; the checkpoint's own files among them; a commit not in this
     history is reported as missing; no repo -> nothing.
  2. since_text: one line, the four shapes.
  3. goal_for_session: the launcher's run.goal wins; else the last
     goal_status sentinel in the transcript (verified shape); else ''.
  4. checkpoint_save records the commit and the goal; restore and the
     session-start banner print the goal and the staleness line.
  5. The halt's deny reason puts the checkpoint FIRST.
  6. The launcher primes the session state with the goal and the manifest.

Run: venv/Scripts/python.exe tests/bench_phase7.py
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


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30)


def _repo(tmp):
    repo = tmp / "repo"
    repo.mkdir(parents=True)
    _git(["init", "-q", "."], repo)
    (repo / "a.py").write_text("print(1)\n", encoding="utf-8")
    (repo / "b.md").write_text("# b\n", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"], repo)
    return repo


def test_repo_state(rs, tmp):
    print("repo_state:")
    repo = _repo(tmp)
    h0 = rs.head(str(repo))
    check("head is a short sha", len(h0) >= 7)
    check("no repo -> empty head", rs.head(str(tmp / "nowhere")) == "" and rs.head("") == "")
    check("since at head: nothing moved", rs.since(h0, str(repo)) == {"commits": 0, "files_changed": 0, "touched": [], "missing": False})
    (repo / "a.py").write_text("print(2)\n", encoding="utf-8")
    _git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "two"], repo)
    (repo / "c.txt").write_text("c\n", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "three"], repo)
    s = rs.since(h0, str(repo), files=[str(repo / "a.py"), "b.md"])
    check("two commits, two files since", s is not None and s["commits"] == 2 and s["files_changed"] == 2)
    check("the checkpoint's touched file is named, the untouched one is not", s is not None and s["touched"] == ["a.py"])
    check("a commit not in this history is missing", (rs.since("deadbeef", str(repo)) or {}).get("missing") is True)
    check("no commit -> None", rs.since("", str(repo)) is None)
    check("no repo -> None", rs.since(h0, str(tmp / "nowhere")) is None)
    print("since_text:")
    check("nothing to say", rs.since_text(None) == "")
    check("unchanged", rs.since_text({"commits": 0, "files_changed": 0, "touched": [], "missing": False}) == "Since this checkpoint: no commits")
    t = rs.since_text(s)
    check("counts and touched files", t == "Since this checkpoint: 2 commits, 2 files changed -- incl. a.py")
    check("singulars", rs.since_text({"commits": 1, "files_changed": 1, "touched": [], "missing": False}) == "Since this checkpoint: 1 commit, 1 file changed")
    check("missing commit wording", "not in this history" in rs.since_text({"missing": True}))


def _transcript(tmp, condition):
    p = tmp / "t.jsonl"
    lines = [
        json.dumps({"type": "user", "timestamp": "2026-09-10T20:00:00.000Z", "message": {"role": "user", "content": "hi"}}),
        json.dumps({"type": "attachment", "timestamp": "2026-09-10T20:00:01.000Z", "attachment": {"type": "goal_status", "sentinel": True, "condition": condition, "met": False}}),
        json.dumps({"type": "attachment", "timestamp": "2026-09-10T20:00:30.000Z", "attachment": {"type": "goal_status", "condition": condition, "met": False, "reason": "not yet", "iterations": 1}}),
    ]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_goal(rs, tmp):
    print("goal_for_session:")
    check("no run block -> ''", rs.goal_for_session({}) == "")
    check("the launcher's goal wins", rs.goal_for_session({"run": {"goal": "  done.txt contains ok ", "transcript_path": "nope"}}) == "done.txt contains ok")
    tp = _transcript(tmp, "the suite is green")
    check("else the transcript's sentinel", rs.goal_for_session({"run": {"transcript_path": str(tp)}}) == "the suite is green")
    check("a missing transcript -> ''", rs.goal_for_session({"run": {"transcript_path": str(tmp / "missing.jsonl")}}) == "")


def test_checkpoint_round_trip(tmp):
    print("checkpoint save -> restore carries commit and goal:")
    store = tmp / "store"
    os.environ["CLAUDE_ENGRAM_DIR"] = str(store)
    from claude_engram.hooks import remind
    from claude_engram.tools.context_guard import ContextGuard

    repo = _repo(tmp / "cp")
    remind._session_id = "s-phase7"
    st = remind.load_state()
    st["run"] = {"goal": "never.txt contains DONE", "transcript_path": ""}
    remind.save_state(st)
    cg = ContextGuard(storage_dir=store / "checkpoints")
    resp = cg.save_checkpoint("task", "step 1", ["a"], ["b"], [str(repo / "a.py")], project_path=str(repo), handoff_summary="handoff")
    data = json.loads(Path((resp.data or {})["checkpoint_file"]).read_text(encoding="utf-8"))
    check("the entry carries the commit", data.get("commit") == subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip())
    check("the entry carries the goal", data.get("goal") == "never.txt contains DONE")
    # Move the repo on, then restore.
    (repo / "a.py").write_text("print(3)\n", encoding="utf-8")
    _git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "moved"], repo)
    out = cg.restore_checkpoint(project_path=str(repo), index=0).to_formatted_string()
    check("restore prints the goal", "**Goal:** never.txt contains DONE" in out)
    check("restore prints the staleness line with the touched file", "Since this checkpoint: 1 commit, 1 file changed -- incl. a.py" in out)
    print("session-start banner:")
    lines = remind._format_restored_context(data)
    check("banner prints the goal", any(l.strip().startswith("Goal: never.txt") for l in lines))
    check("banner prints the staleness line", any("Since this checkpoint: 1 commit" in l for l in lines))
    old = dict(data)
    old.pop("commit", None)
    old.pop("goal", None)
    lines2 = remind._format_restored_context(old)
    check("an older entry without commit/goal prints neither line", not any("Since this checkpoint" in l or l.strip().startswith("Goal:") for l in lines2))
    os.environ.pop("CLAUDE_ENGRAM_DIR", None)


def test_deny_order(st):
    print("deny reason:")
    state = {"stall": {"halted": {"turn": 4, "strikes": 3, "denied": 0}, "strikes": 3}}
    r = st.deny_reason(state, "Bash")
    check("checkpoint FIRST, then the notification, then stop", r.index("FIRST context(checkpoint_save)") < r.index("THEN PushNotification") < r.index("Then stop"))
    check("says it is the record a person will read", "record they will read" in r)


def test_prime(run, tmp):
    print("launcher primes the session state:")
    os.environ["CLAUDE_ENGRAM_DIR"] = str(tmp / "store-prime")
    from claude_engram.hooks import remind

    run.prime_state("s-prime", "done.txt contains ok", "/x/manifest.json")
    remind._session_id = "s-prime"
    st = remind.load_state()
    check("goal, manifest and launcher flag recorded", st["run"]["goal"] == "done.txt contains ok" and st["run"]["manifest"] == "/x/manifest.json" and st["run"]["launcher"] is True)
    remind.mark_session_started(str(tmp), permission_mode="bypassPermissions", transcript_path="/t.jsonl", source="startup")
    st = remind.load_state()
    check("SessionStart keeps the primed goal", st["run"].get("goal") == "done.txt contains ok" and st["run"].get("transcript_path") == "/t.jsonl")
    os.environ.pop("CLAUDE_ENGRAM_DIR", None)


def main():
    from claude_engram import repo_state as rs
    from claude_engram import run
    from claude_engram.hooks import stall as st

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        test_repo_state(rs, tmp)
        test_goal(rs, tmp)
        test_checkpoint_round_trip(tmp)
        test_deny_order(st)
        test_prime(run, tmp)
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
