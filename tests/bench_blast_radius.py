#!/usr/bin/env python3
"""
Benchmark: blast-radius (reverse-dependency edges) off the code index.

Covers _import_targets relative-import resolution, dependents_of, the
blast_radius pre-edit banner (fires only for shared modules), the
impact_analyze cache wiring, and the auto-migration of pre-reverse-edge
indexes. Synthetic project with relative imports — runs anywhere.

Usage:
    python tests/bench_blast_radius.py
"""
import json
import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import claude_engram.mining.code_index as ci
import claude_engram.hooks.precheck as pc
from claude_engram.mining.code_index import build_code_index, _import_targets, CodeIndex
from claude_engram.tools.impact import ImpactAnalyzer

fails = []


def check(name, cond):
    print(("  [PASS] " if cond else "  [FAIL] ") + name)
    if not cond:
        fails.append(name)


print("=" * 70)
print("Blast-Radius / Reverse-Edges Benchmark")
print("=" * 70)

print("\n--- 1. Relative-import target resolution ---")
# regular module a.b.c: '.' is package a.b
check(
    "from . import x (module)",
    "a.b.x" in _import_targets(["from . import x"], "a.b.c", False),
)
check(
    "from .d import y (module)",
    "a.b.d" in _import_targets(["from .d import y"], "a.b.c", False),
)
check(
    "from .. import z (module)",
    "a.z" in _import_targets(["from .. import z"], "a.b.c", False),
)
# package a.b (__init__): '.' is a.b itself
check(
    "from . import x (package)",
    "a.b.x" in _import_targets(["from . import x"], "a.b", True),
)
check(
    "absolute from",
    "pkg.mod" in _import_targets(["from pkg.mod import T"], "x.y", False),
)
check("plain import", "pkg.mod" in _import_targets(["pkg.mod"], "x.y", False))

print("\n--- 2. Reverse edges on a real tree ---")
root = Path(tempfile.mkdtemp(prefix="br_root_"))
idx_dir = Path(tempfile.mkdtemp(prefix="br_idx_"))
(root / "pkg").mkdir()
(root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
(root / "pkg" / "base.py").write_text("class Base: pass\n", encoding="utf-8")
(root / "pkg" / "mid.py").write_text(
    "from .base import Base\nclass Mid(Base): pass\n", encoding="utf-8"
)
(root / "pkg" / "top.py").write_text(
    "from .mid import Mid\nimport pkg.base\n", encoding="utf-8"
)
idx = build_code_index(str(root), idx_dir)
check(
    "base imported by mid+top", idx.dependents_of("pkg.base") == ["pkg.mid", "pkg.top"]
)
check("mid imported by top", idx.dependents_of("pkg.mid") == ["pkg.top"])
check("top is a leaf", idx.dependents_of("pkg.top") == [])
check(
    "module_for_file",
    (idx.module_for_file(str(root / "pkg" / "base.py")) or {}).get("module_path")
    == "pkg.base",
)
check("file_for_module", idx.file_for_module("pkg.mid") == "pkg/mid.py")

print("\n--- 3. blast_radius banner (index monkeypatched) ---")
pc.resolve_code_index = lambda base: idx
ci.resolve_code_index = lambda base: idx
banner = pc.blast_radius(str(root / "pkg" / "base.py"), str(root))
check("banner fires for shared module", "imported by 2 module(s)" in banner)
check("banner names importers", "pkg.mid" in banner and "pkg.top" in banner)
check(
    "leaf module silent", pc.blast_radius(str(root / "pkg" / "top.py"), str(root)) == ""
)
check("non-py silent", pc.blast_radius("x.md", str(root)) == "")

print("\n--- 4. impact_analyze reads the cache ---")
deps = ImpactAnalyzer()._dependents_via_index(root / "pkg" / "base.py", str(root))
check(
    "impact uses index dependents",
    deps is not None and "pkg/mid.py" in deps and "pkg/top.py" in deps,
)
check(
    "impact leaf -> empty (authoritative)",
    ImpactAnalyzer()._dependents_via_index(root / "pkg" / "top.py", str(root)) == [],
)

print("\n--- 5. Auto-migration of pre-reverse-edge index ---")
idx_file = idx_dir / "code_index.json"
data = json.loads(idx_file.read_text(encoding="utf-8"))
del data["module_to_dependents"]
idx_file.write_text(json.dumps(data), encoding="utf-8")
idx2 = build_code_index(str(root), idx_dir)
check(
    "reverse map rebuilt on reload",
    idx2.dependents_of("pkg.base") == ["pkg.mid", "pkg.top"],
)

print("\n" + "=" * 70)
print(
    f"RESULTS: {'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}"
)
print("=" * 70)
sys.exit(1 if fails else 0)
