"""
Benchmark: rotation and the default pack (Autonomy Mode Phase 3).

What must hold:
  1. project_config: defaults, file, env precedence; "auto" rotation mode.
  2. Rotation of session logs: only dailies older than the window move, into
     archive/<YYYY-MM>/, and the month digest is rebuilt from the archived
     originals; a non-daily file and a recent daily are untouched.
  3. Rotation of learnings: every heading shape seen in real files is parsed;
     dated sections older than 90 days move to archive/<NAME>-<year>.md; the
     line-count cap moves the oldest 30+ day sections until the file fits;
     undated and STANDING/permanent sections never move; the file's line
     ending is preserved; a one-line note lands under the H1; a second
     rotation replaces the note rather than stacking it.
  4. Nothing is deleted: every moved line is findable in archive/.
  5. plan() is a pure dry run; run_at_session_end persists the plan unless
     "auto"; pending_notice reads it back; save_plan clears an empty plan.
  6. Default pack: similar() catches rules the workspace already has in
     substance; seed_rules is idempotent and skips inherited rules;
     ensure_structure creates only in a project dir, never twice.
  7. Source guards: SessionStart runs the pack on startup only and announces a
     pending rotation; SessionEnd runs rotation; session_mine(rotate) exists.

Run: venv/Scripts/python.exe tests/bench_phase3.py
"""

import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_fails = []


def check(name, cond):
    print(("  [PASS] " if cond else "  [FAIL] ") + name)
    if not cond:
        _fails.append(name)


def _daily(d: date, title: str) -> str:
    return f"# {d.isoformat()} — {title}\n\n## What happened\n\n- first bullet for {title}\n- second bullet\n\n## Next steps\n\n- next for {title}\n"


def test_config(tmp):
    print("project_config:")
    from claude_engram import project_config as pc

    proj = tmp / "cfg"
    proj.mkdir()
    for k in ("CLAUDE_ENGRAM_ROTATION", "CLAUDE_ENGRAM_DEFAULT_RULES", "CLAUDE_ENGRAM_STRUCTURE"):
        os.environ.pop(k, None)
    c = pc.load(str(proj))
    check("defaults: everything on, 30/90/500", c["rotation"] is True and c["default_rules"] is True and c["structure"] is True and (c["rotation_log_days"], c["rotation_learn_days"], c["rotation_learn_max_lines"]) == (30, 90, 500))
    (proj / ".engram").mkdir()
    (proj / ".engram" / "config.json").write_text(json.dumps({"rotation": "auto", "default_rules": False, "rotation_log_days": 7}), encoding="utf-8")
    c = pc.load(str(proj))
    check("file: rotation auto, rules off, log days 7", c["rotation"] == "auto" and c["default_rules"] is False and c["rotation_log_days"] == 7)
    os.environ["CLAUDE_ENGRAM_ROTATION"] = "0"
    check("env beats file", pc.load(str(proj))["rotation"] is False and not pc.enabled(pc.load(str(proj)), "rotation"))
    os.environ.pop("CLAUDE_ENGRAM_ROTATION")
    (proj / ".engram" / "config.json").write_text("not json", encoding="utf-8")
    check("garbage file -> defaults, no raise", pc.load(str(proj))["rotation"] is True)


