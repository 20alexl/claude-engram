#!/usr/bin/env python3
"""
Benchmark: Session mining foundation.

Tests JSONL parsing, session indexing, background miner, and Smart Session Start.
Uses synthetic JSONL data — runs on any machine with no real session history needed.

Usage:
    python tests/bench_session_mining.py
"""
import json
import sys
import os
import time
import tempfile
import uuid
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_engram.mining.jsonl_reader import (
    path_to_dir_name,
    dir_name_to_path,
    resolve_jsonl_dir,
    get_session_files,
    iter_messages,
    read_tail,
    extract_user_text,
    extract_assistant_text,
    extract_tool_uses,
    extract_file_edits,
    extract_thinking,
)
from claude_engram.mining.session_index import (
    SessionIndex,
    build_index_for_session,
    get_or_create_index,
)
from claude_engram.mining.background import (
    is_mining_running,
    get_mining_status,
)


# ─── Synthetic JSONL helpers ────────────────────────────────────────────


def _make_session_id():
    return str(uuid.uuid4())


def _ts(offset_min=0):
    """ISO timestamp, optionally offset by minutes."""
    t = time.time() + offset_min * 60
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()


def _user_msg(text, session_id, offset_min=0):
    return json.dumps(
        {
            "type": "user",
            "message": {"role": "user", "content": text},
            "sessionId": session_id,
            "timestamp": _ts(offset_min),
        }
    )


def _assistant_msg(text, session_id, offset_min=0, tool_use=None, thinking=None):
    content = []
    if thinking:
        content.append({"type": "thinking", "thinking": thinking})
    content.append({"type": "text", "text": text})
    if tool_use:
        content.append(
            {
                "type": "tool_use",
                "id": f"tu_{uuid.uuid4().hex[:8]}",
                "name": tool_use["name"],
                "input": tool_use.get("input", {}),
            }
        )
    return json.dumps(
        {
            "type": "assistant",
            "message": {"role": "assistant", "content": content},
            "sessionId": session_id,
            "timestamp": _ts(offset_min),
        }
    )


def _tool_result_msg(content, session_id, is_error=False, offset_min=0):
    return json.dumps(
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "content": content,
                        "is_error": is_error,
                    }
                ],
            },
            "sessionId": session_id,
            "timestamp": _ts(offset_min),
        }
    )


def _write_synthetic_session(tmpdir, session_id=None, n_exchanges=10):
    """Write a synthetic JSONL session file. Returns the file path."""
    session_id = session_id or _make_session_id()
    jsonl_path = Path(tmpdir) / f"{session_id}.jsonl"

    lines = []
    for i in range(n_exchanges):
        lines.append(
            _user_msg(f"User message {i}: please fix the auth module", session_id, i)
        )
        lines.append(
            _assistant_msg(
                f"I'll fix the auth module. Here's the change for step {i}.",
                session_id,
                i,
                tool_use={
                    "name": "Edit",
                    "input": {
                        "file_path": f"/project/src/auth.py",
                        "old_string": f"old_code_{i}",
                        "new_string": f"new_code_{i}",
                    },
                },
                thinking=f"Thinking about step {i}: need to update auth logic",
            )
        )
        lines.append(
            _tool_result_msg(f"File edited successfully", session_id, offset_min=i)
        )

    # Add an error exchange
    lines.append(_user_msg("Run the tests now", session_id, n_exchanges))
    lines.append(
        _assistant_msg(
            "Running tests.",
            session_id,
            n_exchanges,
            tool_use={"name": "Bash", "input": {"command": "pytest tests/"}},
        )
    )
    lines.append(
        _tool_result_msg(
            "TypeError: expected str got int\n  File auth.py line 42",
            session_id,
            is_error=True,
            offset_min=n_exchanges,
        )
    )

    jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return jsonl_path


# ─── Tests ──────────────────────────────────────────────────────────────


def test_path_conversion() -> list[tuple[str, bool, str]]:
    """Test directory name <-> path conversion."""
    results = []

    cases = [
        # Windows-style paths
        (r"C:\repo", "C--repo"),
        (r"e:\projects", "e--projects"),
        (r"d:\Code\mini_cl", "d--Code-mini_cl"),
        (r"C:\repo\service-b", "C--repo-service-b"),
        (r"C:\team\repo\myproject", "C--team-repo-myproject"),
    ]

    for path, expected in cases:
        result = path_to_dir_name(path)
        passed = result == expected
        results.append(
            (
                f"path_to_dir_name({path!r})",
                passed,
                f"got {result!r}" if not passed else "",
            )
        )

    return results


