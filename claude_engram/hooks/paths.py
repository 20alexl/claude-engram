"""
Path, manifest, and per-project storage-location helpers.

Extracted from hooks/remind.py so the symbol-index / concurrency code and
the MCP tools can share project resolution without importing the heavy hook
module. Pure location logic, self-contained (os/json/hashlib/pathlib only),
so it never forms an import cycle with remind.py.
"""

import json
import os
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
# these pulls in unrelated projects' mistakes (a V7 __init__.py mistake firing
# on a V8 __init__.py edit), so the pre-edit check requires a full-path match
# for them. Mirrors memory._GENERIC_BASENAMES (kept local to avoid importing
# the heavy memory module on the hot hook path).
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

# Cache: file_path -> resolved project dir (avoids repeated filesystem walks)
_project_dir_cache: dict[str, str] = {}


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
    return Path.home() / ".claude_engram" / "memory.json"


def get_engram_storage_dir() -> Path:
    """Get the Claude Engram storage directory."""
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
    """Ordered dirs to search for a handoff: nearest project first, then any
    ancestor project registered in the manifest. The global checkpoints dir is
    used ONLY as a fallback — appended just when no project-specific dir was
    found.

    Every handoff for a registered project is written to BOTH its own ring and
    the global ring, so the global ring is a cross-project superset. Appending
    it unconditionally made *merged* reads (handoff_history / checkpoint_list /
    get_by_index) surface OTHER projects' handoffs under a project-scoped
    query. Scoping to the project's own ring (plus ancestor projects, which
    legitimately cascade) keeps list/index project-clean; read_latest is
    unaffected since the project's own entry already wins. Unregistered
    projects (no own ring) still resolve via the global fallback."""
    storage = get_engram_storage_dir()
    projects = _get_manifest().get("projects", {})
    dirs: list = []
    seen_hashes = set()
    if project_dir:
        try:
            p = Path(_normalize_path(project_dir))
        except Exception:
            p = None
        while p is not None:
            info = projects.get(_normalize_path(str(p)))
            if info and info["hash"] not in seen_hashes:
                dirs.append(storage / "projects" / info["hash"])
                seen_hashes.add(info["hash"])
            parent = p.parent
            if parent == p:
                break
            p = parent
    if not dirs:
        dirs.append(storage / "checkpoints")
    return dirs
