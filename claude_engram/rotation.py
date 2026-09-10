"""Rotation: keep a project's session logs and learnings from growing without bound.

The reference case is a project whose ``.learnings`` reached 3,500 lines and
whose ``session-logs/`` held 51 dailies. Both are loaded into context by
agents and people, so size is cost. Nothing is deleted by rotation: files and
entries move into ``archive/`` next to where they lived, and a one-line note
at the top of each trimmed file says what moved and where.

Policy (defaults; ``.engram/config.json`` overrides):

  * ``session-logs/YYYY-MM-DD.md`` older than 30 days move to
    ``session-logs/archive/YYYY-MM/`` and the month gets a digest,
    ``session-logs/archive/YYYY-MM.md`` -- one block per day with the title
    and the first bullet of each section, regenerated from the archived
    originals so it is always consistent with them.
  * ``.learnings/ERRORS.md``: dated sections older than 90 days move to
    ``.learnings/archive/ERRORS-YYYY.md``. ``LEARNINGS.md`` holds patterns,
    which do not age out: it rotates only when over the line cap. For either
    file, if the live file is over 500 lines the oldest dated sections older
    than 30 days follow until it fits. Undated sections never move (nothing
    to age them by), and sections marked STANDING / permanent / RULE never
    move.

Section shapes handled, all seen in real files: ``## 2026-06-08 -- title``,
``### 2026-09-09 -- title``, ``## 2026-04-08`` with ``###`` children, and
``## Title (2026-08-04)``. Files keep their own line endings.

``plan()`` is a dry run and returns what would happen; ``apply()`` does it.
SessionEnd computes the plan and, unless ``rotation`` is ``"auto"``, leaves it
in ``.engram/rotation-plan.json`` for SessionStart to announce.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from claude_engram import project_config

DAILY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.md$")
DATE_RE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
KEEP_RE = re.compile(r"\b(STANDING|permanent|never rotate|RULE)\b", re.IGNORECASE)
NOTE_PREFIX = "> Rotated "
PLAN_FILE = "rotation-plan.json"
LEARNING_FILES = ("ERRORS.md", "LEARNINGS.md")


# ---------------------------------------------------------------------------
# Small file helpers (line endings preserved, atomic writes)
# ---------------------------------------------------------------------------


def _read(path: Path) -> tuple[list[str], str]:
    raw = path.read_bytes()
    nl = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8", errors="replace")
    return text.split(nl), nl


def _write(path: Path, lines: list[str], nl: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(nl.join(lines).encode("utf-8"))
    tmp.replace(path)


def _append(path: Path, lines: list[str], nl: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[str] = []
    if path.is_file():
        existing, nl0 = _read(path)
        nl = nl0
        if existing and existing[-1] != "":
            existing.append("")
    _write(path, existing + lines, nl)


def _parse_date(s: str) -> Optional[date]:
    m = DATE_RE.search(s)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Learnings: sections
# ---------------------------------------------------------------------------


def _sections(lines: list[str]) -> tuple[list[str], list[dict]]:
    """Split into a preamble (everything before the first h2/h3 block) and
    top-level sections. A section starts at an h2, or at an h3 that is not
    under an h2 (the ``### date -- title`` shape before any ``##``), and runs
    to the next heading of the same or higher level."""
    preamble: list[str] = []
    sections: list[dict] = []
    cur: Optional[dict] = None
    level_of_cur = 0
    for ln in lines:
        m = HEADING_RE.match(ln)
        lvl = len(m.group(1)) if m else 0
        starts = False
        if m and lvl == 2:
            starts = True
        elif m and lvl == 3 and (cur is None or level_of_cur == 3):
            starts = True
        elif m and lvl == 1:
            # A title line: preamble if nothing started yet, else it closes
            # the current section and lives in the preamble tail (rare).
            if cur is None:
                preamble.append(ln)
                continue
        if starts:
            if cur is not None:
                sections.append(cur)
            title = m.group(2).strip() if m else ""
            cur = {"heading": ln, "title": title, "lines": [ln], "date": _parse_date(title), "keep": bool(KEEP_RE.search(title))}
            level_of_cur = lvl
            continue
        if cur is None:
            preamble.append(ln)
        else:
            cur["lines"].append(ln)
            if not cur["keep"] and KEEP_RE.search(ln) and len(cur["lines"]) <= 3:
                cur["keep"] = True
    if cur is not None:
        sections.append(cur)
    # A date-only h2 followed by h3 children: the h2's date applies to the block.
    for s in sections:
        if s["date"] is None:
            continue
    return preamble, sections


def _strip_note(preamble: list[str]) -> list[str]:
    return [ln for ln in preamble if not ln.startswith(NOTE_PREFIX)]


def _with_note(preamble: list[str], note: str) -> list[str]:
    pre = _strip_note(preamble)
    # After the H1 title if there is one, else at the top.
    idx = 0
    for i, ln in enumerate(pre):
        if ln.startswith("# "):
            idx = i + 1
            break
    out = pre[:idx]
    if idx:
        out.append("")  # blank between the title and the note
    out.append(note)
    rest = pre[idx:]
    while rest and rest[0] == "":
        rest = rest[1:]
    out.append("")
    return out + rest


def _units(base: Path, is_unit) -> list[Path]:
    """``base`` itself plus one level of per-person subdirectories (the
    trade-lab shape: ``.learnings/<name>/``, ``session-logs/<name>/``).
    ``archive/`` is never a unit."""
    if not base.is_dir():
        return []
    units = [base] if is_unit(base) else []
    for d in sorted(base.iterdir()):
        if d.is_dir() and d.name != "archive" and not d.name.startswith(".") and is_unit(d):
            units.append(d)
    return units


def _has_learning_file(d: Path) -> bool:
    return any((d / n).is_file() for n in LEARNING_FILES)


def _has_daily(d: Path) -> bool:
    try:
        return any(DAILY_RE.match(p.name) for p in d.iterdir() if p.is_file())
    except OSError:
        return False


def plan_learnings(project_dir: str, today: Optional[date] = None, cfg: Optional[dict] = None) -> list[dict]:
    """One plan entry per learnings file with something to move."""
    cfg = cfg or project_config.load(project_dir)
    today = today or date.today()
    # ERRORS.md holds dated fixes: they age out. LEARNINGS.md holds patterns,
    # which do not; by default it rotates only when over the line cap (oldest
    # first). rotation_learnings_days > 0 turns age on for it too.
    ages = {
        "ERRORS.md": int(cfg["rotation_learn_days"]),
        "LEARNINGS.md": int(cfg.get("rotation_learnings_days") or 0) or None,
    }
    soft_age = 30
    max_lines = int(cfg["rotation_learn_max_lines"])
    out = []
    for ldir in _units(Path(project_dir) / ".learnings", _has_learning_file):
        out.extend(_plan_learnings_dir(ldir, today, ages, soft_age, max_lines))
    return out


def _plan_learnings_dir(ldir: Path, today: date, ages: dict, soft_age: int, max_lines: int) -> list[dict]:
    out = []
    for name in LEARNING_FILES:
        f = ldir / name
        if not f.is_file():
            continue
        max_age = ages.get(name)
        lines, nl = _read(f)
        preamble, sections = _sections(lines)
        moving: list[dict] = []
        keeping: list[dict] = []
        for s in sections:
            age = (today - s["date"]).days if s["date"] else None
            if not s["keep"] and age is not None and max_age is not None and age > max_age:
                moving.append(s)
            else:
                keeping.append(s)
        live = len(preamble) + sum(len(s["lines"]) for s in keeping)
        if live > max_lines:
            # Oldest dated, not kept, older than the soft age, until it fits.
            candidates = sorted(
                [s for s in keeping if s["date"] and not s["keep"] and (today - s["date"]).days > soft_age],
                key=lambda s: s["date"],
            )
            for s in candidates:
                if live <= max_lines:
                    break
                keeping.remove(s)
                moving.append(s)
                live -= len(s["lines"])
        if not moving:
            continue
        moving.sort(key=lambda s: (s["date"] or date.min))
        by_year: dict[int, list[dict]] = {}
        for s in moving:
            by_year.setdefault((s["date"] or today).year, []).append(s)
        out.append(
            {
                "kind": "learnings",
                "file": str(f),
                "name": name,
                "unit": ldir.name if ldir.name != ".learnings" else "",
                "entries": len(moving),
                "lines_before": len(lines),
                "lines_after": live,
                "targets": {str(y): [s["title"][:80] for s in ss] for y, ss in by_year.items()},
                "_moving": moving,
                "_keeping": keeping,
                "_preamble": preamble,
                "_nl": nl,
            }
        )
    return out


def _apply_learnings(entry: dict, today: date) -> str:
    f = Path(entry["file"])
    nl = entry["_nl"]
    stem = entry["name"].rsplit(".", 1)[0]
    moved_to: list[str] = []
    by_year: dict[int, list[dict]] = {}
    for s in entry["_moving"]:
        by_year.setdefault((s["date"] or today).year, []).append(s)
    for year, ss in sorted(by_year.items()):
        target = f.parent / "archive" / f"{stem}-{year}.md"
        block: list[str] = []
        if not target.is_file():
            block += [f"# {stem} archive {year}", "", f"Rotated out of `{entry['name']}` by claude-engram; entries older than the retention window. Nothing here is lost, and `session_mine(search)` still reaches it.", ""]
        block.append(f"<!-- rotated {today.isoformat()} from {entry['name']}: {len(ss)} entries -->")
        block.append("")
        for s in ss:
            block += s["lines"]
            if block and block[-1] != "":
                block.append("")
        _append(target, block, nl)
        moved_to.append(f"archive/{target.name}")
    note = (
        f"{NOTE_PREFIX}{today.isoformat()}: {entry['entries']} entries older than the retention window moved to "
        + ", ".join(f"`{t}`" for t in moved_to)
        + " (claude-engram rotation; nothing deleted)."
    )
    new_lines = _with_note(entry["_preamble"], note)
    for s in entry["_keeping"]:
        if new_lines and new_lines[-1] != "":
            new_lines.append("")
        new_lines += s["lines"]
    while new_lines and new_lines[-1] == "":
        new_lines.pop()
    new_lines.append("")
    _write(f, new_lines, nl)
    return f"{entry['name']}: {entry['entries']} entries -> {', '.join(moved_to)}"


# ---------------------------------------------------------------------------
# Session logs: dailies -> monthly archive + digest
# ---------------------------------------------------------------------------


def plan_session_logs(project_dir: str, today: Optional[date] = None, cfg: Optional[dict] = None) -> list[dict]:
    cfg = cfg or project_config.load(project_dir)
    today = today or date.today()
    max_age = int(cfg["rotation_log_days"])
    out = []
    for sdir in _units(Path(project_dir) / "session-logs", _has_daily):
        item = _plan_session_logs_dir(sdir, today, max_age)
        if item:
            out.append(item)
    return out


def _plan_session_logs_dir(sdir: Path, today: date, max_age: int) -> Optional[dict]:
    moving: list[tuple[Path, date]] = []
    for f in sorted(sdir.iterdir()):
        m = DAILY_RE.match(f.name)
        if not m or not f.is_file():
            continue
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        if (today - d).days > max_age:
            moving.append((f, d))
    if not moving:
        return None
    months: dict[str, list[str]] = {}
    for f, d in moving:
        months.setdefault(d.strftime("%Y-%m"), []).append(f.name)
    return {
        "kind": "session-logs",
        "dir": str(sdir),
        "unit": sdir.name if sdir.name != "session-logs" else "",
        "files": len(moving),
        "months": months,
        "_moving": [(str(f), d.isoformat()) for f, d in moving],
    }


def _digest_day(path: Path, max_lines: int = 6) -> list[str]:
    """Title + the first bullet under each section, capped."""
    lines, _ = _read(path)
    title = next((ln[2:].strip() for ln in lines if ln.startswith("# ")), path.stem)
    out = [f"## {title}", ""]
    taken = 0
    in_section = False
    got_bullet = False
    for ln in lines:
        if ln.startswith("## "):
            in_section = True
            got_bullet = False
            continue
        if in_section and not got_bullet and ln.lstrip().startswith(("- ", "* ")):
            out.append(ln.strip()[:240])
            got_bullet = True
            taken += 1
            if taken >= max_lines:
                break
    if taken == 0:
        for ln in lines[1:]:
            if ln.strip() and not ln.startswith("#"):
                out.append(ln.strip()[:240])
                break
    out.append(f"_Full log: `archive/{path.stem[:7]}/{path.name}`_")
    out.append("")
    return out


def rebuild_month_digest(sdir: Path, month: str) -> Path:
    mdir = sdir / "archive" / month
    digest = sdir / "archive" / f"{month}.md"
    days = sorted(p for p in mdir.glob("*.md") if DAILY_RE.match(p.name))
    lines = [f"# Session logs {month}", "", f"Digest of {len(days)} archived dailies (claude-engram rotation). Each day's full log is beside this file.", ""]
    for p in days:
        lines += _digest_day(p)
    _write(digest, lines, "\n")
    return digest


def _apply_session_logs(entry: dict, today: date) -> str:
    sdir = Path(entry["dir"])
    touched: set[str] = set()
    for fpath, iso in entry["_moving"]:
        f = Path(fpath)
        if not f.is_file():
            continue
        month = iso[:7]
        dest_dir = sdir / "archive" / month
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f.name
        if dest.exists():
            dest = dest_dir / f"{f.stem}.{int(time.time())}.md"
        f.replace(dest)
        touched.add(month)
    for month in sorted(touched):
        rebuild_month_digest(sdir, month)
    label = f"session-logs/{entry['unit']}" if entry.get("unit") else "session-logs"
    return f"{label}: {entry['files']} dailies -> archive/{{{', '.join(sorted(touched))}}} + digests"


# ---------------------------------------------------------------------------
# Plan / apply / persistence
# ---------------------------------------------------------------------------


def plan(project_dir: str, today: Optional[date] = None, cfg: Optional[dict] = None) -> dict:
    cfg = cfg or project_config.load(project_dir)
    today = today or date.today()
    items = plan_session_logs(project_dir, today, cfg) + plan_learnings(project_dir, today, cfg)
    return {
        "project": str(project_dir).replace("\\", "/"),
        "computed_at": datetime.now().isoformat(timespec="seconds"),
        "config": {k: cfg.get(k) for k in ("rotation", "rotation_log_days", "rotation_learn_days", "rotation_learnings_days", "rotation_learn_max_lines")},
        "items": items,
    }


def apply(p: dict, today: Optional[date] = None) -> list[str]:
    today = today or date.today()
    done: list[str] = []
    for item in p.get("items", []):
        if item.get("kind") == "session-logs":
            done.append(_apply_session_logs(item, today))
        elif item.get("kind") == "learnings":
            done.append(_apply_learnings(item, today))
    return done


def summarize(p: dict) -> str:
    parts = []
    for item in p.get("items", []):
        unit = f"{item['unit']}/" if item.get("unit") else ""
        if item["kind"] == "session-logs":
            parts.append(f"{item['files']} dailies older than the window -> session-logs/{unit}archive/")
        else:
            parts.append(f"{unit}{item['name']}: {item['entries']} entries -> .learnings/{unit}archive/ ({item['lines_before']} -> {item['lines_after']} lines)")
    return "; ".join(parts)


def plan_path(project_dir: str) -> Path:
    return Path(project_dir) / project_config.CONFIG_DIR / PLAN_FILE


def _public(p: dict) -> dict:
    return {**p, "items": [{k: v for k, v in it.items() if not k.startswith("_")} for it in p.get("items", [])]}


def save_plan(project_dir: str, p: dict) -> Optional[Path]:
    path = plan_path(project_dir)
    try:
        if not p.get("items"):
            if path.is_file():
                path.unlink()
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_bytes((json.dumps(_public(p), indent=2) + "\n").encode("utf-8"))
        tmp.replace(path)
        return path
    except Exception:
        return None


def pending_notice(project_dir: str) -> str:
    """One line for the SessionStart banner when a plan is waiting."""
    path = plan_path(project_dir)
    if not path.is_file():
        return ""
    try:
        p = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not p.get("items"):
        return ""
    return (
        f"Rotation pending: {summarize(p)}. Apply with session_mine(rotate, dry_run=false), "
        'or set "rotation": "auto" in .engram/config.json to apply at session end.'
    )


def run_at_session_end(project_dir: str) -> str:
    """Compute the plan; apply it when rotation is "auto", else persist it for
    the next SessionStart to announce. Returns a one-line summary."""
    cfg = project_config.load(project_dir)
    if not project_config.enabled(cfg, "rotation"):
        return ""
    p = plan(project_dir, cfg=cfg)
    if not p["items"]:
        save_plan(project_dir, p)  # clears a stale plan
        return ""
    if cfg.get("rotation") == "auto":
        done = apply(p)
        save_plan(project_dir, {"items": []})
        return "rotated: " + "; ".join(done)
    save_plan(project_dir, p)
    return "rotation planned: " + summarize(p)


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    project = os.getcwd()
    do_apply = False
    i = 0
    while i < len(args):
        if args[i] == "--project" and i + 1 < len(args):
            project = args[i + 1]
            i += 1
        elif args[i] == "--apply":
            do_apply = True
        i += 1
    p = plan(project)
    if not p["items"]:
        print("nothing to rotate")
        return 0
    print(summarize(p))
    if do_apply:
        for line in apply(p):
            print(line)
        save_plan(project, {"items": []})
    else:
        print("(dry run; add --apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
