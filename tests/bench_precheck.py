#!/usr/bin/env python3
"""
Benchmark: pre-edit import/export verification (Capability 1, P1).

Verifies the precision contract: true positives fire (missing export with a
closest-name suggestion, missing module), and every false-positive vector
stays silent (valid export, submodule, relative, external/stdlib, star,
package, multi-line paren import). Synthetic project — runs anywhere.

Usage:
    python tests/bench_precheck.py
"""
import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_engram.mining.code_index import build_code_index
from claude_engram.hooks.precheck import (
    check_imports,
    format_precheck,
    precheck_edit,
    _parse_imported_names,
)

fails = []


def check(name, cond):
    print(("  [PASS] " if cond else "  [FAIL] ") + name)
    if not cond:
        fails.append(name)


print("=" * 70)
print("Pre-Edit Import Verification Benchmark")
print("=" * 70)

root = Path(tempfile.mkdtemp(prefix="pc_root_"))
idx_dir = Path(tempfile.mkdtemp(prefix="pc_idx_"))
(root / "pkg").mkdir()
(root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
(root / "pkg" / "mod.py").write_text(
    '__all__ = ["Processor", "build"]\n'
    'class Processor: pass\n'
    'def build(): pass\n',
    encoding="utf-8",
)
idx = build_code_index(str(root), idx_dir)


def n(text):
    return len(check_imports(idx, text))


print("\n--- 1. True positives ---")
f = check_imports(idx, "from pkg.mod import Processr")
check("typo name flagged", len(f) == 1 and "not exported" in f[0])
check("closest suggestion given", "Closest: Processor" in f[0])
check("missing name flagged", n("from pkg.mod import Nope") == 1)
check("missing module flagged", n("import pkg.typo") == 1)

print("\n--- 2. No false positives ---")
check("valid export silent", n("from pkg.mod import Processor") == 0)
check("valid multi-name silent", n("from pkg.mod import build, Processor") == 0)
check("submodule import silent", n("from pkg import mod") == 0)
check("relative import silent", n("from . import x") == 0)
check("relative dotted silent", n("from .mod import Processor") == 0)
check("external import silent", n("import os") == 0)
check("external from silent", n("from numpy import array") == 0)
check("stdlib multi silent", n("import os, sys, json") == 0)
check("star import silent", n("from pkg.mod import *") == 0)
check("package import silent", n("import pkg") == 0)
check("known module import silent", n("import pkg.mod") == 0)
check("multiline paren import silent", n("from pkg.mod import (\n    Processor,\n)") == 0)

print("\n--- 3. Cap + formatting ---")
many = "from pkg.mod import A\nfrom pkg.mod import B\nfrom pkg.mod import C\n"
check("findings capped at 2", n(many) == 2)
check("empty -> no banner", format_precheck([]) == "")
banner = format_precheck(["x not exported"])
check("banner wraps", banner.startswith("<engram-precheck>") and banner.endswith("</engram-precheck>"))

print("\n--- 4. Entry-point degradation ---")
check("non-py file silent", precheck_edit("notes.md", "from pkg.mod import Nope") == "")
check("no-import text silent", precheck_edit("x.py", "y = 1") == "")
check("parse drops alias", _parse_imported_names("a as b, c") == ["a", "c"])

print("\n" + "=" * 70)
print(f"RESULTS: {'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
print("=" * 70)
sys.exit(1 if fails else 0)