def test_session_logs(tmp):
    print("rotation: session logs")
    from claude_engram import rotation as rot

    today = date(2026, 9, 9)
    proj = tmp / "logs"
    sdir = proj / "session-logs"
    sdir.mkdir(parents=True)
    old1 = today - timedelta(days=70)
    old2 = today - timedelta(days=45)
    recent = today - timedelta(days=5)
    for d, t in ((old1, "alpha"), (old2, "beta"), (recent, "gamma")):
        (sdir / f"{d.isoformat()}.md").write_text(_daily(d, t), encoding="utf-8")
    (sdir / "README.md").write_text("not a daily\n", encoding="utf-8")
    (sdir / "notes").mkdir()
    p = rot.plan(str(proj), today=today)
    items = [i for i in p["items"] if i["kind"] == "session-logs"]
    check("plan lists the two old dailies, not the recent one", len(items) == 1 and items[0]["files"] == 2 and sum(len(v) for v in items[0]["months"].values()) == 2)
    check("plan is a dry run: files untouched", (sdir / f"{old1.isoformat()}.md").is_file())
    done = rot.apply(p, today=today)
    check("apply reports the move", any("2 dailies" in d for d in done))
    m1, m2 = old1.strftime("%Y-%m"), old2.strftime("%Y-%m")
    check("old dailies moved under archive/<month>/", (sdir / "archive" / m1 / f"{old1.isoformat()}.md").is_file() and (sdir / "archive" / m2 / f"{old2.isoformat()}.md").is_file())
    check("recent daily and non-daily files untouched", (sdir / f"{recent.isoformat()}.md").is_file() and (sdir / "README.md").is_file() and (sdir / "notes").is_dir())
    digest = (sdir / "archive" / f"{m1}.md").read_text(encoding="utf-8")
    check("month digest has the day's title and first bullet per section", f"## {old1.isoformat()} — alpha" in digest and "- first bullet for alpha" in digest and "- next for alpha" in digest and "- second bullet" not in digest)
    check("digest points at the archived original", f"archive/{m1}/{old1.isoformat()}.md" in digest)
    p2 = rot.plan(str(proj), today=today)
    check("second plan: nothing left to move", not [i for i in p2["items"] if i["kind"] == "session-logs"])
    # Per-person layout (trade-lab): session-logs/<name>/YYYY-MM-DD.md rotates
    # inside its own folder, with its own archive and digest.
    team = tmp / "team-logs"
    (team / "session-logs" / "alice").mkdir(parents=True)
    (team / "session-logs" / "bob").mkdir(parents=True)
    (team / "session-logs" / "alice" / f"{old1.isoformat()}.md").write_text(_daily(old1, "alice-old"), encoding="utf-8")
    (team / "session-logs" / "bob" / f"{recent.isoformat()}.md").write_text(_daily(recent, "bob-recent"), encoding="utf-8")
    (team / "session-logs" / "README.md").write_text("layout\n", encoding="utf-8")
    pt = rot.plan(str(team), today=today)
    its = [i for i in pt["items"] if i["kind"] == "session-logs"]
    check("per-person: alice's old daily planned, bob's recent one not", len(its) == 1 and its[0]["unit"] == "alice" and its[0]["files"] == 1)
    rot.apply(pt, today=today)
    check("per-person: archived inside alice/, digest beside it", (team / "session-logs" / "alice" / "archive" / m1 / f"{old1.isoformat()}.md").is_file() and (team / "session-logs" / "alice" / "archive" / f"{m1}.md").is_file())
    check("per-person: bob and the README untouched", (team / "session-logs" / "bob" / f"{recent.isoformat()}.md").is_file() and (team / "session-logs" / "README.md").is_file())


