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

# Single source of truth for the running code's version. Must equal pyproject's
# [project].version — tests/test_smoke.py::test_status_version_matches_pyproject
# asserts it, which is what keeps this from drifting the way it once stuck at
# 0.2.0 through the 0.3.x–0.6.x releases.
#
# Why the literal and not importlib.metadata: an EDITABLE install (pip install
# -e .) freezes the dist-info at install time while the code stays live, so the
# metadata lags every release made afterwards. claude_engram_status reported
# v0.8.20 from a 0.8.36 checkout for sixteen releases because of exactly that.
# The literal ships with the code, so it is right for a wheel install too; the
# metadata is only consulted when this constant is somehow unreadable.
__version__ = "0.8.47"


def _installed_version() -> str:
    """The version pip recorded for this distribution, or "" when absent.

    Diagnostic only: a mismatch with ``__version__`` means the install is stale
    (an editable checkout moved on), not that the code is a different version.
    """
    try:
        return _pkg_version("claude-engram")
    except PackageNotFoundError:  # raw checkout, not pip-installed
        return ""
    except Exception:
        return ""
