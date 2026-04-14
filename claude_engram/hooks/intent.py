"""
Semantic intent scorer for auto-capturing decisions from user prompts.

Uses AllMiniLM (sentence-transformers) for cosine similarity against
pre-computed decision templates. Falls back to regex scoring if
sentence-transformers is not installed.

Template embeddings are cached to disk at first use (~80MB model,
~5ms per encoding after warm-up). The model itself is cached by
sentence-transformers in ~/.cache/huggingface/.

Performance:
- Cold start (first ever): ~2s (model download is separate — user runs install)
- Warm start (model cached on disk): ~800ms (model load) + ~5ms (encode)
- Hot path (OS file cache warm): ~200-400ms total
"""

import json
import re
import time
from pathlib import Path
from typing import Optional

# Cache directory for pre-computed embeddings
_CACHE_DIR = Path.home() / ".claude_engram" / "embeddings"
_TEMPLATE_CACHE = _CACHE_DIR / "decision_templates.json"

# Decision templates — sentences that express clear decisions.
# These use realistic generic nouns (not X/Y placeholders) because MiniLM
# embeds content semantically — "X" doesn't match "PostgreSQL".
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

# Minimum similarity to consider a match
DECISION_THRESHOLD = 0.45
# Minimum gap between best decision and best non-decision score
AMBIGUITY_MARGIN = 0.05


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
    # Try to load from cache first
    if _TEMPLATE_CACHE.exists():
        try:
            cache = json.loads(_TEMPLATE_CACHE.read_text())
            # Validate cache has expected keys and correct template count
            if (
                cache.get("decision_count") == len(DECISION_TEMPLATES)
                and cache.get("non_decision_count") == len(NON_DECISION_TEMPLATES)
                and cache.get("model") == "all-MiniLM-L6-v2"
            ):
                return cache
        except Exception:
            pass

    # Need to rebuild — requires sentence-transformers
    SentenceTransformer = _try_import_sentence_transformers()
    if SentenceTransformer is None:
        return None

    try:
        model = SentenceTransformer("all-MiniLM-L6-v2")

        decision_embs = model.encode(DECISION_TEMPLATES, normalize_embeddings=True)
        non_decision_embs = model.encode(
            NON_DECISION_TEMPLATES, normalize_embeddings=True
        )

        cache = {
            "model": "all-MiniLM-L6-v2",
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


def score_decision_semantic(text: str) -> tuple[float, str]:
    """
    Score whether text expresses a decision using semantic similarity.

    Tries three paths in order:
    1. Persistent scorer server (~5ms) — if running
    2. Direct model load (~500ms) — if sentence-transformers installed
    3. Returns (0.0, "") — fallback to regex in caller

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

    SentenceTransformer = _try_import_sentence_transformers()
    if SentenceTransformer is None:
        return (0.0, "")

    cache = _get_or_build_template_cache()
    if cache is None:
        return (0.0, "")

    try:
        import numpy as np

        model = SentenceTransformer("all-MiniLM-L6-v2")

        # Split into sentences and score each
        sentences = re.split(r"(?<=[.!])\s+|\n+", text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 15]
        if not sentences:
            sentences = [text.strip()]

        decision_embs = np.array(cache["decision_embeddings"])
        non_decision_embs = np.array(cache["non_decision_embeddings"])

        best_score = 0.0
        best_text = ""

        for sentence in sentences[:5]:  # Limit to first 5 sentences
            prompt_emb = model.encode([sentence], normalize_embeddings=True)

            # Cosine similarity with decision templates (already normalized, so dot product)
            decision_sims = np.dot(decision_embs, prompt_emb.T).flatten()
            best_decision_sim = float(np.max(decision_sims))

            # Cosine similarity with non-decision templates
            non_decision_sims = np.dot(non_decision_embs, prompt_emb.T).flatten()
            best_non_decision_sim = float(np.max(non_decision_sims))

            # Score: high decision similarity AND low non-decision similarity
            if best_decision_sim >= DECISION_THRESHOLD:
                # Check ambiguity — if non-decision templates are close, it's unclear
                if best_decision_sim - best_non_decision_sim < AMBIGUITY_MARGIN:
                    continue  # Too ambiguous

                # Scale to 0-1 range (0.55 threshold maps to ~0.5 output)
                score = min((best_decision_sim - 0.3) / 0.5, 1.0)

                if score > best_score:
                    best_score = score
                    best_text = sentence[:150]

        return (best_score, best_text)

    except Exception:
        return (0.0, "")


def build_template_cache() -> bool:
    """
    Pre-build the template embedding cache. Call during install.
    Returns True if successful, False if sentence-transformers not available.
    """
    cache = _get_or_build_template_cache()
    return cache is not None
