"""
Claude Engram - A junior agent for Claude Code.

Claude Engram acts as a persistent, intelligent assistant that can:
- Search and understand codebases (Scout)
- Remember context and priorities (Memory)
- Analyze code with local LLM
- And more tools to come...
"""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    # Single source of truth: the installed package metadata (from pyproject).
    # Avoids the silent drift that left this constant stuck at 0.2.0 through
    # the 0.3.x–0.6.x releases.
    __version__ = _pkg_version("claude-engram")
except PackageNotFoundError:  # raw checkout, not pip-installed
    __version__ = "0.0.0+unknown"
