"""
Per-project memory loading and small read-side extractors.

Extracted from hooks/remind.py. Loads per-project memory.json with workspace
inheritance and provides pure helpers over a loaded memory dict. Depends only
on paths.py for location resolution -- no session state, no import cycle.
"""

import json
import re
from pathlib import Path

from .paths import (
    _get_manifest,
    _normalize_path,
    get_engram_storage_dir,
    get_memory_file,
)


def _claude_md_words(project_dir: str) -> set:
    """Significant words of the project's CLAUDE.md (the file Claude Code
    always loads into context). Empty set when there is none."""
    words: set = set()
    try:
        md = Path(project_dir) / "CLAUDE.md"
        if md.exists() and md.stat().st_size < 200_000:
            text = md.read_text(encoding="utf-8", errors="ignore").lower()
            words = {w for w in re.findall(r"[a-z0-9_>-]+", text) if len(w) > 2}
    except Exception:
        pass
    return words


def filter_rules_in_claude_md(rules: list, project_dir: str) -> list:
    """Drop rules whose content already lives in the project's CLAUDE.md.

    That file is in the model's context on every turn — re-injecting the
    same sentences from the rule store is pure token waste (the triple
    CLAUDE.md / engram-rules / MEMORY.md redundancy). A rule is considered
    covered when >=70% of its significant words appear in CLAUDE.md. Rules
    are still enforced and listable; only banner display is deduped.
    """
    md_words = _claude_md_words(project_dir)
    if not md_words:
        return rules
    kept = []
    for r in rules:
        content = (r.get("content", "") if isinstance(r, dict) else str(r)).lower()
        words = {w for w in re.findall(r"[a-z0-9_>-]+", content) if len(w) > 2}
        if words and len(words & md_words) / len(words) >= 0.7:
            continue
        kept.append(r)
    return kept


def _load_project_entries_from_dir(project_hash_dir: Path) -> list[dict]:
    """Load entries from a per-project memory.json file."""
    mem_file = project_hash_dir / "memory.json"
    if mem_file.exists():
        try:
            data = json.loads(mem_file.read_text())
            return data.get("entries", [])
        except Exception:
            pass
    return []


def _load_project_data_from_dir(project_hash_dir: Path) -> dict:
    """Load full project data from a per-project memory.json file."""
    mem_file = project_hash_dir / "memory.json"
    if mem_file.exists():
        try:
            return json.loads(mem_file.read_text())
        except Exception:
            pass
    return {}


def load_project_memory(project_dir: str) -> dict:
    """
    Load memories for a project, including inherited workspace-level memories.

    v5: Uses per-project files via manifest. Falls back to legacy memory.json.
    """
    storage = get_engram_storage_dir()
    manifest = _get_manifest()
    normalized = _normalize_path(project_dir)

    # v5 path: manifest exists with per-project files
    if manifest.get("projects"):
        manifest_projects = manifest["projects"]

        # Load primary project
        primary = None
        if normalized in manifest_projects:
            hash_id = manifest_projects[normalized]["hash"]
            pdir = storage / "projects" / hash_id
            primary = _load_project_data_from_dir(pdir)

        # Collect entries from ancestor paths
        ancestor_entries = []
        check_path = str(Path(normalized).parent)
        while check_path:
            norm_check = check_path.replace("\\", "/")
            if len(norm_check) >= 2 and norm_check[1] == ":":
                norm_check = norm_check[0].lower() + norm_check[1:]
            if norm_check in manifest_projects:
                hash_id = manifest_projects[norm_check]["hash"]
                pdir = storage / "projects" / hash_id
                ancestor_entries.extend(_load_project_entries_from_dir(pdir))
            parent = str(Path(check_path).parent)
            if parent == check_path:
                break
            check_path = parent

        if primary:
            result = dict(primary)
            if ancestor_entries:
                existing_ids = {e.get("id") for e in result.get("entries", [])}
                for entry in ancestor_entries:
                    if entry.get("id") not in existing_ids:
                        result.setdefault("entries", []).append(entry)
            return result

        # Name-based fallback
        project_name = Path(project_dir).name
        for path, info in manifest_projects.items():
            if Path(path).name == project_name:
                hash_id = info["hash"]
                pdir = storage / "projects" / hash_id
                return _load_project_data_from_dir(pdir)

        if ancestor_entries:
            return {"entries": ancestor_entries, "project_name": Path(project_dir).name}

        return {}

    # Legacy fallback: single memory.json
    memory_file = get_memory_file()
    if not memory_file.exists():
        return {}

    try:
        data = json.loads(memory_file.read_text())
        projects = data.get("projects", {})

        primary = projects.get(normalized)
        if not primary:
            for path, proj in projects.items():
                if _normalize_path(path) == normalized:
                    primary = proj
                    break

        ancestor_entries = []
        check_path = str(Path(normalized).parent)
        while check_path:
            norm_check = check_path.replace("\\", "/")
            if len(norm_check) >= 2 and norm_check[1] == ":":
                norm_check = norm_check[0].lower() + norm_check[1:]
            if norm_check in projects:
                ancestor_entries.extend(projects[norm_check].get("entries", []))
            parent = str(Path(check_path).parent)
            if parent == check_path:
                break
            check_path = parent

        if primary:
            result = dict(primary)
            if ancestor_entries:
                existing_ids = {e.get("id") for e in result.get("entries", [])}
                for entry in ancestor_entries:
                    if entry.get("id") not in existing_ids:
                        result.setdefault("entries", []).append(entry)
            return result

        project_name = Path(project_dir).name
        for path, proj in projects.items():
            if Path(path).name == project_name:
                return proj

        if ancestor_entries:
            return {"entries": ancestor_entries, "project_name": Path(project_dir).name}

        return {}
    except Exception:
        return {}


def get_past_mistakes(project_memory: dict) -> list[dict]:
    """Extract past mistakes from project memory, newest first.
    Returns list of dicts with 'id' and 'content' keys."""
    mistakes = []
    entries = project_memory.get("entries", [])

    # Sort by created_at descending (newest first)
    sorted_entries = sorted(entries, key=lambda x: x.get("created_at", 0), reverse=True)

    for entry in sorted_entries:
        if entry.get("archived_at"):
            continue  # acknowledged/hygiene-archived mistakes stay out of banners
        content = entry.get("content", "")
        category = entry.get("category", "")
        entry_id = entry.get("id", "")

        # Check both MISTAKE: prefix and category="mistake"
        if content.upper().startswith("MISTAKE:"):
            mistake_text = (
                content[9:] if content.startswith("MISTAKE: ") else content[8:]
            )
            mistakes.append({"id": entry_id, "content": mistake_text})
        elif category == "mistake":
            mistakes.append({"id": entry_id, "content": content})

    return mistakes


def get_project_rules(project_memory: dict) -> list[dict]:
    """Extract rules from project memory (always show these).
    Returns list of dicts with 'id' and 'content' keys."""
    rules = []
    entries = project_memory.get("entries", [])

    # Sort by relevance descending (most important first)
    sorted_entries = sorted(entries, key=lambda x: x.get("relevance", 5), reverse=True)

    for entry in sorted_entries:
        category = entry.get("category", "")
        if category == "rule":
            rules.append(
                {"id": entry.get("id", ""), "content": entry.get("content", "")}
            )

    return rules


def get_memory_counts(project_memory: dict) -> dict:
    """Get memory counts by category for summary display."""
    entries = project_memory.get("entries", [])
    counts = {}
    for entry in entries:
        cat = entry.get("category", "unknown")
        counts[cat] = counts.get(cat, 0) + 1
    counts["total"] = len(entries)
    return counts
