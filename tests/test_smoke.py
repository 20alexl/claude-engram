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
    ev = autorun.observe(state, str(t), str(tmp_path), turn=True)
    assert ev and ev["event"] == "ended" and state["run"]["auto"]["status"] == "met"
    assert autorun.env_or_state_autonomy(state) is False


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


def test_mined_entries_file_under_the_project_their_files_name(tmp_path: Path):
    from claude_engram.hooks.paths import target_project_for_files, _normalize_path

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


def test_reattribute_pooled_moves_entries_keeping_identity(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CLAUDE_ENGRAM_DIR", str(tmp_path / "store"))
    from claude_engram import migrations
    from claude_engram.tools.memory import MemoryStore

    ws, a, b = _workspace(tmp_path)
    store = MemoryStore(storage_dir=str(tmp_path / "store"))
    store.remember_discovery(str(ws), "MISTAKE: KeyError in a", category="mistake", source="session_mining",
                             relevance=8, related_files=[str(a / "src" / "x.py")], auto_embed=False)
    store.remember_discovery(str(ws), "DECISION: b uses sqlite", category="decision", source="session_mining",
                             relevance=7, related_files=[str(b / "src" / "y.py")], auto_embed=False)
    store.remember_discovery(str(ws), "MISTAKE: no file named", category="mistake", source="session_mining",
                             relevance=8, auto_embed=False)
    store.remember_discovery(str(ws), "MISTAKE: a person's own note", category="mistake", source="work_tracker",
                             relevance=8, related_files=[str(a / "src" / "x.py")], auto_embed=False)
    root = store.get_project(str(ws))
    assert root is not None and len(root.entries) == 4
    ids = {e.content: (e.id, e.created_at) for e in root.entries}

    manifest = json.loads((tmp_path / "store" / "manifest.json").read_text(encoding="utf-8"))
    migrations._reattribute_pooled(tmp_path / "store", manifest)

    fresh = MemoryStore(storage_dir=str(tmp_path / "store"))
    root = fresh.get_project(str(ws))
    pa, pb = fresh.get_project(str(a)), fresh.get_project(str(b))
    assert root is not None and pa is not None and pb is not None
    assert sorted(e.content for e in root.entries) == ["MISTAKE: a person's own note", "MISTAKE: no file named"]
    assert [e.content for e in pa.entries] == ["MISTAKE: KeyError in a"]
    assert [e.content for e in pb.entries] == ["DECISION: b uses sqlite"]
    moved = pa.entries[0]
    assert (moved.id, moved.created_at) == ids["MISTAKE: KeyError in a"]
    # idempotent
    migrations._reattribute_pooled(tmp_path / "store", manifest)
    again = MemoryStore(storage_dir=str(tmp_path / "store")).get_project(str(a))
    assert again is not None and len(again.entries) == 1


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
