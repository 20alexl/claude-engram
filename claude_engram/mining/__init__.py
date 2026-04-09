"""
Claude Engram Session Mining — learn from your complete coding history.

Mines Claude Code's session JSONL logs for decisions, mistakes, approaches,
patterns, and context that hook-time capture misses.
"""

from claude_engram.mining.jsonl_reader import (
    resolve_jsonl_dir,
    get_session_files,
    iter_messages,
    read_tail,
)
from claude_engram.mining.session_index import SessionIndex
from claude_engram.mining.background import start_mining_background
from claude_engram.mining.search import search_sessions, find_decision, find_file_discussions
from claude_engram.mining.patterns import detect_all_patterns
from claude_engram.mining.timeline import build_timeline, get_project_overview

__all__ = [
    "resolve_jsonl_dir",
    "get_session_files",
    "iter_messages",
    "read_tail",
    "SessionIndex",
    "start_mining_background",
    "search_sessions",
    "find_decision",
    "find_file_discussions",
    "detect_all_patterns",
    "build_timeline",
    "get_project_overview",
]