def test_resolve_jsonl_dir() -> list[tuple[str, bool, str]]:
    """Test JSONL directory resolution with synthetic data."""
    results = []

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a fake ~/.claude/projects/ structure
        fake_claude = Path(tmpdir) / ".claude" / "projects"
        fake_proj_dir = fake_claude / "test--project"
        fake_proj_dir.mkdir(parents=True)

        session_id = _make_session_id()
        _write_synthetic_session(str(fake_proj_dir), session_id, n_exchanges=3)

        # resolve_jsonl_dir won't find this (it uses the real ~/.claude),
        # but we can test the path conversion + session file discovery directly
        files = list(fake_proj_dir.glob("*.jsonl"))
        results.append(
            (
                f"Synthetic JSONL created",
                len(files) == 1,
                f"found {len(files)}",
            )
        )

        # Test get_session_files on the fake dir (it takes a project path, not dir)
        # Just verify the file is valid JSONL
        valid = True
        for line in files[0].read_text(encoding="utf-8").strip().split("\n"):
            try:
                json.loads(line)
            except json.JSONDecodeError:
                valid = False
                break
        results.append(
            (
                f"Synthetic JSONL is valid",
                valid,
                "",
            )
        )

    return results


def test_session_files() -> list[tuple[str, bool, str]]:
    """Test getting and sorting session files."""
    results = []

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create multiple sessions with different mtimes
        s1 = _write_synthetic_session(tmpdir, n_exchanges=3)
        time.sleep(0.05)
        s2 = _write_synthetic_session(tmpdir, n_exchanges=5)

        files = sorted(Path(tmpdir).glob("*.jsonl"), key=lambda f: -f.stat().st_mtime)

        results.append(
            (
                f"Found {len(files)} session files",
                len(files) == 2,
                "",
            )
        )

        if len(files) >= 2:
            newest = files[0].stat().st_mtime
            second = files[1].stat().st_mtime
            results.append(
                (
                    "Sorted newest first",
                    newest >= second,
                    "",
                )
            )

    return results


def test_streaming_parser() -> list[tuple[str, bool, str]]:
    """Test streaming JSONL parser."""
    results = []

    with tempfile.TemporaryDirectory() as tmpdir:
        session_file = _write_synthetic_session(tmpdir, n_exchanges=10)

        count = 0
        types = set()
        for offset, msg in iter_messages(session_file):
            count += 1
            types.add(msg.get("type", "?"))

        results.append(
            (
                f"Parsed {count} messages",
                count > 0,
                "",
            )
        )
        results.append(
            (
                f"Found types: {types}",
                "user" in types and "assistant" in types,
                "",
            )
        )
        # 10 exchanges * 3 msgs each + 3 error msgs = 33
        results.append(
            (
                f"Expected ~33 messages, got {count}",
                count == 33,
                "",
            )
        )

    return results


def test_read_tail() -> list[tuple[str, bool, str]]:
    """Test efficient tail reading."""
    results = []

    with tempfile.TemporaryDirectory() as tmpdir:
        session_file = _write_synthetic_session(tmpdir, n_exchanges=50)

        t0 = time.perf_counter()
        tail = read_tail(session_file, n_messages=20)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        results.append(
            (
                f"Tail read {len(tail)} msgs in {elapsed_ms:.0f}ms",
                len(tail) == 20,
                f"got {len(tail)}",
            )
        )
        results.append(
            (
                "Tail read under 500ms",
                elapsed_ms < 500,
                f"{elapsed_ms:.0f}ms",
            )
        )

    return results


