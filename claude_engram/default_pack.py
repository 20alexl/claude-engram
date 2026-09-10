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

PACK_VERSION = 6  # 4: detectors on the rules that need one; 5: the code tier; 6: unattended=deny on the ask-first detectors

# Detectors (hooks/compliance.py) for the pack rules that can be watched by
# a regex. Hand-written, shipped with the rule; a project's own rule that
# already covers the same ground adopts the detector if it has none.
DESTRUCTIVE_DETECTOR = {
    "tools": ["Bash", "PowerShell"],
    "command": (
        r"(?:^|[;&|(]\s*|\bsudo\s+|\bxargs\s+(?:-\S+\s+)*)rm\s+(?!--cached\b)(?!--help\b)"
        r"|\bgit\s+rm\s+(?!--cached\b)"
        r"|\bRemove-Item\b[^|;\n]*(?:-Recurse|-Force)"
        r"|\brmdir\s+/s\b|\bdel\s+/[sq]\b|\brd\s+/s\b"
        r"|\bgit\s+(?:reset\s+--hard|clean\s+-[a-zA-Z]*[fx]|branch\s+-D|checkout\s+--\s|restore\s+--staged|stash\s+drop|filter-branch|filter-repo)"
        r"|\bgit\s+push\b[^|;\n]*(?:--force\b|-f\b|--force-with-lease)"
        r"|\bDROP\s+(?:TABLE|DATABASE|SCHEMA|INDEX)\b|\bTRUNCATE\s+TABLE\b"
        r"|\bformat\s+[a-zA-Z]:|\bmkfs\b|\bdd\s+if=|\bshred\b"
        r"|\btaskkill\b|\bStop-Process\b|\bpkill\b|\bkillall\b|\bkill\s+-9\b"
    ),
    "note": "destructive shell: recursive/forced delete, hard reset, force-push, DROP/TRUNCATE, disk format, kill",
    "unattended": "deny",  # an ask-first rule cannot be asked when nobody is there
}
KILL_BY_NAME_DETECTOR = {
    "tools": ["Bash", "PowerShell"],
    "command": r"\btaskkill\b[^|;\n]*/IM\b|\bStop-Process\b[^|;\n]*-Name\b|\bpkill\b|\bkillall\b|\bkill\s+-9\s+\$\(pgrep",
    "note": "kill by image or process name",
    "unattended": "deny",
}
OUTBOUND_DETECTOR = {
    "tools": ["Bash", "PowerShell"],
    "command": (
        r"\bgit\s+push\b|\bgh\s+(?:pr\s+(?:create|merge|comment|review|close)|issue\s+(?:create|comment|close)|release\s+create|repo\s+create)\b"
        r"|\bglab\s+mr\s+create\b|\bnpm\s+publish\b|\btwine\s+upload\b|\bcargo\s+publish\b|\bdocker\s+push\b"
        r"|\bcurl\b[^|;\n]*(?:-X\s*(?:POST|PUT|PATCH|DELETE)|--data\b|-d\s)"
    ),
    "note": "leaves the machine: push, pull request, publish, outbound POST",
    "unattended": "deny",
}

# The workspace rules, in the words they are written in there.
UNIVERSAL_RULES: list[dict] = [
    {
        "content": "Don't run destructive commands without asking. trash > rm. Never git push --force to main.",
        "reason": "Undo is cheaper than recovery.",
        "detector": DESTRUCTIVE_DETECTOR,
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
        "detector": OUTBOUND_DETECTOR,
    },
    {
        "content": "Proactively push back and bring things to the user's attention: flag risks, forgotten items, and misalignments with the plan without being asked.",
        "reason": "A collaborator who only answers the question asked misses the thing that was about to go wrong.",
        "anchors": ["push back", "pushback"],
    },
    {
        "content": "Follow the user's plan sequentially. Don't skip steps, and don't jump to later steps because they seem more interesting.",
        "reason": "Skipped steps are how a later step builds on something that was never done.",
        "anchors": ["plan sequentially", "skip steps"],
    },
    {
        "content": "Never kill processes by image name; kill only a PID you started.",
        "reason": "A kill-by-name once took down a four-hour GPU run and the memory server together.",
        "detector": KILL_BY_NAME_DETECTOR,
    },
    {
        "content": "Session maintenance is not optional: errors and fixes go in .learnings/ERRORS.md, patterns in .learnings/LEARNINGS.md, and a daily note in session-logs/YYYY-MM-DD.md. Delegate it to a background agent so the main work stays focused.",
        "reason": "Rotation and the next session both read from there; an unrecorded fix gets rediscovered.",
        "anchors": ["session maintenance"],
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
        "content": "Delegate by size, not by habit: do small in-context work yourself; hand multi-hour or parallel builds to subagents; a cheap model for logs and maintenance, a strong one for review and audits; a scripted multi-agent workflow only when the task is genuinely many independent stages, which is rare; every agent prompt carries a hard agent budget; batch source commits so a re-cut happens once.",
        "reason": "Uncapped delegation defaults to expensive fleets; a workflow where one subagent would do is the same waste; unbatched commits get re-cut every time.",
        "anchors": ["delegate by size", "agent budget"],
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
        "anchors": ["leaves the machine", "force-push", "force push"],
        "detector": OUTBOUND_DETECTOR,
    },
    {
        "content": "Write the learning when it happens, not at the end, and only what the repo does not already say. Every markdown document carries the nav header (type, status, updated, project, summary).",
        "reason": "The value is in the entries written while they still hurt; the header is what lets documents be indexed and read at a glance.",
    },
]

