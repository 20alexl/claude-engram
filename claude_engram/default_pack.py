"""The default pack: the working rules and the project structure, on by default.

This is the shape the author's own workspace uses, not an invention: the
structure is the workspace scaffold (``tools/new-project.sh``) -- a headered
``CLAUDE.md`` with Purpose / Testing / Structure, ``.learnings/ERRORS.md``,
``.learnings/LEARNINGS.md`` and ``session-logs/`` -- and the rules are the
workspace ``CLAUDE.md`` rules in their own words, plus the session-maintenance
convention that keeps those files current. A multi-person project keeps its
per-person layout (``.learnings/<name>/``, ``session-logs/<name>/``); the pack
never adds top-level files beside it.

Two tiers, each one line to turn off in ``<project>/.engram/config.json``:

  * ``default_rules``: seeded into the project's memory as ``rule`` entries
    on the first fresh session. Idempotent, and any rule the project or an
    ancestor already has in substance (word overlap) is skipped, so a
    workspace that wrote its own rules keeps them and gets no duplicates.
  * ``structure``: the scaffold, created only where something is missing and
    only in a directory that is already a project (a git repo, a package
    manifest, or a CLAUDE.md), never in a home directory or a drive root.

Shipping opinions is how a tool gets a personality and how it gets in the
way; the pack is short and the opt-out is one line.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date
from pathlib import Path
from typing import Optional

from claude_engram import project_config

PACK_VERSION = 3

# The workspace rules, in the words they are written in there.
UNIVERSAL_RULES: list[dict] = [
    {
        "content": "Don't run destructive commands without asking. trash > rm. Never git push --force to main.",
        "reason": "Undo is cheaper than recovery.",
    },
    {
        "content": "Search first (grep, the code index), then read only relevant files. Don't read entire files when a targeted search works.",
        "reason": "Whole-file reads spend context and hide the one line that matters.",
    },
    {
        "content": "Quality over speed. Do it right the first time. Check actual API signatures before writing code.",
        "reason": "Rework costs more than doing it right once.",
    },
    {
        "content": "Complete prerequisites before moving to dependent work. When you identify something broken that later steps need, fix it first.",
        "reason": "Building on a broken step repeats the failure downstream.",
    },
    {
        "content": "Be direct. No filler. No emojis. Have opinions. Disagree when appropriate.",
        "reason": "A reviewer who agrees with everything reviews nothing.",
    },
    {
        "content": "Try before asking. Be resourceful.",
        "reason": "Most blockers dissolve on the first attempt; ask about the ones that don't.",
    },
    {
        "content": "Private things stay private. Ask before acting externally.",
        "reason": "Sending, pushing and publishing are hard to undo.",
    },
    {
        "content": "Never kill processes by image name; kill only a PID you started.",
        "reason": "A kill-by-name once took down a four-hour GPU run and the memory server together.",
    },
    {
        "content": "Session maintenance is not optional: errors and fixes go in .learnings/ERRORS.md, patterns in .learnings/LEARNINGS.md, and a daily note in session-logs/YYYY-MM-DD.md. Delegate it to a background agent so the main work stays focused.",
        "reason": "Rotation and the next session both read from there; an unrecorded fix gets rediscovered.",
    },
    {
        "content": "Checkpoint when you judge a step done: before declaring a phase, step, or part of a plan finished, call context(checkpoint_save) with what closed and what is next.",
        "reason": "A compaction or a crash keeps only what is written; the model is the one who knows when a unit closed.",
    },
]

# How the work flows. Distilled from the author's best-kept project rulebooks
# (plan-before-code, proposed/open/decided, gates and audits, delegation,
# verification, evidence, git) in their own wording where it exists.
WORKFLOW_RULES: list[dict] = [
    {
        "content": "Plan before code: nothing gets implemented until the design is written down and agreed. Say what you intend, wait for the go, then do it. An approved design is not by itself an approval to build it.",
        "reason": "Code written before the design settles encodes an assumption nobody argued about.",
    },
    {
        "content": "Proposed, open, and decided are three different things. A proposal never silently becomes a decision; a decision is written down where decisions live, with a 'revisit if' condition.",
        "reason": "That is how a repo ends up with six decisions nobody remembers making.",
    },
    {
        "content": "Every milestone has a gate written before the work and a verdict written after. A phase is not done until its gate is met and recorded, and a large milestone gets an independent review (a fresh reviewer or an adversarial pass) before anything is built on it.",
        "reason": "Skipping gates to go faster is how grouping errors reached forty models; a phase that was never audited is a phase nobody knows the state of.",
    },
    {
        "content": "Delegate by size, not by habit: do small in-context work yourself; delegate multi-hour or parallel builds to subagents; use a cheap model for logs and maintenance and a strong one for review; give every agent prompt a hard agent budget; batch source commits so a re-cut happens once.",
        "reason": "Uncapped delegation defaults to expensive fleets; unbatched commits get re-cut every time.",
    },
    {
        "content": "Verify before claiming done: run the targeted tests plus one unmocked end-to-end path, list every created file in the report, and never launch a run on an input you know is broken. 'Found, not fixed' is not done.",
        "reason": "A mocked seam hid a dead path once; a known input defect wasted a full run.",
    },
    {
        "content": "Numbers get a source and evidence gets kept: if a document or a decision cites a number, the thing that produced it is in experiments/ or the run report, with where it came from and when.",
        "reason": "A conclusion is a claim; only the run behind it survives 'are you sure?' a year later.",
    },
    {
        "content": "Anything that leaves the machine is the owner's decision: a push, a pull request, a comment. Local commits are free. Never force-push main. One pull request, one idea; squash by default, but never squash a pull request another branch is stacked on.",
        "reason": "A squashed base orphaned two stacked pull requests once; local commits are free, pushes are not.",
    },
    {
        "content": "Write the learning when it happens, not at the end, and only what the repo does not already say. Every markdown document carries the nav header (type, status, updated, project, summary).",
        "reason": "The value is in the entries written while they still hurt; the header is what lets documents be indexed and read at a glance.",
    },
]

RULES: list[dict] = UNIVERSAL_RULES + WORKFLOW_RULES

STRUCTURE_MARKERS = (".git", "pyproject.toml", "package.json", "Cargo.toml", "go.mod", "CLAUDE.md", "setup.py", "Makefile")
LEARNING_FILES = ("ERRORS.md", "LEARNINGS.md")

_WORD = re.compile(r"[a-z0-9]+")


def _words(s: str) -> set[str]:
    return {w for w in _WORD.findall(s.lower()) if len(w) > 2}


def similar(a: str, b: str, threshold: float = 0.45) -> bool:
    """Same rule in substance: word-set Jaccard, or one's opening inside the other."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return False
    j = len(wa & wb) / len(wa | wb)
    if j >= threshold:
        return True
    head = a.lower()[:40].strip()
    return bool(head) and head in b.lower()