def test_extractors() -> list[tuple[str, bool, str]]:
    """Test message content extractors."""
    results = []

    with tempfile.TemporaryDirectory() as tmpdir:
        session_file = _write_synthetic_session(tmpdir, n_exchanges=5)

        user_texts = 0
        asst_texts = 0
        tool_uses = 0
        file_edits = 0
        thinking_blocks = 0

        for _, msg in iter_messages(session_file):
            text = extract_user_text(msg)
            if text:
                user_texts += 1
            texts = extract_assistant_text(msg)
            asst_texts += len(texts)
            tools = extract_tool_uses(msg)
            tool_uses += len(tools)
            edits = extract_file_edits(msg)
            file_edits += len(edits)
            thinks = extract_thinking(msg)
            thinking_blocks += len(thinks)

        results.append((f"User texts: {user_texts}", user_texts > 0, ""))
        results.append((f"Assistant texts: {asst_texts}", asst_texts > 0, ""))
        results.append((f"Tool uses: {tool_uses}", tool_uses > 0, ""))
        results.append((f"File edits: {file_edits}", file_edits > 0, ""))
        results.append((f"Thinking blocks: {thinking_blocks}", thinking_blocks > 0, ""))

    return results


def test_session_index() -> list[tuple[str, bool, str]]:
    """Test session index building and querying."""
    results = []

    with tempfile.TemporaryDirectory() as tmpdir:
        session_file = _write_synthetic_session(tmpdir, n_exchanges=5)

        t0 = time.perf_counter()
        meta = build_index_for_session(session_file)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        results.append(
            (
                f"Indexed session ({session_file.stat().st_size / 1024:.0f}KB) in {elapsed_ms:.0f}ms",
                True,
                "",
            )
        )
        results.append(
            (
                f"Session ID: {meta.session_id[:12]}",
                len(meta.session_id) > 0,
                "",
            )
        )
        results.append(
            (
                f"Messages: {meta.message_count}",
                meta.message_count > 0,
                "",
            )
        )

        # Test persistence
        idx_dir = Path(tmpdir) / "index"
        idx_dir.mkdir()
        idx = SessionIndex(idx_dir / "session_index.json")
        idx.update_session(meta)
        idx.save()

        idx2 = SessionIndex(idx_dir / "session_index.json")
        loaded = idx2.get_session(meta.session_id)
        results.append(
            (
                "Index persists and reloads",
                loaded is not None,
                "",
            )
        )

        summary = idx2.get_latest_session_summary()
        results.append(
            (
                "Latest session summary works",
                summary is not None,
                f"summary={summary}" if summary is None else "",
            )
        )

    return results


def test_index_performance() -> list[tuple[str, bool, str]]:
    """Test index performance on multiple sessions."""
    results = []

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create 20 sessions of varying sizes
        session_files = []
        for i in range(20):
            f = _write_synthetic_session(tmpdir, n_exchanges=5 + i * 3)
            session_files.append(f)

        t0 = time.perf_counter()
        idx_dir = Path(tmpdir) / "index"
        idx_dir.mkdir()
        idx = SessionIndex(idx_dir / "session_index.json")
        total_bytes = 0

        for f in session_files:
            meta = build_index_for_session(f)
            idx.update_session(meta)
            total_bytes += f.stat().st_size

        idx.save()
        elapsed = time.perf_counter() - t0

        results.append(
            (
                f"All {len(session_files)} sessions ({total_bytes / 1024:.0f}KB) in {elapsed:.1f}s",
                elapsed < 10,
                "",
            )
        )
        results.append(
            (
                f"Total messages: {idx.get_total_messages()}",
                idx.get_total_messages() > 0,
                "",
            )
        )

        # Read-only speed
        t0 = time.perf_counter()
        idx2 = SessionIndex(idx_dir / "session_index.json")
        summary = idx2.get_latest_session_summary()
        read_ms = (time.perf_counter() - t0) * 1000

        results.append(
            (
                f"Read-only load + summary: {read_ms:.1f}ms",
                read_ms < 50,
                "",
            )
        )

    return results


def test_incremental_processing() -> list[tuple[str, bool, str]]:
    """Test that re-processing is skipped for already-indexed sessions."""
    results = []

    with tempfile.TemporaryDirectory() as tmpdir:
        session_file = _write_synthetic_session(tmpdir, n_exchanges=5)

        idx_dir = Path(tmpdir) / "index"
        idx_dir.mkdir()
        idx = SessionIndex(idx_dir / "session_index.json")

        # First pass
        meta = build_index_for_session(session_file)
        idx.update_session(meta)
        idx.save()

        # Check needs_processing
        needs, offset = idx.needs_processing(session_file)
        results.append(
            (
                "Already-indexed file skipped",
                not needs,
                f"needs={needs}, offset={offset}" if needs else "",
            )
        )

    return results


