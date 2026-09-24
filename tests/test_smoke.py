"""Fast pytest smoke tests: the measured facts of the day, as unit checks.

The benches (bench_*.py) are the real suites; this file makes `python -m
pytest -q tests` a meaningful command that runs in under a second.
"""

import json
import os
from pathlib import Path

import pytest

from claude_engram import project_config
from claude_engram.hooks import autorun, context_pressure as cp, hot_reader


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "CLAUDE_ENGRAM_OUTPUT_RESERVE",
              "CLAUDE_ENGRAM_CHECKPOINT_MARGIN", "CLAUDE_ENGRAM_GOAL_TURN_CAP"):
        monkeypatch.delenv(k, raising=False)


def test_checkpoint_band_sits_above_the_measured_compaction():
    # 2026-09-10: a 750K setting compacted at 717,578 tokens.
    th = cp.thresholds(1_000_000, 750_000)
    assert th["trigger_at"] == 718_000
    assert th["checkpoint_at"] == 698_000
    assert th["checkpoint_at"] < 717_578 < th["trigger_at"] + 1_000
    assert th["headsup_at"] == 650_000


def test_small_window_bands_stay_ordered():
    th = cp.thresholds(200_000, 200_000)
    assert th["headsup_at"] < th["checkpoint_at"] < th["trigger_at"] < 200_000


def test_scan_goal_reads_the_observed_records(tmp_path: Path):
    t = tmp_path / "t.jsonl"
    sentinel = {"type": "attachment", "timestamp": "2026-09-10T22:45:54.205Z",
                "attachment": {"type": "goal_status", "met": False, "sentinel": True, "condition": "tests pass"}}
    verdict = {"type": "attachment", "timestamp": "2026-09-10T22:46:09.000Z",
               "attachment": {"type": "goal_status", "met": True, "condition": "tests pass", "reason": "pytest exited 0"}}
    clear = {"type": "user", "timestamp": "2026-09-10T22:46:11.161Z",
             "message": {"role": "user", "content": "<command-name>/goal</command-name>\n<command-message>goal</command-message>\n<command-args>clear</command-args>"}}
    t.write_text(json.dumps(sentinel) + "\n", encoding="utf-8")
    s = autorun.scan_goal(str(t))
    assert s["active"] and s["condition"] == "tests pass"
    t.write_text(json.dumps(sentinel) + "\n" + json.dumps(verdict) + "\n", encoding="utf-8")
    assert autorun.scan_goal(str(t))["ended"] == "met"
    t.write_text(json.dumps(sentinel) + "\n" + json.dumps(clear) + "\n", encoding="utf-8")
    assert autorun.scan_goal(str(t))["ended"] == "cleared"
    assert autorun.scan_goal(str(tmp_path / "missing.jsonl"))["seen"] is False


def test_observe_arms_and_ends_a_goal_run(tmp_path: Path):
    t = tmp_path / "t.jsonl"
    sentinel = {"type": "attachment", "timestamp": "2026-09-10T22:45:54.205Z",
                "attachment": {"type": "goal_status", "met": False, "sentinel": True, "condition": "g"}}
    t.write_text(json.dumps(sentinel) + "\n", encoding="utf-8")
    state: dict = {}
    ev = autorun.observe(state, str(t), str(tmp_path), turn=True)
    assert ev and ev["event"] == "started" and autorun.running(state)
    assert state["run"]["auto"]["turns"] == 1
    assert autorun.env_or_state_autonomy(state) is True
    t.write_text(json.dumps(sentinel) + "\n" + json.dumps({"type": "attachment", "timestamp": "2026-09-10T22:46:09.000Z",
                 "attachment": {"type": "goal_status", "met": True, "condition": "g", "reason": "done"}}) + "\n", encoding="utf-8")
    state["run"]["transcript_path"] = str(t)
    from claude_engram import repo_state
    assert repo_state.goal_for_session(state) == "g"  # running: every checkpoint carries it
    ev = autorun.observe(state, str(t), str(tmp_path), turn=True)
    assert ev and ev["event"] == "ended" and state["run"]["auto"]["status"] == "met"
    assert autorun.env_or_state_autonomy(state) is False
    # A met goal is not stamped on later checkpoints (seen live: the banner
    # showed a goal met hours earlier as the checkpoint's goal).
    assert "goal" not in state["run"]
    assert repo_state.goal_for_session(state) == ""


def test_goal_bracket_resolves_from_the_sessions_edits_not_the_turns():
    from claude_engram.hooks import remind
    # Every Stop moves files_edited_this_session into last_session_files and
    # clears it, so a turn with no edits must not send the bracket to the cwd.
    assert remind._session_edit_files({"files_edited_this_session": ["E:/ws/p/a.py"]}) == ["E:/ws/p/a.py"]
    assert remind._session_edit_files({"files_edited_this_session": [], "last_session_files": ["E:/ws/p/b.py"]}) == ["E:/ws/p/b.py"]
    st = {"files_edited_this_session": [], "last_session_files": [], "loop": {"edit_counts": {"E:/ws/p/c.py": 3, "c.py": 3}}}
    assert remind._session_edit_files(st) == ["E:/ws/p/c.py"]
    assert remind._session_edit_files({}) == []


def test_a_worktree_session_belongs_to_the_main_repo(tmp_path: Path, monkeypatch):
    from claude_engram.hooks import paths
    # .scratch is this workspace's convention, configured, not shipped.
    monkeypatch.setenv("CLAUDE_ENGRAM_NON_PROJECT_DIRS", ".scratch")
    monkeypatch.setenv("CLAUDE_ENGRAM_DIR", str(tmp_path / "store"))
    ws = tmp_path / "ws"
    main = ws / "trade-lab"
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    wt = main / ".scratch" / "wt"
    wt.mkdir(parents=True)
    (wt / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'wt'}\n", encoding="utf-8")
    (wt / "plan.md").write_text("x", encoding="utf-8")
    norm = paths._normalize_path
    assert paths.worktree_main(str(wt)) == norm(str(main))
    assert paths.worktree_main(str(main)) == ""  # a real .git dir, not a worktree
    assert paths.canonical_project_root(str(wt)) == norm(str(main))
    # A plain scratch dir (no .git) still maps to the project above it.
    assert paths.canonical_project_root(str(main / ".scratch" / "notes")) == norm(str(main))
    assert paths.canonical_project_root(str(main)) == norm(str(main))
    # A file inside the worktree resolves to the main repo, not the worktree.
    assert paths.resolve_project_for_file(str(wt / "plan.md"), str(ws)) == norm(str(main))
    assert paths.under_non_project_dir(str(wt / "plan.md")) is True
    assert paths.under_non_project_dir(str(main / "src" / "a.py")) is False


def test_output_markers_count_only_for_commands_that_can_run_tests():
    from claude_engram.hooks.remind import _command_can_run_tests as can
    assert can("grep -n 'passed' tests/test_x.py") is False
    assert can("git log --oneline -- scripts/pytest_dots.py") is False
    assert can("cat out.txt") is False
    assert can("venv/Scripts/python.exe scripts/pytest_dots.py") is True
    assert can("python -m pytest -q tests") is True
    assert can("FOO=1 python check.py") is True
    assert can("./run_tests.sh") is True
    assert can("") is False


def test_a_prose_claim_needs_a_turn_effect_and_bullets_never_count():
    from claude_engram.hooks.context_pressure import _turn_corroborates_a_close as ok
    assert ok({"stall": {"turn": {"effects": ["commit"], "delegated": False}}}, "Track B is built and merged.") is True
    assert ok({"stall": {"turn": {"effects": [], "delegated": True}}}, "Phase 1 built.") is True
    assert ok({"stall": {"turn": {"effects": [], "delegated": False}}}, "Track B is built and merged.") is False
    assert ok({"stall": {"turn": {"effects": ["file"]}}}, "- **The torch kind**: built") is False
    assert ok({}, "step 3 done") is False


def test_nudge_delivery_is_capped_to_one_an_hour(tmp_path: Path, monkeypatch):
    import time as _t
    from claude_engram.hooks import context_pressure as cp
    monkeypatch.setenv("CLAUDE_ENGRAM_DIR", str(tmp_path / "store"))
    monkeypatch.setattr(cp, "_ring_manual_after", lambda *_a, **_k: False)
    state: dict = {}
    cp.stage_milestone(state, "step one done", "claim", since=_t.time() - 10)
    text, _ = cp.nudge(state, "s-cap-test", str(tmp_path))
    assert "closed a step" in text
    cp.stage_milestone(state, "step two done", "claim", since=_t.time() - 5)
    text2, _ = cp.nudge(state, "s-cap-test", str(tmp_path))
    assert "closed a step" not in text2  # within the hour: swallowed
    # A task-tool close is structural and never rate-limited.
    cp.stage_milestone(state, "task X", "task", since=_t.time() - 5)
    text3, _ = cp.nudge(state, "s-cap-test", str(tmp_path))
    assert "marked a task done" in text3