# How code is written. Distilled from the author's most refined project
# rulebook (shape, correctness) plus the two standing preferences that
# recur across their projects: performance from the start, both OSes.
CODE_RULES: list[dict] = [
    {
        "content": "One function, one purpose. If it does a second thing it becomes two functions; the tell is the word 'and' in the name or in the sentence you would use to describe it. No massive files or scripts: break things down by purpose.",
        "reason": "A file that holds everything touching one topic is a file nobody can hold in their head, and an agent editing it has the same problem with less warning.",
        "anchors": ["one function, one purpose", "massive files"],
    },
    {
        "content": "Names are semantically accurate: a file, folder, variable or function is named for what it does now, never a category that means nothing (utils, helpers, manager, handler, data2). A hard-to-name thing usually does more than one job. Comments explain why, not what.",
        "reason": "The code says what; a comment earns its place by recording the reason, the constraint, or the thing that was tried and did not work.",
        "anchors": ["semantically accurate", "why, not what"],
    },
    {
        "content": "Nothing left lying around: no commented-out code, no dead branches, no scaffolding from an abandoned approach, no TODO that outlived the person who wrote it.",
        "reason": "Git remembers the old version; the file does not have to.",
        "anchors": ["lying around", "commented-out code"],
    },
    {
        "content": "Verify before you claim: run it and quote what it printed. Not 'this should work', not 'tests pass' -- the output, from having watched it. A green typecheck is not a green build, and a green build is not a correct answer.",
        "reason": "The failure mode is not a crash; it is a number that looks fine and is wrong.",
        "anchors": ["quote what it printed", "green typecheck"],
    },
    {
        "content": "Never swallow an error on the decision path: no bare except, no catch that logs and continues, no fallback to a default that looks reasonable. Fail loudly.",
        "reason": "A silent exception inside a check is indistinguishable from a check that passed.",
        "anchors": ["swallow an error", "bare except"],
    },
    {
        "content": "Same inputs, same outputs: no wall-clock reads and no unseeded randomness anywhere a decision is made.",
        "reason": "A run you cannot reproduce is an anecdote, and a disagreement between two runs you cannot reproduce is unresolvable.",
        "anchors": ["same inputs, same outputs", "unseeded randomness"],
    },
    {
        "content": "Prefer the real thing to a stand-in. Do not write mocks that return what you expect; where a substitute is genuinely needed it is a real implementation of the seam driven by real data (a simulator, a replay of captured responses). A simulator is not a mock; a mock is a thing that agrees with you.",
        "reason": "A hand-written stand-in encodes your belief about how the other side behaves, and that belief is the single most likely thing to be wrong.",
        "anchors": ["real thing to a stand-in", "mock is a thing that agrees"],
    },
    {
        "content": "Secrets never appear in code, a commit, a log line, or a pull request body. Not once, not temporarily, not in a branch you plan to rebase.",
        "reason": "Git remembers, and a key that has been committed is a key that has been rotated.",
        "anchors": ["secrets never appear"],
    },
    {
        "content": "Build for performance from the start: batching, indexes, caching tiers and bounded memory on day one, sized for the real scale, never 'make it work, then make it fast'.",
        "reason": "The slow version is the one that ships; performance deferred is performance never added.",
        "anchors": ["performance from the start", "make it fast"],
    },
    {
        "content": "Code runs on both Windows and Linux: pathlib everywhere, no shell-specific assumptions, and a fallback for any platform-only primitive (sockets, file watching, compilation).",
        "reason": "Every project here is developed on one OS and run on the other.",
        "anchors": ["both Windows and Linux", "pathlib everywhere"],
    },
    {
        "content": "Pick the fast path on purpose: the right data structure and algorithm first (a set or dict over a scan, an index over a full read, a vectorized operation over a Python loop, approximate nearest neighbours over brute force at scale), then the library known to be fastest for the job, not the one that came to mind first. An O(n^2) that 'works' is a bug at real scale.",
        "reason": "The obvious approach is usually the slow one, and it is the one that gets shipped if nobody chooses.",
        "anchors": ["fast path on purpose", "fastest for the job"],
    },
    {
        "content": "Never do work twice: cache what is pure and expensive, stream what does not fit in memory, batch what round-trips, run in parallel what is independent. The hot path reads no file, takes no lock and makes no call it does not need.",
        "reason": "Repeated work is the commonest performance bug and the easiest to avoid at design time.",
        "anchors": ["work twice", "hot path"],
    },
    {
        "content": "Smart over busy: the shortest correct solution wins. Measure before optimizing and optimize what the profile names, not what looks slow; keep the measurement beside the change.",
        "reason": "Optimization by intuition makes code longer and no faster; a number from a profiler survives review.",
        "anchors": ["smart over busy", "what the profile names"],
    },
]