def test_incremental_append_merges() -> list[tuple[str, bool, str]]:
    """A grown session re-indexed from its offset must MERGE with the existing
    entry, not replace it with tail-only counts (the PreCompact-then-SessionEnd
    double-mining bug: counts and files_edited silently reset)."""
    results = []
    from claude_engram.mining.session_index import merge_session_meta

    with tempfile.TemporaryDirectory() as tmpdir:
        sid = _make_session_id()
        session_file = _write_synthetic_session(tmpdir, session_id=sid, n_exchanges=5)

        idx_dir = Path(tmpdir) / "index"
        idx_dir.mkdir()
        idx = SessionIndex(idx_dir / "session_index.json")

        # First pass (full)
        meta1 = build_index_for_session(session_file)
        idx.update_session(meta1)
        idx.save()
        full_count = meta1.message_count
        full_files = set(meta1.files_edited)

        # Simulate appended messages: rewrite the SAME session file with extra
        # exchanges so it grows past the stored offset.
        bigger = _write_synthetic_session(tmpdir, session_id=sid, n_exchanges=9)

        needs, offset = idx.needs_processing(bigger)
        results.append(
            (
                f"Grown file needs incremental pass from offset {offset}",
                needs and offset > 0,
                f"needs={needs}, offset={offset}",
            )
        )

        tail = build_index_for_session(bigger, start_offset=offset)
        tail_count = tail.message_count
        existing = idx.get_by_jsonl_file(bigger.name)
        merged = merge_session_meta(existing, tail)
        idx.update_session(merged)
        idx.save()

        entry = idx.get_by_jsonl_file(bigger.name)
        results.append(
            (
                f"Merged count {entry['message_count']} = full {full_count} + tail {tail_count}",
                entry["message_count"] == full_count + tail_count
                and entry["message_count"] > full_count,
                "",
            )
        )
        results.append(
            (
                "Files from the first pass survive the merge",
                full_files.issubset(set(entry["files_edited"])),
                f"lost: {full_files - set(entry['files_edited'])}",
            )
        )
        results.append(
            (
                "Identity fields survive (first_timestamp, session_id)",
                bool(entry["first_timestamp"]) and bool(entry["session_id"]),
                "",
            )
        )

    return results