def test_learnings(tmp):
    print("rotation: learnings")
    from claude_engram import rotation as rot

    today = date(2026, 9, 9)
    proj = tmp / "learn"
    ldir = proj / ".learnings"
    ldir.mkdir(parents=True)
    old = (today - timedelta(days=120)).isoformat()
    mid = (today - timedelta(days=45)).isoformat()
    new = (today - timedelta(days=3)).isoformat()
    body = "\r\n".join(
        [
            "# Errors & Fixes",
            "",
            f"### {new} — fresh h3 before any h2",
            "- keep me (recent)",
            "",
            f"## {old} — old dated h2",
            "- old body A",
            "",
            f"## {old}",
            "### child under date-only h2",
            "- old body B",
            "",
            f"## Titled with date in parens ({old})",
            "- old body C",
            "",
            "## Undated topical section",
            "- never moves, nothing to age it by",
            "",
            f"## {old} — STANDING rule about pushes",
            "- never moves either",
            "",
            f"## {mid} — middling",
            "- 45 days old, inside the 90-day window",
            "",
        ]
    )
    (ldir / "ERRORS.md").write_bytes(body.encode("utf-8"))
    p = rot.plan(str(proj), today=today)
    items = [i for i in p["items"] if i["kind"] == "learnings"]
    check("plan: three old dated sections move", len(items) == 1 and items[0]["entries"] == 3)
    titles = sum(items[0]["targets"].values(), [])
    check("moving = the dated h2, the date-only h2 block, the parenthesised date", any("old dated h2" in t for t in titles) and any(t == old for t in titles) and any("parens" in t for t in titles))
    check("kept = recent h3, undated, STANDING, 45-day", not any("fresh h3" in t or "Undated" in t or "STANDING" in t or "middling" in t for t in titles))
    rot.apply(p, today=today)
    raw = (ldir / "ERRORS.md").read_bytes()
    check("CRLF preserved", b"\r\n" in raw and b"\n\n" not in raw.replace(b"\r\n", b""))
    text = raw.decode("utf-8")
    check("note under the H1", text.splitlines()[0] == "# Errors & Fixes" and text.splitlines()[2].startswith("> Rotated 2026-09-09: 3 entries"))
    check("kept sections still present", "fresh h3" in text and "Undated topical" in text and "STANDING rule" in text and "middling" in text)
    check("moved sections gone from the live file", "old body A" not in text and "old body B" not in text and "old body C" not in text)
    year = old[:4]
    arch = (ldir / "archive" / f"ERRORS-{year}.md").read_bytes().decode("utf-8")
    check("archive holds every moved line", "old body A" in arch and "child under date-only h2" in arch and "old body C" in arch)
    check("archive has a header and a rotation marker", arch.startswith("# ERRORS archive") and f"<!-- rotated {today.isoformat()} from ERRORS.md: 3 entries -->" in arch)
    # Second rotation on a later day replaces the note instead of stacking it.
    later = today + timedelta(days=100)
    p3 = rot.plan(str(proj), today=later)
    rot.apply(p3, today=later)
    text3 = (ldir / "ERRORS.md").read_bytes().decode("utf-8")
    check("second rotation: exactly one note line", text3.count("> Rotated ") == 1 and f"> Rotated {later.isoformat()}" in text3)

    # Line cap: a file under the age window but over the cap moves the oldest
    # 30+ day sections until it fits; undated sections don't count as movable.
    proj2 = tmp / "learn2"
    (proj2 / ".learnings").mkdir(parents=True)
    (proj2 / ".engram").mkdir()
    (proj2 / ".engram" / "config.json").write_text(json.dumps({"rotation_learn_max_lines": 30}), encoding="utf-8")
    parts = ["# Learnings", ""]
    for i in range(6):
        d = (today - timedelta(days=35 + i)).isoformat()
        parts += [f"## {d} — entry {i}"] + [f"- line {j} of entry {i}" for j in range(8)] + [""]
    parts += ["## Undated big section"] + [f"- undated line {j}" for j in range(12)] + [""]
    (proj2 / ".learnings" / "LEARNINGS.md").write_text("\n".join(parts), encoding="utf-8")
    p4 = rot.plan(str(proj2), today=today)
    it = [i for i in p4["items"] if i["kind"] == "learnings"]
    check("cap plan exists with lines_after <= cap or all movable moved", len(it) == 1 and (it[0]["lines_after"] <= 30 or it[0]["entries"] == 6))
    rot.apply(p4, today=today)
    live = (proj2 / ".learnings" / "LEARNINGS.md").read_text(encoding="utf-8")
    check("cap: oldest entries moved first, undated stays", "entry 5" not in live and "Undated big section" in live)
    arch2 = (proj2 / ".learnings" / "archive" / f"LEARNINGS-{today.year}.md").read_text(encoding="utf-8")
    check("cap: moved entries in the year archive", "entry 5" in arch2)
    # LEARNINGS.md: patterns don't age out. Under the cap, an old entry stays;
    # rotation_learnings_days turns age on.
    proj3 = tmp / "learn3"
    (proj3 / ".learnings").mkdir(parents=True)
    (proj3 / ".learnings" / "LEARNINGS.md").write_text(f"# Learnings\n\n## {old} — old pattern\n- still true\n", encoding="utf-8")
    check("LEARNINGS: old entry under the cap is NOT rotated by age", not [i for i in rot.plan(str(proj3), today=today)["items"] if i["kind"] == "learnings"])
    (proj3 / ".engram").mkdir()
    (proj3 / ".engram" / "config.json").write_text(json.dumps({"rotation_learnings_days": 90}), encoding="utf-8")
    check("LEARNINGS: age rule opt-in via rotation_learnings_days", [i for i in rot.plan(str(proj3), today=today)["items"] if i["kind"] == "learnings"][0]["entries"] == 1)
    # Per-person learnings (.learnings/<name>/ERRORS.md) rotate inside their folder.
    team = tmp / "team-learn"
    (team / ".learnings" / "alice").mkdir(parents=True)
    hdr = "---\ntype: learnings\nstatus: active\nupdated: 2026-08-01\nproject: team\nsummary: alice's errors\n---\n\n"
    (team / ".learnings" / "alice" / "ERRORS.md").write_text(hdr + f"# Errors\n\n## {old} — ancient\n- gone\n\n## {new} — fresh\n- stays\n", encoding="utf-8")
    pt = rot.plan(str(team), today=today)
    its = [i for i in pt["items"] if i["kind"] == "learnings"]
    check("per-person learnings planned under its unit", len(its) == 1 and its[0]["unit"] == "alice" and its[0]["entries"] == 1)
    rot.apply(pt, today=today)
    live = (team / ".learnings" / "alice" / "ERRORS.md").read_text(encoding="utf-8")
    check("nav header preserved, note under the H1, fresh entry kept", live.startswith("---\ntype: learnings") and "# Errors\n\n> Rotated " in live and "fresh" in live and "ancient" not in live)
    check("archive inside alice/", (team / ".learnings" / "alice" / "archive" / f"ERRORS-{old[:4]}.md").is_file())


