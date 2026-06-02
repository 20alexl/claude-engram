#!/usr/bin/env python3
"""
Benchmark: Code index (per-project symbol table).

Tests the ast-based symbol extractor and the incremental, mtime-keyed,
sub-project-scoped CodeIndex that backs pre-edit verification + blast-radius.
Synthetic project tree — runs on any machine, no real history needed.

Usage:
    python tests/bench_code_index.py
"""
import ast
import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_engram.mining.code_index import (
    build_code_index,
    extract_module,
    _format_signature,
)

fails = []


def check(name, cond):
    print(("  [PASS] " if cond else "  [FAIL] ") + name)
    if not cond:
        fails.append(name)


print("=" * 70)
print("Code Index Benchmark")
print("=" * 70)

root = Path(tempfile.mkdtemp(prefix="ci_root_"))
idx_dir = Path(tempfile.mkdtemp(prefix="ci_idx_"))
(root / "pkg").mkdir()
(root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
(root / "pkg" / "mod.py").write_text(
    "from .other import helper\n"
    "import os\n\n"
    '__all__ = ["Processor", "build"]\n\n'
    "class Processor(nn.Module):\n"
    "    def __init__(self, d_model, n_layers=4, *, dropout=0.0):\n"
    "        self.d_model = d_model\n"
    "        self.layers = []\n"
    "    def forward(self, x):\n"
    "        return x\n\n"
    "def build(cfg) -> Processor:\n"
    "    return Processor(cfg)\n\n"
    "def _private():\n"
    "    pass\n\n"
    "CONST = 5\n",
    encoding="utf-8",
)
# nested sub-project (boundary-stop must exclude it) + a venv (skip)
(root / "sub").mkdir()
(root / "sub" / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
(root / "sub" / "inner.py").write_text("class ShouldNotIndex: pass\n", encoding="utf-8")
(root / "venv").mkdir()
(root / "venv" / "junk.py").write_text("x=1\n", encoding="utf-8")

print("\n--- 1. Build + scoping ---")
idx = build_code_index(str(root), idx_dir)
check("build returns index", idx is not None)
mods = idx.modules
check("pkg/mod.py indexed", "pkg/mod.py" in mods)
check("boundary-stop excludes nested sub-project", "sub/inner.py" not in mods)
check("venv skipped", "venv/junk.py" not in mods)

print("\n--- 2. Extraction fidelity ---")
m = mods.get("pkg/mod.py", {})
check("module_path dotted", m.get("module_path") == "pkg.mod")
check("exports from __all__", m.get("exports") == ["Processor", "build"])
cls = m.get("classes", {}).get("Processor", {})
check("class bases", cls.get("bases") == ["nn.Module"])
check(
    "__init__ signature",
    cls.get("methods", {}).get("__init__")
    == "(self, d_model, n_layers=4, *, dropout=0.0)",
)
check("forward signature", cls.get("methods", {}).get("forward") == "(self, x)")
check("instance attrs captured", cls.get("attrs") == ["d_model", "layers"])
check(
    "function w/ return annotation",
    m.get("functions", {}).get("build") == "(cfg) -> Processor",
)
check("private function recorded", "_private" in m.get("functions", {}))
check("import os recorded", "os" in m.get("imports", []))
check("from-import recorded", "from .other import helper" in m.get("imports", []))

print("\n--- 3. Reverse map / queries ---")
check("resolve_symbol Processor", idx.resolve_symbol("Processor") == ["pkg.mod"])
check("exports_of by dotted", idx.exports_of("pkg.mod") == ["Processor", "build"])
check("symbol_count > 0", idx.symbol_count() > 0)

print("\n--- 4. Signature edge cases ---")
tree = ast.parse("def f(a, b, /, c, *args, d, e=2, **kw) -> int: pass")
sig = _format_signature(tree.body[0].args, tree.body[0].returns)
check("posonly/vararg/kwonly/kwarg", sig == "(a, b, /, c, *args, d, e=2, **kw) -> int")

print("\n--- 5. Degrade to silence ---")
check("syntax error returns None", extract_module("def (:\n", "bad.py") is None)

print("\n--- 6. Incremental + deletion ---")
rec_before = dict(mods["pkg/mod.py"])
idx2 = build_code_index(str(root), idx_dir)
check("rebuild stable (mtime incremental)", idx2.modules["pkg/mod.py"] == rec_before)
(root / "pkg" / "mod.py").unlink()
idx3 = build_code_index(str(root), idx_dir)
check("deleted module dropped", "pkg/mod.py" not in idx3.modules)
check("reverse map cleared after delete", idx3.resolve_symbol("Processor") == [])

print("\n" + "=" * 70)
print(
    f"RESULTS: {'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}"
)
print("=" * 70)
sys.exit(1 if fails else 0)