RULES: list[dict] = UNIVERSAL_RULES + WORKFLOW_RULES + CODE_RULES

STRUCTURE_MARKERS = (".git", "pyproject.toml", "package.json", "Cargo.toml", "go.mod", "CLAUDE.md", "setup.py", "Makefile")
LEARNING_FILES = ("ERRORS.md", "LEARNINGS.md")

_WORD = re.compile(r"[a-z0-9]+")


def _words(s: str) -> set[str]:
    return {w for w in _WORD.findall(s.lower()) if len(w) > 2}


def similar(a: str, b: str, threshold: float = 0.45, anchors: Optional[list[str]] = None) -> bool:
    """Same rule in substance: word-set Jaccard, one's opening inside the
    other, or a rule-specific anchor phrase present in the existing text (a
    user's own "Delegate session maintenance..." covers the pack's longer
    session-maintenance rule even though the words mostly differ)."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return False
    j = len(wa & wb) / len(wa | wb)
    if j >= threshold:
        return True
    head = a.lower()[:40].strip()
    if head and head in b.lower():
        return True
    bl = b.lower()
    return any(anc.lower() in bl for anc in (anchors or []))


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


def existing_rules(project_dir: str) -> list[dict]:
    """This project's rules plus inherited ones from ancestors, as raw
    entries ({id, content, detector, ...})."""
    try:
        from claude_engram.hooks.storage import load_project_memory

        pm = load_project_memory(project_dir)
        return [
            e
            for e in pm.get("entries", []) or []
            if isinstance(e, dict) and e.get("category") == "rule" and not e.get("archived_at")
        ]
    except Exception:
        return []


def existing_rule_texts(project_dir: str) -> list[str]:
    """This project's rules plus inherited ones from ancestors."""
    return [str(e.get("content", "")) for e in existing_rules(project_dir)]


def _attach_detector(store, project_dir: str, rule_id: str, detector: dict) -> bool:
    """Attach a pack detector to a covering rule that has none. The rule may
    live in this project or in an ancestor (workspace-level rules are
    inherited), so walk up until a store knows the id."""
    p = Path(project_dir).resolve()
    for _ in range(12):
        try:
            ok, _msg = store.set_detector(str(p), rule_id, detector)
        except Exception:
            ok = False
        if ok:
            return True
        if p.parent == p:
            break
        p = p.parent
    return False


