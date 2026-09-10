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