def test_plan_persistence(tmp):
    print("plan persistence and SessionEnd behaviour:")
    from claude_engram import rotation as rot

    today = date.today()
    proj = tmp / "persist"
    (proj / "session-logs").mkdir(parents=True)
    old = today - timedelta(days=60)
    (proj / "session-logs" / f"{old.isoformat()}.md").write_text(_daily(old, "old"), encoding="utf-8")
    msg = rot.run_at_session_end(str(proj))
    check("default mode plans, does not apply", msg.startswith("rotation planned") and (proj / "session-logs" / f"{old.isoformat()}.md").is_file())
    check("plan persisted for SessionStart", rot.plan_path(str(proj)).is_file() and "Rotation pending" in rot.pending_notice(str(proj)))
    check("persisted plan has no private keys", not any(k.startswith("_") for it in json.loads(rot.plan_path(str(proj)).read_text(encoding="utf-8"))["items"] for k in it))
    (proj / ".engram" / "config.json").write_text(json.dumps({"rotation": "auto"}), encoding="utf-8")
    msg = rot.run_at_session_end(str(proj))
    check("auto mode applies at session end", msg.startswith("rotated:") and not (proj / "session-logs" / f"{old.isoformat()}.md").is_file())
    check("applied plan cleared; no pending notice", not rot.plan_path(str(proj)).is_file() and rot.pending_notice(str(proj)) == "")
    (proj / ".engram" / "config.json").write_text(json.dumps({"rotation": False}), encoding="utf-8")
    check("rotation off -> nothing", rot.run_at_session_end(str(proj)) == "")


