"""
Semantic intent scorer for auto-capturing decisions from user prompts.

Uses the configured embedding model (sentence-transformers) for cosine
similarity against pre-computed decision templates. Falls back to regex
scoring if sentence-transformers is not installed.

Template embeddings are cached to disk at first use (~5ms per encoding
after warm-up). The model itself is cached by sentence-transformers in
~/.cache/huggingface/.

Performance:
- Cold start (first ever): ~2s (model download is separate — user runs install)
- Warm start (model cached on disk): ~800ms (model load) + ~5ms (encode)
- Hot path (OS file cache warm): ~200-400ms total
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Optional


def _resolve_cache_dir() -> Path:
    """Template cache lives in engram storage (honors CLAUDE_ENGRAM_DIR)."""
    override = os.environ.get("CLAUDE_ENGRAM_DIR", "")
    base = Path(override).expanduser() if override else Path.home() / ".claude_engram"
    return base / "embeddings"


# Cache directory for pre-computed embeddings
_CACHE_DIR = _resolve_cache_dir()
_TEMPLATE_CACHE = _CACHE_DIR / "decision_templates.json"

# Decision templates — sentences that express clear decisions.
# These use realistic generic nouns (not X/Y placeholders) because encoders
# embed content semantically — "X" doesn't match "PostgreSQL".
DECISION_TEMPLATES = [
    # Technology/tool switches
    "let's use PostgreSQL instead of SQLite for the database",
    "switch to TypeScript for the frontend components",
    "we should adopt Redis for caching instead of Memcached",
    "go with FastAPI instead of Flask for the API server",
    "replace the old middleware with the new framework",
    "migrate from JavaScript to TypeScript for type safety",
    "rewrite the backend in Go instead of Python",
    "upgrade to the latest version of the library",
    "move to a monorepo structure for the project",
    "let's use Docker for the development environment",
    "switch to using async functions throughout the codebase",
    "I want to use GraphQL instead of REST for the API",
    # Convention/rule decisions
    "from now on always use strict mode in TypeScript files",
    "going forward prefer composition over inheritance",
    "always validate inputs at the API boundary layer",
    "the convention should be snake_case for all Python files",
    "stick with the existing naming conventions for consistency",
    "keep using the current architecture, it works well",
    "prefer functional components over class components",
    # Negation decisions
    "don't use var anymore, use const and let instead",
    "stop using console.log for debugging, use the logger",
    "avoid raw SQL queries, use the ORM instead",
    "never import from the internal package directly",
    "get rid of the old jQuery code and use modern JavaScript",
    "remove the deprecated endpoints from the API",
    "drop support for the legacy database format",
    # Architecture decisions
    "use the repository pattern for data access",
    "implement dependency injection for better testability",
    "separate the concerns into microservices",
    "use a message queue for background processing",
    "add a caching layer between the API and database",
    "refactor to use the event-driven architecture pattern",
]

# Non-decision templates — things that look similar but are NOT decisions.
NON_DECISION_TEMPLATES = [
    "what does this function do and how does it work",
    "can you explain how the authentication system works",
    "fix the bug in the login page handler",
    "there's an error in the database connection code",
    "run the test suite and check for failures",
    "looks good, let's ship it to production",
    "should we use Redis or Memcached for caching",
    "what if we tried using a different framework",
    "how about using GraphQL for this endpoint",
    "maybe we could try a different approach to this",
    "what are the options for the database migration",
    "tell me about the authentication middleware",
    "help me understand the routing configuration",
    "review the changes in the pull request",
    "commit these changes to the main branch",
    "check the error logs for the server crash",
    "where is the configuration file located",
    "how do I set up the development environment",
]

# Minimum similarity to consider a match. Note: the capture cutoff
# (score >= 0.45 in remind) already implies sim >= 0.525, so this gate
# only binds above that — kept at 0.45 for the raw-score consumers.
DECISION_THRESHOLD = 0.45
# Minimum gap between best decision and best non-decision score.
# Retuned for bge-base (was 0.05, tuned on MiniLM): 0.025 measured
# F1 72.7% -> 76.9% on the 220-prompt bench (recall 66.7 -> 77.5,
# precision 80.0 -> 76.2) — lost decisions are unrecoverable, noise
# captures get deduped, so the recall side of the trade wins.
AMBIGUITY_MARGIN = 0.025


def _try_import_sentence_transformers():
    """Try to import sentence-transformers. Returns None if not installed."""
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer
    except ImportError:
        return None


def _get_or_build_template_cache() -> Optional[dict]:
    """
    Load cached template embeddings, or build them if missing.
    Returns dict with 'decision_embeddings' and 'non_decision_embeddings' as lists,
    or None if sentence-transformers is not available.
    """
    from claude_engram.embed_config import embed_signature, load_sentence_transformer

    sig = embed_signature()

    # Try to load from cache first; a cache built by a different embedding
    # model is invalid (vectors from two models share no space) and rebuilds.
    if _TEMPLATE_CACHE.exists():
        try:
            cache = json.loads(_TEMPLATE_CACHE.read_text())
            # Validate cache has expected keys and correct template count
            if (
                cache.get("decision_count") == len(DECISION_TEMPLATES)
                and cache.get("non_decision_count") == len(NON_DECISION_TEMPLATES)
                and cache.get("model") == sig
            ):
                return cache
        except Exception:
            pass

    # Need to rebuild — requires sentence-transformers
    if _try_import_sentence_transformers() is None:
        return None

    try:
        model = load_sentence_transformer()

        decision_embs = model.encode(DECISION_TEMPLATES, normalize_embeddings=True)
        non_decision_embs = model.encode(
            NON_DECISION_TEMPLATES, normalize_embeddings=True
        )

        cache = {
            "model": sig,
            "decision_count": len(DECISION_TEMPLATES),
            "non_decision_count": len(NON_DECISION_TEMPLATES),
            "decision_embeddings": decision_embs.tolist(),
            "non_decision_embeddings": non_decision_embs.tolist(),
            "built_at": time.time(),
        }

        # Save to disk
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        temp = _TEMPLATE_CACHE.with_suffix(".json.tmp")
        temp.write_text(json.dumps(cache))
        temp.replace(_TEMPLATE_CACHE)

        return cache
    except Exception:
        return None


# The capture cutoff every path shares: the best of the semantic and the
# regex tier has to reach this before the shape gate is consulted.
CAPTURE_THRESHOLD = 0.6
# Stored decisions keep the matched sentence to this many characters, cut
# at a word.
CAPTURE_MAX_CHARS = 300


def capture_decision(text: str, server_only: bool = False) -> str:
    """The one judgement behind every decision capture. The prompt hook
    (a typed prompt, live) and the session miner (a correction found in a
    transcript, bootstrap and live ticks) both call this, so a sentence is
    stored or not by the same rule wherever it was seen. Before 0.8.49 the
    two paths kept separate rules and drifted (2026-09-23: the miner's
    preference path was the last leak, about half of its entries real).

    Tiers, best score wins: the semantic scorer (the daemon, or an
    in-process model unless ``server_only``), then the regex scorer over
    each sentence. The winner has to reach CAPTURE_THRESHOLD and pass the
    shape gate (mining/decision_gate.looks_like_decision). Returns the
    sentence to store, cut at a word to CAPTURE_MAX_CHARS, or "" when
    nothing qualifies. Never raises.
    """
    try:
        prompt = (text or "").strip()
        if len(prompt) < 15:
            return ""
        best_score, best_text = 0.0, ""
        try:
            best_score, best_text = score_decision_semantic(prompt, server_only=server_only)
        except Exception:
            best_score, best_text = 0.0, ""

        # Lazy: remind imports this module.
        from claude_engram.hooks.remind import _cut_words, _score_decision_intent
        from claude_engram.mining.decision_gate import looks_like_decision

        sentences = [s.strip() for s in re.split(r"(?<=[.!])\s+|\n+", prompt) if len(s.strip()) > 15]
        if len(sentences) <= 1:
            sentences = [prompt]
        for sentence in sentences:
            regex_score, regex_text = _score_decision_intent(sentence)
            if regex_score > best_score:
                best_score, best_text = regex_score, regex_text

        if best_score < CAPTURE_THRESHOLD or not best_text or len(best_text) < 15:
            return ""
        if not looks_like_decision(best_text):
            return ""
        return _cut_words(best_text, CAPTURE_MAX_CHARS)
    except Exception:
        return ""


def score_decision_semantic(text: str, server_only: bool = False) -> tuple[float, str]:
    """
    Score whether text expresses a decision using semantic similarity.

    One path: the persistent scorer daemon (~5ms). When no daemon answers,
    (0.0, "") -- the caller's regex tier scores. No process loads the model
    for a prompt any more; ``server_only`` is kept for the callers that
    pass it.

    Returns (score 0.0-1.0, extracted_text).
    """
    if len(text.strip()) < 15:
        return (0.0, "")

    # Path 1: Try persistent server (fastest — model already loaded)
    try:
        from claude_engram.hooks.scorer_server import score_via_server

        score, extracted = score_via_server(text)
        if score > 0.0 or extracted:
            return (score, extracted)
        # Server returned 0 — could be genuine 0 or server not running.
        # Check if server is actually reachable before falling through.
        from claude_engram.hooks.scorer_server import PORT_FILE

        if PORT_FILE.exists():
            return (score, extracted)  # Server is running, score is genuinely 0
    except Exception:
        pass

    # No daemon answered: the regex tier scores. A hook process never loads
    # the model itself -- that load is ~1.4 GB resident and ~3 GB of commit
    # charge per hook, and it fired on every prompt of every session while
    # no daemon was bound (2026-09-25, under a chain of orphaned daemons).
    del server_only
    return (0.0, "")


def build_template_cache() -> bool:
    """
    Pre-build the template embedding cache. Call during install.
    Returns True if successful, False if sentence-transformers not available.
    """
    cache = _get_or_build_template_cache()
    return cache is not None