def test_tool_chunk_extraction() -> list[tuple[str, bool, str]]:
    """Test that tool_use/tool_result pairs produce searchable chunks."""
    results = []

    from claude_engram.mining.search import _extract_tool_chunks

    session_id = _make_session_id()

    # Bash command with output
    assistant = json.loads(
        _assistant_msg(
            "Running tests.",
            session_id,
            tool_use={"name": "Bash", "input": {"command": "pytest tests/ -v"}},
        )
    )
    user_result = json.loads(
        _tool_result_msg(
            "PASSED: 5 tests\nFAILED: 2 tests\ntest_auth.py::test_login FAILED",
            session_id,
        )
    )
    chunks = _extract_tool_chunks(
        assistant, user_result, session_id, "test.jsonl", 1, _ts()
    )
    results.append(
        (
            f"Bash chunk extracted: {len(chunks)}",
            len(chunks) == 1,
            f"got {len(chunks)}" if len(chunks) != 1 else "",
        )
    )
    if chunks:
        preview = chunks[0][0].preview
        results.append(
            (
                "Bash preview has command",
                "pytest" in preview,
                preview[:80],
            )
        )
        results.append(
            (
                "Bash chunk type is 'tool'",
                chunks[0][0].msg_type == "tool",
                "",
            )
        )

    # Bash error
    error_result = json.loads(
        _tool_result_msg(
            "TypeError: expected str got int\n  File auth.py, line 42\n  in validate_token",
            session_id,
            is_error=True,
        )
    )
    chunks = _extract_tool_chunks(
        assistant, error_result, session_id, "test.jsonl", 2, _ts()
    )
    if chunks:
        results.append(
            (
                "Error preview captured",
                "TypeError" in chunks[0][0].preview,
                "",
            )
        )

    # Edit tool
    edit_assistant = json.loads(
        _assistant_msg(
            "Fixing auth.",
            session_id,
            tool_use={
                "name": "Edit",
                "input": {
                    "file_path": "/project/src/auth.py",
                    "old_string": "def validate(token):",
                    "new_string": "def validate(token: str) -> bool:",
                },
            },
        )
    )
    edit_result = json.loads(_tool_result_msg("File edited.", session_id))
    chunks = _extract_tool_chunks(
        edit_assistant, edit_result, session_id, "test.jsonl", 3, _ts()
    )
    results.append(
        (
            f"Edit chunk extracted: {len(chunks)}",
            len(chunks) == 1,
            "",
        )
    )
    if chunks:
        results.append(
            (
                "Edit has file in related_files",
                "auth.py" in chunks[0][0].related_files,
                "",
            )
        )
        results.append(
            (
                "Edit preview has old→new",
                "validate" in chunks[0][0].preview,
                chunks[0][0].preview[:80],
            )
        )

    # Read tool — should be skipped (low search value)
    read_assistant = json.loads(
        _assistant_msg(
            "Reading config.",
            session_id,
            tool_use={"name": "Read", "input": {"file_path": "/project/config.yaml"}},
        )
    )
    read_result = json.loads(_tool_result_msg("key: value", session_id))
    chunks = _extract_tool_chunks(
        read_assistant, read_result, session_id, "test.jsonl", 4, _ts()
    )
    results.append(
        (
            "Read tool skipped (no chunk)",
            len(chunks) == 0,
            f"got {len(chunks)}" if chunks else "",
        )
    )

    # Non-tool message pair should produce nothing
    plain_user = json.loads(_user_msg("Just a question", session_id))
    chunks = _extract_tool_chunks(
        plain_user, plain_user, session_id, "test.jsonl", 5, _ts()
    )
    results.append(
        (
            "Non-tool pair produces no chunks",
            len(chunks) == 0,
            "",
        )
    )

    return results


def test_post_test_file_linking() -> list[tuple[str, bool, str]]:
    """Test that test failures link to recently-edited files."""
    results = []

    from claude_engram.hooks.remind import (
        _auto_record_test,
        load_state,
        record_file_edit,
        mark_session_started,
    )

    # Use generic temp paths
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = str(Path(tmpdir) / "myproject")
        file_a = str(Path(tmpdir) / "myproject" / "src" / "processor.py")
        file_b = str(Path(tmpdir) / "myproject" / "src" / "compiler.py")

        mark_session_started(project_dir)
        record_file_edit(file_a)
        record_file_edit(file_b)

        state = load_state()
        edited = state.get("files_edited_this_session", [])
        results.append(
            (
                f"Files tracked: {len(edited)}",
                len(edited) >= 2,
                "",
            )
        )

        # Simulate test failure
        _auto_record_test(False, "AssertionError: expected 5 got 3")
        results.append(
            (
                "Test failure recorded",
                True,
                "",
            )
        )

        # Check test result has file context (loop data lives in the
        # per-session hook state now, not a shared loop_detector.json)
        test_results = load_state().get("loop", {}).get("test_results", [])
        if test_results:
            last = test_results[-1]
            has_files = "files_since_last_test" in last
            file_names = [
                Path(f).name for f in last.get("files_since_last_test", [])
            ]
            results.append(
                (
                    f"Test result has file context: {file_names}",
                    has_files,
                    "",
                )
            )
        else:
            results.append(("Test results exist", False, "empty"))

    return results


# ─── Runner ─────────────────────────────────────────────────────────────


def _fake_vec(text, dim=8):
    """Deterministic unit vector per text — identical text => cosine 1.0."""
    import hashlib

    h = hashlib.md5(text.encode("utf-8", errors="replace")).digest()
    v = [b / 255.0 + 0.01 for b in h[:dim]]
    n = sum(x * x for x in v) ** 0.5
    return [x / n for x in v]


