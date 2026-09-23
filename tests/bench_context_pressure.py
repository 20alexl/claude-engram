"""
Benchmark: context pressure -- distance to the compaction point and the
checkpoint nudges keyed on it (hooks/context_pressure.py).

Hooks get no context-usage numbers; the statusline does. The statusline
mirrors them to a per-session file and the hooks compute how far the session
is from where auto-compaction fires. Everything here is a DISTANCE to that
point, never a raw percent: the statusline's used_percentage is against the
full 200K/1M window, but a native-1M model compacts at ~967K by default and
CLAUDE_CODE_AUTO_COMPACT_WINDOW / autoCompactWindow can move the point.

What must hold:
  1. autoCompactWindow parsing accepts every documented form.
  2. compaction_point precedence: env > settings > model default; capped at
     the window; the two model defaults (200K boundary, ~967K).
  3. Thresholds sit BELOW the point (10% / 3% of the window; 5% on 200K).
  4. The statusline mirror round-trips and is keyed by session_id.
  5. The nudge fires once per band per compaction cycle, in order
     (heads-up, then checkpoint), never twice, and re-arms after PostCompact.
  6. A mirror written before the last compaction is ignored (it still shows
     the pre-compaction count) -- no false checkpoint-now right after compact.
  7. The cadence nudge fires after N stops and a deliberate save resets it.
  8. The shipped `statusline` subcommand records the mirror and prints a line.
  9. Source guards: every main-session injection site in remind.py attaches
     the nudge, and checkpoint_save notes the deliberate save.
 10. Provenance: a manual checkpoint_save then restore prints the From line
     (it used to store project_path only under metadata, so a same-ring
     restore printed no origin at all).

Run: venv/Scripts/python.exe tests/bench_context_pressure.py
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
        "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
        "CLAUDE_ENGRAM_HEADSUP_FRACTION",
        "CLAUDE_ENGRAM_OUTPUT_RESERVE",
        "CLAUDE_ENGRAM_CHECKPOINT_MARGIN",
        "CLAUDE_ENGRAM_CHECKPOINT_CADENCE",
    ):
        os.environ.pop(k, None)
    # The user's real ~/.claude/settings.json may carry autoCompactWindow
    # (it does on the author's machine since /autocompact 750k); point the
    # user-settings lookup at an empty config dir so defaults are defaults.
    cfg = Path(tempfile.gettempdir()) / "engram-bench-empty-config"
    cfg.mkdir(parents=True, exist_ok=True)
    os.environ["CLAUDE_CONFIG_DIR"] = str(cfg)


def test_parse_window_value(cp):
    print("autoCompactWindow forms:")
    cases = [
        (200000, 200000),
        ("200000", 200000),
        ("500k", 500_000),
        ("500K", 500_000),
        ("1M", 1_000_000),
        (200, 200_000),  # bare 100..1000 = thousands
        ("750", 750_000),
        (None, None),
        (True, None),
        ("", None),
        ("auto", None),
    ]
    for raw, want in cases:
        check(f"parse {raw!r} -> {want}", cp.parse_window_value(raw) == want)


def test_compaction_point(cp, tmp):
    print("compaction point precedence and defaults:")
    _clean_env()
    proj = tmp / "proj"
    (proj / ".claude").mkdir(parents=True, exist_ok=True)
    check("1M model default is ~967K", cp.compaction_point(1_000_000, str(proj)) == (967_000, "model-default"))
    check("200K model default is the boundary", cp.compaction_point(200_000, str(proj)) == (200_000, "model-default"))

    (proj / ".claude" / "settings.json").write_text(json.dumps({"autoCompactWindow": "500k"}), encoding="utf-8")
    check("settings autoCompactWindow read", cp.compaction_point(1_000_000, str(proj)) == (500_000, "settings"))

    # Managed (enterprise) settings outrank every project and user file;
    # drop-ins in managed-settings.d/ merge alphabetically, later wins.
    managed = tmp / "managed"
    (managed / "managed-settings.d").mkdir(parents=True, exist_ok=True)
    _orig_dir, _orig_reg = cp._managed_dir, cp._managed_registry
    cp._managed_dir = lambda: managed
    cp._managed_registry = lambda: {}
    try:
        (managed / "managed-settings.json").write_text(json.dumps({"autoCompactWindow": "600k"}), encoding="utf-8")
        check("managed file beats the project setting", cp.compaction_point(1_000_000, str(proj)) == (600_000, "managed"))
        (managed / "managed-settings.d" / "10-base.json").write_text(json.dumps({"autoCompactWindow": "620k"}), encoding="utf-8")
        (managed / "managed-settings.d" / "20-team.json").write_text(json.dumps({"autoCompactWindow": "650k"}), encoding="utf-8")
        check("the last drop-in wins", cp.compaction_point(1_000_000, str(proj)) == (650_000, "managed"))
        cp._managed_registry = lambda: {"autoCompactWindow": 700000}
        check("the registry policy outranks the files", cp.compaction_point(1_000_000, str(proj)) == (700_000, "managed"))
        os.environ["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = "800000"
        check("the env var still wins over managed", cp.compaction_point(1_000_000, str(proj)) == (800_000, "env"))
        os.environ.pop("CLAUDE_CODE_AUTO_COMPACT_WINDOW", None)
    finally:
        cp._managed_dir, cp._managed_registry = _orig_dir, _orig_reg
    (proj / ".claude" / "settings.local.json").write_text(json.dumps({"autoCompactWindow": 300}), encoding="utf-8")
    check("settings.local beats settings", cp.compaction_point(1_000_000, str(proj)) == (300_000, "settings"))
    check("settings capped at the window", cp.compaction_point(200_000, str(proj)) == (200_000, "settings"))

    os.environ["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = "750000"
    check("env beats settings", cp.compaction_point(1_000_000, str(proj)) == (750_000, "env"))
    os.environ["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = "2000000"
    check("env capped at the window", cp.compaction_point(1_000_000, str(proj)) == (1_000_000, "env"))
    os.environ["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = "500"  # env is plain count only; below 100K = ignored
    check("env below the documented minimum is ignored", cp.compaction_point(1_000_000, str(proj))[1] == "settings")
    os.environ["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = "banana"
    check("env garbage is ignored", cp.compaction_point(1_000_000, str(proj))[1] == "settings")
    _clean_env()


def test_thresholds(cp):
    print("thresholds sit below the point:")
    _clean_env()
    # Auto-compaction fires BELOW the setting: measured 717,578 pre-compaction
    # tokens against a 750K setting (2026-09-10), i.e. the output reserve.
    th = cp.thresholds(1_000_000, 750_000)
    check("1M/750K: trigger at 718K (setting minus the 32K reserve)", th["trigger_at"] == 718_000)
    check("1M/750K: checkpoint at 698K (20K above the trigger)", th["checkpoint_at"] == 698_000)
    check("1M/750K: heads-up at 650K", th["headsup_at"] == 650_000)
    check("the measured compaction (717,578) sits ABOVE the checkpoint band", th["checkpoint_at"] < 717_578 < th["trigger_at"] + 1_000)
    th = cp.thresholds(1_000_000, 967_000)
    check("1M default: heads-up at 867K", th["headsup_at"] == 867_000)
    check("1M default: checkpoint at 915K", th["checkpoint_at"] == 915_000)
    th = cp.thresholds(200_000, 200_000)
    check("200K: trigger at 168K, checkpoint at 158K (10K margin)", th["trigger_at"] == 168_000 and th["checkpoint_at"] == 158_000)
    check("200K: heads-up pulled under the checkpoint band", th["headsup_at"] == 148_000 and th["headsup_at"] < th["checkpoint_at"])
    os.environ["CLAUDE_ENGRAM_OUTPUT_RESERVE"] = "40000"
    check("output reserve env override", cp.thresholds(1_000_000, 750_000)["trigger_at"] == 710_000)
    os.environ["CLAUDE_ENGRAM_CHECKPOINT_MARGIN"] = "30000"
    check("checkpoint margin env override", cp.thresholds(1_000_000, 750_000)["checkpoint_at"] == 680_000)
    os.environ["CLAUDE_ENGRAM_OUTPUT_RESERVE"] = "junk"  # nonsense -> default
    os.environ["CLAUDE_ENGRAM_CHECKPOINT_MARGIN"] = "-5"
    check("garbage env -> defaults", cp.thresholds(1_000_000, 750_000)["checkpoint_at"] == 698_000)
    _clean_env()


def _payload(sid, used, window=1_000_000, model="Claude Fable 5.1"):
    return {
        "session_id": sid,
        "model": {"id": "claude-fable-5-1", "display_name": model},
        "context_window": {
            "total_input_tokens": used,
            "context_window_size": window,
            "used_percentage": 100.0 * used / window,
        },
        "cost": {"total_cost_usd": 1.25},
        "cwd": "E:/ws/proj",
    }


def test_mirror(cp):
    print("statusline mirror:")
    p = cp.record_statusline(_payload("s-1", 123_456))
    check("record returns the mirror path", p is not None and p.name == "s-1.ctx.json")
    m = cp.read_mirror("s-1")
    check("mirror round-trips tokens", m is not None and m["total_input_tokens"] == 123_456)
    check("mirror round-trips window", m is not None and m["context_window_size"] == 1_000_000)
    check("mirror carries a timestamp", m is not None and abs(time.time() - m["ts"]) < 5)
    check("no session_id -> nothing recorded", cp.record_statusline({"context_window": {}}) is None)
    check("unknown session reads None", cp.read_mirror("nope") is None)
    check("empty session reads None", cp.read_mirror("") is None)


def test_assess(cp):
    print("assessment bands:")
    _clean_env()
    os.environ["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = "750000"
    a = cp.assess({"total_input_tokens": 600_000, "context_window_size": 1_000_000, "ts": time.time()})
    check("600K of 750K -> clear", a["band"] == "clear" and a["distance"] == 150_000)
    a = cp.assess({"total_input_tokens": 660_000, "context_window_size": 1_000_000, "ts": time.time()})
    check("660K -> headsup", a["band"] == "headsup")
    a = cp.assess({"total_input_tokens": 725_000, "context_window_size": 1_000_000, "ts": time.time()})
    check("725K -> checkpoint", a["band"] == "checkpoint")
    a = cp.assess({"total_input_tokens": 0, "context_window_size": 1_000_000, "ts": time.time()})
    check("0 tokens -> nodata", a["band"] == "nodata")
    check("no mirror -> nodata", cp.assess(None)["band"] == "nodata")
    _clean_env()


def test_nudge_sequence(cp):
    print("nudge latching across a compaction cycle:")
    _clean_env()
    os.environ["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = "750000"
    sid = "s-nudge"
    state: dict = {"last_session_start": time.time()}

    cp.record_statusline(_payload(sid, 400_000))
    t, ch = cp.nudge(state, sid)
    check("clear band: no text, no change", t == "" and not ch)

    cp.record_statusline(_payload(sid, 660_000))
    t, ch = cp.nudge(state, sid)
    check("heads-up fires once", "Context pressure" in t and "Compaction #1 is coming" in t and ch)
    check("heads-up names the checkpoint point", "~698K" in t)
    t2, ch2 = cp.nudge(state, sid)
    check("heads-up does not repeat", t2 == "" and not ch2)

    cp.record_statusline(_payload(sid, 700_000))
    t, ch = cp.nudge(state, sid)
    check("checkpoint-now fires", t.startswith("<engram-context>CHECKPOINT NOW") and ch)
    check("checkpoint-now says the distance to the trigger", "18K tokens to the auto-compaction trigger (~718K; the 750K setting minus the output reserve)" in t)
    t2, _ = cp.nudge(state, sid)
    check("checkpoint-now does not repeat", t2 == "")
    check("checkpoint-now text names the tool call", "context(checkpoint_save)" in t)

    # Compaction. The mirror still holds 700K until the statusline re-runs.
    time.sleep(0.02)
    cp.note_compaction(state)
    a = cp.current_assessment(state, sid)
    check("pre-compaction mirror ignored after compact", a["band"] == "nodata" and "predates" in a["reason"])
    t, ch = cp.nudge(state, sid)
    check("no false checkpoint-now right after compaction", t == "")
    r = cp.rhythm_text(state, sid)
    check("rhythm line after compaction", r.startswith("Compaction #1.") and "checkpoint at ~698K" in r and "auto-compaction at ~718K (the 750K env setting minus the output reserve)" in r)

    # Fresh reading in the new cycle.
    time.sleep(0.02)
    cp.record_statusline(_payload(sid, 120_000))
    t, _ = cp.nudge(state, sid)
    check("new cycle at 120K: clear", t == "")
    cp.record_statusline(_payload(sid, 660_000))
    t, _ = cp.nudge(state, sid)
    check("new cycle: heads-up re-arms", "Compaction #2 is coming" in t)
    cp.record_statusline(_payload(sid, 730_000))
    t, _ = cp.nudge(state, sid)
    check("new cycle: checkpoint-now re-arms", "CHECKPOINT NOW" in t)

    # Skipping straight into the checkpoint band latches heads-up too.
    state2: dict = {"last_session_start": time.time()}
    sid2 = "s-jump"
    cp.record_statusline(_payload(sid2, 740_000))
    t, _ = cp.nudge(state2, sid2)
    check("jump to checkpoint band: checkpoint text only", "CHECKPOINT NOW" in t and "Context pressure:" not in t)
    cp.record_statusline(_payload(sid2, 745_000))
    t, _ = cp.nudge(state2, sid2)
    check("jump: heads-up does not fire late", t == "")
    _clean_env()


def test_cadence(cp):
    print("fallback cadence and the deliberate-save reset:")
    _clean_env()
    check("fallback cadence is a long fuse, not a schedule", cp.CADENCE_STOPS >= 50)
    os.environ["CLAUDE_ENGRAM_CHECKPOINT_CADENCE"] = "3"
    sid = "s-cadence"
    state: dict = {"last_session_start": time.time()}
    cp.record_statusline(_payload(sid, 100_000))
    for _ in range(2):
        cp.note_stop(state)
    t, _ = cp.nudge(state, sid)
    check("below cadence: silent", t == "")
    cp.note_stop(state)
    t, ch = cp.nudge(state, sid)
    check("at cadence: fires", "Checkpoint fallback: 3 turns" in t and ch)
    t, _ = cp.nudge(state, sid)
    check("cadence re-arms (counter reset), silent right after", t == "")
    for _ in range(3):
        cp.note_stop(state)
    t, _ = cp.nudge(state, sid)
    check("fires again after another full cadence", "Checkpoint fallback" in t)
    for _ in range(2):
        cp.note_stop(state)
    cp.note_manual_checkpoint(state)
    cp.note_stop(state)
    t, _ = cp.nudge(state, sid)
    check("deliberate save resets the count", t == "" and state["pressure"]["stops_since_checkpoint"] == 1)
    # A band nudge takes the slot; the cadence waits.
    os.environ["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = "750000"
    for _ in range(3):
        cp.note_stop(state)
    cp.record_statusline(_payload(sid, 660_000))
    t, _ = cp.nudge(state, sid)
    check("band nudge wins the slot over cadence", "Context pressure" in t and "cadence" not in t.lower())
    _clean_env()


def test_not_recording(cp, tmp):
    print("statusline configured but silent:")
    proj = tmp / "proj-nr"
    (proj / ".claude").mkdir(parents=True, exist_ok=True)
    (proj / ".claude" / "settings.json").write_text(json.dumps({"statusLine": {"type": "command", "command": "x"}}), encoding="utf-8")
    state = {"last_session_start": time.time() - 10}
    t, _ = cp.nudge(state, "s-silent", str(proj))
    check("young session: no announcement yet", t == "")
    state = {"last_session_start": time.time() - cp.NOT_RECORDING_AFTER_SECS - 1}
    t, ch = cp.nudge(state, "s-silent", str(proj))
    check("old session, no mirror: announced once", "no context reading has arrived" in t and ch)
    t, _ = cp.nudge(state, "s-silent", str(proj))
    check("announced only once", t == "")
    check("session_start_text silent when a statusLine exists", cp.session_start_text(str(proj)) == "")
    bare = tmp / "proj-bare"
    bare.mkdir(exist_ok=True)
    check("session_start_text names the gap without one", "no statusLine configured" in cp.session_start_text(str(bare)) or cp.statusline_configured(str(bare)))


def test_cli(tmp):
    print("shipped statusline subcommand:")
    env = dict(os.environ, CLAUDE_ENGRAM_DIR=str(tmp), CLAUDE_CODE_AUTO_COMPACT_WINDOW="750000")
    r = subprocess.run(
        [sys.executable, "-m", "claude_engram.hooks.context_pressure", "statusline"],
        input=json.dumps(_payload("s-cli", 600_000)),
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env=env,
        timeout=60,
    )
    check("exit 0", r.returncode == 0)
    check("prints a status line", "ctx 600K/1000K" in r.stdout and "compact at 750K (150K left)" in r.stdout)
    check("mirror written by the CLI", (tmp / "sessions" / "s-cli.ctx.json").is_file())
    r = subprocess.run(
        [sys.executable, "-m", "claude_engram.hooks.context_pressure", "assess", "s-cli"],
        capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=60,
    )
    check("assess subcommand reports the band", r.returncode == 0 and '"band": "clear"' in r.stdout)
    r = subprocess.run(
        [sys.executable, "-m", "claude_engram.hooks.context_pressure", "statusline"],
        input="not json", capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=60,
    )
    check("garbage stdin still exits 0 (a statusline must keep rendering)", r.returncode == 0)


def test_source_guards():
    print("source guards:")
    remind_src = (ROOT / "claude_engram" / "hooks" / "remind.py").read_text(encoding="utf-8")
    n = len(re.findall(r"_with_pressure\(result, project_dir\)", remind_src))
    check(f"every injection site attaches the nudge ({n} sites, need 5)", n >= 5)
    check("Stop counts a turn", "_cp.note_stop(" in remind_src)
    check("PostCompact opens a cycle and restates the rhythm", "_cp.note_compaction(" in remind_src and "_cp.rhythm_text(" in remind_src)
    check("SessionStart announces a missing statusLine", "_cp.session_start_text(" in remind_src)
    guard_src = (ROOT / "claude_engram" / "tools" / "context_guard.py").read_text(encoding="utf-8")
    check("checkpoint_save notes the deliberate save", "_cp.note_manual_checkpoint(" in guard_src)


def test_milestones(cp):
    print("milestones: the model's own 'step done' as the trigger:")
    from claude_engram.hooks import milestones as ms

    positives = [
        "Phase 1 is built, verified, and committed locally.",
        "Step 3 done. Next is the run report.",
        "All 60 checks pass.",
        "60/60 pass, pyright clean.",
        "That closes part A of the plan.",
        "The migration landed and tests are green.",
        "Finished the refactor of the scorer module.",
        "Phase 2 wrapped up; moving to phase 3.",
        "Milestone reached: the report module is in place.",
        "Goal met: done.txt contains ok and check.py prints PASS.",
        "Run 3 of 3 done and the loop is stopped.",
        "Phase 1 is built and verified.",
    ]
    negatives = [
        "Is phase 1 done?",
        "Phase 2 is not done yet.",
        "Step 4 is done so far, but the tests aren't.",
        "When step 3 is complete I'll move on.",
        "This will be done once the tests pass.",
        "I'm still working on step 2.",
        "Let me read the file.",
        "Reading the plan section now.",
        "Here is the plan for phase 2: build the report.",
        "Done.",
        "The feature is half done.",
        "Waiting on you for the push.",
        "Committed as f3a61b0.",
        "I'll mark the task complete after you confirm.",
        "The step needs to be verified before it is done.",
        "The goal is not met yet; two benches still fail.",
        # Three real false positives from 2026-09-09 (instruction, prediction,
        # a quote of the prediction): talk ABOUT completion, not claims of it.
        "Exit after it says the goal is met.",
        "After the third line lands, the next verdict should say met, and the goal clears itself.",
        'The second nudge fired on another of my sentences, "the next verdict should say met, and the goal clears itself," which is a prediction.',
        "Run the suite until phase 2 is green.",
        "Your step 3 is done when the file exists.",
        "Run 2 of 3 done; one more to go.",
        # Two more real false positives (2026-09-09): restated history with a
        # unit noun hiding in a hyphenated compound, and a quoted sentence
        # discussed under a bold header.
        "Checkpoint restored. It matches where we are, with one commit behind: it names `8748488` as latest, and `ef0bb83` (the pushback and follow-plan rules) landed after it was saved.",
        '**Milestone classifier: restated history reads as a fresh claim.** "X landed after it was saved" fired a nudge this turn.',
        "Phase 1 was already built last session; today is phase 2.",
        "The migration had landed before this run started.",
        "As of the previous commit the step is complete, nothing new here.",
        'The harness printed "step 2 is done", which is the quote we discuss.',
    ]
    for t in positives:
        s, q = ms.classify_completion(t, use_semantic=False)
        check(f"claim: {t[:48]!r}", s >= ms.THRESHOLD and bool(q))
    for t in negatives:
        s, _ = ms.classify_completion(t, use_semantic=False)
        check(f"not a claim: {t[:48]!r}", s < ms.THRESHOLD)
    # Sentence-level: a claim buried in a long message is still found, and
    # the quote is the claiming sentence.
    long = "I read three files and ran the bench.\n\nStep 2 is complete.\n\nNext I will look at the docs."
    s, q = ms.classify_completion(long, use_semantic=False)
    check("claim found inside a long message", s >= ms.THRESHOLD and q == "Step 2 is complete.")
    # Commits are not a trigger by design.
    s, _ = ms.classify_completion("Committed locally as f3a61b0, tree clean.", use_semantic=False)
    check("a commit sentence is not a claim", s < ms.THRESHOLD)

    # Semantic tier: a WEAK regex match passes only with a positive margin.
    # unit noun + completion word in one sentence but far apart (outside the
    # strong-match windows): the regex tier alone must not decide this.
    weak = (
        "The plan we agreed on this morning, with every one of its sub-items "
        "and the extra tests the reviewer wanted, is I think done."
    )
    check("bench premise: that sentence is a WEAK regex match", ms._regex_tier(weak) == ms.WEAK)
    s, _ = ms.classify_completion(weak, use_semantic=False)
    check("weak match alone is not a claim", s < ms.THRESHOLD)
    orig = ms._embed_batch

    n_c, n_n = len(ms._COMPLETION_TEMPLATES), len(ms._NON_COMPLETION_TEMPLATES)

    def near_completion(_texts):
        # sentence close to the completion templates, far from the others
        return [[1.0, 0.0]] + [[1.0, 0.1]] * n_c + [[0.0, 1.0]] * n_n

    def near_non_completion(_texts):
        return [[1.0, 0.0]] + [[0.0, 1.0]] * n_c + [[1.0, 0.0]] * n_n

    try:
        ms._embed_batch = near_completion
        s, _ = ms.classify_completion(weak)
        check("weak + semantic margin -> claim", s >= ms.THRESHOLD)
        ms._embed_batch = near_non_completion
        s, _ = ms.classify_completion(weak)
        check("weak + negative margin -> not a claim", s < ms.THRESHOLD)
        ms._embed_batch = lambda _texts: []
        s, _ = ms.classify_completion(weak)
        check("scorer down: weak stays weak", s < ms.THRESHOLD)
    finally:
        ms._embed_batch = orig

    # Staging through the Stop hook and delivery at the next injection point.
    _clean_env()
    sid = "s-milestone"
    state: dict = {"last_session_start": time.time()}
    cp.record_statusline(_payload(sid, 100_000))
    cp.note_stop(state, "Looking into the failing bench now.")
    t, _ = cp.nudge(state, sid)
    check("ordinary turn: nothing staged", t == "" and state["pressure"]["milestone_pending"] is None)
    # A claim in a turn that changed nothing is a status line, not a close
    # (the trade-lab trial's four nudges on report prose, 2026-09-11).
    cp.note_stop(state, "Phase 1 is built and verified. Next is the run report.")
    check("claim without a turn effect: nothing staged", state["pressure"]["milestone_pending"] is None)
    state["stall"] = {"turn": {"effects": ["file"], "tools": 2}}
    cp.note_stop(state, "Phase 1 is built and verified. Next is the run report.")
    check("completion claim staged at Stop", isinstance(state["pressure"]["milestone_pending"], dict))
    check("claim resets the fallback counter", state["pressure"]["stops_since_checkpoint"] == 0)
    t, ch = cp.nudge(state, sid)
    check("milestone nudge delivered once", "Last turn you closed a step" in t and "Phase 1 is built" in t and ch)
    check("nudge names the call", "context(checkpoint_save" in t)
    t, _ = cp.nudge(state, sid)
    check("not delivered twice", t == "")
    # One prose nudge an hour: a second claim inside the window is swallowed.
    cp.note_stop(state, "Step 1b is done as well.")
    t, _ = cp.nudge(state, sid)
    check("a second prose nudge within the hour is swallowed", t == "" and state["pressure"]["milestone_pending"] is None)
    cp.MILESTONE_NUDGE_GAP_SECS = 0  # the rest of this section tests delivery, not the cap
    # The ideal path: a deliberate checkpoint landed in the same turn.
    time.sleep(0.01)
    cp.note_manual_checkpoint(state)
    cp.note_stop(state, "Step 2 done, checkpoint saved.")
    check("claim with a checkpoint this turn: nothing staged", state["pressure"]["milestone_pending"] is None)
    # A checkpoint that lands after the claim but before delivery answers it silently.
    time.sleep(0.01)
    cp.note_stop(state, "Step 3 complete.")
    check("staged again", isinstance(state["pressure"]["milestone_pending"], dict))
    time.sleep(0.01)
    cp.note_manual_checkpoint(state)
    t, _ = cp.nudge(state, sid)
    check("checkpoint after the claim clears the nudge silently", t == "")
    # A save made from ANOTHER process reaches the ring, not this state's
    # flag (two false nudges on 2026-09-10): the ring answers the nudge.
    from claude_engram.hooks import remind as _remind

    time.sleep(0.01)
    cp.note_stop(state)  # a plain turn after the save, so the next claim is a fresh turn
    time.sleep(0.01)
    cp.note_stop(state, "Step 4 complete.")
    check("claim staged (no flag this turn)", isinstance(state["pressure"]["milestone_pending"], dict))
    _orig = _remind.get_handoff_data
    _remind.get_handoff_data = lambda p="": {"kind": "manual", "created": time.time() + 1.0}
    try:
        t, _ = cp.nudge(state, sid, "E:/ws/proj")
    finally:
        _remind.get_handoff_data = _orig
    check("a newer manual entry in the ring answers the nudge without the flag", t == "")
    time.sleep(0.01)
    cp.note_stop(state, "Step 5 complete.")
    _remind.get_handoff_data = lambda p="": {"kind": "auto", "created": time.time() + 1.0}
    try:
        t, _ = cp.nudge(state, sid, "E:/ws/proj")
    finally:
        _remind.get_handoff_data = _orig
    check("an automatic entry does not (only a deliberate save counts)", "Step 5 complete" in t)
    # The usual order inside one turn: save first, closing sentence last. A
    # ring entry written after the previous stop but BEFORE the claim answers
    # it (the third false nudge of 2026-09-10 was exactly this ordering).
    time.sleep(0.01)
    cp.note_stop(state)  # previous stop = the turn's start
    time.sleep(0.01)
    saved_at = time.time()  # the save, mid-turn
    time.sleep(0.01)
    cp.note_stop(state, "Step 6 complete.")  # the claim, at the turn's end
    check("the claim carries the turn's start", state["pressure"]["milestone_pending"]["since"] > 0)
    _remind.get_handoff_data = lambda p="": {"kind": "manual", "created": saved_at}
    try:
        t, _ = cp.nudge(state, sid, "E:/ws/proj")
    finally:
        _remind.get_handoff_data = _orig
    check("a save earlier in the same turn answers the claim", t == "")
    time.sleep(0.01)
    cp.note_stop(state)
    turn_start = time.time()
    time.sleep(0.01)
    cp.note_stop(state, "Step 7 complete.")
    _remind.get_handoff_data = lambda p="": {"kind": "manual", "created": turn_start - 5}
    try:
        t, _ = cp.nudge(state, sid, "E:/ws/proj")
    finally:
        _remind.get_handoff_data = _orig
    check("a save from BEFORE the turn does not", "Step 7 complete" in t)
    # Task tools path stages with kind=task.
    cp.stage_milestone(state, "Implement user authentication", "task")
    t, _ = cp.nudge(state, sid)
    check("task-completed nudge", "You marked a task done" in t and "Implement user authentication" in t)
    # Pressure band outranks the milestone in the same slot; the milestone waits.
    os.environ["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = "750000"
    cp.record_statusline(_payload(sid, 660_000))
    cp.stage_milestone(state, "Round 4 closed", "claim")
    t, _ = cp.nudge(state, sid)
    check("heads-up wins the slot", "Context pressure" in t and "Round 4" not in t)
    t, _ = cp.nudge(state, sid)
    check("milestone delivered on the next slot", "Round 4 closed" in t)
    cp.MILESTONE_NUDGE_GAP_SECS = 3600
    _clean_env()
    check("plan text asks to bank the plan's steps", "pending_steps" in ms.plan_text())

    remind_src = (ROOT / "claude_engram" / "hooks" / "remind.py").read_text(encoding="utf-8")
    check("Stop passes the final message to note_stop", "_cp.note_stop(_st, str(last_message or \"\"))" in remind_src)
    check("post_milestone_json branch exists", 'hook_type == "post_milestone_json"' in remind_src and "def _hook_post_milestone" in remind_src)
    install_src = (ROOT / "install.py").read_text(encoding="utf-8")
    check("installer registers ExitPlanMode|TaskUpdate", '"ExitPlanMode|TaskUpdate"' in install_src and "post_milestone_json" in install_src)
    skill_src = (ROOT / "claude_engram" / "skill" / "engram" / "SKILL.md").read_text(encoding="utf-8")
    check("skill carries the rule: checkpoint when YOU judge a step done", "Checkpoint when YOU judge a step done" in skill_src)


def test_provenance(tmp):
    print("restore provenance (From line) on a manual save:")
    from claude_engram.hooks import remind
    from claude_engram.tools.context_guard import ContextGuard

    storage = tmp / "checkpoints"
    proj_dirs = {"E:/ws/projA": tmp / "projects" / "aaaa1111"}
    remind._project_hash_dir = lambda p: proj_dirs.get(p)
    remind._global_handoff_dir = lambda: storage
    remind._handoff_candidate_dirs = lambda p="": [d for d in (proj_dirs.get(p), storage) if d]
    cg = ContextGuard(storage_dir=storage)
    cg.save_checkpoint(
        task_description="Alpha task",
        current_step="step 2",
        completed_steps=["step 1"],
        pending_steps=["step 2", "step 3"],
        files_involved=["a.py"],
        project_path="E:/ws/projA",
    )
    ring = json.loads((proj_dirs["E:/ws/projA"] / "handoff_history.json").read_text(encoding="utf-8"))
    entry = ring["handoffs"][-1]
    check("ring entry carries project_path top-level", entry.get("project_path") == "E:/ws/projA")
    r = cg.restore_checkpoint(project_path="E:/ws/projA")
    check("restore prints the From line", "**From:** projA" in (r.reasoning or ""))
    check("same-project restore has no cross-project warning", not any("you asked from" in w for w in (r.warnings or [])))
    # Legacy entry: project_path only under metadata (pre-0.8.14 manual save).
    legacy = {
        "kind": "manual",
        "created": time.time(),
        "task_description": "Legacy task",
        "metadata": {"project_path": "E:/ws/projA"},
        "summary": "Legacy task",
    }
    lines = remind._format_restored_context(legacy)
    check("banner derives the project from metadata on a legacy entry", lines and ", projA" in lines[0])
    # A foreign checkpoint served from the global ring into a project with
    # no ring of its own must be labelled with ITS project, not the cwd's:
    # the file-based inference resolved against the cwd and said "goal-test"
    # for an engram checkpoint.
    foreign = {
        "kind": "manual",
        "created": time.time(),
        "task_description": "Engram phases 1-2",
        "summary": "Engram phases 1-2",
        "project_path": "E:/workspace/claude-engram",
        "files_in_progress": ["E:/workspace/claude-engram/claude_engram/run_report.py"],
    }
    lines = remind._format_restored_context(foreign)
    check("banner labels a foreign checkpoint with its own project", lines and ", claude-engram" in lines[0] and "goal-test" not in lines[0])


def test_budget(cp, tmp):
    print("usage budget (5-hour / 7-day windows):")
    _clean_env()
    for k in ("CLAUDE_ENGRAM_BUDGET_FIVE_HOUR_PCT", "CLAUDE_ENGRAM_BUDGET_SEVEN_DAY_PCT"):
        os.environ.pop(k, None)
    sid = "s-budget"
    now = time.time()
    payload = {
        "session_id": sid,
        "context_window": {"total_input_tokens": 50_000, "context_window_size": 1_000_000},
        "rate_limits": {
            "five_hour": {"used_percentage": 93, "resets_at": int(now + 41 * 60)},
            "seven_day": {"used_percentage": 40, "resets_at": int(now + 3 * 86400)},
        },
    }
    cp.record_statusline(payload)
    m = cp.read_mirror(sid)
    check("the mirror carries both windows", m["five_hour_pct"] == 93 and m["seven_day_pct"] == 40 and m["five_hour_resets_at"] == int(now + 41 * 60))
    state = {}
    t, changed = cp.nudge(state, sid, str(tmp / "no-proj"))
    check("5-hour window at 93% fires once", changed and "5-hour window is at 93%" in t and "resets" in t and "in 41 min" in t)
    check("...with the park-until-reset instruction", "ScheduleWakeup" in t and "checkpoint_save" in t)
    check("...and the weekly at 40% stays quiet", "7-day" not in t)
    t2, _ = cp.nudge(state, sid, str(tmp / "no-proj"))
    check("same window: not again", "Usage budget" not in t2)
    payload["rate_limits"]["five_hour"]["used_percentage"] = 97
    cp.record_statusline(payload)
    t3, _ = cp.nudge(state, sid, str(tmp / "no-proj"))
    check("rising inside the same window: still quiet", "Usage budget" not in t3)
    payload["rate_limits"]["five_hour"] = {"used_percentage": 91, "resets_at": int(now + 5 * 3600 + 41 * 60)}
    cp.record_statusline(payload)
    t4, _ = cp.nudge(state, sid, str(tmp / "no-proj"))
    check("a new window (new resets_at) fires again", "5-hour window is at 91%" in t4)
    payload["rate_limits"]["seven_day"] = {"used_percentage": 96, "resets_at": int(now + 2 * 86400)}
    cp.record_statusline(payload)
    t5, _ = cp.nudge(state, sid, str(tmp / "no-proj"))
    check("weekly at 96% fires with its reset", "7-day window is at 96%" in t5 and "resets" in t5 and "unattended" in t5)
    check("weekly once", "7-day" not in cp.nudge(state, sid, str(tmp / "no-proj"))[0])
    os.environ["CLAUDE_ENGRAM_BUDGET_FIVE_HOUR_PCT"] = "50"
    payload["rate_limits"]["five_hour"] = {"used_percentage": 55, "resets_at": int(now + 9 * 3600)}
    cp.record_statusline(payload)
    t6, _ = cp.nudge(state, sid, str(tmp / "no-proj"))
    check("threshold is env-tunable", "5-hour window is at 55%" in t6)
    os.environ.pop("CLAUDE_ENGRAM_BUDGET_FIVE_HOUR_PCT", None)
    api = {"session_id": "s-apikey", "context_window": {"total_input_tokens": 1, "context_window_size": 200_000}}
    cp.record_statusline(api)
    check("an API-key session (no rate_limits) never fires", "Usage budget" not in cp.nudge({}, "s-apikey", str(tmp / "no-proj"))[0])
    check("the shipped statusline shows the 5-hour figure", "5h 93%" in cp._fmt_statusline(dict(payload, rate_limits={"five_hour": {"used_percentage": 93}})))
    check("reset formatting: passed", "passed" in cp._fmt_reset(now - 10))
    check("reset formatting: days", " d)" in cp._fmt_reset(now + 3 * 86400))
    check("reset formatting: unknown", cp._fmt_reset(None) == "" and cp._fmt_reset("x") == "")


def test_stop_failure(tmp):
    print("StopFailure is recorded with the window's reset:")
    from claude_engram.hooks import context_pressure as cp

    sid = "s-stopfail"
    now = time.time()
    cp.record_statusline({
        "session_id": sid,
        "context_window": {"total_input_tokens": 10, "context_window_size": 1_000_000},
        "rate_limits": {"five_hour": {"used_percentage": 100, "resets_at": int(now + 1800)}},
    })
    env = dict(os.environ, CLAUDE_ENGRAM_DIR=os.environ["CLAUDE_ENGRAM_DIR"], CLAUDE_PROJECT_DIR=str(tmp), CLAUDE_ENGRAM_NO_DAEMON="1")
    r = subprocess.run(
        [sys.executable, "-m", "claude_engram.hooks.remind", "stop_failure_json"],
        input=json.dumps({"session_id": sid, "hook_event_name": "StopFailure", "error_type": "rate_limit",
                          "error": "You've hit your session limit", "permission_mode": "bypassPermissions"}),
        capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=120,
    )
    check("hook exits 0 and prints nothing (output is ignored by Claude Code)", r.returncode == 0 and r.stdout.strip() == "")
    st = json.loads((Path(os.environ["CLAUDE_ENGRAM_DIR"]) / "sessions" / f"{sid}.json").read_text(encoding="utf-8"))
    f = (st.get("run") or {}).get("failures") or []
    check("failure recorded with type, message and the window's reset", len(f) == 1 and f[0]["error_type"] == "rate_limit" and f[0]["five_hour_resets_at"] == int(now + 1800) and f[0]["five_hour_pct"] == 100)
    from claude_engram import run_report as rr

    rep = rr.collect(sid, str(tmp), st)
    md = rr.render_md(rep)
    check("the run report says how it ended and when the window resets", "API failure at" in md and "rate_limit" in md and "5-hour window at 100%" in md and "resets" in md)
    inst = (ROOT / "install.py").read_text(encoding="utf-8")
    check("install registers StopFailure", '"StopFailure"' in inst and "stop_failure_json" in inst)


_SEED_SRC = '''
import time, sys
from claude_engram.hooks import remind
from claude_engram import handoff_store as hs

project = sys.argv[1]
dirs = [d for d in (remind._project_hash_dir(project), remind._global_handoff_dir()) if d]
hs.write_handoff(
    {"kind": "manual", "task_description": "Autonomy build: 0.8.28 committed, live test next",
     "summary": "Autonomy build: 0.8.28 committed, live test next",
     "current_step": "reply to the user", "pending_steps": ["live test", "one push"],
     "project_path": project, "files_involved": ["autorun.py"], "created": time.time(),
     "task_id": "task_replay_1", "goal": "the stack is pushed once"},
    dirs,
)
'''


def test_compaction_reinjection(tmp):
    """Replay of the 2026-09-10 auto compaction (session 4f414c78, 1M Fable,
    autoCompactWindow 750K): the heads-up fired at 651K, the checkpoint band
    (then 720K) never did because Claude Code compacted at 717,578, and the
    checkpoint banked nine minutes earlier never reached the model because
    PostCompact printed plain stdout and SessionStart(compact) skipped it."""
    print("the auto compaction, replayed:")
    from claude_engram.hooks import context_pressure as cp

    _clean_env()
    os.environ["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = "750000"
    sid = "s-replay-0910"
    state: dict = {"last_session_start": time.time()}
    cp.record_statusline(_payload(sid, 651_000))
    t, _ = cp.nudge(state, sid)
    check("651K: the heads-up (as observed live)", "Compaction #1 is coming" in t)
    cp.record_statusline(_payload(sid, 700_000))
    t, _ = cp.nudge(state, sid)
    check("700K: CHECKPOINT NOW fires before the measured compaction point", t.startswith("<engram-context>CHECKPOINT NOW"))
    cp.record_statusline(_payload(sid, 717_578))
    a = cp.current_assessment(state, sid)
    check("717,578 (the measured pre-compaction size) is inside the checkpoint band", a["band"] == "checkpoint" and a["checkpoint_at"] < 717_578)
    t, _ = cp.nudge(state, sid)
    check("no second call at 717K (once per cycle)", t == "")

    # PostCompact through the real hook: bookkeeping only. Claude Code's
    # hook output schema has no PostCompact channel (a hookSpecificOutput
    # with that event name is rejected, 2.1.268), so the rhythm is stated
    # by the SessionStart(compact) banner below.
    proj = tmp / "replay-proj"
    proj.mkdir(parents=True, exist_ok=True)
    env = dict(
        os.environ,
        CLAUDE_ENGRAM_DIR=os.environ["CLAUDE_ENGRAM_DIR"],
        CLAUDE_PROJECT_DIR=str(proj),
        CLAUDE_ENGRAM_LIVE_MINE="0",
        CLAUDE_ENGRAM_NO_DAEMON="1",
    )
    r = subprocess.run(
        [sys.executable, "-m", "claude_engram.hooks.remind", "post_compact_json"],
        input=json.dumps({"session_id": sid, "cwd": str(proj), "hook_event_name": "PostCompact",
                          "trigger": "auto", "compact_summary": ""}),
        capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=120,
    )
    check("PostCompact emits nothing (Claude Code's hook schema has no PostCompact channel)", r.returncode == 0 and r.stdout.strip() == "")
    st = json.loads((Path(os.environ["CLAUDE_ENGRAM_DIR"]) / "sessions" / f"{sid}.json").read_text(encoding="utf-8"))
    check("the compaction opened cycle 1 in the state", int((st.get("pressure") or {}).get("cycle", 0)) == 1)

    # SessionStart(compact) through the real hook: the checkpoint banked
    # before the compaction is shown to the model again.
    seed = Path(os.environ["CLAUDE_ENGRAM_DIR"]) / "_seed_replay.py"
    seed.write_text(_SEED_SRC, encoding="utf-8")
    s = subprocess.run([sys.executable, str(seed), str(proj)], capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=120)
    check("seed wrote a manual checkpoint into the project ring", s.returncode == 0)
    r = subprocess.run(
        [sys.executable, "-m", "claude_engram.hooks.remind", "session_start_json"],
        input=json.dumps({"session_id": sid, "source": "compact", "cwd": str(proj), "hook_event_name": "SessionStart"}),
        # cwd=ROOT, not proj: the hook spawns background mining with its cwd,
        # and on Windows that child holds the temp dir past teardown.
        capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=120,
    )
    try:
        ctx2 = json.loads(r.stdout)["hookSpecificOutput"].get("additionalContext", "")
    except Exception:
        ctx2 = ""
    check("SessionStart(compact) shows the banked checkpoint (was skipped)", "CHECKPOINT [manual" in ctx2 and "task_replay_1" in ctx2 and "0.8.28 committed" in ctx2)
    check("... with its goal and next steps", "Goal: the stack is pushed once" in ctx2 and "Pending: 2 steps" in ctx2)
    check("SessionStart(compact) states the rhythm with the measured trigger", "Compaction #1. Rhythm" in ctx2 and "checkpoint at ~698K" in ctx2 and "auto-compaction at ~718K" in ctx2)
    st2 = json.loads((Path(os.environ["CLAUDE_ENGRAM_DIR"]) / "sessions" / f"{sid}.json").read_text(encoding="utf-8"))
    check("the banner did not open a second cycle for the same compaction", int((st2.get("pressure") or {}).get("cycle", 0)) == 1)
    _clean_env()


def main():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        os.environ["CLAUDE_ENGRAM_DIR"] = str(tmp)
        _clean_env()
        from claude_engram.hooks import context_pressure as cp

        test_parse_window_value(cp)
        test_compaction_point(cp, tmp)
        test_thresholds(cp)
        test_mirror(cp)
        test_assess(cp)
        test_nudge_sequence(cp)
        test_cadence(cp)
        test_not_recording(cp, tmp)
        test_cli(tmp)
        test_source_guards()
        test_milestones(cp)
        test_provenance(tmp)
        test_compaction_reinjection(tmp)
        test_budget(cp, tmp)
        test_stop_failure(tmp)

    print()
    if _fails:
        print(f"FAILED: {len(_fails)}")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
