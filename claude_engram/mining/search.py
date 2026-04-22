"""
Cross-session search — find conversations, decisions, and context across sessions.

Builds an embedding index over conversation chunks:
  - User messages (questions, directives)
  - Assistant text blocks (explanations, decisions)
  - Tool content: bash commands + output, edit summaries, error tracebacks, file reads
  - Subagent conversations (Explore, Plan, code-reviewer, etc.)

Stored as session_embeddings.npy + session_embeddings_index.json.

Search modes:
  - semantic: AllMiniLM cosine similarity (typo-tolerant)
  - keyword: substring match on chunk previews (fast, exact)
  - hybrid: both, weighted combination
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from claude_engram.mining.jsonl_reader import (
    resolve_jsonl_dir,
    iter_messages,
    extract_user_text,
    extract_assistant_text,
    extract_tool_uses,
    extract_tool_results,
    extract_file_edits,
    extract_bash_commands,
    get_timestamp,
    get_session_id,
)


@dataclass
class SearchResult:
    """A search result from session mining."""

    chunk_text: str  # The matched text (preview)
    score: float  # Relevance score (0-1)
    session_id: str = ""
    timestamp: str = ""
    msg_type: str = ""  # "user" | "assistant" | "subagent" | "tool" | "subagent_tool"
    surrounding: list[str] = field(default_factory=list)  # Context messages
    related_files: list[str] = field(default_factory=list)


@dataclass
class ChunkIndex:
    """Lightweight index entry for a searchable conversation chunk."""

    session_id: str
    jsonl_file: str
    msg_offset: int  # Message index in the JSONL
    timestamp: str
    msg_type: str  # "user" | "assistant"
    preview: str  # First 200 chars of text
    related_files: list[str] = field(default_factory=list)


def _extract_tool_chunks(
    prev_msg: dict,
    curr_msg: dict,
    session_id: str,
    jsonl_file: str,
    msg_offset: int,
    ts: str,
) -> list[tuple["ChunkIndex", str]]:
    """
    Extract searchable chunks from tool_use (prev_msg) + tool_result (curr_msg) pairs.

    Returns list of (ChunkIndex, embed_text) tuples.
    """
    chunks = []

    # Get tool uses from the assistant message
    tool_uses = extract_tool_uses(prev_msg) if prev_msg else []
    if not tool_uses:
        return chunks

    # Get tool results from the current user message
    tool_results = extract_tool_results(curr_msg)

    # Build result text (stderr, stdout, error content)
    result_text = ""
    is_error = False
    for tr in tool_results:
        if isinstance(tr, dict):
            if tr.get("is_error"):
                is_error = True
            content = tr.get("content", "")
            if isinstance(content, str):
                result_text = content
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        result_text = block.get("content", "") or block.get("text", "")
                        if block.get("is_error"):
                            is_error = True
                        if result_text:
                            break

    # Also check toolUseResult field (bash results have stdout/stderr)
    tur = curr_msg.get("toolUseResult", {})
    if isinstance(tur, dict):
        stdout = tur.get("stdout", "")
        stderr = tur.get("stderr", "")
        if stderr:
            result_text = stderr
            is_error = True
        elif stdout and not result_text:
            result_text = stdout

    for tool in tool_uses:
        name = tool["name"]
        inp = tool.get("input", {})

        if name == "Bash":
            cmd = inp.get("command", "")
            if not cmd or len(cmd) < 5:
                continue
            # Truncate command to first meaningful line
            cmd_short = cmd.split("\n")[0][:150]

            if is_error and result_text:
                # Error output — high value, index the error
                error_lines = result_text.strip().split("\n")
                # Take first + last few lines (traceback pattern)
                if len(error_lines) > 8:
                    summary = "\n".join(error_lines[:3] + ["..."] + error_lines[-3:])
                else:
                    summary = "\n".join(error_lines[:8])
                preview = f"[bash error] {cmd_short}\n{summary}"
            elif result_text:
                # Normal output — take first and last lines
                out_lines = result_text.strip().split("\n")
                if len(out_lines) > 6:
                    summary = "\n".join(out_lines[:3] + ["..."] + out_lines[-2:])
                else:
                    summary = "\n".join(out_lines[:5])
                preview = f"[bash] {cmd_short}\n{summary}"
            else:
                preview = f"[bash] {cmd_short}"

            if len(preview) < 20:
                continue

            chunks.append((
                ChunkIndex(
                    session_id=session_id,
                    jsonl_file=jsonl_file,
                    msg_offset=msg_offset,
                    timestamp=ts,
                    msg_type="tool",
                    preview=preview[:300],
                ),
                preview[:500],
            ))

        elif name in ("Edit", "Write"):
            fp = inp.get("file_path", "")
            if not fp:
                continue
            fname = Path(fp).name
            old = inp.get("old_string", "")
            new = inp.get("new_string", "")
            content = inp.get("content", "")

            if old and new:
                # Edit — summarize what changed
                preview = f"[edit] {fname}: replaced {old[:80]} → {new[:80]}"
            elif content:
                # Write — first meaningful line
                first_lines = content.strip().split("\n")[:3]
                preview = f"[write] {fname}: {' '.join(first_lines)[:120]}"
            else:
                preview = f"[edit] {fname}"

            if is_error and result_text:
                preview += f"\n  ERROR: {result_text[:100]}"

            chunks.append((
                ChunkIndex(
                    session_id=session_id,
                    jsonl_file=jsonl_file,
                    msg_offset=msg_offset,
                    timestamp=ts,
                    msg_type="tool",
                    preview=preview[:300],
                    related_files=[fname],
                ),
                preview[:500],
            ))

        # Read tools skipped — "[read] filename" has near-zero search value
        # and bloats the index. File paths are captured in related_files on edits.

    return chunks


def build_session_embeddings(
    project_path: str,
    index,  # SessionIndex
    engram_storage_dir: str = "~/.claude_engram",
) -> int:
    """
    Build/update conversation chunk embeddings for search.

    Extracts searchable chunks (user messages + assistant text blocks),
    embeds them with AllMiniLM in batch, stores as .npy + index JSON.

    Returns count of new chunks embedded.
    """
    storage = Path(engram_storage_dir).expanduser()
    manifest_path = storage / "manifest.json"
    if not manifest_path.exists():
        return 0

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    norm_path = _normalize_path(project_path)
    proj_info = manifest.get("projects", {}).get(norm_path)
    if not proj_info:
        return 0

    hash_dir = storage / "projects" / proj_info["hash"]
    emb_path = hash_dir / "session_embeddings.npy"
    idx_path = hash_dir / "session_embeddings_index.json"

    # Load existing index
    existing_chunks: list[dict] = []
    existing_sessions: set[str] = set()
    if idx_path.exists():
        try:
            data = json.loads(idx_path.read_text(encoding="utf-8"))
            existing_chunks = data.get("chunks", [])
            existing_sessions = {c["session_id"] for c in existing_chunks}
        except Exception:
            pass

    # Find new sessions to process
    jsonl_dir = resolve_jsonl_dir(project_path)
    if not jsonl_dir:
        return 0

    new_chunks: list[ChunkIndex] = []
    new_texts: list[str] = []

    for session_id, session_meta in index.sessions.items():
        if session_id in existing_sessions:
            continue

        jsonl_file = jsonl_dir / session_meta.get("jsonl_file", "")
        if not jsonl_file.exists():
            continue

        msg_idx = 0
        prev_msg = None
        jfile = session_meta.get("jsonl_file", "")
        for _, msg in iter_messages(jsonl_file, types={"user", "assistant"}):
            msg_idx += 1
            ts = get_timestamp(msg)

            # User messages (questions, directives)
            user_text = extract_user_text(msg)
            if user_text and 15 < len(user_text) < 1000:
                chunk = ChunkIndex(
                    session_id=session_id,
                    jsonl_file=jfile,
                    msg_offset=msg_idx,
                    timestamp=ts,
                    msg_type="user",
                    preview=user_text[:200],
                )
                new_chunks.append(chunk)
                new_texts.append(user_text[:500])

            # Assistant text blocks (substantive content only)
            for text in extract_assistant_text(msg):
                if len(text) < 50:
                    continue
                if text.startswith("```") or text.startswith("{"):
                    continue

                files = extract_file_edits(msg)
                chunk = ChunkIndex(
                    session_id=session_id,
                    jsonl_file=jfile,
                    msg_offset=msg_idx,
                    timestamp=ts,
                    msg_type="assistant",
                    preview=text[:200],
                    related_files=[Path(f).name for f in files[:5]],
                )
                new_chunks.append(chunk)
                new_texts.append(text[:500])

            # Tool chunks: pair previous assistant (tool_use) with current user (tool_result)
            if prev_msg and msg.get("type") == "user":
                for tool_chunk, tool_text in _extract_tool_chunks(
                    prev_msg, msg, session_id, jfile, msg_idx, ts,
                ):
                    new_chunks.append(tool_chunk)
                    new_texts.append(tool_text)

            prev_msg = msg

        # Also scan subagent conversations for this session
        session_dir = jsonl_dir / jfile.replace(".jsonl", "")
        subagents_dir = session_dir / "subagents"
        if subagents_dir.exists():
            for sub_jsonl in subagents_dir.glob("*.jsonl"):
                sub_msg_idx = 0
                sub_prev_msg = None
                for _, msg in iter_messages(sub_jsonl, types={"user", "assistant"}):
                    sub_msg_idx += 1
                    ts = get_timestamp(msg)

                    # Assistant text from subagents (their findings/analysis)
                    for text in extract_assistant_text(msg):
                        if len(text) < 50 or text.startswith("```") or text.startswith("{"):
                            continue
                        files = extract_file_edits(msg)
                        chunk = ChunkIndex(
                            session_id=session_id,
                            jsonl_file=sub_jsonl.name,
                            msg_offset=sub_msg_idx,
                            timestamp=ts,
                            msg_type="subagent",
                            preview=text[:200],
                            related_files=[Path(f).name for f in files[:5]],
                        )
                        new_chunks.append(chunk)
                        new_texts.append(text[:500])

                    # Tool chunks from subagents too
                    if sub_prev_msg and msg.get("type") == "user":
                        for tool_chunk, tool_text in _extract_tool_chunks(
                            sub_prev_msg, msg, session_id, sub_jsonl.name, sub_msg_idx, ts,
                        ):
                            tool_chunk.msg_type = "subagent_tool"
                            new_chunks.append(tool_chunk)
                            new_texts.append(tool_text)

                    sub_prev_msg = msg

    if not new_texts:
        return 0

    # Batch embed in chunks of 200 (large batches can timeout)
    BATCH_SIZE = 200
    new_embeddings = []
    try:
        from claude_engram.hooks.scorer_server import embed_batch_via_server

        for i in range(0, len(new_texts), BATCH_SIZE):
            batch = new_texts[i : i + BATCH_SIZE]
            batch_embs = embed_batch_via_server(batch)
            new_embeddings.extend(batch_embs)
    except Exception:
        return 0

    # Filter out failed embeddings
    valid_chunks = []
    valid_embeddings = []
    for chunk, emb in zip(new_chunks, new_embeddings):
        if emb and len(emb) > 0:
            valid_chunks.append(chunk)
            valid_embeddings.append(emb)

    if not valid_embeddings:
        return 0

    # Merge with existing
    try:
        import numpy as np

        if emb_path.exists() and existing_chunks:
            # Don't use mmap — we're overwriting this file, and Windows
            # throws Errno 22 if you np.save to a mmap'd file
            old_matrix = np.load(str(emb_path))
            new_matrix = np.array(valid_embeddings, dtype=np.float32)
            combined = np.vstack([old_matrix, new_matrix])
        else:
            combined = np.array(valid_embeddings, dtype=np.float32)

        # Atomic save via temp file
        # np.save auto-appends .npy, so use stem without extension
        tmp_stem = emb_path.parent / "session_embeddings_tmp"
        np.save(str(tmp_stem), combined)  # creates session_embeddings_tmp.npy
        (emb_path.parent / "session_embeddings_tmp.npy").replace(emb_path)
    except ImportError:
        # No numpy — store as JSON fallback
        emb_json_path = hash_dir / "session_embeddings.json"
        all_embs = []
        if emb_json_path.exists():
            try:
                all_embs = json.loads(emb_json_path.read_text())
            except Exception:
                pass
        all_embs.extend(valid_embeddings)
        emb_json_path.write_text(json.dumps(all_embs), encoding="utf-8")

    # Save index
    all_chunks = existing_chunks + [
        {
            "session_id": c.session_id,
            "jsonl_file": c.jsonl_file,
            "msg_offset": c.msg_offset,
            "timestamp": c.timestamp,
            "msg_type": c.msg_type,
            "preview": c.preview,
            "related_files": c.related_files,
        }
        for c in valid_chunks
    ]

    tmp = idx_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"chunks": all_chunks}, indent=2), encoding="utf-8")
    tmp.replace(idx_path)

    return len(valid_chunks)


def search_sessions(
    project_path: str,
    query: str,
    limit: int = 10,
    method: str = "hybrid",
    since: str = "",
    until: str = "",
    engram_storage_dir: str = "~/.claude_engram",
) -> list[SearchResult]:
    """
    Search across session conversations.

    Args:
        query: Search query (typo-tolerant with semantic method)
        limit: Max results
        method: "semantic" | "keyword" | "hybrid"
        since: ISO date string to filter results after (e.g. "2026-04-01")
        until: ISO date string to filter results before

    Returns list of SearchResult sorted by relevance.
    """
    storage = Path(engram_storage_dir).expanduser()
    manifest_path = storage / "manifest.json"
    if not manifest_path.exists():
        return []

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Try this project, then walk up to parent workspace
    hash_dir = _resolve_hash_dir_with_inheritance(
        project_path, manifest, storage, require_file="session_embeddings_index.json"
    )
    if not hash_dir:
        return []

    idx_path = hash_dir / "session_embeddings_index.json"

    if not idx_path.exists():
        return []

    idx_data = json.loads(idx_path.read_text(encoding="utf-8"))
    chunks = idx_data.get("chunks", [])
    if not chunks:
        return []

    # Temporal filtering — filter chunks by date range before scoring
    if since or until:
        filtered_chunks = []
        filtered_indices = []
        for i, chunk in enumerate(chunks):
            ts = chunk.get("timestamp", "")[:10]  # YYYY-MM-DD
            if since and ts < since:
                continue
            if until and ts > until:
                continue
            filtered_chunks.append(chunk)
            filtered_indices.append(i)
        chunks = filtered_chunks
        if not chunks:
            return []
    else:
        filtered_indices = list(range(len(chunks)))

    # Keyword scoring
    keyword_scores = [0.0] * len(chunks)
    if method in ("keyword", "hybrid"):
        query_lower = query.lower()
        query_words = query_lower.split()
        for i, chunk in enumerate(chunks):
            preview = chunk.get("preview", "").lower()
            # Word overlap scoring
            matched = sum(1 for w in query_words if w in preview)
            if matched > 0:
                keyword_scores[i] = matched / len(query_words)

    # Semantic scoring
    semantic_scores = [0.0] * len(chunks)
    if method in ("semantic", "hybrid"):
        emb_path = hash_dir / "session_embeddings.npy"
        try:
            import numpy as np
            from claude_engram.hooks.scorer_server import embed_via_server

            query_emb = embed_via_server(query)
            if query_emb and emb_path.exists():
                matrix = np.load(str(emb_path), mmap_mode="r")
                query_arr = np.array(query_emb, dtype=np.float32)
                # Use filtered indices if temporal filter was applied
                if filtered_indices and len(filtered_indices) < len(matrix):
                    sub_matrix = matrix[filtered_indices]
                    sims = np.dot(sub_matrix, query_arr)
                else:
                    sims = np.dot(matrix, query_arr)
                semantic_scores = sims.tolist()
        except Exception:
            pass

    # Combine scores
    results = []
    for i, chunk in enumerate(chunks):
        if method == "hybrid":
            score = 0.6 * semantic_scores[i] + 0.4 * keyword_scores[i]
        elif method == "semantic":
            score = semantic_scores[i]
        else:
            score = keyword_scores[i]

        if score > 0.2:
            results.append(
                SearchResult(
                    chunk_text=chunk.get("preview", ""),
                    score=score,
                    session_id=chunk.get("session_id", ""),
                    timestamp=chunk.get("timestamp", ""),
                    msg_type=chunk.get("msg_type", ""),
                    related_files=chunk.get("related_files", []),
                )
            )

    results.sort(key=lambda r: -r.score)
    return results[:limit]


def find_decision(
    project_path: str,
    query: str,
    engram_storage_dir: str = "~/.claude_engram",
) -> list[SearchResult]:
    """
    Find when/why a specific decision was made.

    Searches across sessions with context expansion — returns the decision
    plus surrounding conversation for full reasoning.
    """
    results = search_sessions(
        project_path,
        query,
        limit=5,
        method="semantic",
        engram_storage_dir=engram_storage_dir,
    )

    # Expand context: for each result, load surrounding messages
    jsonl_dir = resolve_jsonl_dir(project_path)
    if not jsonl_dir:
        return results

    for result in results:
        # Find the JSONL file for this session
        storage = Path(engram_storage_dir).expanduser()
        manifest = json.loads((storage / "manifest.json").read_text())
        norm_path = _normalize_path(project_path)
        proj_info = manifest.get("projects", {}).get(norm_path)
        if not proj_info:
            continue

        hash_dir = storage / "projects" / proj_info["hash"]
        idx_data = json.loads((hash_dir / "session_embeddings_index.json").read_text())

        # Find the chunk's JSONL file
        for chunk in idx_data.get("chunks", []):
            if (
                chunk.get("session_id") == result.session_id
                and chunk.get("preview") == result.chunk_text
            ):
                jsonl_file = jsonl_dir / chunk["jsonl_file"]
                if jsonl_file.exists():
                    result.surrounding = _get_surrounding_messages(
                        jsonl_file, chunk["msg_offset"], window=3
                    )
                break

    return results


def find_file_discussions(
    project_path: str,
    file_path: str,
    limit: int = 10,
    engram_storage_dir: str = "~/.claude_engram",
) -> list[SearchResult]:
    """
    Find conversations where a specific file was discussed or edited.

    Useful for "why was this implemented this way?" questions.
    """
    from pathlib import Path as P

    storage = Path(engram_storage_dir).expanduser()
    manifest_path = storage / "manifest.json"
    if not manifest_path.exists():
        return []

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    hash_dir = _resolve_hash_dir_with_inheritance(
        project_path, manifest, storage, require_file="session_embeddings_index.json"
    )
    if not hash_dir:
        return []

    idx_path = hash_dir / "session_embeddings_index.json"
    idx_data = json.loads(idx_path.read_text(encoding="utf-8"))
    chunks = idx_data.get("chunks", [])

    target_name = P(file_path).name.lower()

    results = []
    for chunk in chunks:
        # Check related_files
        files = [f.lower() for f in chunk.get("related_files", [])]
        preview = chunk.get("preview", "").lower()

        score = 0.0
        if target_name in files:
            score = 1.0
        elif target_name in preview:
            score = 0.7
        elif P(file_path).stem.lower() in preview:
            score = 0.5

        if score > 0:
            results.append(
                SearchResult(
                    chunk_text=chunk.get("preview", ""),
                    score=score,
                    session_id=chunk.get("session_id", ""),
                    timestamp=chunk.get("timestamp", ""),
                    msg_type=chunk.get("msg_type", ""),
                    related_files=chunk.get("related_files", []),
                )
            )

    results.sort(key=lambda r: (-r.score, r.timestamp))
    return results[:limit]


def _get_surrounding_messages(
    jsonl_path: Path,
    target_offset: int,
    window: int = 3,
) -> list[str]:
    """Get surrounding message previews for context expansion."""
    messages = []
    for _, msg in iter_messages(jsonl_path, types={"user", "assistant"}):
        messages.append(msg)

    # Find the target message region
    start = max(0, target_offset - window)
    end = min(len(messages), target_offset + window + 1)

    context = []
    for msg in messages[start:end]:
        user_text = extract_user_text(msg)
        if user_text:
            context.append(f"[user] {user_text[:150]}")
        else:
            texts = extract_assistant_text(msg)
            if texts:
                context.append(f"[assistant] {texts[0][:150]}")

    return context


def _normalize_path(project_path: str) -> str:
    """Normalize project path for manifest lookup."""
    norm = str(Path(project_path).resolve()).replace("\\", "/")
    if len(norm) >= 2 and norm[1] == ":":
        norm = norm[0].lower() + norm[1:]
    return norm


def _resolve_hash_dir_with_inheritance(
    project_path: str,
    manifest: dict,
    storage: Path,
    require_file: str = "",
) -> Optional[Path]:
    """
    Find the hash dir for a project, walking up to parent workspace if needed.

    If require_file is set, only returns dirs that contain that file.
    This handles sub-projects that don't have their own session data
    but whose parent workspace does.
    """
    norm = _normalize_path(project_path)
    projects = manifest.get("projects", {})

    # Try this path and all parents
    current = norm
    while True:
        if current in projects:
            hash_dir = storage / "projects" / projects[current]["hash"]
            if not require_file or (hash_dir / require_file).exists():
                return hash_dir

        parent = str(Path(current).parent).replace("\\", "/")
        if parent == current:
            break
        current = parent

    return None
