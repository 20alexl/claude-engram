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

import os as _os
import sys as _sys

# Hook processes run as `python -m claude_engram.hooks...` from the
# session's working directory, which Python puts FIRST on sys.path. A
# session that had cd'd into a vendored package directory holding an
# email.py had every hook die at import: that file shadowed the stdlib
# `email` package that importlib.metadata loads (2026-09-24). Under -m,
# drop the cwd entry before anything else is imported. This package's own
# modules resolve through its __path__ and dependencies through
# site-packages, so nothing of engram's needs the cwd. Python 3.11+ has
# `-P` for the same thing; this covers 3.10 and every installed hook line.
if _sys.argv[:1] == ["-m"] and _sys.path and not getattr(_sys.flags, "safe_path", False):
    try:
        _head = _sys.path[0]
        if _head == "" or _os.path.normcase(_os.path.abspath(_head)) == _os.path.normcase(_os.getcwd()):
            del _sys.path[0]
    except Exception:
        pass

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
__version__ = "0.8.56"


def _installed_version() -> str:
    """The version pip recorded for this distribution, or "" when absent.

    Diagnostic only: a mismatch with ``__version__`` means the install is stale
    (an editable checkout moved on), not that the code is a different version.
    """
    try:
        # Lazy: importlib.metadata pulls in the stdlib email package, and
        # the package import must stay free of anything a stray file in
        # the working directory could shadow.
        from importlib.metadata import PackageNotFoundError, version as _pkg_version

        return _pkg_version("claude-engram")
    except Exception:  # PackageNotFoundError on a raw checkout, or anything else
        return ""