def test_default_pack(tmp):
    print("default pack:")
    from claude_engram import default_pack as dp

    check("similar: paraphrase of the destructive-commands rule", dp.similar(dp.RULES[0]["content"], "No destructive commands without asking. trash > rm. Never git push --force to main. (Reason: Protect against accidents)"))
    check("similar: unrelated rule is not", not dp.similar(dp.RULES[0]["content"], "Use tabs for indentation in Go files."))
    check("similar: search-first paraphrase", dp.similar(dp.RULES[1]["content"], "Search first (qmd/grep), then read only relevant files. Don't read entire files when a targeted search works."))
    sm = next(r for r in dp.RULES if "Session maintenance" in r["content"])
    check("anchor: a short user rule covers the pack's long session-maintenance rule", dp.similar(sm["content"], "Delegate session maintenance (learnings, errors, session logs) to background sonnet sub-agents.", anchors=sm["anchors"]))
    check("anchor: no anchor, no match", not dp.similar(sm["content"], "Delegate session maintenance (learnings, errors, session logs) to background sonnet sub-agents."))
    home = Path.home()
    check("home dir is never a project", not dp.is_project_dir(str(home)))
    bare = tmp / "bare"
    bare.mkdir()
    check("a bare dir is not a project; nothing created", not dp.is_project_dir(str(bare)) and dp.ensure_structure(str(bare)) == [])
    proj = tmp / "proj"
    (proj / ".git").mkdir(parents=True)
    created = dp.ensure_structure(str(proj))
    check("structure created in a git project", set(created) == {"CLAUDE.md", ".learnings/ERRORS.md", ".learnings/LEARNINGS.md", "session-logs/"})
    cm = (proj / "CLAUDE.md").read_text(encoding="utf-8")
    check("CLAUDE.md is the workspace scaffold: nav header + Purpose/Testing/Structure", cm.startswith("---\ntype: readme\nstatus: active\nupdated: ") and f"project: {proj.name}\n" in cm and "## Purpose" in cm and "## Testing" in cm and "## Structure" in cm)
    check("CLAUDE.md carries the workflow section (plan before code, gates, delegation, verify, evidence, git, record)", "## Workflow" in cm and "Plan before code" in cm and "Gates and audits" in cm and "Delegate by size" in cm and "Verify before done" in cm)
    em = (proj / ".learnings" / "ERRORS.md").read_text(encoding="utf-8")
    check("ERRORS.md is the scaffold's headered file", em.startswith("---\ntype: learnings\n") and "# Errors\n\nProject-specific errors and fixes." in em)
    # A multi-person project (trade-lab's shape) keeps its layout: no
    # top-level ERRORS/LEARNINGS beside the per-person folders.
    team = tmp / "team"
    (team / ".git").mkdir(parents=True)
    (team / ".learnings" / "alice").mkdir(parents=True)
    (team / "session-logs" / "alice").mkdir(parents=True)
    created_team = dp.ensure_structure(str(team))
    check("per-person layout: only CLAUDE.md added, no top-level learnings files", created_team == ["CLAUDE.md"] and not (team / ".learnings" / "ERRORS.md").exists())
    (proj / "CLAUDE.md").write_text("# mine\n", encoding="utf-8")
    check("second run creates nothing and keeps the user's CLAUDE.md", dp.ensure_structure(str(proj)) == [] and (proj / "CLAUDE.md").read_text(encoding="utf-8") == "# mine\n")

    # Seeding against an isolated store: a project whose ancestor already has
    # two of the rules gets the rest, once.
    from claude_engram.tools.memory import MemoryStore
    from claude_engram.hooks import remind

    ws = tmp / "ws"
    sub = ws / "sub"
    (sub / ".git").mkdir(parents=True)
    store = MemoryStore()
    store.add_rule(str(ws), "No destructive commands without asking. trash > rm. Never git push --force to main.", "safety")
    store.add_rule(str(ws), "Be direct. No filler. No emojis. Have opinions.", "preference")
    rep = dp.seed_rules(str(sub))
    check("inherited rules skipped, the rest added", len(rep["skipped"]) >= 2 and len(rep["added"]) == len(dp.RULES) - len(rep["skipped"]) and len(rep["added"]) >= 4)
    rules_after = [r.content for r in MemoryStore().get_rules(str(sub))]
    check("added rules live in the sub-project store", any("Never kill processes by image name" in r for r in rules_after))
    check("workflow tier seeded too (plan before code, gates, delegation)", any(r.startswith("Plan before code") for r in rules_after) and any("gate written before the work" in r for r in rules_after) and any(r.startswith("Delegate by size") for r in rules_after))
    check("pack = universal + workflow", len(dp.RULES) == len(dp.UNIVERSAL_RULES) + len(dp.WORKFLOW_RULES) and len(dp.WORKFLOW_RULES) >= 6)
    # Workflow tier can be turned off on its own.
    wf_off = tmp / "ws" / "wf-off"
    (wf_off / ".git").mkdir(parents=True)
    (wf_off / ".engram").mkdir()
    (wf_off / ".engram" / "config.json").write_text(json.dumps({"workflow_rules": False, "structure": False}), encoding="utf-8")
    dp.run_at_session_start(str(wf_off))
    wf_rules = [r.content for r in MemoryStore().get_rules(str(wf_off))]
    check("workflow_rules=false: universal seeded, workflow not", any("Never kill processes" in r for r in wf_rules) and not any(r.startswith("Plan before code") for r in wf_rules))
    rep2 = dp.seed_rules(str(sub))
    check("second seed is a no-op (marker)", rep2["already_seeded"] and rep2["added"] == [])
    rules_again = [r.content for r in MemoryStore().get_rules(str(sub))]
    check("no duplicates after the second seed", len(rules_again) == len(rules_after))
    dp.ensure_structure(str(sub))
    lines = dp.run_at_session_start(str(sub))
    check("session-start lines: nothing new to announce on a seeded, scaffolded project", lines == [])
    (sub / ".engram").mkdir(exist_ok=True)
    (sub / ".engram" / "config.json").write_text(json.dumps({"default_rules": False, "structure": False}), encoding="utf-8")
    fresh = tmp / "ws" / "fresh"
    (fresh / ".git").mkdir(parents=True)
    (fresh / ".engram").mkdir()
    (fresh / ".engram" / "config.json").write_text(json.dumps({"default_rules": False, "structure": False}), encoding="utf-8")
    check("opt-out: nothing seeded, nothing created", dp.run_at_session_start(str(fresh)) == [] and not (fresh / ".learnings").exists() and MemoryStore().get_rules(str(fresh)) == [])
    _ = remind  # keep the import (state dir is the isolated store)