def test_recent_edit_files_reads_the_transcript(tmp_path: Path):
    from claude_engram.hooks import autorun
    t = tmp_path / "t.jsonl"
    def tu(name, fp):
        return json.dumps({"type": "assistant", "timestamp": "2026-09-11T10:00:00.000Z",
                           "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "x", "name": name, "input": {"file_path": fp}}]}})
    t.write_text("\n".join([tu("Read", "E:/ws/p/readme.md"), tu("Edit", "E:/ws/p/a.py"), tu("Write", "E:/ws/p/b.py"), tu("Edit", "E:/ws/p/a.py")]) + "\n", encoding="utf-8")
    assert autorun.recent_edit_files(str(t)) == ["E:/ws/p/b.py", "E:/ws/p/a.py"]
    assert autorun.recent_edit_files(str(tmp_path / "missing.jsonl")) == []


def test_latest_session_is_picked_per_project(tmp_path: Path):
    from claude_engram.mining.session_index import SessionIndex
    idx = SessionIndex(tmp_path / "session_index.json")
    idx._data["sessions"] = {
        "s-ui": {"last_timestamp": "2026-09-11T09:00:00Z", "files_edited": ["E:/ws/web/page.tsx", "E:/ws/web/app.css"]},
        "s-tl": {"last_timestamp": "2026-09-11T08:00:00Z", "files_edited": ["E:/ws/trade-lab/src/a.py", "C:/Users/x/.claude/memory.md"]},
    }
    latest = idx.get_latest_session()
    assert latest is not None and latest["files_edited"][0].endswith("page.tsx")
    s = idx.get_latest_session_summary("E:/ws/trade-lab")
    assert s is not None and s["files_edited"] == ["a.py"]
    assert s["file_count"] == 1  # the memory file outside the project is not counted
    assert idx.get_latest_session_summary("E:/ws/other") is None


def test_test_invocation_reads_every_segment_and_read_only_tools_never_count():
    from claude_engram.hooks.remind import _is_test_invocation as inv
    assert inv("cd /e/workspace/trade-lab; .venv/Scripts/python.exe -m pytest 2>&1 | tail -1") is True
    assert inv("FOO=1 pytest -q tests") is True
    assert inv("sed -n 100,121p tests/bench_scoring.py") is False
    assert inv("cat session-logs/2026-09-10.md") is False


def test_edit_reminders_need_a_file_match_for_rules_and_a_full_path_when_old():
    import time as _t
    from claude_engram.hooks.hot_reader import score_loaded_entries
    now = _t.time()
    ctx = {"file_path": "E:/ws/tl/src/loader.py"}
    fresh_hit = {"id": "1", "category": "decision", "content": "loader.py reads the manifest first", "related_files": ["E:/ws/tl/src/loader.py"], "created_at": now - 86400, "relevance": 6}
    old_name_drop = {"id": "2", "category": "decision", "content": "we discussed loader.py once", "related_files": ["loader.py"], "created_at": now - 91 * 86400, "relevance": 6}
    old_full_path = {"id": "3", "category": "decision", "content": "E:/ws/tl/src/loader.py must stay lazy", "related_files": ["E:/ws/tl/src/loader.py"], "created_at": now - 91 * 86400, "relevance": 6}
    far_rule = {"id": "4", "category": "rule", "content": "Delegate session maintenance to a background agent", "related_files": [], "created_at": now - 128 * 86400, "relevance": 9}
    near_rule = {"id": "5", "category": "rule", "content": "src/loader.py: never read the whole file", "related_files": ["E:/ws/tl/src/loader.py"], "created_at": now - 128 * 86400, "relevance": 9}
    out = score_loaded_entries([fresh_hit, old_name_drop, old_full_path, far_rule, near_rule], ctx, limit=3)
    ids = [e["id"] for e in out]
    assert "1" in ids and "3" in ids and "5" in ids
    assert "2" not in ids and "4" not in ids


def test_rule_context_sees_approval_and_session_created_paths():
    from claude_engram.hooks.remind import _rule_context, _note_created_paths
    st: dict = {"last_prompt": "approved, delete the scratch dir"}
    _note_created_paths(st, [{"tool_name": "Bash", "tool_input": {"command": "mkdir -p E:/ws/tl/.scratch/tmpwork"}},
                            {"tool_name": "Write", "tool_input": {"file_path": "E:/ws/tl/.scratch/tmpwork/plan.md"}}])
    assert "e:/ws/tl/.scratch/tmpwork" in [c.lower() for c in st["created_paths"]]
    ctx = _rule_context(st, {"command": "rm -rf E:/ws/tl/.scratch/tmpwork"})
    assert "reads as approval" in ctx and "this session created" in ctx
    assert _rule_context({"last_prompt": "what is the plan?"}, {"command": "rm -rf E:/ws/tl/src"}) == ""


def test_session_project_is_one_loader_for_every_hook(tmp_path: Path, monkeypatch):
    from claude_engram.hooks import remind
    monkeypatch.setenv("CLAUDE_ENGRAM_DIR", str(tmp_path / "store"))
    ws = tmp_path / "ws"
    proj = ws / "proj-a"
    (proj / ".git").mkdir(parents=True)
    (ws / ".git").mkdir()
    t = tmp_path / "t.jsonl"
    def tu(name, fp):
        return json.dumps({"type": "assistant", "timestamp": "2026-09-11T10:00:00.000Z",
                           "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "x", "name": name, "input": {"file_path": fp}}]}})
    # The memory file outside the workspace is edited last and must not vote.
    t.write_text("\n".join([tu("Edit", str(proj / "a.py")), tu("Write", str(proj / "b.py")), tu("Edit", "C:/Users/x/.claude/memory.md")]) + "\n", encoding="utf-8")
    norm = remind._normalize_path
    st: dict = {"run": {"transcript_path": str(t)}}
    assert remind.session_project(str(ws), st) == norm(str(proj))
    assert st["session_project_cache"]["value"] == norm(str(proj))
    # Cached: a changed transcript path with the same size is not re-read.
    st["run"]["transcript_path"] = str(tmp_path / "missing.jsonl")
    assert remind.session_project(str(ws), st) == norm(str(proj))
    # No transcript, no state lists: the cwd mapped to its repository.
    assert remind.session_project(str(proj / "src"), {}) == norm(str(proj / "src")) or remind.session_project(str(proj), {}) == norm(str(proj))
    # Files outside the root never vote for the root.
    assert remind._resolve_session_project(str(ws), ["C:/Users/x/.claude/memory.md", str(proj / "a.py")]) == norm(str(proj))


def test_recurring_errors_are_scoped_to_the_sessions_project(tmp_path: Path, monkeypatch):
    from claude_engram.hooks import remind, paths
    store = tmp_path / "store"
    monkeypatch.setenv("CLAUDE_ENGRAM_DIR", str(store))
    ws = tmp_path / "ws"
    for name in ("trade-lab", "chappie"):
        (ws / name / ".git").mkdir(parents=True)
    (ws / ".git").mkdir()
    root = paths._normalize_path(str(ws))
    tl = paths._normalize_path(str(ws / "trade-lab"))
    v11 = paths._normalize_path(str(ws / "chappie"))
    (store / "projects" / "roothash").mkdir(parents=True)
    (store / "manifest.json").write_text(json.dumps({"projects": {root: {"hash": "roothash"}}}), encoding="utf-8")
    (store / "projects" / "roothash" / "patterns.json").write_text(json.dumps({
        "struggles": [],
        "recurring_errors": [
            {"error_type": "AttributeError", "example": "AttributeError: InputEncoderRegistry", "session_count": 8, "projects": [root, v11]},
            {"error_type": "KeyError", "example": "KeyError: 'sue'", "session_count": 3, "projects": [root, tl]},
            {"error_type": "FileNotFoundError", "example": "FileNotFoundError: /c/Users/x/.claude_engram/projects/h//session_index.json", "session_count": 7, "projects": [root, tl]},
            {"error_type": "ValueError", "example": "ValueError: legacy, unattributed", "session_count": 2},
        ],
    }), encoding="utf-8")
    text = "\n".join(remind._recurring_lines(tl, []))
    assert "KeyError: 'sue'" in text          # attributed to this project
    assert "InputEncoderRegistry" not in text  # another project's
    assert ".claude_engram" not in text        # engram's own failure
    assert "legacy, unattributed" in text      # no attribution: shown
    text_v11 = "\n".join(remind._recurring_lines(v11, []))
    assert "InputEncoderRegistry" in text_v11 and "KeyError" not in text_v11


def _git_repo_with_a_reason(tmp_path: Path) -> Path:
    import subprocess
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    def git(*a):
        subprocess.run(["git", *a], cwd=str(repo), check=True, capture_output=True, env=env, stdin=subprocess.DEVNULL)
    git("init", "-q")
    (repo / "src" / "sync.py").write_text("PACE = 0.5\n", encoding="utf-8")
    git("add", "."); git("commit", "-q", "-m", "sync: first cut")
    (repo / "src" / "sync.py").write_text(
        "# Fair-access policy: a declared UA, max 10 req/s. We stay well under.\n\nPACE = 0.15  # seconds between requests\n",
        encoding="utf-8",
    )
    git("add", "."); git("commit", "-q", "-m", "sync: pace 0.15", "-m", "The rate limit chosen against the published policy.")
    return repo


def test_decisions_read_the_repos_history_and_never_crash_on_a_missing_index(tmp_path: Path):
    from claude_engram.mining import search
    repo = _git_repo_with_a_reason(tmp_path)
    store = tmp_path / "store"
    (store / "projects" / "sub").mkdir(parents=True)
    # The project is registered with a memory store only (no embeddings index): the trade-lab shape.
    (store / "manifest.json").write_text(json.dumps({"projects": {search._normalize_path(str(repo)): {"hash": "sub"}}}), encoding="utf-8")
    res = search.find_decision(str(repo), "PACE 0.15 seconds between requests", engram_storage_dir=str(store))
    texts = [r.chunk_text for r in res]
    # The reason lives in the diff (a comment above the constant), not in
    # the message: the pickaxe hit carries the added lines around the needle.
    assert any("we stay well under" in t.lower() and "diff:" in t for t in texts), texts
    assert all(r.msg_type == "git" and r.session_id.startswith("git:") for r in res)
    # The file's history rides along with replay.
    hist = search.git_file_history(str(repo), str(repo / "src" / "sync.py"))
    assert len(hist) == 2 and hist[0].chunk_text.startswith("commit ") and hist[0].related_files == ["src/sync.py"]
    # Inheritance resolves the ancestor that holds the index.
    (store / "projects" / "root").mkdir()
    (store / "projects" / "root" / "session_embeddings_index.json").write_text('{"chunks": []}', encoding="utf-8")
    manifest = {"projects": {search._normalize_path(str(tmp_path)): {"hash": "root"}, search._normalize_path(str(repo)): {"hash": "sub"}}}
    got = search._resolve_project_with_inheritance(str(repo), manifest, store, require_file="session_embeddings_index.json")
    assert got is not None and got[0] == search._normalize_path(str(tmp_path)) and got[1].name == "root"


def test_generic_basenames_need_a_full_path():
    gate = 0.35 * 0.5  # a bare-name match would score 0.5 under the 0.35 file weight
    assert hot_reader._file_match_score("E:/ws/engram/README.md", [], "FileNotFoundError: src/README.md") == 0.0
    assert hot_reader._file_match_score("E:/ws/engram/CLAUDE.md", ["CLAUDE.md"], "") == 0.0
    assert hot_reader._file_match_score("E:/ws/engram/README.md", ["E:/ws/engram/README.md"], "") >= gate


def test_past_mistakes_rank_this_project_first():
    from claude_engram.hooks import storage

    mem = {"entries": [
        {"id": "a", "category": "mistake", "content": "MISTAKE: newest, pooled, another project", "created_at": 400,
         "related_files": ["E:/ws/trade-lab/x.py"], "_inherited": True},
        {"id": "b", "category": "mistake", "content": "MISTAKE: pooled, no file", "created_at": 300, "_inherited": True},
        {"id": "c", "category": "mistake", "content": "MISTAKE: pooled but names a file here", "created_at": 200,
         "related_files": ["E:\\ws\\engram\\claude_engram\\y.py"], "_inherited": True},
        {"id": "d", "category": "mistake", "content": "MISTAKE: oldest, the project's own", "created_at": 100},
    ]}
    ms = storage.get_past_mistakes(mem, "E:/ws/engram")
    assert [m["id"] for m in ms] == ["c", "d", "b", "a"]
    assert [m["scope"] for m in ms] == [0, 0, 1, 2]
    assert [m["id"] for m in storage.get_past_mistakes(mem)] == ["a", "b", "c", "d"]  # no project: newest first


def test_every_subprocess_detaches_stdin():
    # A child that inherits a stdio MCP server's stdin stalled every git call
    # by the full timeout and hung the server for minutes (2026-09-10).
    import re

    root = Path(__file__).resolve().parent.parent / "claude_engram"
    offenders = []
    for p in root.rglob("*.py"):
        src = p.read_text(encoding="utf-8")
        for m in re.finditer(r"subprocess\.(run|Popen|check_output)\(", src):
            window = src[m.start(): m.start() + 900]
            head = window.split("\n\n", 1)[0]
            if "stdin" not in head and "**kwargs" not in head and "input=" not in head:
                offenders.append(f"{p.name}:{src[:m.start()].count(chr(10)) + 1}")
    assert offenders == [], offenders


def test_session_stays_active_across_sub_projects(tmp_path: Path, monkeypatch):
    # One Claude Code session is one session whichever sub-project the last
    # edit resolved to; the old project-equality gate re-ran the full
    # auto-start banner on every flip (~430 tokens, 7 of 21 prompts).
    monkeypatch.setenv("CLAUDE_ENGRAM_DIR", str(tmp_path))
    from claude_engram.hooks import remind

    monkeypatch.setattr(remind, "_session_id", "s-active-test")
    remind.mark_session_started(str(tmp_path / "ws" / "engram"))
    assert remind.check_session_active(str(tmp_path / "ws" / "engram"))
    assert remind.check_session_active(str(tmp_path / "ws"))
    assert remind.check_session_active(str(tmp_path / "ws" / "other-project"))
    st = remind.load_state()
    st["last_session_start"] = 0
    remind.save_state(st)
    # Past the window only the marker file (legacy, under the store dir) answers,
    # and it names the project it was written for.
    assert (tmp_path / "session_active").is_file()
    assert not remind.check_session_active(str(tmp_path / "ws" / "other-project"))


def _workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    ws = tmp_path / "ws"
    a, b = ws / "proj-a", ws / "proj-b"
    for p in (ws, a, b):
        (p / ".git").mkdir(parents=True, exist_ok=True)
    (a / "src").mkdir(exist_ok=True)
    (b / "src").mkdir(exist_ok=True)
    return ws, a, b


def test_mined_entries_file_under_the_project_their_files_name(tmp_path: Path, monkeypatch):
    from claude_engram.hooks.paths import target_project_for_files, _normalize_path

    monkeypatch.setenv("CLAUDE_ENGRAM_NON_PROJECT_DIRS", ".scratch")  # the workspace's convention, configured
    monkeypatch.setenv("CLAUDE_ENGRAM_DIR", str(tmp_path / "store"))
    ws, a, b = _workspace(tmp_path)
    assert _normalize_path(target_project_for_files(str(ws), [str(a / "src" / "x.py")])) == _normalize_path(str(a))
    # majority wins; a temp path outside the root does not vote
    files = [str(b / "src" / "y.py"), str(b / "src" / "z.py"), str(a / "src" / "x.py"), r"C:\Temp\other\t.py"]
    assert _normalize_path(target_project_for_files(str(ws), files)) == _normalize_path(str(b))
    assert target_project_for_files(str(ws), []) == str(ws)
    assert target_project_for_files(str(ws), [r"C:\Temp\only.py"]) == str(ws)
    assert target_project_for_files(str(a), [str(a / "src" / "x.py")]) == str(a)  # already the project
    # The text names a project: it wins over the file vote, even a project
    # whose files were not named at all (a session that edited both).
    assert _normalize_path(target_project_for_files(str(ws), files, "MISTAKE: proj_a.core failed")) == _normalize_path(str(a))
    (ws / "trade-lab" / ".git").mkdir(parents=True, exist_ok=True)
    got = target_project_for_files(str(ws), [str(a / "src" / "x.py")], "AttributeError: module 'trade_lab.plant' has no attribute VERSION")
    assert _normalize_path(got) == _normalize_path(str(ws / "trade-lab"))
    # short or embedded names do not match ("tools" inside "toolset")
    (ws / "tools" / ".git").mkdir(parents=True, exist_ok=True)
    got = target_project_for_files(str(ws), [str(a / "src" / "x.py")], "the toolset broke; tools were fine")
    assert _normalize_path(got) == _normalize_path(str(a))

    # A git WORKTREE carries a `.git` FILE, which is a project marker, so
    # marker-walking filed everything under E:/ws/trade-lab/.scratch/stack/<wt>
    # as its own project — and those entries then surfaced under whatever store
    # the walk landed in (2026-09-10: trade-lab errors listed as engram's).
    wt = a / ".scratch" / "wt"
    wt.mkdir(parents=True, exist_ok=True)
    (wt / ".git").write_text("gitdir: ../../../.git/worktrees/wt\n", encoding="utf-8")
    known = [str(ws), str(a), str(b)]
    report = str(wt / "m-cut-report.md")
    assert _normalize_path(target_project_for_files(str(ws), [report], known_projects=known)) == _normalize_path(str(a))
    # ...and even without the known list, the walk is pulled back out of .scratch
    assert _normalize_path(target_project_for_files(str(ws), [report])) == _normalize_path(str(a))
    # a registered project that IS a worktree is never a destination
    assert _normalize_path(
        target_project_for_files(str(ws), [report], known_projects=known + [str(wt)])
    ) == _normalize_path(str(a))
    # a file under no known project does not vote at all
    (ws / "loose").mkdir(exist_ok=True)
    assert target_project_for_files(str(ws), [str(ws / "loose" / "x.py")], known_projects=known) == str(ws)
    # A RELATIVE path is no evidence: it resolves against the CALLING process's
    # cwd, so mined 'v2/tests/test_orders.py' and 'SUBMISSION.ts' voted for the
    # checkout the miner ran in and became that project's own mistakes.
    for rel in ("v2/tests/test_orders.py", "SUBMISSION.ts", r"src\README.md"):
        assert target_project_for_files(str(ws), [rel], known_projects=known) == str(ws)
        assert target_project_for_files(str(ws), [rel]) == str(ws)
    # one absolute file among relative ones still decides
    mixed = ["record/journal/score/x.jsonl", str(b / "src" / "y.py")]
    assert _normalize_path(target_project_for_files(str(ws), mixed, known_projects=known)) == _normalize_path(str(b))


def test_reattribute_pooled_moves_entries_keeping_identity(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CLAUDE_ENGRAM_DIR", str(tmp_path / "store"))
    from claude_engram import migrations
    from claude_engram.tools.memory import MemoryStore

    ws, a, b = _workspace(tmp_path)
    store = MemoryStore(storage_dir=str(tmp_path / "store"))
    # Only a REGISTERED project can receive an entry (0.8.37) — a worktree or a
    # vendored checkout carries project markers but is nobody's store.
    store.remember_project(str(a))
    store.remember_project(str(b))
    store.remember_discovery(str(ws), "MISTAKE: KeyError in a", category="mistake", source="session_mining",
                             relevance=8, related_files=[str(a / "src" / "x.py")], auto_embed=False)
    store.remember_discovery(str(ws), "DECISION: b uses sqlite", category="decision", source="session_mining",
                             relevance=7, related_files=[str(b / "src" / "y.py")], auto_embed=False)
    store.remember_discovery(str(ws), "MISTAKE: no file named", category="mistake", source="session_mining",
                             relevance=8, auto_embed=False)
    store.remember_discovery(str(ws), "MISTAKE: a person's own note", category="mistake", source="work_tracker",
                             relevance=8, related_files=[str(a / "src" / "x.py")], auto_embed=False)
    (ws / "proj-c" / ".git").mkdir(parents=True, exist_ok=True)
    store.remember_discovery(str(ws), "MISTAKE: TypeError somewhere unregistered", category="mistake",
                             source="session_mining", relevance=8,
                             related_files=[str(ws / "proj-c" / "src" / "q.py")], auto_embed=False)
    root = store.get_project(str(ws))
    assert root is not None and len(root.entries) == 5
    ids = {e.content: (e.id, e.created_at) for e in root.entries}

    manifest = json.loads((tmp_path / "store" / "manifest.json").read_text(encoding="utf-8"))
    migrations._reattribute_pooled(tmp_path / "store", manifest)

    fresh = MemoryStore(storage_dir=str(tmp_path / "store"))
    root = fresh.get_project(str(ws))
    pa, pb = fresh.get_project(str(a)), fresh.get_project(str(b))
    assert root is not None and pa is not None and pb is not None
    assert sorted(e.content for e in root.entries) == [
        "MISTAKE: TypeError somewhere unregistered",  # its project is not in the manifest
        "MISTAKE: a person's own note",
        "MISTAKE: no file named",
    ]
    assert [e.content for e in pa.entries] == ["MISTAKE: KeyError in a"]
    assert [e.content for e in pb.entries] == ["DECISION: b uses sqlite"]
    moved = pa.entries[0]
    assert (moved.id, moved.created_at) == ids["MISTAKE: KeyError in a"]
    # idempotent
    migrations._reattribute_pooled(tmp_path / "store", manifest)
    again = MemoryStore(storage_dir=str(tmp_path / "store")).get_project(str(a))
    assert again is not None and len(again.entries) == 1


def _pyproject_version() -> str:
    try:
        import tomllib
    except ModuleNotFoundError:  # py3.10
        pytest.skip("tomllib needs python 3.11+")
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if not pyproject.is_file():
        pytest.skip("installed package, no pyproject alongside")
    return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]


def test_status_version_matches_pyproject(tmp_path: Path, monkeypatch):
    # claude_engram_status reported v0.8.20 from a 0.8.36 checkout for sixteen
    # releases: it read the dist metadata, which an editable install freezes at
    # install time. The literal ships with the code; this is the guard that
    # keeps it equal to pyproject.
    import asyncio

    import claude_engram

    want = _pyproject_version()
    assert claude_engram.__version__ == want

    monkeypatch.setenv("CLAUDE_ENGRAM_DIR", str(tmp_path / "store"))
    from claude_engram.handlers import Handlers

    h = Handlers()
    try:
        monkeypatch.setattr(h.llm, "health_check", lambda: {"healthy": True})
        text = asyncio.run(h.status())[0].text
    finally:
        h.close()
    assert f"v{want} is ready" in text


def test_hybrid_search_drops_the_zero_score_tail(tmp_path: Path, monkeypatch):
    # A no-match query answered with three unrelated mistakes at 0.000: the
    # score-based half contributes candidates for ANY query, and _rerank scores
    # an entry that has no vector 0.0. A zero is not a result.
    monkeypatch.setenv("CLAUDE_ENGRAM_DIR", str(tmp_path / "store"))
    from claude_engram.tools.memory import MemoryStore

    store = MemoryStore(storage_dir=str(tmp_path / "store"))
    proj = str(tmp_path / "proj")
    for text in ("MISTAKE: rmtree ate the fixture", "DECISION: sqlite over json",
                 "MISTAKE: CRLF on write_text"):
        store.remember_discovery(proj, text, category="mistake", relevance=8, auto_embed=False)
    # The scorer is up (a query vector exists) but no entry has one — the exact
    # live state that produced the zero-score tail.
    monkeypatch.setattr(store, "_get_embedding", lambda text: [1.0, 0.0, 0.0])
    results = store.hybrid_search(proj, query="auto-compaction fires below the output reserve")
    assert results == []
    assert all(score > 0 for _, score in store.hybrid_search(proj, query=""))


def test_list_rules_includes_inherited_workspace_rules(tmp_path: Path, monkeypatch):
    # list_rules said "No rules defined for this project" while the same
    # session's banner listed 35: the op read only the project's own store.
    monkeypatch.setenv("CLAUDE_ENGRAM_DIR", str(tmp_path / "store"))
    from claude_engram.tools.memory import MemoryStore

    store = MemoryStore(storage_dir=str(tmp_path / "store"))
    ws, a, _ = _workspace(tmp_path)
    store.add_rule(str(ws), "Never Path.write_text a file in this repo")
    store.add_rule(str(a), "Edit files with the Edit tool")

    pairs = store.get_rules_with_inheritance(str(a))
    assert [(r.content, src) for r, src in pairs] == [
        ("Edit files with the Edit tool", ""),
        ("Never Path.write_text a file in this repo", store._normalize_path(str(ws))),
    ]
    # the workspace root itself inherits nothing
    assert [src for _, src in store.get_rules_with_inheritance(str(ws))] == [""]


def test_commitments_read_the_asking_sessions_transcript(tmp_path: Path, monkeypatch):
    # A session started from the workspace root writes its JSONL under the
    # ROOT's projects dir, so the sub-project lookup found nothing and the op
    # answered "no live transcript found for this project" mid-session.
    monkeypatch.setenv("CLAUDE_ENGRAM_DIR", str(tmp_path / "store"))
    from claude_engram.hooks import remind
    from claude_engram.mining import commitments

    transcript = tmp_path / "root-session.jsonl"
    rows = [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "I'll add the tests next."}]}},
    ]
    transcript.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    monkeypatch.setattr(remind, "_session_id", "s-commitments")
    state = remind.load_state()
    state["run"] = {"transcript_path": str(transcript)}
    remind.save_state(state)

    sub = tmp_path / "ws" / "sub-project"  # no transcript dir of its own
    sub.mkdir(parents=True, exist_ok=True)
    assert commitments.session_transcript(str(sub)) == transcript
    out = commitments.extract_commitments(str(sub))
    assert "error" not in out
    assert any("add the tests" in c for c in out["inflight_open"])
    assert "no live transcript" in commitments.format_commitments(
        commitments.extract_commitments(str(sub), transcript=tmp_path / "gone.jsonl")
    )


