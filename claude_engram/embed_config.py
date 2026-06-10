"""
Embedding model configuration.

One place decides which sentence-transformers model (and optional Matryoshka
truncation dim) every embedding consumer uses: the scorer server, decision
templates, memory embeddings, and session-search embeddings.

Resolution order: env vars > ~/.claude_engram/config.json > default.

    CLAUDE_ENGRAM_EMBED_MODEL   e.g. "google/embeddinggemma-300m"
    CLAUDE_ENGRAM_EMBED_DIM     e.g. "256" (Matryoshka truncation; empty = native)

config.json:
    {"embed_model": "google/embeddinggemma-300m", "embed_dim": 256}

Every embedding store is stamped with embed_signature(). A store whose stamp
does not match the current signature is discarded and rebuilt rather than
mixed: vectors from two models share no space, and silently mixing them was
the failure mode this module exists to prevent.

stdlib-only: hook processes import this on a 1s budget.
"""

import json
import os
from pathlib import Path

DEFAULT_MODEL = "all-MiniLM-L6-v2"


def _storage_dir() -> Path:
    override = os.environ.get("CLAUDE_ENGRAM_DIR", "")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude_engram"


def get_embed_config() -> dict:
    """Resolve {"model": str, "dim": int | None}. dim None = model native."""
    cfg = {}
    cfg_file = _storage_dir() / "config.json"
    if cfg_file.exists():
        try:
            cfg = json.loads(cfg_file.read_text())
        except Exception:
            cfg = {}

    model = (
        os.environ.get("CLAUDE_ENGRAM_EMBED_MODEL")
        or cfg.get("embed_model")
        or DEFAULT_MODEL
    )
    dim_raw = os.environ.get("CLAUDE_ENGRAM_EMBED_DIM") or cfg.get("embed_dim")
    try:
        dim = int(dim_raw) if dim_raw else None
    except (TypeError, ValueError):
        dim = None
    return {"model": model, "dim": dim}


def embed_signature() -> str:
    """Stable id of the active embedding space, stored in every embedding
    index. Unstamped legacy stores are treated as the default signature."""
    c = get_embed_config()
    return f"{c['model']}@{c['dim'] or 'native'}"


DEFAULT_SIGNATURE = f"{DEFAULT_MODEL}@native"


def load_sentence_transformer():
    """Construct the configured SentenceTransformer (truncated if dim set).
    Raises ImportError when sentence-transformers is not installed."""
    from sentence_transformers import SentenceTransformer

    c = get_embed_config()
    if c["dim"]:
        return SentenceTransformer(c["model"], truncate_dim=c["dim"])
    return SentenceTransformer(c["model"])
