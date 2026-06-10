"""Claude Engram Tools - individual capabilities.

Lazy exports (PEP 562): importing one tool must not pay for all of them.
The pre-edit hook imports memory scoring on a 1s budget; an eager __init__
dragged httpx + pydantic + the audit engine into every hook process.
"""

import importlib

_EXPORTS = {
    "SearchEngine": ".scout",
    "MemoryStore": ".memory",
    "FileSummarizer": ".summarizer",
    "DependencyMapper": ".dependencies",
    "ConventionTracker": ".conventions",
    "ImpactAnalyzer": ".impact",
    "SessionManager": ".session",
    "WorkTracker": ".work_tracker",
    "Thinker": ".thinker",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    if name in _EXPORTS:
        module = importlib.import_module(_EXPORTS[name], __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
