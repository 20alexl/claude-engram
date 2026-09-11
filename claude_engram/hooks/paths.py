"""
Path, manifest, and per-project storage-location helpers.

Extracted from hooks/remind.py so the symbol-index / concurrency code and
the MCP tools can share project resolution without importing the heavy hook
module. Pure location logic, self-contained (os/json/hashlib/pathlib only),
so it never forms an import cycle with remind.py.
"""

import json
import os
import re
from pathlib import Path


def _normalize_path(path: str) -> str:
    """Normalize a path for consistent storage (lowercase drive, forward slashes)."""
    # Resolve to absolute, then use forward slashes for consistency
    normalized = str(Path(path).resolve()).replace("\\", "/")
    # Lowercase drive letter on Windows (D:/Code -> d:/Code)
    if len(normalized) >= 2 and normalized[1] == ":":
        normalized = normalized[0].lower() + normalized[1:]
    return normalized


# Project markers — files that indicate a project root
_PROJECT_MARKERS = {
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "go.sum",
    "pom.xml",
    "build.gradle",
    "CMakeLists.txt",
    "Makefile",
    "setup.py",
    "setup.cfg",
    ".git",
    "CLAUDE.md",
}

# Generic filenames present in nearly every project — a bare basename match on
# these pulls in unrelated projects' mistakes, so the pre-edit check requires a
# full-path match for them. One definition, in the stdlib-only hot_reader.
from .hot_reader import _GENERIC_BASENAMES  # noqa: E402,F401

# Cache: file_path -> resolved project dir (avoids repeated filesystem walks)
_project_dir_cache: dict[str, str] = {}


# Directory names that make everything beneath them somebody else's workspace,
# not a project of its own: a scratch area, a vendored tree, a cache. A git
# WORKTREE under one of these carries a `.git` file, which is a project marker,
# so marker-walking alone happily resolved E:/ws/trade-lab/.scratch/stack/<wt>
# to the worktree and filed trade-lab's errors under a directory nobody asks
# about (they then surfaced as claude-engram's own, 2026-09-10).
_NON_PROJECT_SEGMENTS = {".scratch", "node_modules", ".venv", "venv", "__pycache__"}


def _is_absolute_path(raw: str) -> bool:
    """True when ``raw`` names a location on its own, cwd-independently.

    A RELATIVE related_file is no evidence of anything: ``Path.resolve()`` pins
    it to whatever directory the process happens to run in, so a mined
    ``'v2/tests/test_orders.py'`` voted for the checkout the MINER was started
    from. That is how trading_bot's, kaggriculture's and trade-lab's errors
    became claude-engram's own -- the 0.8.36 migration ran from the engram
    checkout (2026-09-10). Windows drive and UNC paths are recognized on Linux
    too: a store written on Windows is read on both.
    """
    raw = raw.strip()
    if not raw:
        return False
    if raw.startswith("\\\\") or raw.startswith("//"):
        return True  # UNC share
    if re.match(r"^[A-Za-z]:[\\/]", raw):
        return True  # drive-absolute, whatever platform reads it
    try:
        return Path(raw).is_absolute()
    except Exception:
        return False


def _inside_non_project_dir(path: str, root: str) -> bool:
    """True when ``path`` lies under a scratch/vendor/cache dir below ``root``."""
    base = root.lower().rstrip("/")
    rel = path.lower().rstrip("/")
    if rel.startswith(base + "/"):
        rel = rel[len(base) + 1 :]
    return any(seg in _NON_PROJECT_SEGMENTS for seg in rel.split("/"))


def _nearest_real_project(sub: str, root: str) -> str:
    """``sub``, or its nearest ancestor that is not inside a scratch/vendor dir."""
    cur = sub
    base = root.lower().rstrip("/")
    while cur.lower().rstrip("/") != base and _inside_non_project_dir(cur, root):
        parent = str(Path(cur).parent).replace("\\", "/")
        if parent == cur:
            break
        cur = _normalize_path(parent)
    return cur


