"""
Claude Engram - persistent memory and session intelligence for Claude Code.

Hooks capture what happens as you work (edits, errors, decisions, test runs);
MCP tools cover what needs judgment (saving discoveries, rules, checkpoints).
The pieces:
- Memory: scored, tiered storage of rules, mistakes, decisions, discoveries
- Checkpoints: durable task state that survives compaction and session ends
- Mining: session transcripts turned into recurring patterns and recall
- Code index: import/symbol graph behind precheck and blast-radius warnings
"""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    # Single source of truth: the installed package metadata (from pyproject).
    # Avoids the silent drift that left this constant stuck at 0.2.0 through
    # the 0.3.x–0.6.x releases.
    __version__ = _pkg_version("claude-engram")
except PackageNotFoundError:  # raw checkout, not pip-installed
    __version__ = "0.0.0+unknown"