def is_project_dir(project_dir: str) -> bool:
    p = Path(project_dir)
    try:
        if not p.is_dir():
            return False
        if p == Path.home() or p.parent == p:
            return False
    except Exception:
        return False
    return any((p / m).exists() for m in STRUCTURE_MARKERS)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def _marker_path(project_dir: str) -> Optional[Path]:
    try:
        from claude_engram.hooks.remind import get_project_memory_dir

        d = get_project_memory_dir(project_dir)
        return Path(d) / "default_pack.json"
    except Exception:
        return None


def seeded_version(project_dir: str) -> int:
    p = _marker_path(project_dir)
    if not p or not p.is_file():
        return 0
    try:
        return int(json.loads(p.read_text(encoding="utf-8")).get("version", 0))
    except Exception:
        return 0


def existing_rule_texts(project_dir: str) -> list[str]:
    """This project's rules plus inherited ones from ancestors."""
    try:
        from claude_engram.hooks.storage import load_project_memory, get_project_rules

        return [r.get("content", "") for r in get_project_rules(load_project_memory(project_dir))]
    except Exception:
        return []


def seed_rules(project_dir: str, force: bool = False, include_workflow: bool = True) -> dict:
    """Add the pack's rules the project does not already have in substance.
    Returns {"added": [...], "skipped": [...], "already_seeded": bool}."""
    report: dict = {"added": [], "skipped": [], "already_seeded": False}
    if not force and seeded_version(project_dir) >= PACK_VERSION:
        report["already_seeded"] = True
        return report
    existing = existing_rule_texts(project_dir)
    try:
        from claude_engram.tools.memory import MemoryStore

        store = MemoryStore()
    except Exception:
        return report
    rules = UNIVERSAL_RULES + (WORKFLOW_RULES if include_workflow else [])
    for rule in rules:
        if any(similar(rule["content"], e) for e in existing):
            report["skipped"].append(rule["content"][:60])
            continue
        try:
            ok, _ = store.add_rule(project_dir, rule["content"], rule["reason"])
        except Exception:
            ok = False
        (report["added"] if ok else report["skipped"]).append(rule["content"][:60])
    p = _marker_path(project_dir)
    if p:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(
                (json.dumps({"version": PACK_VERSION, "seeded_at": time.time(), "added": report["added"], "skipped": report["skipped"]}, indent=2) + "\n").encode("utf-8")
            )
        except Exception:
            pass
    return report


# ---------------------------------------------------------------------------
# Structure: the workspace scaffold, headered per tools/NAVIGATION-SPEC.md
# ---------------------------------------------------------------------------


