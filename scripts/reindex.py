#!/usr/bin/env python3
"""Rebuild session index, extractions, and search embeddings for a project.

Usage:
    python scripts/reindex.py E:\\workspace              # incremental
    python scripts/reindex.py E:\\workspace --force       # full rebuild (clears + re-embeds)
    python scripts/reindex.py E:\\workspace --extract     # re-extract empty sessions only
    python scripts/reindex.py E:\\workspace --force --extract  # full rebuild + re-extract all
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_engram.mining.session_index import build_project_index, resolve_project_index
from claude_engram.mining.search import build_session_embeddings


def _ensure_scorer():
    """Verify scorer server is available (auto-starts on demand)."""
    try:
        from claude_engram.hooks.scorer_server import embed_via_server

        result = embed_via_server("test")
        if not result:
            print("Scorer server failed to start")
            return False
        return True
    except ImportError:
        print("sentence-transformers not installed")
        return False


def _resolve_project_dir(project_path):
    """Resolve engram storage dir for a project."""
    storage = Path.home() / ".claude_engram"
    manifest = json.loads((storage / "manifest.json").read_text())
    norm = project_path.replace("\\", "/").lower().rstrip("/")
    return manifest.get("projects", {}).get(norm), storage


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    project_path = sys.argv[1]
    force = "--force" in sys.argv
    extract = "--extract" in sys.argv

    proj_info, storage = _resolve_project_dir(project_path)

    if force and proj_info:
        h = storage / "projects" / proj_info["hash"]
        (h / "session_embeddings_index.json").unlink(missing_ok=True)
        (h / "session_embeddings.npy").unlink(missing_ok=True)
        print("Cleared search index")
        if extract:
            # Delete extraction files that should be reprocessed:
            # - empty files (no content at all)
            # - files extracted without scorer (scorer_available=false)
            extractions_dir = h / "extractions"
            if extractions_dir.exists():
                deleted = 0
                for f in extractions_dir.glob("*.json"):
                    try:
                        data = json.loads(f.read_text())
                        has_content = any(
                            data.get(k)
                            for k in ("decisions", "mistakes", "approaches", "corrections")
                        )
                        had_scorer = data.get("scorer_available", False)
                        if not has_content or not had_scorer:
                            f.unlink()
                            deleted += 1
                    except Exception:
                        f.unlink()
                        deleted += 1
                print(f"Cleared {deleted} extraction files for reprocessing")

    if not _ensure_scorer():
        return 1

    t0 = time.time()
    index = build_project_index(project_path)
    if not index:
        index = resolve_project_index(project_path)
    if not index:
        print("No sessions found (checked parent workspaces too)")
        return 1

    print(f"Sessions: {index.get_session_count()}")

    # Run extractions if requested
    if extract:
        try:
            from claude_engram.mining.extractors import run_extraction_pipeline

            t1 = time.time()
            ext_count = run_extraction_pipeline(project_path, index)
            print(f"Extracted {ext_count} findings in {time.time() - t1:.1f}s")
        except Exception as e:
            print(f"Extraction failed: {e}")

    # Build search embeddings
    embed_count = build_session_embeddings(project_path, index)
    print(f"Indexed {embed_count} search chunks in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
