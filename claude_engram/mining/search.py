"""
Cross-session search — find conversations, decisions, and context across sessions.

Builds an embedding index over conversation chunks:
  - User messages (questions, directives)
  - Assistant text blocks (explanations, decisions)
  - Tool content: bash commands + output, edit summaries, error tracebacks, file reads
  - Subagent conversations (Explore, Plan, code-reviewer, etc.)

Stored as monthly .npy shards under session_embeddings/ plus one
session_embeddings_index.json (v2). Flat v1 stores (single ever-growing
.npy) migrate automatically on the next miner run.

Search modes:
  - semantic: embedding cosine similarity (typo-tolerant)
  - keyword: substring match on chunk previews (fast, exact)
  - hybrid: both, weighted combination
"""

import json
import os
import re
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


# Hit classification: tag a search result by what it IS, so a next-step or a
# decision isn't ranked indistinguishably from mid-task narration. Order
# matters — most distinctive first.
_KIND_PATTERNS = [
    (
        "error",
        re.compile(
            r"\b(error|exception|traceback|failed|attributeerror|typeerror|"
            r"valueerror|keyerror|importerror|assertion|stack ?trace)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "decision",
        re.compile(
            r"\b(decid\w+|let'?s (?:use|go with)|switch(?:ing)? to|"
            r"we'?ll (?:use|go with)|going with|went with|chose|choosing|"
            r"opt(?:ed|ing)? for|the call is|i'?d (?:use|go with|rather))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "next-step",
        re.compile(
            r"(\bi'?ll |\bnext step|\bnext is|\bnext up|\bto-?do\b|\bremaining\b|"
            r"\bstill (?:need|have) to|\bfollow-?up|\blet me )",
            re.IGNORECASE,
        ),
    ),
]


def classify_chunk(text: str) -> str:
    """Classify a search hit as error / decision / next-step / narration."""
    for kind, pat in _KIND_PATTERNS:
        if pat.search(text or ""):
            return kind
    return "narration"


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

            chunks.append(
                (
                    ChunkIndex(
                        session_id=session_id,
                        jsonl_file=jsonl_file,
                        msg_offset=msg_offset,
                        timestamp=ts,
                        msg_type="tool",
                        preview=preview[:300],
                    ),
                    preview[:500],
                )
            )

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

            chunks.append(
                (
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
                )
            )

        # Read tools skipped — "[read] filename" has near-zero search value
        # and bloats the index. File paths are captured in related_files on edits.

    return chunks


def _month_of(ts: str) -> str:
    """Shard key (YYYY-MM) for an ISO timestamp; 'undated' when absent."""
    return ts[:7] if ts and len(ts) >= 7 else "undated"


def _iter_index_chunks(idx_data: dict):
    """Yield chunk dicts from either store layout (v2 shards or v1 flat)."""
    if "shards" in idx_data:
        for key in sorted(idx_data.get("shards", {})):
            yield from idx_data["shards"][key].get("chunks", [])
    else:
        yield from idx_data.get("chunks", [])


def _chunk_to_dict(c: ChunkIndex) -> dict:
    return {
        "session_id": c.session_id,
        "jsonl_file": c.jsonl_file,
        "msg_offset": c.msg_offset,
        "timestamp": c.timestamp,
        "msg_type": c.msg_type,
        "preview": c.preview,
        "related_files": c.related_files,
    }


def _subs_changed(jsonl_dir: Path, session_meta: dict, progress: dict) -> bool:
    """Cheap (stat-only) check: did any subagent JSONL appear or grow since
    the watermarks in `progress` were written?"""
    jfile = session_meta.get("jsonl_file", "")
    subagents_dir = jsonl_dir / jfile.replace(".jsonl", "") / "subagents"
    if not subagents_dir.exists():
        return False
    known = progress.get("subs", {})
    for sub_jsonl in subagents_dir.glob("*.jsonl"):
        rec = known.get(sub_jsonl.name)
        try:
            size = sub_jsonl.stat().st_size
        except OSError:
            continue
        if rec is None or int(rec[1]) != size:
            return True
    return False


def _scan_session_chunks(
    jsonl_dir: Path,
    session_id: str,
    session_meta: dict,
    progress: dict,
) -> tuple[list[ChunkIndex], list[str], dict]:
    """
    Collect searchable chunks for one session, emitting only messages PAST
    the stored watermarks (a per-file index over user/assistant messages).
    A session that grew after indexing — PreCompact then SessionEnd, or a
    long-lived conversation resumed across days — contributes exactly its
    new tail instead of being skipped wholesale (the pre-v2 behavior).

    Returns (chunks, texts, new_progress); new_progress carries updated
    watermarks plus subagent file sizes so an unchanged session costs a few
    stat() calls on the next run.
    """
    jfile = session_meta.get("jsonl_file", "")
    jsonl_file = jsonl_dir / jfile
    main_mark = int(progress.get("main", 0))

    chunks: list[ChunkIndex] = []
    texts: list[str] = []

    msg_idx = 0
    prev_msg = None
    if jsonl_file.exists():
        for _, msg in iter_messages(jsonl_file, types={"user", "assistant"}):
            msg_idx += 1
            ts = get_timestamp(msg)

            if msg_idx > main_mark:
                # User messages (questions, directives)
                user_text = extract_user_text(msg)
                if user_text and 15 < len(user_text) < 1000:
                    chunks.append(
                        ChunkIndex(
                            session_id=session_id,
                            jsonl_file=jfile,
                            msg_offset=msg_idx,
                            timestamp=ts,
                            msg_type="user",
                            preview=user_text[:200],
                        )
                    )
                    texts.append(user_text[:500])

                # Assistant text blocks (substantive content only)
                for text in extract_assistant_text(msg):
                    if len(text) < 50:
                        continue
                    if text.startswith("```") or text.startswith("{"):
                        continue
                    files = extract_file_edits(msg)
                    chunks.append(
                        ChunkIndex(
                            session_id=session_id,
                            jsonl_file=jfile,
                            msg_offset=msg_idx,
                            timestamp=ts,
                            msg_type="assistant",
                            preview=text[:200],
                            related_files=[Path(f).name for f in files[:5]],
                        )
                    )
                    texts.append(text[:500])

                # Tool chunks: pair previous assistant (tool_use) with current
                # user (tool_result). prev_msg is tracked through skipped
                # messages too, so a result that lands just past the watermark
                # still finds its tool_use.
                if prev_msg and msg.get("type") == "user":
                    for tool_chunk, tool_text in _extract_tool_chunks(
                        prev_msg, msg, session_id, jfile, msg_idx, ts
                    ):
                        chunks.append(tool_chunk)
                        texts.append(tool_text)

            prev_msg = msg

    # Subagent conversations: per-file watermarks. Size unchanged -> not
    # even parsed; new or grown files contribute their tail.
    old_subs = progress.get("subs", {})
    new_subs: dict = {}
    subagents_dir = jsonl_dir / jfile.replace(".jsonl", "") / "subagents"
    if subagents_dir.exists():
        for sub_jsonl in subagents_dir.glob("*.jsonl"):
            try:
                size = sub_jsonl.stat().st_size
            except OSError:
                continue
            rec = old_subs.get(sub_jsonl.name) or [0, -1]
            sub_mark, prev_size = int(rec[0]), int(rec[1])
            if size == prev_size:
                new_subs[sub_jsonl.name] = [sub_mark, size]
                continue

            sub_idx = 0
            sub_prev_msg = None
            for _, msg in iter_messages(sub_jsonl, types={"user", "assistant"}):
                sub_idx += 1
                ts = get_timestamp(msg)

                if sub_idx > sub_mark:
                    for text in extract_assistant_text(msg):
                        if (
                            len(text) < 50
                            or text.startswith("```")
                            or text.startswith("{")
                        ):
                            continue
                        files = extract_file_edits(msg)
                        chunks.append(
                            ChunkIndex(
                                session_id=session_id,
                                jsonl_file=sub_jsonl.name,
                                msg_offset=sub_idx,
                                timestamp=ts,
                                msg_type="subagent",
                                preview=text[:200],
                                related_files=[Path(f).name for f in files[:5]],
                            )
                        )
                        texts.append(text[:500])

                    if sub_prev_msg and msg.get("type") == "user":
                        for tool_chunk, tool_text in _extract_tool_chunks(
                            sub_prev_msg, msg, session_id, sub_jsonl.name, sub_idx, ts
                        ):
                            tool_chunk.msg_type = "subagent_tool"
                            chunks.append(tool_chunk)
                            texts.append(tool_text)

                sub_prev_msg = msg

            new_subs[sub_jsonl.name] = [max(sub_mark, sub_idx), size]

    new_progress = dict(progress)
    new_progress["main"] = max(main_mark, msg_idx)
    new_progress["subs"] = new_subs
    return chunks, texts, new_progress


def _wipe_embedding_store(hash_dir: Path):
    """Remove the session-embedding store entirely (index, shards, legacy
    flat files). Used on model change or corruption — the next miner run
    rebuilds from scratch in the current vector space."""
    (hash_dir / "session_embeddings_index.json").unlink(missing_ok=True)
    (hash_dir / "session_embeddings.npy").unlink(missing_ok=True)
    (hash_dir / "session_embeddings.json").unlink(missing_ok=True)
    shard_dir = hash_dir / "session_embeddings"
    if shard_dir.exists():
        for f in shard_dir.glob("*.npy"):
            f.unlink(missing_ok=True)


def _migrate_v1_store(hash_dir: Path, idx_data: dict, np) -> Optional[dict]:
    """
    Split a v1 flat store (one ever-growing .npy + a chunks list) into
    monthly shards. Row order == chunk order is the v1 invariant; on any
    mismatch the store is wiped and rebuilt by the next run.

    Returns the new v2 index dict, or None if the store was wiped.
    """
    from claude_engram.embed_config import LEGACY_SIGNATURE

    emb_path = hash_dir / "session_embeddings.npy"
    chunks = idx_data.get("chunks", [])
    if not emb_path.exists() or not chunks:
        _wipe_embedding_store(hash_dir)
        return None
    try:
        matrix = np.load(str(emb_path))
    except Exception:
        _wipe_embedding_store(hash_dir)
        return None
    if len(matrix.shape) != 2 or matrix.shape[0] != len(chunks):
        _wipe_embedding_store(hash_dir)
        return None

    # One shard per session (keyed by its first chunk's month) so a
    # session's rows never straddle shards.
    session_shard: dict[str, str] = {}
    for c in chunks:
        sid = c.get("session_id", "")
        if sid not in session_shard:
            session_shard[sid] = _month_of(c.get("timestamp", ""))

    shard_rows: dict[str, list[int]] = {}
    shard_chunks: dict[str, list[dict]] = {}
    for i, c in enumerate(chunks):
        key = session_shard.get(c.get("session_id", ""), "undated")
        shard_rows.setdefault(key, []).append(i)
        shard_chunks.setdefault(key, []).append(c)

    shard_dir = hash_dir / "session_embeddings"
    shard_dir.mkdir(exist_ok=True)
    for key, rows in shard_rows.items():
        sub = matrix[rows]
        tmp_stem = shard_dir / f"{key}_tmp"
        np.save(str(tmp_stem), sub)
        (shard_dir / f"{key}_tmp.npy").replace(shard_dir / f"{key}.npy")

    # Watermarks from what was actually embedded. max(msg_offset) can
    # undercount (trailing chunk-less messages), which is safe: re-scanning
    # those messages emits nothing new. meta_count=-1 forces one
    # reconciliation scan per session, after which v2 bookkeeping is exact.
    progress: dict[str, dict] = {}
    for c in chunks:
        sid = c.get("session_id", "")
        if not sid:
            continue
        p = progress.setdefault(
            sid,
            {"shard": session_shard.get(sid, "undated"), "main": 0, "subs": {},
             "meta_count": -1},
        )
        if c.get("msg_type") in ("user", "assistant"):
            p["main"] = max(p["main"], int(c.get("msg_offset", 0)))
        else:
            sub_file = c.get("jsonl_file", "")
            if sub_file and c.get("msg_type", "").startswith("subagent"):
                rec = p["subs"].get(sub_file) or [0, -1]
                rec[0] = max(int(rec[0]), int(c.get("msg_offset", 0)))
                p["subs"][sub_file] = rec

    emb_path.unlink(missing_ok=True)
    return {
        "version": 2,
        "model": idx_data.get("model", LEGACY_SIGNATURE),
        "shards": {k: {"chunks": v} for k, v in shard_chunks.items()},
        "session_progress": progress,
    }


def _prune_old_shards(shards: dict, session_progress: dict, shard_dir: Path) -> bool:
    """Apply CLAUDE_ENGRAM_SESSION_RETENTION_DAYS: drop whole months older
    than the cutoff (default 0 = keep everything). Returns True if anything
    was pruned."""
    try:
        retention_days = int(
            os.environ.get("CLAUDE_ENGRAM_SESSION_RETENTION_DAYS", "0") or 0
        )
    except ValueError:
        retention_days = 0
    if retention_days <= 0:
        return False
    cutoff_month = time.strftime(
        "%Y-%m", time.localtime(time.time() - retention_days * 86400)
    )
    doomed = [k for k in shards if k != "undated" and k < cutoff_month]
    for key in doomed:
        (shard_dir / f"{key}.npy").unlink(missing_ok=True)
        del shards[key]
    if doomed:
        gone = set(doomed)
        for sid in [s for s, p in session_progress.items() if p.get("shard") in gone]:
            del session_progress[sid]
    return bool(doomed)


def build_session_embeddings(
    project_path: str,
    index,  # SessionIndex
    engram_storage_dir: str = "~/.claude_engram",
) -> int:
    """
    Build/update conversation chunk embeddings for search.

    v2 store: monthly .npy shards under session_embeddings/ plus one index
    JSON. Appending a session rewrites only its own month's shard instead
    of the whole matrix (the v1 store was an 80MB+ full rewrite at every
    session end), and per-session watermarks make grown JSONLs contribute
    their new tail instead of being skipped as already-seen.

    Optional retention: CLAUDE_ENGRAM_SESSION_RETENTION_DAYS prunes shards
    older than N days (default 0 = keep everything).

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
    idx_path = hash_dir / "session_embeddings_index.json"

    from claude_engram.embed_config import LEGACY_SIGNATURE, embed_signature

    sig = embed_signature()

    try:
        import numpy as np
    except ImportError:
        return 0  # no numpy = no embedding store (keyword search still works)

    # Load the index. A store built by a different embedding model is
    # discarded wholesale: its vectors share no space with the configured
    # model's, so everything rebuilds from scratch in the new space.
    idx_data: Optional[dict] = None
    if idx_path.exists():
        try:
            loaded = json.loads(idx_path.read_text(encoding="utf-8"))
            if loaded.get("model", LEGACY_SIGNATURE) != sig:
                _wipe_embedding_store(hash_dir)
            elif "shards" in loaded:
                idx_data = loaded
            elif "chunks" in loaded:
                idx_data = _migrate_v1_store(hash_dir, loaded, np)
                if idx_data is not None:
                    # Commit immediately: the shards are on disk and the flat
                    # npy is gone, so an index still claiming v1 would make
                    # the next run wipe the store as corrupt.
                    tmp = idx_path.with_suffix(".json.tmp")
                    tmp.write_text(json.dumps(idx_data), encoding="utf-8")
                    tmp.replace(idx_path)
        except Exception:
            _wipe_embedding_store(hash_dir)

    if idx_data is None:
        idx_data = {"version": 2, "model": sig, "shards": {}, "session_progress": {}}

    shards: dict = idx_data.setdefault("shards", {})
    session_progress: dict = idx_data.setdefault("session_progress", {})

    jsonl_dir = resolve_jsonl_dir(project_path)
    if not jsonl_dir:
        return 0

    new_chunks: list[ChunkIndex] = []
    new_texts: list[str] = []
    # session_id -> (new_progress, shard_key) applied only if this run commits
    pending_progress: dict[str, tuple[dict, str]] = {}

    for session_id, session_meta in index.sessions.items():
        expected_main = int(session_meta.get("user_message_count", 0)) + int(
            session_meta.get("assistant_message_count", 0)
        )
        prog = session_progress.get(session_id)
        if prog is not None:
            # Change-based trigger (not >) so index-counter drift can't cause
            # an endless rescan loop; the watermark dedups emission either way.
            if int(prog.get("meta_count", -1)) == expected_main and not _subs_changed(
                jsonl_dir, session_meta, prog
            ):
                continue
        else:
            prog = {}

        chunks, texts, new_prog = _scan_session_chunks(
            jsonl_dir, session_id, session_meta, prog
        )
        new_prog["meta_count"] = expected_main

        shard_key = prog.get("shard") or ""
        if not shard_key:
            first_ts = ""
            if chunks:
                first_ts = chunks[0].timestamp
            shard_key = _month_of(first_ts or session_meta.get("first_timestamp", ""))
        new_prog["shard"] = shard_key

        pending_progress[session_id] = (new_prog, shard_key)
        new_chunks.extend(chunks)
        new_texts.extend(texts)

    shard_dir = hash_dir / "session_embeddings"

    if not new_texts:
        # Nothing to embed, but watermark/size bookkeeping and retention
        # still advance (e.g. growth that produced no searchable chunks).
        pruned = _prune_old_shards(shards, session_progress, shard_dir)
        if pending_progress or pruned:
            for sid, (new_prog, _key) in pending_progress.items():
                session_progress[sid] = new_prog
            tmp = idx_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(idx_data), encoding="utf-8")
            tmp.replace(idx_path)
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

    # Filter out failed embeddings; group by shard
    shard_new_chunks: dict[str, list[ChunkIndex]] = {}
    shard_new_vecs: dict[str, list] = {}
    valid_count = 0
    for chunk, emb in zip(new_chunks, new_embeddings):
        if emb and len(emb) > 0:
            key = pending_progress[chunk.session_id][1]
            shard_new_chunks.setdefault(key, []).append(chunk)
            shard_new_vecs.setdefault(key, []).append(emb)
            valid_count += 1

    if not valid_count:
        return 0

    shard_dir.mkdir(exist_ok=True)

    for key, vecs in shard_new_vecs.items():
        new_matrix = np.array(vecs, dtype=np.float32)
        entry = shards.setdefault(key, {"chunks": []})
        shard_path = shard_dir / f"{key}.npy"

        if shard_path.exists() and entry["chunks"]:
            # Don't use mmap — we're overwriting this file, and Windows
            # throws Errno 22 if you np.save to a mmap'd file
            old = np.load(str(shard_path))
            expected_rows = len(entry["chunks"])
            if len(old.shape) != 2 or old.shape[0] < expected_rows:
                # Shard corrupt beyond the crash-tail case: wipe everything;
                # the next run rebuilds the whole store consistently.
                _wipe_embedding_store(hash_dir)
                return 0
            if old.shape[0] > expected_rows:
                # Crash between shard write and index write last run: the
                # orphan tail rows have no chunks. Drop them; their sessions
                # re-embed because progress was never committed either.
                old = old[:expected_rows]
            if old.shape[1] != new_matrix.shape[1]:
                _wipe_embedding_store(hash_dir)
                return 0
            combined = np.vstack([old, new_matrix])
        else:
            combined = new_matrix

        tmp_stem = shard_dir / f"{key}_tmp"
        np.save(str(tmp_stem), combined)
        (shard_dir / f"{key}_tmp.npy").replace(shard_path)
        entry["chunks"].extend(_chunk_to_dict(c) for c in shard_new_chunks[key])

    # Commit watermarks now that every shard write succeeded
    for sid, (new_prog, _key) in pending_progress.items():
        session_progress[sid] = new_prog

    _prune_old_shards(shards, session_progress, shard_dir)

    tmp = idx_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(idx_data), encoding="utf-8")
    tmp.replace(idx_path)

    return valid_count


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

    # Flatten the store into (chunk, location) pairs. v2 keeps chunks in
    # monthly shards (location = shard key + row); a not-yet-migrated v1
    # store is one flat list backed by a single .npy (location = row).
    chunk_locs: list[tuple[str, int]] = []
    if "shards" in idx_data:
        chunks = []
        for shard_key in sorted(idx_data.get("shards", {})):
            # Whole-shard temporal skip: a "2026-04" shard can't contain
            # rows matching since="2026-05-01" (chunk-level filter still
            # runs for boundary months).
            if since and shard_key != "undated" and shard_key < since[:7]:
                continue
            if until and shard_key != "undated" and shard_key > until[:7]:
                continue
            for row, c in enumerate(idx_data["shards"][shard_key].get("chunks", [])):
                chunks.append(c)
                chunk_locs.append((shard_key, row))
    else:
        chunks = idx_data.get("chunks", [])
        chunk_locs = [("", i) for i in range(len(chunks))]
    if not chunks:
        return []

    # Temporal filtering — filter chunks by date range before scoring
    if since or until:
        filtered_chunks = []
        filtered_locs = []
        for i, chunk in enumerate(chunks):
            ts = chunk.get("timestamp", "")[:10]  # YYYY-MM-DD
            if since and ts < since:
                continue
            if until and ts > until:
                continue
            filtered_chunks.append(chunk)
            filtered_locs.append(chunk_locs[i])
        chunks = filtered_chunks
        chunk_locs = filtered_locs
        if not chunks:
            return []

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

    # Semantic scoring. Skipped when the stored vectors were built by a
    # different embedding model than the configured one (the query embeds in
    # the current space; dotting it against another model's vectors is
    # garbage even when the dims happen to agree). Keyword scoring still
    # works; the miner rebuilds the store on its next run.
    semantic_scores = [0.0] * len(chunks)
    from claude_engram.embed_config import LEGACY_SIGNATURE, embed_signature

    _index_model = idx_data.get("model", LEGACY_SIGNATURE)
    if method in ("semantic", "hybrid") and _index_model == embed_signature():
        try:
            import numpy as np
            from claude_engram.hooks.scorer_server import embed_via_server

            query_emb = embed_via_server(query)
            if query_emb:
                query_arr = np.array(query_emb, dtype=np.float32)
                if "shards" in idx_data:
                    # Gather each surviving chunk's vector from its shard
                    shard_dir = hash_dir / "session_embeddings"
                    by_shard: dict[str, list[tuple[int, int]]] = {}
                    for pos, (key, row) in enumerate(chunk_locs):
                        by_shard.setdefault(key, []).append((pos, row))
                    for key, items in by_shard.items():
                        shard_path = shard_dir / f"{key}.npy"
                        if not shard_path.exists():
                            continue
                        try:
                            m = np.load(str(shard_path), mmap_mode="r")
                        except Exception:
                            continue
                        rows = [r for _, r in items]
                        if len(m.shape) != 2 or max(rows) >= m.shape[0]:
                            continue  # shard out of sync — keyword only
                        sims = np.dot(np.asarray(m[rows]), query_arr)
                        for (pos, _), val in zip(items, sims.tolist()):
                            semantic_scores[pos] = float(val)
                else:
                    emb_path = hash_dir / "session_embeddings.npy"
                    if emb_path.exists():
                        matrix = np.load(str(emb_path), mmap_mode="r")
                        rows = [r for _, r in chunk_locs]
                        if len(rows) < matrix.shape[0]:
                            sims = np.dot(matrix[rows], query_arr)
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
        for chunk in _iter_index_chunks(idx_data):
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
    chunks = list(_iter_index_chunks(idx_data))

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