def test_v2_embedding_store() -> list[tuple[str, bool, str]]:
    """Sharded v2 store: build, watermarked re-run, append growth,
    v1 migration, and retention pruning. Embedding transport is patched to a
    deterministic local function — no scorer server involved."""
    results = []
    try:
        import numpy as np
    except ImportError:
        return [("v2 store (numpy missing)", True, "skipped")]

    from claude_engram.hooks import scorer_server
    from claude_engram.mining import search as search_mod
    from claude_engram.mining.search import build_session_embeddings, search_sessions
    from claude_engram.mining.session_index import (
        SessionIndex,
        build_index_for_session,
        merge_session_meta,
    )
    from claude_engram.embed_config import embed_signature
    from claude_engram.mining.search import _normalize_path

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        storage = tmpdir / "engram"
        jdir = tmpdir / "jsonl"
        jdir.mkdir(parents=True)
        hash_dir = storage / "projects" / "abc12345"
        hash_dir.mkdir(parents=True)
        proj_path = "/proj/v2bench"
        storage.joinpath("manifest.json").write_text(
            json.dumps(
                {"version": 5, "projects": {_normalize_path(proj_path): {"hash": "abc12345"}}}
            )
        )

        old_resolve = search_mod.resolve_jsonl_dir
        old_batch = scorer_server.embed_batch_via_server
        old_single = scorer_server.embed_via_server
        old_env = os.environ.get("CLAUDE_ENGRAM_DIR")
        old_ret = os.environ.get("CLAUDE_ENGRAM_SESSION_RETENTION_DAYS")
        search_mod.resolve_jsonl_dir = lambda p: jdir
        scorer_server.embed_batch_via_server = lambda texts: [
            _fake_vec(t) for t in texts
        ]
        scorer_server.embed_via_server = lambda t: _fake_vec(t)
        os.environ["CLAUDE_ENGRAM_DIR"] = str(storage)
        os.environ.pop("CLAUDE_ENGRAM_SESSION_RETENTION_DAYS", None)
        try:
            # --- initial build ---
            sid = _make_session_id()
            session_file = _write_synthetic_session(str(jdir), sid, n_exchanges=5)
            index = SessionIndex(hash_dir / "session_index.json")
            meta = build_index_for_session(Path(session_file))
            meta.session_id = sid
            index.update_session(meta)
            index.save()

            n1 = build_session_embeddings(proj_path, index, str(storage))
            results.append(("initial build embeds chunks", n1 > 0, f"n={n1}"))

            idx_path = hash_dir / "session_embeddings_index.json"
            idx = json.loads(idx_path.read_text())
            results.append(
                (
                    "index is v2 sharded",
                    idx.get("version") == 2 and "shards" in idx,
                    "",
                )
            )
            shard_files = list((hash_dir / "session_embeddings").glob("*.npy"))
            results.append(
                ("one monthly shard written", len(shard_files) == 1, f"{len(shard_files)}")
            )
            if shard_files:
                key = next(iter(idx["shards"]))
                m = np.load(str(shard_files[0]))
                results.append(
                    (
                        "shard rows == shard chunks",
                        m.shape[0] == len(idx["shards"][key]["chunks"]),
                        f"{m.shape[0]} vs {len(idx['shards'][key]['chunks'])}",
                    )
                )

            # --- unchanged re-run: watermark makes it a no-op ---
            n2 = build_session_embeddings(proj_path, index, str(storage))
            results.append(("unchanged re-run adds nothing", n2 == 0, f"n={n2}"))

            # --- grow the SAME session (same sid => same filename, more
            # exchanges), merge index meta exactly like the production
            # incremental path, then re-embed ---
            existing = dict(index.sessions[sid])
            grown_file = _write_synthetic_session(str(jdir), sid, n_exchanges=9)
            tail = build_index_for_session(
                Path(grown_file), start_offset=existing["processed_offset"]
            )
            tail.session_id = sid
            merged = merge_session_meta(existing, tail)
            index.update_session(merged)
            index.save()

            n3 = build_session_embeddings(proj_path, index, str(storage))
            results.append(
                ("grown session contributes its tail", n3 > 0, f"n={n3}")
            )

            idx = json.loads(idx_path.read_text())
            all_chunks = [
                c for s in idx["shards"].values() for c in s["chunks"]
            ]
            keys = [
                (c["jsonl_file"], c["msg_offset"], c["msg_type"], c["preview"])
                for c in all_chunks
            ]
            results.append(
                (
                    "no duplicate chunks after growth",
                    len(keys) == len(set(keys)),
                    f"{len(keys)} chunks, {len(set(keys))} unique",
                )
            )
            max_off = max(c["msg_offset"] for c in all_chunks)
            results.append(
                (
                    "tail offsets reach the grown end",
                    max_off > int(existing["user_message_count"])
                    + int(existing["assistant_message_count"]) - 2,
                    f"max_off={max_off}",
                )
            )

            # shard rows still aligned after append
            key = next(iter(idx["shards"]))
            m = np.load(str((hash_dir / "session_embeddings" / f"{key}.npy")))
            results.append(
                (
                    "shard rows realigned after append",
                    m.shape[0] == len(idx["shards"][key]["chunks"]),
                    f"{m.shape[0]} vs {len(idx['shards'][key]['chunks'])}",
                )
            )

            # --- search across the sharded store ---
            hits = search_sessions(
                proj_path, "auth module", limit=5, method="keyword",
                engram_storage_dir=str(storage),
            )
            results.append(("keyword search finds sharded chunks", len(hits) > 0, ""))
            if all_chunks:
                target = all_chunks[0]["preview"]
                hits = search_sessions(
                    proj_path, target[:80], limit=3, method="semantic",
                    engram_storage_dir=str(storage),
                )
                results.append(
                    ("semantic search gathers from shards", len(hits) > 0, "")
                )

            # --- v1 migration (second project) ---
            hash_dir2 = storage / "projects" / "def67890"
            hash_dir2.mkdir(parents=True)
            proj2 = "/proj/v1legacy"
            manifest = json.loads(storage.joinpath("manifest.json").read_text())
            manifest["projects"][_normalize_path(proj2)] = {"hash": "def67890"}
            storage.joinpath("manifest.json").write_text(json.dumps(manifest))

            sid_old = _make_session_id()
            v1_chunks = [
                {
                    "session_id": sid_old,
                    "jsonl_file": "old.jsonl",
                    "msg_offset": i + 1,
                    "timestamp": f"2026-01-0{i + 1}T10:00:00Z",
                    "msg_type": "user" if i % 2 == 0 else "assistant",
                    "preview": f"legacy chunk {i} about quantum flux capacitors",
                    "related_files": [],
                }
                for i in range(4)
            ]
            v1_vecs = np.array(
                [_fake_vec(c["preview"]) for c in v1_chunks], dtype=np.float32
            )
            np.save(str(hash_dir2 / "session_embeddings"), v1_vecs)  # -> .npy
            (hash_dir2 / "session_embeddings_index.json").write_text(
                json.dumps({"chunks": v1_chunks, "model": embed_signature()})
            )

            index2 = SessionIndex(hash_dir2 / "session_index.json")
            n4 = build_session_embeddings(proj2, index2, str(storage))
            idx2 = json.loads(
                (hash_dir2 / "session_embeddings_index.json").read_text()
            )
            results.append(
                (
                    "v1 store migrated to shards",
                    idx2.get("version") == 2 and "2026-01" in idx2.get("shards", {}),
                    f"shards={list(idx2.get('shards', {}))}",
                )
            )
            results.append(
                (
                    "flat npy removed after migration",
                    not (hash_dir2 / "session_embeddings.npy").exists(),
                    "",
                )
            )
            mig = np.load(str(hash_dir2 / "session_embeddings" / "2026-01.npy"))
            results.append(
                (
                    "migrated vectors preserved",
                    mig.shape == v1_vecs.shape
                    and bool(np.allclose(mig, v1_vecs)),
                    f"{mig.shape}",
                )
            )
            hits = search_sessions(
                proj2, "quantum flux capacitors", limit=3, method="hybrid",
                engram_storage_dir=str(storage),
            )
            results.append(
                ("migrated store still searchable", len(hits) > 0, f"{len(hits)} hits")
            )

            # --- retention pruning ---
            os.environ["CLAUDE_ENGRAM_SESSION_RETENTION_DAYS"] = "30"
            build_session_embeddings(proj2, index2, str(storage))
            idx2 = json.loads(
                (hash_dir2 / "session_embeddings_index.json").read_text()
            )
            pruned = "2026-01" not in idx2.get("shards", {}) and not (
                hash_dir2 / "session_embeddings" / "2026-01.npy"
            ).exists()
            results.append(("retention prunes old shards", pruned, ""))
        finally:
            search_mod.resolve_jsonl_dir = old_resolve
            scorer_server.embed_batch_via_server = old_batch
            scorer_server.embed_via_server = old_single
            if old_env is None:
                os.environ.pop("CLAUDE_ENGRAM_DIR", None)
            else:
                os.environ["CLAUDE_ENGRAM_DIR"] = old_env
            if old_ret is None:
                os.environ.pop("CLAUDE_ENGRAM_SESSION_RETENTION_DAYS", None)
            else:
                os.environ["CLAUDE_ENGRAM_SESSION_RETENTION_DAYS"] = old_ret

    return results


