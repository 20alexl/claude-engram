"""
Hot-path memory reader and relevance scoring for hook-time injection.

stdlib-only ON PURPOSE: the pre-edit hook is a fresh Python process with a
1s budget, and this module used to live in tools/memory.py — importing it
dragged in the whole tools package (pydantic, httpx, the audit engine) and
cost ~185ms per hook before any work happened. Everything here works on raw
dicts. MemoryStore re-exports these names for back-compat.
"""

import json
import math
import os
import re
import time
from pathlib import Path

# Scoring weights for memory relevance ranking
SCORE_WEIGHTS = {
    "file_match": 0.35,
    "tag_overlap": 0.20,
    "recency": 0.20,
    "relevance": 0.15,
    "access_freq": 0.10,
}
CATEGORY_BONUSES = {"rule": 0.3, "mistake": 0.2}
RECENCY_HALF_LIFE_DAYS = 30

# Filenames that exist in nearly every project/package. A bare basename match
# on these is meaningless (every project has an __init__.py), so they require a
# full-path signal before a memory counts as file-relevant — otherwise a service-a
# mistake about __init__.py fires on every service-b __init__.py edit.
_GENERIC_BASENAMES = {
    "__init__.py",
    "__main__.py",
    "__init__.ts",
    "index.js",
    "index.ts",
    "index.tsx",
    "mod.rs",
    "setup.py",
    "conftest.py",
    "types.ts",
}

# Tag patterns for inferring context tags from a file path in hooks
_HOOK_TAG_PATTERNS = {
    r"\bauth\b|login|password|authentication": "auth",
    r"test|pytest|unittest|jest": "testing",
    r"config|settings|\.env": "config",
    r"database|db|sql|migration": "database",
    r"api|endpoint|route|handler": "api",
    r"security|vulnerability": "security",
    r"performance|optimize|slow": "performance",
    r"bug|fix|error|crash": "bugfix",
}


def _file_match_score(ctx_file: str, related_files: list, content: str) -> float:
    """Path-aware file relevance in [0, 1].

    The key fix for cross-version false positives: when a related file carries
    directory info, we require *path compatibility* (same file in absolute or
    relative form), not just a shared basename. ``service-a/.../losses/__init__.py``
    and ``service-b/.../losses/__init__.py`` share their whole suffix but are different
    files — they diverge at the ``service-a``/``service-b`` component, so they do NOT match.

    - Same path (abs or rel form of one path) -> 1.0
    - Bare-basename locator (no dir info), non-generic name -> 0.5
    - Generic basename without a full-path signal -> 0.0
    - Full path mentioned in the memory text -> 0.7; bare name-drop -> 0.3
    """
    if not ctx_file:
        return 0.0
    ctx_norm = ctx_file.replace("\\", "/").lower().strip("/")
    ctx_name = ctx_norm.rsplit("/", 1)[-1]
    generic = ctx_name in _GENERIC_BASENAMES

    best = 0.0
    for rf in related_files or []:
        if not rf:
            continue
        rf_norm = str(rf).replace("\\", "/").lower().strip("/")
        if rf_norm.rsplit("/", 1)[-1] != ctx_name:
            continue  # different file entirely
        if "/" in rf_norm:
            # Related file has directory info: demand path compatibility. A
            # mere shared basename across diverging paths is NOT a match.
            if (
                ctx_norm == rf_norm
                or ctx_norm.endswith("/" + rf_norm)
                or rf_norm.endswith("/" + ctx_norm)
            ):
                return 1.0
            continue
        # Bare basename locator (no path) — weak, worthless if generic.
        best = max(best, 0.0 if generic else 0.5)

    cn = content.replace("\\", "/").lower()
    if ctx_norm in cn:
        best = max(best, 0.7)  # full path appears in the memory -> strong signal
    elif not generic and ctx_name in cn:
        # A *specific* filename mentioned in a memory is real signal and matched
        # before — keep it (passes the gate). Only *generic* names are rejected
        # (the `not generic` guard): the bug is generic basenames and diverging
        # paths, not specific-filename recall.
        best = max(best, 0.5)
    return min(best, 1.0)


_FILE_EXTS = r"(?:py|js|ts|tsx|jsx|go|rs|java|cpp|c|h|md|json|yaml|yml|toml)"
_FILE_PATH_RE = re.compile(r"[\w/\\.:-]+\." + _FILE_EXTS)