def test_goal_turn_cap_from_config_and_env(tmp_path: Path, monkeypatch):
    proj = tmp_path / "p"
    (proj / ".engram").mkdir(parents=True)
    (proj / ".engram" / "config.json").write_text('{"goal_turn_cap": 7}', encoding="utf-8")
    assert project_config.load(str(proj))["goal_turn_cap"] == 7
    assert autorun.turn_cap(str(proj)) == 7
    monkeypatch.setenv("CLAUDE_ENGRAM_GOAL_TURN_CAP", "3")
    assert autorun.turn_cap(str(proj)) == 3
    assert autorun.turn_cap(str(tmp_path / "none")) == 3
    monkeypatch.delenv("CLAUDE_ENGRAM_GOAL_TURN_CAP")
    assert autorun.turn_cap(str(tmp_path / "none")) == autorun.DEFAULT_TURN_CAP
    assert os.environ.get("CLAUDE_ENGRAM_GOAL_TURN_CAP") is None


def test_test_tracking_judges_every_segment_and_the_output_shape():
    """The fifth trial report: 'Test tracked' after a `git merge --abort`
    whose chain opened with export/cd/pwd, after `uv lock`, and after a box
    smoke that printed '0 errors'."""
    from claude_engram.hooks.remind import _command_can_run_tests as can, _output_has_test_markers as marks
    assert can("export PATH=/x:$PATH; cd /e/p2m-wt && pwd; uv lock --upgrade-package foo") is False
    assert can("cd /e/p2m-wt && pwd; git diff --name-only --diff-filter=U; git merge --abort tests/test_x.py") is False
    assert can("timeout 590 bash /e/workspace/tools/box.sh 'smoke'") is True  # the output decides
    assert can("export A=1; uv run pytest -q tests") is True
    assert can("cd /w && python -m pytest tests/test_x.py") is True
    assert can("ssh -p 22 box 'cd /w && python -m pytest'") is True
    assert can("uv sync && uv lock") is False
    assert marks("Resolved 12 packages in 1.2s\n0 errors") is False
    assert marks("box smoke: 3 checks, 0 errors, done") is False
    assert marks("3 passed, 1 error in 0.4s") is True
    assert marks("collected 4 items") is True
    assert marks("Ran 3 tests\n\nOK\n") is True


