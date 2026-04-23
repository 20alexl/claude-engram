#!/usr/bin/env python3
"""Rebuild session search index for a project.

Usage:
    python scripts/reindex.py E:\\workspace          # incremental (new sessions only)
    python scripts/reindex.py E:\\workspace --force   # full rebuild
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_engram.mining.session_index import build_project_index, resolve_project_index
from claude_engram.mining.search import build_session_embeddings


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    project_path = sys.argv[1]
    force = "--force" in sys.argv

    if force:
        storage = Path.home() / ".claude_engram"
        manifest = json.loads((storage / "manifest.json").read_text())
        norm = project_path.replace("\\", "/").lower().rstrip("/")
        proj_info = manifest.get("projects", {}).get(norm)
        if proj_info:
            h = storage / "projects" / proj_info["hash"]
            (h / "session_embeddings_index.json").unlink(missing_ok=True)
            (h / "session_embeddings.npy").unlink(missing_ok=True)
            print("Cleared existing index")

    # Ensure scorer server is running (loads AllMiniLM model)
    try:
        from claude_engram.hooks.scorer_server import start_server_background, embed_via_server

        start_server_background()
        # Wait for server to be ready
        for _ in range(30):
            if embed_via_server("test"):
                break
            time.sleep(0.5)
        else:
            print("Scorer server failed to start")
            return 1
    except ImportError:
        print("sentence-transformers not installed — needed for embeddings")
        return 1

    t0 = time.time()
    # Try direct build first, then workspace inheritance for sub-projects
    index = build_project_index(project_path)
    if not index:
        index = resolve_project_index(project_path)
    if not index:
        print("No sessions found (checked parent workspaces too)")
        return 1

    count = build_session_embeddings(project_path, index)
    print(f"Indexed {count} chunks in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