def _header(kind: str, project: str, summary: str, today: str) -> str:
    return f"---\ntype: {kind}\nstatus: active\nupdated: {today}\nproject: {project}\nsummary: {summary}\n---\n\n"


_WORKFLOW_MD = """## Workflow

- **Plan before code.** Nothing gets implemented until the design is written down and agreed. Say what you intend, wait for the go, then do it. An approved design is not by itself an approval to build it.
- **Proposed, open, decided.** Three different things. A proposal never silently becomes a decision; a decision is written down with a "revisit if" condition.
- **Gates and audits.** Every milestone has a gate written before the work and a verdict after. A large milestone gets an independent review before anything is built on it.
- **Delegate by size.** Small in-context work yourself; multi-hour or parallel builds to subagents; a cheap model for logs and maintenance, a strong one for review; every agent prompt carries a hard agent budget; batch source commits so a re-cut happens once.
- **Verify before done.** Targeted tests plus one unmocked end-to-end path; every created file listed in the report; never launch a run on an input you know is broken.
- **Evidence.** Numbers get a source; the run behind a cited number is kept in `experiments/` or the run report.
- **Git.** Anything that leaves the machine is the owner's decision; local commits are free. Never force-push `main`. One pull request, one idea; squash by default, never a pull request something is stacked on.
- **Record.** Errors and fixes in `.learnings/ERRORS.md`, patterns in `.learnings/LEARNINGS.md`, a daily note in `session-logs/`, written when it happens. Every markdown document carries the nav header.
"""


def _claude_md(project: str, today: str) -> str:
    return _header("readme", project, f"TODO - one line describing {project}.", today) + (
        f"# {project}\n\n"
        "## Purpose\n(describe the project)\n\n"
        "## Testing\n```bash\n# (add test commands)\n```\n\n"
        "## Structure\n- `.learnings/` — Errors and learnings\n- `session-logs/` — Daily session logs\n\n"
        + _WORKFLOW_MD
    )


def _errors_md(project: str, today: str) -> str:
    return _header("learnings", project, f"Project-specific errors and fixes for {project}.", today) + "# Errors\n\nProject-specific errors and fixes.\n"


def _learnings_md(project: str, today: str) -> str:
    return _header("learnings", project, f"Project-specific learnings and patterns for {project}.", today) + "# Learnings\n\nProject-specific learnings and patterns.\n"


def _per_person_layout(root: Path) -> bool:
    """trade-lab's shape: .learnings/<name>/ and session-logs/<name>/. Leave it alone."""
    for base in (root / ".learnings", root / "session-logs"):
        if base.is_dir() and any(d.is_dir() and not d.name.startswith(".") and d.name != "archive" for d in base.iterdir()):
            return True
    return False


def ensure_structure(project_dir: str, today: Optional[str] = None) -> list[str]:
    """Create the missing pieces of the scaffold; return what was created."""
    if not is_project_dir(project_dir):
        return []
    root = Path(project_dir)
    today = today or date.today().isoformat()
    created: list[str] = []
    per_person = _per_person_layout(root)
    wanted = {"CLAUDE.md": _claude_md(root.name, today)}
    if not per_person:
        wanted[".learnings/ERRORS.md"] = _errors_md(root.name, today)
        wanted[".learnings/LEARNINGS.md"] = _learnings_md(root.name, today)
    for rel, body in wanted.items():
        p = root / rel
        if p.exists():
            continue
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(body.encode("utf-8"))
            created.append(rel)
        except Exception:
            continue
    logs = root / "session-logs"
    if not logs.exists():
        try:
            logs.mkdir(parents=True)
            created.append("session-logs/")
        except Exception:
            pass
    return created


# ---------------------------------------------------------------------------
# Entry point for SessionStart
# ---------------------------------------------------------------------------


def run_at_session_start(project_dir: str) -> list[str]:
    """Seed rules and create structure per config; return banner lines."""
    lines: list[str] = []
    cfg = project_config.load(project_dir)
    if project_config.enabled(cfg, "structure"):
        created = ensure_structure(project_dir)
        if created:
            lines.append(
                "Project structure created: " + ", ".join(created) + ' (turn off with "structure": false in .engram/config.json)'
            )
    if project_config.enabled(cfg, "default_rules") and is_project_dir(project_dir):
        rep = seed_rules(project_dir, include_workflow=project_config.enabled(cfg, "workflow_rules"))
        if rep["added"]:
            lines.append(
                f"Default rules seeded: {len(rep['added'])} added, {len(rep['skipped'])} already covered "
                '(memory(list_rules) to review; "default_rules": false in .engram/config.json to opt out)'
            )
    return lines