def target_project_for_files(
    project_path: str,
    related_files: list,
    content: str = "",
    known_projects: "list[str] | None" = None,
) -> str:
    """The sub-project a mined entry belongs to, from the files it names.

    Sessions run from a workspace root mine everything into the ROOT store,
    so a sub-project's own store stayed empty while the root pooled every
    sibling's mistakes (2026-09-10: claude-engram's store held 0 of the 148
    mistakes about it). The majority of the named files wins; files outside
    the root (temp dirs, other drives) do not vote. When the entry's text
    names one of the candidate projects (``trade_lab`` in a traceback), that
    project wins over the file vote -- a session that edits two projects
    lists both projects' files. A RELATIVE path never votes: it would resolve
    against the calling process's cwd, not the work's. Falls back to
    ``project_path`` itself.

    ``known_projects``: the projects the store actually knows (the manifest's
    keys). Given them, a file votes for the DEEPEST known project that
    contains it and no marker walking happens at all -- which is what keeps a
    git worktree or a vendored checkout (both carry project markers) from
    becoming a destination. Without them the walk still runs, but its answer
    is pulled back to the nearest ancestor that is not inside a scratch,
    vendor or cache directory. Either way an entry never lands in a path
    under another project's .scratch/, node_modules/, .venv/, venv/ or
    __pycache__/."""
    root = _normalize_path(project_path) if project_path else ""
    if not root or not related_files:
        return project_path
    root_l = root.lower().rstrip("/") + "/"

    # Registered destinations under the root, deepest first, junk paths dropped.
    known: list[str] = []
    if known_projects:
        for k in known_projects or []:
            try:
                n = _normalize_path(str(k))
            except Exception:
                continue
            if n.lower().rstrip("/") == root.lower().rstrip("/"):
                continue  # the root is the fallback, never a vote
            if not n.lower().startswith(root_l):
                continue  # a sibling of the root: out of scope
            if _inside_non_project_dir(n, root):
                continue  # a worktree/vendor dir registered by accident
            known.append(n)
        known.sort(key=lambda p: p.count("/"), reverse=True)

    def _owner(p: str) -> str:
        """The known project containing ``p`` (deepest wins), or ""."""
        pl = p.lower()
        for k in known:
            kl = k.lower().rstrip("/")
            if pl == kl or pl.startswith(kl + "/"):
                return k
        return ""

    votes: dict[str, int] = {}
    for f in related_files or []:
        if not _is_absolute_path(str(f)):
            continue  # relative: would resolve against this process's cwd
        try:
            p = _normalize_path(str(f))
        except Exception:
            continue
        if not p.lower().startswith(root_l):
            continue  # outside the mining root: no vote
        if known_projects is not None:
            sub = _owner(p)  # under no known project: no vote
        else:
            try:
                sub = _nearest_real_project(resolve_project_for_file(p, root), root)
            except Exception:
                continue
        if not sub or sub.lower().rstrip("/") == root.lower().rstrip("/"):
            continue
        votes[sub] = votes.get(sub, 0) + 1
    if not votes:
        return project_path
    text = (content or "").lower()
    if text:
        # Voted projects first, then the other candidates under the root: a
        # traceback that says `trade_lab` belongs there even when the
        # session's edits named another project's files. The candidate pool is
        # the known projects when the caller supplied them, otherwise every
        # marked child of the root.
        candidates = list(votes)
        extra: list[str] = list(known)
        if known_projects is None:
            extra = []
            try:
                for child in sorted(Path(root).iterdir()):
                    if child.is_dir() and any(
                        (child / m).exists() for m in _PROJECT_MARKERS
                    ):
                        extra.append(_normalize_path(str(child)))
            except Exception:
                pass
        for n in extra:
            if n not in candidates:
                candidates.append(n)
        for sub in candidates:
            name = Path(sub).name.lower()
            if len(name) < 6:
                continue  # short names ("tools", "docs") match ordinary words
            for variant in {name, name.replace("-", "_"), name.replace("_", "-")}:
                if re.search(r"(?<![a-z0-9])" + re.escape(variant) + r"(?![a-z0-9])", text):
                    return sub
    return max(votes.items(), key=lambda kv: kv[1])[0]


def resolve_project_for_file(file_path: str, workspace_root: str = "") -> str:
    """
    Resolve which sub-project a file belongs to within a workspace.

    Walks up from the file toward workspace_root, looking for project markers
    (pyproject.toml, package.json, Cargo.toml, .git, etc.).

    Returns the project directory, or workspace_root if no marker found.
    """
    if not file_path:
        return workspace_root or _normalize_path(os.getcwd())

    # Check cache
    if file_path in _project_dir_cache:
        return _project_dir_cache[file_path]

    workspace = (
        Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
    )
    target = Path(file_path).resolve()

    # If the file IS the workspace (not inside a sub-project), just use workspace
    if target == workspace or not str(target).startswith(str(workspace)):
        return _normalize_path(str(workspace))

    # Walk up from file's directory toward workspace root
    current = target.parent if target.is_file() else target
    best_project = workspace  # Default fallback

    while current >= workspace:
        for marker in _PROJECT_MARKERS:
            if (current / marker).exists():
                best_project = current
                # Don't break — keep walking up. We want the CLOSEST marker
                # to the file, but if we're at workspace level that's just cwd.
                # So we actually want to stop at the first marker we find.
                result = _normalize_path(str(current))
                _project_dir_cache[file_path] = result
                return result
        if current == workspace:
            break
        current = current.parent

    result = _normalize_path(str(best_project))
    _project_dir_cache[file_path] = result
    return result