def test_schema_canary() -> list[tuple[str, bool, str]]:
    """The miner's JSONL-format canary: warns on recognition collapse,
    stays quiet when healthy or under-informed."""
    results = []
    from types import SimpleNamespace

    from claude_engram.mining.background import _schema_canary

    def _sessions(specs):
        # specs: list of (lines, known, ts)
        return {
            f"s{i}": {
                "line_count": lines,
                "known_type_count": known,
                "last_timestamp": ts,
            }
            for i, (lines, known, ts) in enumerate(specs)
        }

    healthy = SimpleNamespace(
        sessions=_sessions(
            [(200, 196, f"2026-06-0{i + 1}T10:00:00Z") for i in range(8)]
        )
    )
    results.append(("healthy history stays quiet", _schema_canary(healthy) == "", ""))

    collapsed = SimpleNamespace(
        sessions=_sessions(
            [(200, 196, f"2026-06-0{i + 1}T10:00:00Z") for i in range(6)]
            + [(200, 30, f"2026-06-2{i}T10:00:00Z") for i in range(3)]
        )
    )
    warn = _schema_canary(collapsed)
    results.append(
        ("recognition collapse warns", bool(warn), warn[:60] if warn else "no warning")
    )

    tiny_recent = SimpleNamespace(
        sessions=_sessions(
            [(200, 196, f"2026-06-0{i + 1}T10:00:00Z") for i in range(6)]
            + [(10, 1, f"2026-06-2{i}T10:00:00Z") for i in range(3)]
        )
    )
    results.append(
        ("tiny sessions don't trigger", _schema_canary(tiny_recent) == "", "")
    )

    sparse = SimpleNamespace(
        sessions=_sessions([(200, 30, "2026-06-01T10:00:00Z")] * 3)
    )
    results.append(("too little data stays quiet", _schema_canary(sparse) == "", ""))

    return results