def seed_rules(project_dir: str, force: bool = False, include_workflow: bool = True, include_code: bool = True) -> dict:
    """Add the pack's rules the project does not already have in substance.
    Returns {"added": [...], "skipped": [...], "already_seeded": bool}."""
    report: dict = {"added": [], "skipped": [], "already_seeded": False}
    if not force and seeded_version(project_dir) >= PACK_VERSION:
        report["already_seeded"] = True
        return report
    existing_entries = existing_rules(project_dir)
    try:
        from claude_engram.tools.memory import MemoryStore

        store = MemoryStore()
    except Exception:
        return report
    report["detectors_attached"] = []
    rules = UNIVERSAL_RULES + (WORKFLOW_RULES if include_workflow else []) + (CODE_RULES if include_code else [])
    for rule in rules:
        covering = [
            e
            for e in existing_entries
            if similar(rule["content"], str(e.get("content", "")), anchors=rule.get("anchors"))
        ]
        if covering:
            report["skipped"].append(rule["content"][:60])
            # The project's own rule covers this ground; if the pack rule
            # ships a detector and the covering rule has none, it adopts it.
            det = rule.get("detector")
            for e in covering:
                if not det or not e.get("id"):
                    continue
                have = e.get("detector")
                if not have:
                    if _attach_detector(store, project_dir, str(e["id"]), det):
                        report["detectors_attached"].append(str(e["id"]))
                elif (
                    isinstance(have, dict)
                    and have.get("note") == det.get("note")
                    and det.get("unattended")
                    and have.get("unattended") != det.get("unattended")
                ):
                    # A pack-shaped detector from an earlier pack version:
                    # carry the newer policy onto it, keep everything else.
                    if _attach_detector(store, project_dir, str(e["id"]), {**have, "unattended": det["unattended"]}):
                        report["detectors_attached"].append(str(e["id"]))
            continue
        try:
            ok, _ = store.add_rule(
                project_dir, rule["content"], rule["reason"], detector=rule.get("detector")
            )
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
- **Delegate by size.** Small in-context work yourself; multi-hour or parallel builds to subagents; a cheap model for logs and maintenance, a strong one for review and audits; a scripted multi-agent workflow only when the task is genuinely many independent stages, which is rare; every agent prompt carries a hard agent budget; batch source commits so a re-cut happens once.
- **Verify before done.** Targeted tests plus one unmocked end-to-end path; every created file listed in the report; never launch a run on an input you know is broken.
- **Evidence.** Numbers get a source; the run behind a cited number is kept in `experiments/` or the run report.
- **Git.** Anything that leaves the machine is the owner's decision; local commits are free. Never force-push `main`. One pull request, one idea; squash by default, never a pull request something is stacked on.
- **Record.** Errors and fixes in `.learnings/ERRORS.md`, patterns in `.learnings/LEARNINGS.md`, a daily note in `session-logs/`, written when it happens. Every markdown document carries the nav header.
"""

_CODE_MD = """## Code

- **One function, one purpose.** If it does a second thing it becomes two functions; the tell is the word "and". No massive files or scripts: break things down by purpose.
- **Names are semantically accurate.** Named for what it does now; never `utils`, `helpers`, `manager`, `handler`, `data2`. Comments explain why, not what.
- **Nothing left lying around.** No commented-out code, dead branches, abandoned scaffolding, or stale `TODO`s. Git remembers the old version.
- **Verify before you claim.** Run it and quote what it printed. A green typecheck is not a green build; a green build is not a correct answer.
- **Never swallow an error on the decision path.** No bare `except`, no catch-and-continue, no reasonable-looking default. Fail loudly.
- **Same inputs, same outputs.** No wall-clock reads or unseeded randomness where a decision is made.
- **Prefer the real thing to a stand-in.** No mocks that return what you expect; a substitute is a real implementation of the seam driven by real data. A simulator is not a mock; a mock is a thing that agrees with you.
- **Secrets never appear** in code, a commit, a log line, or a pull request body.
- **Performance from the start.** Batching, indexes, caching tiers and bounded memory on day one, at the real scale. Never "make it work, then make it fast".
- **Both Windows and Linux.** `pathlib` everywhere, no shell-specific assumptions, a fallback for any platform-only primitive.
- **Pick the fast path on purpose.** The right data structure and algorithm first (a set or dict over a scan, an index over a full read, a vectorized operation over a loop, ANN over brute force at scale), then the library known to be fastest for the job. An O(n²) that "works" is a bug at real scale.
- **Never do work twice.** Cache what is pure and expensive, stream what does not fit, batch what round-trips, parallelize what is independent. The hot path reads no file, takes no lock and makes no call it does not need.
- **Smart over busy.** The shortest correct solution wins. Measure before optimizing and optimize what the profile names, not what looks slow; keep the measurement beside the change.
"""


def _claude_md(project: str, today: str) -> str:
    return _header("readme", project, f"TODO - one line describing {project}.", today) + (
        f"# {project}\n\n"
        "## Purpose\n(describe the project)\n\n"
        "## Testing\n```bash\n# (add test commands)\n```\n\n"
        "## Structure\n- `.learnings/` — Errors and learnings\n- `session-logs/` — Daily session logs\n\n"
        + _WORKFLOW_MD
        + "\n"
        + _CODE_MD
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
        rep = seed_rules(
            project_dir,
            include_workflow=project_config.enabled(cfg, "workflow_rules"),
            include_code=project_config.enabled(cfg, "code_rules"),
        )
        if rep["added"]:
            lines.append(
                f"Default rules seeded: {len(rep['added'])} added, {len(rep['skipped'])} already covered "
                '(memory(list_rules) to review; "default_rules": false in .engram/config.json to opt out)'
            )
    return lines