def get_project_dir(file_path: str = "") -> str:
    """
    Get the project directory, optionally scoped to a file's sub-project.

    Priority:
    1. CLAUDE_PROJECT_DIR env var (if set explicitly)
    2. Sub-project resolution from file_path (walks up looking for markers)
    3. Current working directory (fallback)
    """
    explicit = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if explicit:
        return _normalize_path(explicit)

    workspace_root = _normalize_path(os.getcwd())

    if file_path:
        return resolve_project_for_file(file_path, workspace_root)

    return workspace_root


def get_memory_file() -> Path:
    """Get the Claude Engram memory file path (legacy compat)."""
    return get_engram_storage_dir() / "memory.json"


def get_engram_storage_dir() -> Path:
    """Get the Claude Engram storage directory.

    CLAUDE_ENGRAM_DIR overrides the default ~/.claude_engram -- the seam test
    benches use for isolation (patching HOME does not move Path.home() on
    Windows, which made the old bench harnesses silently write to the real
    store)."""
    override = os.environ.get("CLAUDE_ENGRAM_DIR", "")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude_engram"


def _get_manifest() -> dict:
    """Load manifest.json if it exists."""
    manifest_file = get_engram_storage_dir() / "manifest.json"
    if manifest_file.exists():
        try:
            return json.loads(manifest_file.read_text())
        except Exception:
            pass
    return {}


def get_project_memory_dir(project_dir: str) -> Path:
    """Get the per-project memory directory for a project."""
    storage = get_engram_storage_dir()
    manifest = _get_manifest()
    normalized = _normalize_path(project_dir)
    projects = manifest.get("projects", {})
    if normalized in projects:
        hash_id = projects[normalized]["hash"]
        return storage / "projects" / hash_id
    # Not in manifest yet — compute hash
    import hashlib

    hash_id = hashlib.md5(normalized.encode()).hexdigest()[:8]
    return storage / "projects" / hash_id


def _global_handoff_dir() -> Path:
    """Global checkpoints dir — the cross-project fallback for handoffs."""
    return get_engram_storage_dir() / "checkpoints"


def _project_hash_dir(project_dir: str) -> "Path | None":
    """The per-project hash dir for handoff storage, or None when the project
    is not yet registered in the manifest (then only the global dir is used)."""
    if not project_dir:
        return None
    info = _get_manifest().get("projects", {}).get(_normalize_path(project_dir))
    if info:
        return get_engram_storage_dir() / "projects" / info["hash"]
    return None


def _handoff_candidate_dirs(project_dir: str = "") -> list:
    """Ordered dirs to search for a handoff: the project's own ring, then its
    DESCENDANT project rings, then ancestor rings. The global checkpoints dir
    is used ONLY as a fallback — appended just when no project-specific dir was
    found.

    Descendants are in scope because a workspace root is a real place to ask
    from. Without them, a restore at ``E:/workspace`` could only read the root
    ring while the session's actual final checkpoint sat in
    ``E:/workspace/chappie/V11`` — and, because the root ring is rarely empty,
    the call returned a HOURS-STALE entry and reported success. Silently
    restoring stale state is the exact failure a checkpoint system exists to
    prevent, so a query now sees everything at or beneath it. (The SessionStart
    banner already resolved the subtree this way via _subtree_manual_handoff;
    the MCP restore/list path did not.)

    Ordering does not decide selection — read_history sorts merged entries by
    recency and read_latest prefers the newest *manual* — so a nearer ring
    never wins on position alone, only on being newer.

    Descendants are still a strict subset of the tree you asked about: a
    sibling project can never appear. That is what the global ring (a
    cross-project superset written alongside every project ring) would have
    dragged in, which is why it stays a fallback rather than an always-on
    candidate. Unregistered projects (no own ring) resolve through it."""
    storage = get_engram_storage_dir()
    projects = _get_manifest().get("projects", {})
    dirs: list = []
    seen_hashes = set()

    def _add(info: dict) -> None:
        if info and info["hash"] not in seen_hashes:
            dirs.append(storage / "projects" / info["hash"])
            seen_hashes.add(info["hash"])

    if project_dir:
        try:
            p = Path(_normalize_path(project_dir))
        except Exception:
            p = None
        if p is not None:
            norm = _normalize_path(str(p))
            _add(projects.get(norm))
            # Descendants, nearest first: a shallower sub-project is the more
            # likely home of a checkpoint saved against a parent scope.
            for path, info in sorted(
                projects.items(), key=lambda kv: kv[0].count("/")
            ):
                if path.startswith(norm.rstrip("/") + "/"):
                    _add(info)
        while p is not None:
            _add(projects.get(_normalize_path(str(p))))
            parent = p.parent
            if parent == p:
                break
            p = parent
    if not dirs:
        dirs.append(storage / "checkpoints")
    return dirs
