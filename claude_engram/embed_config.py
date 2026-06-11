"""
Embedding model configuration.

One place decides which sentence-transformers model (and optional Matryoshka
truncation dim) every embedding consumer uses: the scorer server, decision
templates, memory embeddings, and session-search embeddings.

Resolution order: env vars > ~/.claude_engram/config.json > default
(BAAI/bge-base-en-v1.5, native 768 dims — ungated, no API token needed).

    CLAUDE_ENGRAM_EMBED_MODEL   e.g. "all-MiniLM-L6-v2" (light: ~90MB vs ~440MB)
    CLAUDE_ENGRAM_EMBED_DIM     e.g. "256" (Matryoshka truncation; empty = native;
                                only for models trained for it, e.g. embeddinggemma)

config.json:
    {"embed_model": "all-MiniLM-L6-v2"}

Every embedding store is stamped with embed_signature(). A store whose stamp
does not match the current signature is discarded and rebuilt rather than
mixed: vectors from two models share no space, and silently mixing them was
the failure mode this module exists to prevent.

stdlib-only: hook processes import this on a 1s budget.
"""

import json
import os
from pathlib import Path

DEFAULT_MODEL = "BAAI/bge-base-en-v1.5"
DEFAULT_DIM = None  # set only if the default model wants Matryoshka truncation

# Signature assumed for UNSTAMPED embedding stores (written before stamping
# existed, i.e. by the original encoder). Pinned forever — do NOT update this
# when DEFAULT_MODEL changes, or legacy stores get misread as the new model.
LEGACY_SIGNATURE = "all-MiniLM-L6-v2@native"


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
    if dim is None and dim_raw is None and model == DEFAULT_MODEL:
        # No dim given anywhere: the default model gets its tuned truncation.
        # An explicit model choice (even the same string) with an explicit
        # dim — or any dim value at all — is always respected as-is.
        dim = DEFAULT_DIM
    return {"model": model, "dim": dim}


def embed_signature() -> str:
    """Stable id of the active embedding space, stored in every embedding
    index. Unstamped legacy stores are treated as LEGACY_SIGNATURE."""
    c = get_embed_config()
    return f"{c['model']}@{c['dim'] or 'native'}"


def load_sentence_transformer():
    """Construct the configured SentenceTransformer (truncated if dim set).
    Raises ImportError when sentence-transformers is not installed."""
    from sentence_transformers import SentenceTransformer

    c = get_embed_config()
    if c["dim"]:
        return SentenceTransformer(c["model"], truncate_dim=c["dim"])
    return SentenceTransformer(c["model"])