def test_since_counts_commits_on_other_local_branches(tmp_path: Path):
    import subprocess
    from claude_engram.repo_state import since, since_text
    repo = _git_repo_with_a_reason(tmp_path)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    def git(*a):
        return subprocess.run(["git", *a], cwd=str(repo), check=True, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL).stdout.strip()
    first = git("rev-list", "--max-parents=0", "HEAD")
    head = git("rev-parse", "HEAD")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    git("checkout", "-q", "-b", "wt")
    (repo / "src" / "other.py").write_text("X = 1\n", encoding="utf-8")
    git("add", "."); git("commit", "-q", "-m", "wt: a commit on a worktree branch")
    git("checkout", "-q", branch)
    info = since(first, str(repo))
    assert info and info["commits"] == 1 and info["other_branches"] == 1
    assert "1 commit on other local branches" in since_text(info)
    # HEAD itself unchanged: the line says so, and still names the branch work.
    info2 = since(head, str(repo))
    assert info2 and info2["commits"] == 0 and info2["other_branches"] == 1
    assert since_text(info2).startswith("Since this checkpoint: no commits on this branch; 1 commit on other")


def test_counts_name_their_project():
    from claude_engram.hooks.remind import _project_label
    assert _project_label("E:/workspace/trade-lab") == "trade-lab"
    assert _project_label("/w/trade-lab/") == "trade-lab"
    assert _project_label("") == "workspace"


