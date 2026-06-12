"""Curated-lessons bridge: ingest dated lesson files as protected memories.

Many workspaces keep hand-curated learning notes next to the code
(`.learnings/LEARNINGS.md` and friends). They are the highest
signal-per-byte text in a repo — dated, structured, written at the moment
of insight — and without this bridge they are invisible to the injection
layer that could resurface them at exactly the right moment.

Strictly opt-in — nothing workspace-specific ships here, not even a
default path:
- Sources come ONLY from config.json ``lessons_globs`` (a list of globs
  relative to each project root, e.g. ``[".learnings/*.md"]`` or
  ``["docs/lessons/*.md"]``). No config key, no feature: the tool never
  guesses which markdown files are curated lessons.
- Entry format: a line starting ``YYYY-MM-DD — text`` (em/en dash or
  hyphen) opens an entry, which runs until the next dated line. Undated
  content is ignored — dates make sync idempotent and the age shown at
  injection honest.

Synced entries are category="lesson": protected like rules (never
archived, never decayed, skipped by dedup — the FILE is the source of
truth), source="lessons:<relpath>", reconciled per file every miner run
(edits update, removals retire). Trigger surface for injection scoring:
tags from backticked tokens and module-ish words, related_files from
explicit file mentions PLUS files that import a mentioned module, joined
through the code index — "surface the numba lesson whenever a session
touches a file importing numba".
"""

import hashlib
import json
import re
import time
from pathlib import Path

_DATE_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*[—–-]\s*(.*)$")
_TICKED = re.compile(r"`([^`]{2,60})`")
_FILE_MENTION = re.compile(
    r"\b([\w./\\-]+\.(?:py|md|js|ts|tsx|jsx|rs|go|java|toml|json|yaml|yml))\b"
)
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")

MAX_FILE_BYTES = 500_000
MIN_ENTRY_CHARS = 40
MAX_ENTRY_CHARS = 1500


def _lesson_files(project_root: Path, cfg: dict) -> "list[Path]":
    globs = cfg.get("lessons_globs")
    if not isinstance(globs, list) or not globs:
        return []  # opt-in only: no configured globs, no feature
    out: list[Path] = []
    for g in globs:
        try:
            out.extend(sorted(project_root.glob(str(g))))
        except Exception:
            continue
    files = []
    for p in out:
        try:
            if p.is_file() and p.stat().st_size < MAX_FILE_BYTES:
                files.append(p)
        except OSError:
            continue
    return files


def _parse_lessons(text: str) -> "list[tuple[str, str]]":
    """(date, content) per dated entry; an entry runs to the next dated line."""
    entries: list[tuple[str, str]] = []
    cur_date = ""
    cur_lines: list[str] = []

    def _flush():
        if cur_date and cur_lines:
            content = " ".join(cur_lines).strip()
            if len(content) >= MIN_ENTRY_CHARS:
                entries.append((cur_date, content[:MAX_ENTRY_CHARS]))

    for line in text.splitlines():
        m = _DATE_LINE.match(line.strip())
        if m:
            _flush()
            cur_date = m.group(1)
            cur_lines = [m.group(2)] if m.group(2) else []
        elif cur_date and line.strip():
            cur_lines.append(line.strip())
    _flush()
    return entries


def _module_importers(idx) -> "dict[str, list[str]]":
    """bare module name (lower) -> basenames of indexed files importing it."""
    out: dict[str, list[str]] = {}
    if idx is None:
        return out
    try:
        for rel, rec in idx.modules.items():
            base = Path(rel).name
            for imp in rec.get("imports", []):
                if imp.startswith("from "):
                    parts = imp.split()
                    mod = parts[1].lstrip(".").split(".")[0] if len(parts) > 1 else ""
                else:
                    mod = imp.split(".")[0]
                if mod:
                    out.setdefault(mod.lower(), []).append(base)
    except Exception:
        return {}
    return out


def _entry_fields(
    date: str, content: str, importers: "dict[str, list[str]]"
) -> dict:
    tags = {"lesson"}
    related: set = set()
    for t in _TICKED.findall(content):
        tok = t.strip().split("(")[0]
        if re.fullmatch(r"[\w.-]+", tok) and len(tok) < 40:
            tags.add(tok.split(".")[0].lower())
    for fm in _FILE_MENTION.findall(content):
        related.add(Path(fm).name)
    for w in set(_WORD.findall(content)):
        wl = w.lower()
        if wl in importers:
            tags.add(wl)
            related.update(importers[wl][:6])
    try:
        created = time.mktime(time.strptime(date, "%Y-%m-%d"))
    except (ValueError, OverflowError):
        created = time.time()
    return {
        "content": f"LESSON: {content}",
        "tags": sorted(tags)[:10],
        "related_files": sorted(related)[:10],
        "created_at": created,
    }


def sync_lessons(store, project_path: str) -> int:
    """Reconcile a project's lesson files into its memory store.

    Full per-file reconciliation: new entries appear, edited entries
    update, entries removed from the file retire from the hot store (the
    file is the source of truth — nothing is archived because nothing is
    lost). Returns the number of changes. Never raises.
    """
    try:
        root = Path(project_path)
        if not root.is_dir():
            return 0
        cfg = {}
        try:
            cfg_file = Path(str(store.storage_dir)).expanduser() / "config.json"
            if cfg_file.exists():
                cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
        files = _lesson_files(root, cfg)
        if not files:
            return 0

        from claude_engram.mining.code_index import resolve_code_index
        from claude_engram.tools.memory import MemoryEntry

        proj = store.get_project(project_path) or store.remember_project(
            project_path
        )
        idx = None
        try:
            idx = resolve_code_index(project_path)
        except Exception:
            pass
        importers = _module_importers(idx)

        changed = 0
        for f in files:
            try:
                rel = f.relative_to(root).as_posix()
            except ValueError:
                rel = f.name
            source_key = f"lessons:{rel}"
            try:
                parsed = _parse_lessons(
                    f.read_text(encoding="utf-8", errors="ignore")
                )
            except OSError:
                continue

            desired: dict[str, dict] = {}
            for date, content in parsed:
                eid = hashlib.md5(
                    f"{source_key}:{date}:{content[:120]}".encode("utf-8")
                ).hexdigest()[:12]
                desired[eid] = _entry_fields(date, content, importers)

            existing = {
                e.id: e for e in proj.entries if e.source == source_key
            }
            for eid, fields in desired.items():
                if eid in existing:
                    e = existing.pop(eid)
                    if (
                        e.content != fields["content"]
                        or e.related_files != fields["related_files"]
                        or e.tags != fields["tags"]
                    ):
                        e.content = fields["content"]
                        e.tags = fields["tags"]
                        e.related_files = fields["related_files"]
                        changed += 1
                else:
                    proj.entries.append(
                        MemoryEntry(
                            id=eid,
                            content=fields["content"],
                            category="lesson",
                            source=source_key,
                            relevance=8,
                            created_at=fields["created_at"],
                            last_accessed=time.time(),
                            access_count=1,
                            tags=fields["tags"],
                            related_files=fields["related_files"],
                        )
                    )
                    changed += 1
            # Entries gone from the file retire from the hot store.
            for stale in existing.values():
                proj.entries.remove(stale)
                changed += 1

        if changed:
            store._rebuild_indexes(proj)
            store._save()
        return changed
    except Exception:
        return 0