def test_source_guards():
    print("source guards:")
    remind_src = (ROOT / "claude_engram" / "hooks" / "remind.py").read_text(encoding="utf-8")
    check("SessionStart runs the pack on startup only", 'if source == "startup":' in remind_src and "_dp.run_at_session_start(project_dir)" in remind_src)
    check("SessionStart announces a pending rotation", "_rot.pending_notice(project_dir)" in remind_src)
    check("SessionEnd runs rotation on the session's project", "_rot.run_at_session_end(_resolve_session_project(project_dir, files_edited))" in remind_src)
    defs = (ROOT / "claude_engram" / "tool_definitions_v2.py").read_text(encoding="utf-8")
    handlers = (ROOT / "claude_engram" / "handlers.py").read_text(encoding="utf-8")
    check("session_mine(rotate, dry_run) advertised and dispatched", '"rotate"' in defs and '"dry_run"' in defs and 'operation == "rotate"' in handlers)


def main():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        os.environ["CLAUDE_ENGRAM_DIR"] = str(tmp / "store")
        test_config(tmp)
        test_session_logs(tmp)
        test_learnings(tmp)
        test_plan_persistence(tmp)
        test_default_pack(tmp)
        test_source_guards()
    print()
    if _fails:
        print(f"FAILED: {len(_fails)}")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