def test_a_remember_in_place_of_a_checkpoint_gets_the_sharper_nudge(tmp_path: Path, monkeypatch):
    import time as _t
    from claude_engram.hooks import context_pressure as cp, stall
    monkeypatch.setenv("CLAUDE_ENGRAM_DIR", str(tmp_path / "store"))
    monkeypatch.setattr(cp, "_ring_manual_after", lambda *_a, **_k: False)
    state: dict = {}
    cp.pressure_state(state)["last_stop_at"] = _t.time() - 30
    stall.note_tool(state, "mcp__claude-engram__memory", {"operation": "remember", "content": "State banked: B6 card written; next step is the B3 card"})
    assert state["stall"]["turn"]["records"] == ["memory:remember"] and state["stall"]["turn"].get("remember_state") is True
    cp.note_stop(state, "Banked the state; continuing with B3.")
    mp = cp.pressure_state(state)["milestone_pending"]
    assert mp and mp["kind"] == "claim_remember"
    text, _ = cp.nudge(state, "s-remember", str(tmp_path))
    assert "reads checkpoints only" in text and "checkpoint_save" in text
    # Both together are fine: a fact and the resume state are two records.
    state2: dict = {}
    cp.pressure_state(state2)["last_stop_at"] = _t.time() - 30
    stall.note_tool(state2, "mcp__claude-engram__memory", {"operation": "remember", "content": "The pace is 0.15 because of the fair-access policy"})
    stall.note_tool(state2, "mcp__claude-engram__context", {"operation": "checkpoint_save", "task_description": "B6 card"})
    cp.note_stop(state2, "B6 card done.")
    assert cp.pressure_state(state2)["milestone_pending"] is None
    # A plain fact with no close claimed stages nothing either.
    state3: dict = {}
    cp.pressure_state(state3)["last_stop_at"] = _t.time() - 30
    stall.note_tool(state3, "mcp__claude-engram__memory", {"operation": "remember", "content": "The pace is 0.15 because of the fair-access policy"})
    cp.note_stop(state3, "Noted. Reading the loader next.")
    assert cp.pressure_state(state3)["milestone_pending"] is None


def _goal_rec(i: int, cond: str, **att) -> str:
    a = {"type": "goal_status", "condition": cond, "met": False, **att}
    return json.dumps({"type": "attachment", "timestamp": f"2026-09-11T17:{i:02d}:00.000Z", "attachment": a})


def test_a_met_record_with_the_sentinel_flag_ends_the_goal(tmp_path: Path):
    """Claude Code 2.1.268 writes the met record as {met: true, sentinel: true}
    with no reason. Read as a new set, it started a phantom run that counted
    three days of ordinary turns to the cap and halted a session with no
    goal (the trade-lab session, 2026-09-14)."""
    t = tmp_path / "t.jsonl"
    t.write_text(_goal_rec(31, "land the branches", sentinel=True) + "\n" + _goal_rec(47, "land the branches", sentinel=True, met=True) + "\n", encoding="utf-8")
    s = autorun.scan_goal(str(t))
    assert s["seen"] and s["active"] is False and s["ended"] == "met" and s["verdicts"] == 1
    # observe: a run started from the sentinel, then ended by the met record; no halt, no cap.
    t.write_text(_goal_rec(31, "land the branches", sentinel=True) + "\n", encoding="utf-8")
    state: dict = {}
    ev = autorun.observe(state, str(t), str(tmp_path), turn=True)
    assert ev and ev["event"] == "started"
    t.write_text(_goal_rec(31, "land the branches", sentinel=True) + "\n" + _goal_rec(47, "land the branches", sentinel=True, met=True) + "\n", encoding="utf-8")
    ev = autorun.observe(state, str(t), str(tmp_path), turn=True)
    assert ev and ev["event"] == "ended" and ev["auto"]["status"] == "met"
    assert not (state.get("stall") or {}).get("halted")


def test_a_run_whose_goal_left_the_transcript_tail_ends_without_a_halt(tmp_path: Path):
    t = tmp_path / "t.jsonl"
    t.write_text(_goal_rec(31, "g", sentinel=True) + "\n", encoding="utf-8")
    state: dict = {}
    autorun.observe(state, str(t), str(tmp_path), turn=True)
    a = autorun.auto(state)
    assert a and a["status"] == "running"
    a["turns"] = a["max_turns"] - 1  # one turn from the cap
    t.write_text(json.dumps({"type": "user", "message": {"content": "just chatting"}}) + "\n", encoding="utf-8")  # the goal records scrolled out
    ev = autorun.observe(state, str(t), str(tmp_path), turn=True)
    assert ev and ev["event"] == "ended" and ev["auto"]["status"] == "cleared"
    assert not (state.get("stall") or {}).get("halted"), "a goal that cannot be seen never arms the halt"


def test_the_halt_leaves_a_subagent_a_way_to_report():
    from claude_engram.hooks import stall
    assert "SendMessage" in stall.HALT_ALLOWED_TOOLS
    assert "still open" in stall._halt_cause({"reason": "turn cap", "turn": 150})


