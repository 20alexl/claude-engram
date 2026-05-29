"""
Code Index — incremental, mtime-keyed symbol index per project.

The substrate for proactive code-awareness (pre-edit import/export
verification, blast-radius, file summaries). Parses Python with ``ast`` and
records, per module: dotted path, public exports, classes (bases / methods +
signatures / attrs), functions (+ signatures), and raw imports. Plus a
``symbol_to_modules`` reverse map for fast resolution.

Scope: ONE project, bounded by nested project markers. Walking a workspace
root therefore indexes only the root's own files, not its sub-projects — each
sub-project gets its own index (resolved with workspace inheritance, like
memory). This is deliberate: a pooled cross-project symbol table would
reintroduce the V7/V8 cross-pollution that path-aware relevance fixed.

Build is incremental: a module is re-parsed only when its mtime changes;
deleted files are dropped. Pure ``ast`` — no LLM, no network. Degrades to
silence on any parse/read error (never emits a wrong symbol).

Storage: ~/.claude_engram/projects/<hash>/code_index.json
"""

import ast
import json
import os
from pathlib import Path
from typing import Optional


# Directories never worth indexing (deps, caches, build output, vcs).
SKIP_DIRS = {
    "node_modules",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    "site-packages",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".eggs",
    ".idea",
    ".vscode",
}

# Files that mark a directory as its own project — the walk treats a child dir
# containing any of these as a boundary and does not descend into it, so the
# index stays scoped to a single project.
PROJECT_MARKERS = {
    "pyproject.toml",
    "setup.py",
    "package.json",
    "Cargo.toml",
    "go.mod",
    ".git",
    "CLAUDE.md",
}

# Safety bound: never index more than this many files in one project. If hit,
# the index records it (no silent truncation — see design principle).
DEFAULT_MAX_FILES = 4000


# ── AST extraction ──────────────────────────────────────────────────────────


def _module_path_from_rel(rel_path: str) -> str:
    """'pkg/sub/mod.py' -> 'pkg.sub.mod'; 'pkg/__init__.py' -> 'pkg'."""
    p = rel_path.replace("\\", "/")
    if p.endswith(".py"):
        p = p[:-3]
    parts = [seg for seg in p.split("/") if seg]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _format_signature(args: ast.arguments, returns: Optional[ast.AST]) -> str:
    """Render an ast.arguments into a compact signature string, e.g.
    '(self, d_model, n_layers=4, *args, dropout=0.0, **kw) -> Processor'."""

    def render_default(node: Optional[ast.AST]) -> str:
        if node is None:
            return ""
        try:
            return "=" + ast.unparse(node)
        except Exception:
            return "=..."

    parts: list[str] = []

    posonly = list(getattr(args, "posonlyargs", []) or [])
    normal = list(args.args or [])
    # Defaults align to the tail of posonly+normal.
    pos_plus_normal = posonly + normal
    defaults = list(args.defaults or [])
    n_no_default = len(pos_plus_normal) - len(defaults)
    for i, a in enumerate(pos_plus_normal):
        d = defaults[i - n_no_default] if i >= n_no_default else None
        parts.append(a.arg + render_default(d))
        if posonly and i == len(posonly) - 1:
            parts.append("/")

    if args.vararg:
        parts.append("*" + args.vararg.arg)
    elif args.kwonlyargs:
        parts.append("*")

    for a, d in zip(args.kwonlyargs or [], args.kw_defaults or []):
        parts.append(a.arg + render_default(d))

    if args.kwarg:
        parts.append("**" + args.kwarg.arg)

    sig = "(" + ", ".join(parts) + ")"
    if returns is not None:
        try:
            sig += " -> " + ast.unparse(returns)
        except Exception:
            pass
    return sig


def _base_name(node: ast.AST) -> str:
    """Best-effort dotted name for a class base / decorator."""
    try:
        return ast.unparse(node)
    except Exception:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return "?"