def main():
    print("=" * 70)
    print("BENCHMARK: Session Mining Foundation")
    print("=" * 70)

    total_pass = 0
    total_fail = 0

    test_suites = [
        ("1. Path Conversion", test_path_conversion),
        ("2. Resolve JSONL Dir", test_resolve_jsonl_dir),
        ("3. Session Files", test_session_files),
        ("4. Streaming Parser", test_streaming_parser),
        ("5. Read Tail", test_read_tail),
        ("6. Content Extractors", test_extractors),
        ("7. Session Index", test_session_index),
        ("8. Index Performance", test_index_performance),
        ("9. Incremental Processing", test_incremental_processing),
        ("9b. Incremental Append Merges", test_incremental_append_merges),
        ("10. Tool Chunk Extraction", test_tool_chunk_extraction),
        ("11. Post-Test File Linking", test_post_test_file_linking),
        ("12. Sharded v2 Embedding Store", test_v2_embedding_store),
        ("13. Schema Canary", test_schema_canary),
    ]

    for suite_name, test_fn in test_suites:
        print(f"\n--- {suite_name} ---")
        try:
            results = test_fn()
            for desc, passed, detail in results:
                status = "PASS" if passed else "FAIL"
                if passed:
                    total_pass += 1
                else:
                    total_fail += 1
                line = f"  [{status}] {desc}"
                if detail:
                    line += f"  ({detail})"
                print(line)
        except Exception as e:
            total_fail += 1
            print(f"  [ERROR] {suite_name}: {e}")
            import traceback

            traceback.print_exc()

    print(f"\n{'=' * 70}")
    print(
        f"TOTAL: {total_pass} passed, {total_fail} failed "
        f"({total_pass}/{total_pass + total_fail})"
    )
    print(f"{'=' * 70}")

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