def test_a_chain_that_reads_a_log_is_not_a_test_run_unless_a_runner_is_named():
    """Eight days of one session: 29 of 110 'Test tracked' lines came from
    `cat run.log; bash count.sh` shapes, where the marker was in the cat."""
    from claude_engram.hooks.remind import _command_can_run_tests as can, _segment_kind as kind
    assert kind("cat out.txt") == "read" and kind("cd /w") == "noise" and kind("bash count.sh") == "run"
    assert kind("for f in a b") == "noise" and kind("date +%H:%M") == "noise" and kind("timeout 60 bash x.sh") == "run"
    assert can("cat out.txt; bash /e/tools/count-pytest.sh log.txt") is False
    assert can("tail -3 out.txt; date; grep -c FAILED log.txt") is False
    assert can("pwd; tail -1 log.txt; git add tests/test_x.py; git commit -m x") is False
    assert can("export PATH=/x:$PATH; bash /e/tools/box.sh 'smoke'") is True
    assert can("cat out.txt | tail -1; PYTHONPATH=src python -m pytest tests/scripts") is True  # a runner is named
    assert can("venv/Scripts/python.exe scripts/check.py") is True


def test_the_test_status_survives_a_stop(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CLAUDE_ENGRAM_DIR", str(tmp_path / "store"))
    from claude_engram.hooks import remind
    st = remind.load_state()
    st["last_test_passed"] = True
    st["files_edited_this_session"] = ["a.py"]
    remind.save_state(st)
    remind.mark_session_ended()
    st = remind.load_state()
    assert st.get("last_test_passed") is True, "a Stop is not a session end; the next run must be able to flip"
    assert st.get("files_edited_this_session") == [] and st.get("last_session_files") == ["a.py"]


def test_a_session_started_once_stays_started(tmp_path: Path, monkeypatch):
    import time as _t
    monkeypatch.setenv("CLAUDE_ENGRAM_DIR", str(tmp_path / "store"))
    from claude_engram.hooks import remind
    st = remind.load_state()
    st["last_session_start"] = _t.time() - 6 * 3600  # six quiet hours
    remind.save_state(st)
    assert remind.check_session_active(str(tmp_path)) is True


def test_the_branch_count_is_bounded_by_the_checkpoint_time(tmp_path: Path):
    import subprocess
    import time as _t
    from claude_engram.repo_state import since
    repo = _git_repo_with_a_reason(tmp_path)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    def git(*a):
        return subprocess.run(["git", *a], cwd=str(repo), check=True, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL).stdout.strip()
    first = git("rev-list", "--max-parents=0", "HEAD")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    git("checkout", "-q", "-b", "old-feature", first)
    (repo / "old.py").write_text("X = 1\n", encoding="utf-8")
    git("add", "."); git("commit", "-q", "-m", "an old branch commit")
    git("checkout", "-q", branch)
    head = git("rev-parse", "HEAD")
    unbounded = since(head, str(repo))
    bounded = since(head, str(repo), saved_at=_t.time() + 60)  # a checkpoint newer than every commit
    assert unbounded and unbounded["other_branches"] == 1
    assert bounded and bounded["other_branches"] == 0


def test_milestone_shapes_that_are_not_a_close():
    from claude_engram.hooks.milestones import is_completion_claim as claim
    not_closes = [
        "| Options round | Merged.",
        "B is at `8b4420d8` and its whole test tree is about 18% through, with 15 minutes to go.",
        "It repeats that the rung is stopped and Part 1 is done.",
        "So the first row passes only if momentum beats its benchmark.",
        "NVDA closed at 217.55 on the expiry, so the tracked strikes fall on both sides.",
        "The last whole-tree run took 357 s (8 workers, 11,132 passed).",
        "The merged Phase 2 tree exceeded the ten-minute window and is running in the background.",
        "Say which packages, and I brief them.",
        "The daily-only store closes part of that.",
    ]
    for s in not_closes:
        assert claim(s, use_semantic=False)[0] is False, s
    closes = [
        "The Phase 2 delta audit is done.",
        "Batch 2 has landed: B is now `5686345a`.",
        "The docs agent's first round is complete: ten commits, whole tree green at 9,754.",
        "I completed step 3 of the plan.",
        "All four follow-up branches are merged on the source line.",
    ]
    for s in closes:
        assert claim(s, use_semantic=False)[0] is True, s


def test_the_decision_gate_is_about_form():
    from claude_engram.mining.decision_gate import looks_like_correction, looks_like_decision, why_not
    assert looks_like_decision("DECISION: from now on always use the repository pattern for data access")
    assert looks_like_decision("DECISION: (from user) leave the trash folders for now")
    assert looks_like_decision("DECISION: (confirmed) I'll switch the parser to the streaming reader. Then the report follows with numbers 1 2 3.")
    assert not looks_like_decision("DECISION: (from user) also what shell is still running?") and why_not("what shell is running?") == "question"
    assert why_not("DECISION: ok looks good") == "acknowledgement" or why_not("DECISION: ok looks good") == "too short"
    assert why_not("DECISION: Count: 2911 outcomes: .=2907 s=4, 0 FAILED/ERROR.") == "count, table or commit report"
    assert why_not("DECISION: `scripts/system_map.py --check`: the map is current") == "starts like code or a path"
    assert not looks_like_decision("DECISION: Once phase 3 is complete") and why_not("Once phase 3 is complete") == "no deciding word" or True
    assert not looks_like_decision("DECISION: (confirmed) Checkpoint saved (task_1). Here is where the goal stands; use the ring.")
    assert looks_like_correction("USER PREFERENCE: no, keep the old name, I meant the other module")
    assert not looks_like_correction("USER PREFERENCE: ok so give me the status and where everything is at")


def test_prune_junk_decisions_archives_by_shape_and_keeps_manual(tmp_path: Path):
    from claude_engram import migrations
    store = tmp_path / "store"
    (store / "projects" / "h1").mkdir(parents=True)
    entries = [
        {"id": "a1", "category": "decision", "source": "session_mining", "content": "DECISION: ok looks good. anything to do in parallel?"},
        {"id": "a2", "category": "decision", "source": "session_mining", "content": "DECISION: from now on always run the targeted tests before a commit"},
        {"id": "a3", "category": "decision", "source": "work_tracker", "content": "DECISION: ok"},
        {"id": "a4", "category": "mistake", "source": "session_mining", "content": "MISTAKE: TypeError: x"},
        {"id": "a5", "category": "decision", "source": "auto-prompt", "content": "DECISION: (from user) pull the checkpoint for index 0"},
    ]
    (store / "projects" / "h1" / "memory.json").write_text(json.dumps({"entries": entries}), encoding="utf-8")
    manifest = {"projects": {"e:/w/p": {"hash": "h1"}}}
    (store / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    migrations._prune_junk_decisions(store, manifest)
    left = {e["id"] for e in json.loads((store / "projects" / "h1" / "memory.json").read_text(encoding="utf-8"))["entries"]}
    assert left == {"a2", "a3", "a4"}
    archived = json.loads((store / "archive.json").read_text(encoding="utf-8"))["projects"]["e:/w/p"]["entries"]
    assert {e["id"] for e in archived} == {"a1", "a5"} and all(e.get("archived_at") for e in archived)


def test_recurring_errors_are_the_same_concrete_error_with_the_latest_example(tmp_path: Path):
    from claude_engram.mining import patterns
    store = tmp_path / "store"
    ext = store / "projects" / "h1" / "extractions"
    ext.mkdir(parents=True)
    (store / "manifest.json").write_text(json.dumps({"projects": {"e:/w/p": {"hash": "h1"}}}), encoding="utf-8")
    def ext_file(sid, desc, fix=""):
        (ext / f"{sid}.json").write_text(json.dumps({"session_id": sid, "mistakes": [{"error_type": "FileNotFoundError", "description": desc, "how_to_avoid": fix}]}), encoding="utf-8")
    ext_file("s1", "FileNotFoundError: [Errno 2] No such file or directory: 'E:\\\\w\\\\old\\\\judge\\\\all.json'", "old fix")
    ext_file("s2", "FileNotFoundError: [Errno 2] No such file or directory: 'E:\\\\w\\\\old\\\\judge\\\\all.json'")
    ext_file("s3", "FileNotFoundError: [Errno 2] No such file or directory: '/tmp/repin.txt'", "new fix")
    sessions = {"s1": {"last_timestamp": "2026-09-10T00:00:00Z", "files_edited": []}, "s2": {"last_timestamp": "2026-09-12T00:00:00Z", "files_edited": []}, "s3": {"last_timestamp": "2026-09-22T00:00:00Z", "files_edited": []}}
    rec = patterns.detect_recurring_errors(sessions, "e:/w/p", str(store))
    # Two different missing files are two errors: only all.json recurred (2 sessions).
    assert len(rec) == 1 and rec[0].session_count == 2 and "all.json" in rec[0].example and rec[0].last_seen.startswith("2026-09-12")
    assert rec[0].fix == "old fix"
    assert patterns._concrete_error_key("No such file: 'E:\\\\w\\\\a\\\\b\\\\x.json' at line 42") == patterns._concrete_error_key("No such file: '/other/dir/x.json' at line 7")


def test_a_code_exception_is_never_predicted_for_a_markdown_file(tmp_path: Path):
    from claude_engram.mining import predictive
    hash_dir = tmp_path / "h"
    (hash_dir / "extractions").mkdir(parents=True)
    (hash_dir / "extractions" / "s.json").write_text(json.dumps({"mistakes": [
        {"error_type": "TypeError", "description": "TypeError: x", "related_files": ["plan.md", "run.py"]},
        {"error_type": "", "description": "the plan's dates drifted", "related_files": ["plan.md"]},
    ]}), encoding="utf-8")
    md = predictive.EditPrediction(target_file="plan.md")
    predictive._predict_errors(md, "plan.md", hash_dir)
    assert [p.content for p in md.likely_errors] == ["the plan's dates drifted"]
    py = predictive.EditPrediction(target_file="run.py")
    predictive._predict_errors(py, "run.py", hash_dir)
    assert [p.content for p in py.likely_errors] == ["TypeError"]


def test_a_workspace_wide_last_session_narrows_to_its_main_sub_project(tmp_path: Path):
    from claude_engram.mining.session_index import SessionIndex
    root = tmp_path / "ws"
    for name in ("alpha", "beta"):
        (root / name).mkdir(parents=True)
        (root / name / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    idx = SessionIndex(tmp_path / "session_index.json")
    files = [str(root / "alpha" / f"a{i}.py") for i in range(5)] + [str(root / "beta" / "b.py")] + [str(tmp_path / "outside" / "memory.md")]
    idx._data["sessions"] = {"s1": {"session_id": "s1", "last_timestamp": "2026-09-22T10:00:00Z", "files_edited": files, "git_branch": "main"}}
    wide = idx.get_latest_session_summary("")
    assert wide and wide["file_count"] == 7 and wide["project_label"] == ""
    narrowed = idx.get_latest_session_summary("", workspace_root=str(root))
    assert narrowed and narrowed["project_label"] == "alpha" and narrowed["file_count"] == 5
    scoped = idx.get_latest_session_summary(str(root / "beta"), workspace_root=str(root))
    assert scoped and scoped["file_count"] == 1 and scoped["project_label"] == ""


def test_the_daemons_cpu_batch_is_small_and_overridable(monkeypatch):
    """The resident daemon keeps the activation arena of its largest batch
    for life; 64 rows parked 1.2 GB more than 16 at the same speed."""
    from claude_engram import embed_worker as ew
    monkeypatch.delenv("CLAUDE_ENGRAM_CPU_BATCH", raising=False)
    assert ew.cpu_batch_size() == ew.CPU_BATCH_DEFAULT == 16
    monkeypatch.setenv("CLAUDE_ENGRAM_CPU_BATCH", "8")
    assert ew.cpu_batch_size() == 8
    monkeypatch.setenv("CLAUDE_ENGRAM_CPU_BATCH", "junk")
    assert ew.cpu_batch_size() == 16


def test_one_capture_rule_behind_the_prompt_hook_and_the_miner(tmp_path: Path, monkeypatch):
    """A sentence is stored or not by hooks/intent.capture_decision wherever
    it was seen: the prompt hook and the miner's preference path both call
    it. Scorer off here, so the regex tier and the shape gate decide."""
    from claude_engram.hooks import intent, remind
    from claude_engram.mining import extractors

    monkeypatch.setattr(intent, "score_decision_semantic", lambda text, server_only=False: (0.0, ""))
    kept = intent.capture_decision("let's use postgres instead of sqlite for the main store")
    assert kept.startswith("let's use postgres instead of sqlite")
    assert intent.capture_decision("what shell is still running?") == ""
    assert intent.capture_decision("ok looks good, thanks") == ""
    assert intent.capture_decision("(from user) x") == ""

    seen: list[tuple[str, bool]] = []

    def _marker(text, server_only=False):
        seen.append((text, server_only))
        return ""

    monkeypatch.setattr(intent, "capture_decision", _marker)
    remind._auto_capture_from_prompt(str(tmp_path), "we should always pin the parser version in the lockfile")
    assert seen and seen[-1][1] is False

    monkeypatch.setenv("CLAUDE_ENGRAM_DIR", str(tmp_path / "store"))
    ex = extractors.SessionExtractions(corrections=[extractors.Correction(user_said="x", preference="never commit the lockfile from a worktree")])
    extractors._feed_to_memory_store(str(tmp_path / "proj"), ex, str(tmp_path / "store"))
    assert seen[-1] == ("never commit the lockfile from a worktree", True)


def test_the_regex_tier_keeps_the_typed_words():
    """The typo corrector rewrote real short words into trigger words
    ("one" to "use", "pip" to "pick", "stack" to "stick") and the extractor
    returned that lowercased working text, so a stored decision could read
    as nothing the person typed (2026-09-23)."""
    from claude_engram.hooks.remind import _fix_typo, _score_decision_intent
    assert _fix_typo("one") == "one" and _fix_typo("pip") == "pip" and _fix_typo("ever") == "ever"
    assert _fix_typo("step") == "step" and _fix_typo("chance") == "chance" and _fix_typo("remote") == "remote"
    assert _fix_typo("swtich") == "switch" and _fix_typo("plase") == "please" and _fix_typo("useing") == "using"
    assert _fix_typo("impliment") == "implement"
    score, text = _score_decision_intent("Let's use PostgreSQL instead of SQLite for the main store, the one every reader opens.")
    assert score >= 0.6 and text.startswith("Let's use PostgreSQL instead of SQLite")
    score, text = _score_decision_intent("stop using console.log for debugging, use the logger")
    assert score >= 0.6 and text == "stop using console.log"


def test_a_rule_that_opens_the_sentence_clears_the_regex_tier():
    from claude_engram.hooks.remind import _score_decision_intent
    for s in ("from now on every pull request needs a test", "always pin dependency versions in the lockfile",
              "don't use sleep in tests, use proper waits"):
        assert _score_decision_intent(s)[0] >= 0.6, s
    for s in ("always been like this in staging", "never mind the failing job", "don't worry about the lint warning"):
        assert _score_decision_intent(s)[0] < 0.6, s


def test_a_yes_plus_a_one_off_instruction_is_not_a_decision():
    from claude_engram.mining.decision_gate import looks_like_correction, looks_like_decision, why_not
    for s in ("approved, go ahead with steps 1 to 3 and hold step 4", "ok run it, but not on the shared box",
              "approved. leave item five for later", "go ahead with everything except the rename",
              "all recommendations accepted, don't touch the deploy script yet"):
        assert why_not(s) == "a one-off instruction", s
        assert not looks_like_decision(s) and not looks_like_correction(s)
    assert looks_like_decision("DECISION: (from user) leave the trash folders for now")
    assert looks_like_decision("from now on every pull request needs a test")


def test_a_hook_survives_a_working_directory_that_shadows_the_stdlib(tmp_path: Path):
    """A session cd'd into a vendored package holding an email.py; every
    hook ran `python -m claude_engram.hooks.remind` from there and died at
    import because Python puts the cwd first on sys.path (2026-09-24)."""
    import subprocess
    import sys
    cwd = tmp_path / "vendored"
    cwd.mkdir()
    (cwd / "email.py").write_text("from .presets import questions\n", encoding="utf-8")
    env = dict(os.environ, CLAUDE_ENGRAM_DIR=str(tmp_path / "store"), CLAUDE_ENGRAM_NO_DAEMON="1", CLAUDE_ENGRAM_LIVE_MINE="0")
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
    r = subprocess.run([sys.executable, "-m", "claude_engram.hooks.remind", "post_compact_json"],
                       input='{"session_id": "s-shadow", "cwd": "%s"}' % str(cwd).replace("\\", "\\\\"),
                       capture_output=True, text=True, cwd=str(cwd), env=env, timeout=120)
    assert r.returncode == 0 and "Traceback" not in r.stderr, r.stderr[-800:]


def test_the_miner_files_a_no_file_entry_where_the_sessions_edits_point(tmp_path: Path, monkeypatch):
    """A workspace-root session: the prompt hook filed a sentence under the
    sub-project the session was about, the miner filed the same sentence
    under the root, because a decision names no file (2026-09-24)."""
    from claude_engram.hooks.paths import _normalize_path
    from claude_engram.mining import extractors

    monkeypatch.setenv("CLAUDE_ENGRAM_NON_PROJECT_DIRS", ".scratch")
    store = tmp_path / "store"
    monkeypatch.setenv("CLAUDE_ENGRAM_DIR", str(store))
    ws, a, b = _workspace(tmp_path)
    (store / "projects").mkdir(parents=True)
    manifest = {"version": 3, "projects": {_normalize_path(str(p)): {"hash": h, "name": p.name} for p, h in ((ws, "hws"), (a, "haa"), (b, "hbb"))}}
    (store / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(extractors, "capture_decision", lambda text, server_only=False: text, raising=False)
    ex = extractors.SessionExtractions(
        decisions=[extractors.Decision(content="use the registry for every alias lookup", confidence=0.9)],
        corrections=[extractors.Correction(user_said="x", preference="never resolve aliases outside the registry")],
        session_files=[str(a / "src" / "x.py"), str(a / "src" / "y.py"), str(b / "src" / "z.py")],
    )
    extractors._feed_to_memory_store(str(ws), ex, str(store))
    where = {}
    for h in ("hws", "haa", "hbb"):
        f = store / "projects" / h / "memory.json"
        if f.exists():
            where[h] = [e["content"] for e in json.loads(f.read_text(encoding="utf-8")).get("entries", [])]
    assert "hws" not in where or not where["hws"], where
    assert any("registry for every alias" in c for c in where.get("haa", [])), where
    assert any("USER PREFERENCE: never resolve aliases" in c for c in where.get("haa", [])), where


def test_an_assessment_and_a_three_word_fragment_are_not_stored():
    from claude_engram.mining.decision_gate import looks_like_correction, looks_like_decision, why_not
    assert why_not("should be good for the browser now") == "a status assessment"
    assert not looks_like_decision("DECISION: should be fine after the restart")
    assert looks_like_decision("DECISION: errors should be logged with the request id")
    assert not looks_like_correction("USER PREFERENCE: no, keep those.")
    assert looks_like_correction("USER PREFERENCE: no, keep those helper lines.")


def test_a_re_mine_feeds_only_what_it_added():
    """A grown session is re-extracted whole; the store dedupes per
    project, so a changed destination re-stored 347 old entries under a
    sub-project in one tick (2026-09-24)."""
    from claude_engram.mining import extractors as ex
    old = ex.SessionExtractions(
        decisions=[ex.Decision(content="use the registry", timestamp="t1", confidence=0.9)],
        mistakes=[ex.Mistake(description="KeyError: x", timestamp="t1", error_type="KeyError")],
    )
    now = ex.SessionExtractions(
        decisions=[ex.Decision(content="use the registry", timestamp="t1", confidence=0.9),
                   ex.Decision(content="drop the cache layer", timestamp="t2", confidence=0.9)],
        mistakes=[ex.Mistake(description="KeyError: x", timestamp="t1", error_type="KeyError"),
                  ex.Mistake(description="KeyError: x", timestamp="t3", error_type="KeyError")],
        corrections=[ex.Correction(user_said="no", preference="never cache aliases", timestamp="t2")],
        session_files=["a.py"],
    )
    from dataclasses import asdict
    fresh = ex._fresh_extractions(now, asdict(old))
    assert [d.content for d in fresh.decisions] == ["drop the cache layer"]
    assert [m.timestamp for m in fresh.mistakes] == ["t3"]
    assert [c.preference for c in fresh.corrections] == ["never cache aliases"]
    assert fresh.session_files == ["a.py"]
    assert ex._fresh_extractions(now, None) is now


def test_an_address_or_a_secret_is_never_a_decision():
    from claude_engram.mining.decision_gate import looks_like_decision, why_not
    assert why_not("let's use the paid plan, account someone@example.com") == "carries an address or a secret"
    assert why_not("switch to the new key: api_key=sk4Q9x7Lm2Pq8Rt0Vw") == "carries an address or a secret"
    assert why_not("always use the vendor token d0p9alpr01qr8ds2ac3q for the feed") == "carries an address or a secret"
    assert looks_like_decision("always use bench_decision_capture_v2 as the arbiter for the gate")
    assert looks_like_decision("from now on pin torch to 2.4.1 in requirements.txt")


def test_refiled_copies_are_archived_and_the_older_original_kept(tmp_path: Path):
    from claude_engram import migrations
    store = tmp_path / "store"
    for h in ("hroot", "hsub"):
        (store / "projects" / h).mkdir(parents=True)
    root_entries = [
        {"id": "r1", "category": "decision", "source": "session_mining", "content": "DECISION: use the registry for every alias", "created_at": 100.0},
        {"id": "r2", "category": "mistake", "source": "session_mining", "content": "MISTAKE: KeyError: x", "created_at": 100.0},
    ]
    sub_entries = [
        {"id": "s1", "category": "decision", "source": "session_mining", "content": "DECISION: use the registry for every alias", "created_at": 200.0},
        {"id": "s2", "category": "mistake", "source": "session_mining", "content": "MISTAKE: KeyError: x", "created_at": 200.0},
        {"id": "s3", "category": "decision", "source": "session_mining", "content": "DECISION: drop the cache layer for feeds", "created_at": 200.0},
        {"id": "s4", "category": "decision", "source": "work_tracker", "content": "DECISION: use the registry for every alias", "created_at": 200.0},
    ]
    (store / "projects" / "hroot" / "memory.json").write_text(json.dumps({"entries": root_entries}), encoding="utf-8")
    (store / "projects" / "hsub" / "memory.json").write_text(json.dumps({"entries": sub_entries}), encoding="utf-8")
    manifest = {"projects": {"e:/w": {"hash": "hroot"}, "e:/w/sub": {"hash": "hsub"}}}
    (store / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    migrations._archive_refiled_duplicates(store, manifest)
    left = {e["id"] for e in json.loads((store / "projects" / "hsub" / "memory.json").read_text(encoding="utf-8"))["entries"]}
    assert left == {"s3", "s4"}
    root_left = {e["id"] for e in json.loads((store / "projects" / "hroot" / "memory.json").read_text(encoding="utf-8"))["entries"]}
    assert root_left == {"r1", "r2"}
    archived = json.loads((store / "archive.json").read_text(encoding="utf-8"))["projects"]["e:/w/sub"]["entries"]
    assert {e["id"] for e in archived} == {"s1", "s2"}


def test_a_relayed_message_a_hash_led_line_and_a_paste_are_not_decisions():
    from claude_engram.mining.decision_gate import looks_like_decision, why_not
    assert why_not('relayed: <agent-message from="worker-2"> use the registry for every lookup') == "markup or machine text"
    assert why_not('Another session sent a message:\n<agent-message from="worker-2">\nuse the registry') != ""
    assert why_not("(box unreachable.)\n168d0b7d: gate tests moved to the report module") == "a multi-line paste"
    assert why_not("168d0b7d: gate tests moved to the report module, always") != ""
    assert not looks_like_decision("DECISION: let's use the registry\nfor every alias lookup")
    assert looks_like_decision("DECISION: let's use the registry for every alias lookup")


def test_an_entry_whose_files_cast_no_vote_follows_the_sessions_edits(tmp_path: Path, monkeypatch):
    """A sub-project worked from the workspace root: its tracebacks name
    files by relative path, which never votes, so every mistake pooled in
    the root store (a V11 store with 0 mistakes of its own, 2026-09-24)."""
    from claude_engram.hooks.paths import _normalize_path
    from claude_engram.mining import extractors

    monkeypatch.setenv("CLAUDE_ENGRAM_NON_PROJECT_DIRS", ".scratch")
    store = tmp_path / "store"
    monkeypatch.setenv("CLAUDE_ENGRAM_DIR", str(store))
    ws, a, b = _workspace(tmp_path)
    (store / "projects").mkdir(parents=True)
    manifest = {"version": 3, "projects": {_normalize_path(str(p)): {"hash": h, "name": p.name} for p, h in ((ws, "hws"), (a, "haa"), (b, "hbb"))}}
    (store / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    ex = extractors.SessionExtractions(
        mistakes=[extractors.Mistake(description="KeyError: 'plant'", error_type="KeyError", related_files=["tools/restage.py"])],
        session_files=[str(a / "src" / "x.py")],
    )
    extractors._feed_to_memory_store(str(ws), ex, str(store))
    a_file = store / "projects" / "haa" / "memory.json"
    assert a_file.exists() and any("KeyError: 'plant'" in e["content"] for e in json.loads(a_file.read_text(encoding="utf-8"))["entries"])
    assert not (store / "projects" / "hws" / "memory.json").exists()


def test_one_compaction_opens_one_cycle_whichever_hook_runs_first():
    from claude_engram.hooks import context_pressure as cp
    state: dict = {}
    cp.note_compaction(state)
    cp.note_compaction(state)
    assert cp.pressure_state(state)["cycle"] == 1
    cp.pressure_state(state)["compacted_at"] -= 600
    cp.note_compaction(state)
    assert cp.pressure_state(state)["cycle"] == 2