def extract_file_refs(content: str) -> list[str]:
    """Extract file references from text, keeping full/relative paths rather
    than collapsing to basenames — so directory context survives and a
    ``service-a/.../x.py`` reference stays distinguishable from ``service-b/.../x.py``.

    Note: the previous implementation used a *capturing* extension group, so
    ``re.findall`` returned only the extension ("py") and every path was
    dropped; its fallback then kept basenames only. That left related_files
    without directory info — the root data cause of cross-version false
    positives. This keeps the whole matched path (non-capturing group, with
    ``/ \\ :`` in the character class for dirs and Windows drive letters).
    """
    files = set()
    for m in _FILE_PATH_RE.findall(content):
        m = m.strip().strip("\"'`,()[]{}<>")
        if m and not m.startswith("."):
            files.add(m)
    return sorted(files)


def score_entry(entry: dict, context: dict) -> float:
    """Score a raw entry dict against context. Fast, no Pydantic."""
    score = 0.0
    ctx_file = context.get("file_path", "")
    related_files = entry.get("related_files", [])
    content = entry.get("content", "")
    entry_tags = set(entry.get("tags", []))

    # File match (0.35) — path-aware (see _file_match_score): a shared
    # basename across diverging paths is not a match, and generic names
    # need a full-path signal.
    file_score = (
        _file_match_score(ctx_file, related_files, content) if ctx_file else 0.0
    )
    score += SCORE_WEIGHTS["file_match"] * file_score

    # Tag overlap (0.20)
    ctx_tags = set(context.get("tags", []))
    if ctx_file:
        for pattern, tag in _HOOK_TAG_PATTERNS.items():
            if re.search(pattern, ctx_file, re.IGNORECASE):
                ctx_tags.add(tag)
    if ctx_tags and entry_tags:
        tag_score = len(ctx_tags & entry_tags) / len(ctx_tags)
    else:
        tag_score = 0.0
    score += SCORE_WEIGHTS["tag_overlap"] * tag_score

    # Recency (0.20)
    last_accessed = entry.get("last_accessed", entry.get("created_at", 0))
    age_days = (time.time() - last_accessed) / 86400 if last_accessed else 999
    recency_score = math.exp(-age_days / RECENCY_HALF_LIFE_DAYS)
    score += SCORE_WEIGHTS["recency"] * recency_score

    # Relevance (0.15)
    score += SCORE_WEIGHTS["relevance"] * (entry.get("relevance", 5) / 10.0)

    # Access frequency (0.10)
    score += SCORE_WEIGHTS["access_freq"] * min(entry.get("access_count", 1) / 10.0, 1.0)

    # Category bonuses
    category = entry.get("category", "")
    score += CATEGORY_BONUSES.get(category, 0.0)

    return min(score, 1.0)


def _memory_injection_weight() -> float:
    """Bounded multiplier from the injection-outcome feedback loop
    (mining/outcomes.py, persisted by the miner to injection_weights.json).
    Above 1.0 when memory injections precede passing tests more than
    baseline — inject a little more eagerly; below 1.0, more selectively.
    1.0 when the file is absent, unreadable, or the loop lacks samples."""
    try:
        base = os.environ.get("CLAUDE_ENGRAM_DIR", "")
        root = Path(base).expanduser() if base else Path.home() / ".claude_engram"
        raw = json.loads((root / "injection_weights.json").read_text())
        return min(1.2, max(0.8, float(raw.get("weights", {}).get("memory", 1.0))))
    except Exception:
        return 1.0


def score_loaded_entries(
    all_entries: list[dict], context: dict, limit: int = 3
) -> list[dict]:
    """
    Score and rank already-loaded entries for injection. The single scoring
    seam: HotMemoryReader delegates here after loading, and the pre-edit hook
    calls it directly with the project memory it already loaded (one parse of
    memory.json per hook, not two).

    Filter policy: only memories with DIRECT file relevance are injected.
    Rules always pass but are capped at one alongside file context. Tag-only
    matches were removed as too loose. No file-relevant memories -> silence.
    """
    if not all_entries:
        return []

    scored = []
    ctx_file = context.get("file_path", "")
    for entry in all_entries:
        s = score_entry(entry, context)
        if s > 0.1:
            scored.append((entry, s))

    scored.sort(key=lambda x: x[1], reverse=True)

    if ctx_file:
        file_relevant = []
        rules = []
        # The outcome feedback loop scales the relevance gate: a memory kind
        # that precedes passing tests above baseline lowers the bar slightly,
        # one that precedes failures raises it. Bounded to 0.42-0.62.
        gate = 0.5 / _memory_injection_weight()
        for entry, _s in scored:
            category = entry.get("category", "")
            if category == "rule":
                rules.append(entry)
                continue
            # Direct file relevance only — path-aware, so a shared basename
            # across diverging paths (e.g. service-a vs service-b) is not treated
            # as a match and generic names like __init__.py need a full path.
            related = entry.get("related_files", [])
            content = entry.get("content", "")
            if _file_match_score(ctx_file, related, content) >= gate:
                file_relevant.append(entry)

        # Only show rules when there's something file-specific to go with
        # them. Dumping generic rules on every unrelated edit is noise —
        # rules were already shown at SessionStart.
        if file_relevant:
            result = file_relevant[:limit]
            remaining = limit - len(result)
            if remaining > 0 and rules:
                result.extend(rules[:1])
            return result

        # No file-relevant memories — return nothing (silent)
        return []

    return [e for e, _ in scored[:limit]]