def _class_attrs(cls: ast.ClassDef) -> list[str]:
    """Collect class-level names + ``self.x`` assignments in any method."""
    attrs: set[str] = set()
    for node in cls.body:
        # class-level: x = ... / x: T = ...
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    attrs.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            attrs.add(node.target.id)
        # self.x = ... inside methods
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign):
                    for t in sub.targets:
                        if (
                            isinstance(t, ast.Attribute)
                            and isinstance(t.value, ast.Name)
                            and t.value.id == "self"
                        ):
                            attrs.add(t.attr)
                elif (
                    isinstance(sub, ast.AnnAssign)
                    and isinstance(sub.target, ast.Attribute)
                    and isinstance(sub.target.value, ast.Name)
                    and sub.target.value.id == "self"
                ):
                    attrs.add(sub.target.attr)
    return sorted(attrs)


def extract_module(source: str, rel_path: str) -> Optional[dict]:
    """Parse Python source into a module record. Returns None on syntax error
    (caller leaves any prior record in place rather than recording garbage)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None

    classes: dict[str, dict] = {}
    functions: dict[str, str] = {}
    imports: list[str] = []
    assigned: list[str] = []
    dunder_all: Optional[list[str]] = None

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions[node.name] = _format_signature(node.args, node.returns)
        elif isinstance(node, ast.ClassDef):
            methods: dict[str, str] = {}
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods[sub.name] = _format_signature(sub.args, sub.returns)
            classes[node.name] = {
                "bases": [_base_name(b) for b in node.bases],
                "methods": methods,
                "attrs": _class_attrs(node),
            }
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = ("." * (node.level or 0)) + (node.module or "")
            names = ", ".join(a.name for a in node.names)
            imports.append(f"from {mod} import {names}")
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assigned.append(t.id)
                    if t.id == "__all__" and isinstance(node.value, (ast.List, ast.Tuple)):
                        vals = []
                        for el in node.value.elts:
                            if isinstance(el, ast.Constant) and isinstance(el.value, str):
                                vals.append(el.value)
                        dunder_all = vals
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assigned.append(node.target.id)

    # Exports: explicit __all__ wins; else public top-level names.
    if dunder_all is not None:
        exports = dunder_all
    else:
        exports = [
            n
            for n in list(classes) + list(functions) + assigned
            if not n.startswith("_")
        ]
        # de-dup, preserve order
        seen: set[str] = set()
        exports = [n for n in exports if not (n in seen or seen.add(n))]

    return {
        "module_path": _module_path_from_rel(rel_path),
        "exports": exports,
        "classes": classes,
        "functions": functions,
        "imports": imports,
    }


# ── Index store ───────────────────────────────────────────────────────────


class CodeIndex:
    """Per-project symbol index. Mirrors SessionIndex: versioned, atomic save,
    incremental by mtime, with a reverse symbol map for fast lookup."""

    VERSION = 1

    def __init__(self, index_path: Path):
        self._path = index_path
        self._data: dict = {
            "version": self.VERSION,
            "root": "",
            "modules": {},
            "symbol_to_modules": {},
            "truncated": False,
            "file_count": 0,
        }
        self._dirty = False
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

    def save(self):
        if not self._dirty:
            return
        self._rebuild_symbol_map()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        tmp.replace(self._path)
        self._dirty = False

    # -- mutation --
    @property
    def modules(self) -> dict[str, dict]:
        return self._data.setdefault("modules", {})

    def needs_processing(self, rel_path: str, mtime: float) -> bool:
        rec = self.modules.get(rel_path)
        return not rec or abs(rec.get("mtime", 0.0) - mtime) > 1e-6

    def update_module(self, rel_path: str, record: dict, mtime: float):
        record = dict(record)
        record["mtime"] = mtime
        self.modules[rel_path] = record
        self._dirty = True

    def drop_missing(self, present_rel_paths: set[str]):
        """Remove modules whose files no longer exist."""
        gone = [r for r in self.modules if r not in present_rel_paths]
        for r in gone:
            del self.modules[r]
        if gone:
            self._dirty = True

    def _rebuild_symbol_map(self):
        sym: dict[str, list[str]] = {}
        for rec in self.modules.values():
            dotted = rec.get("module_path", "")
            names = (
                list(rec.get("classes", {}))
                + list(rec.get("functions", {}))
                + list(rec.get("exports", []))
            )
            for n in set(names):
                sym.setdefault(n, [])
                if dotted not in sym[n]:
                    sym[n].append(dotted)
        self._data["symbol_to_modules"] = sym

    # -- query (used by the pre-edit hook) --
    def by_dotted(self, module_path: str) -> Optional[dict]:
        for rec in self.modules.values():
            if rec.get("module_path") == module_path:
                return rec
        return None

    def exports_of(self, module_path: str) -> Optional[list[str]]:
        rec = self.by_dotted(module_path)
        return rec.get("exports") if rec else None

    def resolve_symbol(self, name: str) -> list[str]:
        return self._data.get("symbol_to_modules", {}).get(name, [])

    def all_symbols(self) -> list[str]:
        return list(self._data.get("symbol_to_modules", {}))

    def module_count(self) -> int:
        return len(self.modules)

    def symbol_count(self) -> int:
        return len(self._data.get("symbol_to_modules", {}))

    @property
    def truncated(self) -> bool:
        return bool(self._data.get("truncated"))


# ── Build ───────────────────────────────────────────────────────────────────


def _iter_python_files(root: Path, max_files: int) -> tuple[list[Path], bool]:
    """Walk ``root`` for .py files, skipping SKIP_DIRS and not descending into
    nested project-marker dirs. Returns (files, truncated)."""
    files: list[Path] = []
    truncated = False
    root_str = str(root)
    for dirpath, dirnames, filenames in os.walk(root):
        # prune skip dirs and hidden dirs
        dirnames[:] = [
            d
            for d in dirnames
            if d not in SKIP_DIRS and not d.startswith(".")
        ]
        # do not descend into nested sub-projects (but allow the root itself)
        if dirpath != root_str:
            here = Path(dirpath)
            if any((here / m).exists() for m in PROJECT_MARKERS):
                dirnames[:] = []
                continue
        for fn in filenames:
            if fn.endswith(".py"):
                files.append(Path(dirpath) / fn)
                if len(files) >= max_files:
                    return files, True
    return files, truncated


def build_code_index(
    project_root: str,
    index_dir: Path,
    max_files: int = DEFAULT_MAX_FILES,
) -> Optional[CodeIndex]:
    """Build/update the code index for a single project rooted at
    ``project_root``, storing at ``index_dir/code_index.json``. Incremental:
    only re-parses files whose mtime changed; drops deleted files."""
    root = Path(project_root)
    if not root.is_dir():
        return None

    index = CodeIndex(index_dir / "code_index.json")
    index._data["root"] = str(root)

    files, truncated = _iter_python_files(root, max_files)
    present: set[str] = set()

    for fp in files:
        try:
            rel = fp.relative_to(root).as_posix()
        except ValueError:
            rel = fp.as_posix()
        present.add(rel)
        try:
            mtime = fp.stat().st_mtime
        except OSError:
            continue
        if not index.needs_processing(rel, mtime):
            continue
        try:
            source = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        record = extract_module(source, rel)
        if record is not None:
            index.update_module(rel, record, mtime)

    index.drop_missing(present)
    if index._data.get("truncated") != truncated:
        index._data["truncated"] = truncated
        index._dirty = True
    index._data["file_count"] = len(present)
    index.save()
    return index


def resolve_code_index(
    project_path: str,
    engram_storage_dir: str = "~/.claude_engram",
) -> Optional[CodeIndex]:
    """Load an existing code index for a project (no build). Walks up to a
    parent project if the sub-project has none yet — workspace inheritance,
    matching how memory and handoffs resolve."""
    from claude_engram.hooks.paths import get_project_memory_dir

    p = Path(project_path)
    seen: set[str] = set()
    while True:
        try:
            d = get_project_memory_dir(str(p))
        except Exception:
            d = None
        if d is not None and str(d) not in seen:
            seen.add(str(d))
            idx_path = d / "code_index.json"
            if idx_path.exists():
                idx = CodeIndex(idx_path)
                if idx.module_count() > 0:
                    return idx
        parent = p.parent
        if parent == p:
            break
        p = parent
    return None
