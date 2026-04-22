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

from claude_engram.mining.session_index import build_project_index
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

    t0 = time.time()
    index = build_project_index(project_path)
    if not index:
        print("No sessions found")
        return 1

    count = build_session_embeddings(project_path, index)
    print(f"Indexed {count} chunks in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