class HotMemoryReader:
    """
    Lightweight, read-only reader for hook-time memory injection.

    v5: Reads per-project files via manifest. Falls back to legacy memory.json.
    Works on raw dicts (no Pydantic parsing) for speed.
    Designed to be instantiated per hook call — no caching.
    """

    def __init__(self, storage_dir: str = ""):
        if not storage_dir:
            storage_dir = os.environ.get("CLAUDE_ENGRAM_DIR", "~/.claude_engram")
        self._storage = Path(storage_dir).expanduser()
        self._manifest_file = self._storage / "manifest.json"
        self._projects_dir = self._storage / "projects"
        # Legacy fallback
        self.memory_file = self._storage / "memory.json"
        self._manifest = None

    def _load_manifest(self) -> dict:
        """Load manifest (cached per instance)."""
        if self._manifest is not None:
            return self._manifest
        if self._manifest_file.exists():
            try:
                self._manifest = json.loads(self._manifest_file.read_text())
                return self._manifest
            except Exception:
                pass
        self._manifest = {}
        return self._manifest

    def _load_project_entries(self, norm_path: str) -> list[dict]:
        """Load entries for a single project from its per-project file."""
        manifest = self._load_manifest()
        projects = manifest.get("projects", {})
        if norm_path not in projects:
            return []
        hash_id = projects[norm_path]["hash"]
        mem_file = self._projects_dir / hash_id / "memory.json"
        if mem_file.exists():
            try:
                data = json.loads(mem_file.read_text())
                return data.get("entries", [])
            except Exception:
                pass
        return []

    def load_entries(self, project_path: str) -> list[dict]:
        """All entries for a project including ancestor (workspace) inheritance."""
        normalized = str(Path(project_path).resolve()).replace("\\", "/")
        if len(normalized) >= 2 and normalized[1] == ":":
            normalized = normalized[0].lower() + normalized[1:]

        manifest = self._load_manifest()

        # v5 path: use manifest + per-project files
        if manifest.get("projects"):
            all_entries = []
            # Walk this path and ancestors for inheritance
            check_path = normalized
            while check_path:
                entries = self._load_project_entries(check_path)
                all_entries.extend(entries)
                parent = str(Path(check_path).parent).replace("\\", "/")
                if parent == check_path:
                    break
                check_path = parent

            # Name-based fallback
            if not all_entries:
                project_name = Path(project_path).name
                for path, info in manifest.get("projects", {}).items():
                    if Path(path).name == project_name:
                        all_entries.extend(self._load_project_entries(path))
                        break
            return all_entries

        # Legacy fallback: read old memory.json
        if not self.memory_file.exists():
            return []
        try:
            data = json.loads(self.memory_file.read_text())
        except Exception:
            return []

        projects = data.get("projects", {})
        all_entries = []
        check_path = normalized
        while check_path:
            if check_path in projects:
                all_entries.extend(projects[check_path].get("entries", []))
            parent = str(Path(check_path).parent).replace("\\", "/")
            if parent == check_path:
                break
            check_path = parent

        if not all_entries:
            project_name = Path(project_path).name
            for path, p in projects.items():
                if Path(path).name == project_name:
                    all_entries.extend(p.get("entries", []))
                    break
        return all_entries

    def get_scored_memories(
        self,
        project_path: str,
        context: dict,
        limit: int = 3,
    ) -> list[dict]:
        """
        Score and rank hot memories for injection.

        Args:
            project_path: Project directory
            context: {"file_path": str, "tool_name": str, "command": str, "tags": list[str]}
            limit: Max memories to return

        Returns:
            List of raw entry dicts sorted by score descending.
        """
        return score_loaded_entries(self.load_entries(project_path), context, limit)

    # Back-compat: some callers/benches used the staticmethod directly.
    _score_entry = staticmethod(score_entry)
