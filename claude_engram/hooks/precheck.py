"""
Pre-edit import/export verification — Capability 1, Phase P1.

Reads the per-project code index and checks the PROPOSED edit content for
import statements that won't resolve: a name not exported by a known internal
module, or an internal module path that doesn't exist. Advisory only, capped
at a couple of findings, and deliberately conservative — it stays silent on
anything it cannot verify with high confidence:

  - relative imports (``from . import x``) — no current-package context here
  - external / stdlib imports — not in the index, not ours to judge
  - ``import *`` and multi-line parenthesised imports — not parsed
  - missing / stale index, or any error — degrade to silence

A wrong proactive warning is worse than silence (it trains the agent to ignore
the channel), so every rule above errs toward a false negative.
"""

import re
from typing import Optional

from claude_engram.mining.code_index import CodeIndex, resolve_code_index

_FROM_RE = re.compile(r"^[ \t]*from[ \t]+([.\w]+)[ \t]+import[ \t]+(.+)$", re.MULTILINE)
_IMPORT_RE = re.compile(
    r"^[ \t]*import[ \t]+([\w.]+(?:[ \t]*,[ \t]*[\w.]+)*)", re.MULTILINE
)

MAX_FINDINGS = 2


def _parse_imported_names(raw: str) -> list[str]:
    """Names from a 'from X import a, b as c' tail. Multi-line paren imports
    (tail begins with '(') aren't parsed — return [] (stay silent)."""
    raw = raw.strip()
    if raw.startswith("("):
        return []
    raw = raw.rstrip("\\").strip()
    if raw == "*" or not raw:
        return []
    names = []
    for part in raw.split(","):
        part = part.split(" as ")[0].split("#")[0].strip()
        if part.isidentifier():
            names.append(part)
    return names


def _closest(name: str, candidates: list[str]) -> Optional[str]:
    import difflib

    best = difflib.get_close_matches(name, candidates, n=1, cutoff=0.7)
    return best[0] if best else None


def check_imports(index: CodeIndex, text: str) -> list[str]:
    """High-confidence-only findings for imports in ``text`` that won't resolve
    against the index. Returns at most MAX_FINDINGS terse strings."""
    findings: list[str] = []
    roots = index.known_roots()
    if not roots:
        return findings

    def internal(mod: str) -> bool:
        # absolute import whose top segment is a package we actually index
        return bool(mod) and not mod.startswith(".") and mod.split(".")[0] in roots

    # from X import a, b, ...
    for mod, tail in _FROM_RE.findall(text):
        if not internal(mod):
            continue
        exports = index.exports_of(mod)
        if exports is None:
            continue  # X not a known module-with-exports -> can't verify
        for name in _parse_imported_names(tail):
            if name in exports or index.is_module(f"{mod}.{name}"):
                continue  # exported, or a valid submodule import
            sugg = _closest(name, exports)
            tip = f" Closest: {sugg}." if sugg else ""
            shown = ", ".join(exports[:6]) + ("..." if len(exports) > 6 else "")
            findings.append(
                f"`{name}` is not exported by `{mod}` (exports: {shown}).{tip}"
            )
            if len(findings) >= MAX_FINDINGS:
                return findings

    # import X / import X.Y / import a, b
    for group in _IMPORT_RE.findall(text):
        for mod in (s.strip() for s in group.split(",")):
            if not internal(mod):
                continue
            if index.is_package_prefix(mod):
                continue  # module or package exists
            findings.append(f"module `{mod}` not found in this project's index.")
            if len(findings) >= MAX_FINDINGS:
                return findings

    return findings


def format_precheck(findings: list[str]) -> str:
    if not findings:
        return ""
    lines = ["<engram-precheck>"]
    lines += [f"- {f}" for f in findings[:MAX_FINDINGS]]
    lines.append("</engram-precheck>")
    return "\n".join(lines)


BLAST_MIN_DEPENDENTS = 2  # don't nag for near-leaf modules


def _short(dotted: str) -> str:
    parts = dotted.split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else dotted


def read_context(file_path: str, project_path: str = "") -> str:
    """One-line code-index orientation for a file about to be Read: what the
    module is, its key symbols, and how widely it's imported. Silent for
    files the index doesn't know (non-Python, unindexed, or any failure)."""
    if not file_path.endswith(".py"):
        return ""
    try:
        from pathlib import Path

        base = project_path or str(Path(file_path).parent)
        idx = resolve_code_index(base)
        if idx is None:
            return ""
        rec = idx.module_for_file(file_path)
        if not rec:
            return ""
        mod = rec.get("module_path", "")
        classes = list(rec.get("classes", {}))
        functions = list(rec.get("functions", {}))
        symbols = classes[:4] + functions[: max(0, 6 - len(classes[:4]))]
        parts = [f"`{mod}`"]
        if symbols:
            more = len(classes) + len(functions) - len(symbols)
            parts.append(
                "defines " + ", ".join(symbols) + (f" +{more} more" if more > 0 else "")
            )
        deps = idx.dependents_of(mod)
        if len(deps) >= BLAST_MIN_DEPENDENTS:
            parts.append(f"imported by {len(deps)} module(s)")
        if len(parts) == 1:
            return ""
        return "- " + "; ".join(parts)
    except Exception:
        return ""


def blast_radius(file_path: str, project_path: str = "") -> str:
    """Terse pre-edit blast radius: how many project modules import the one
    being edited. Silent for near-leaf modules (< BLAST_MIN_DEPENDENTS) and on
    any failure. Reads the cached reverse-edges — no filesystem walk."""
    if not file_path.endswith(".py"):
        return ""
    try:
        from pathlib import Path

        base = project_path or str(Path(file_path).parent)
        idx = resolve_code_index(base)
        if idx is None:
            return ""
        rec = idx.module_for_file(file_path)
        if not rec:
            return ""
        mod = rec.get("module_path", "")
        deps = idx.dependents_of(mod)
        if len(deps) < BLAST_MIN_DEPENDENTS:
            return ""
        names = ", ".join(_short(d) for d in deps[:8])
        more = f" +{len(deps) - 8} more" if len(deps) > 8 else ""
        return (
            "<engram-blast-radius>\n"
            f"- `{mod}` is imported by {len(deps)} module(s): {names}{more}. "
            "Check these callers if you change its signatures or exports.\n"
            "</engram-blast-radius>"
        )
    except Exception:
        return ""


def precheck_edit(file_path: str, proposed_text: str, project_path: str = "") -> str:
    """Resolve the project's code index and verify the imports in the proposed
    edit text. Returns a terse precheck banner, or '' (incl. on any failure)."""
    if not proposed_text or "import" not in proposed_text:
        return ""
    # Only meaningful for Python today (the index is Python-only).
    if file_path and not file_path.endswith(".py"):
        return ""
    try:
        from pathlib import Path

        base = project_path or str(Path(file_path).parent)
        idx = resolve_code_index(base)
        if idx is None:
            return ""
        return format_precheck(check_imports(idx, proposed_text))
    except Exception:
        return ""
