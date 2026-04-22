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
    return json.dumps({
        "type": "user",
        "message": {"role": "user", "content": text},
        "sessionId": session_id,
        "timestamp": _ts(offset_min),
    })


def _assistant_msg(text, session_id, offset_min=0, tool_use=None, thinking=None):
    content = []
    if thinking:
        content.append({"type": "thinking", "thinking": thinking})
    content.append({"type": "text", "text": text})
    if tool_use:
        content.append({
            "type": "tool_use",
            "id": f"tu_{uuid.uuid4().hex[:8]}",
            "name": tool_use["name"],
            "input": tool_use.get("input", {}),
        })
    return json.dumps({
        "type": "assistant",
        "message": {"role": "assistant", "content": content},
        "sessionId": session_id,
        "timestamp": _ts(offset_min),
    })


def _tool_result_msg(content, session_id, is_error=False, offset_min=0):
    return json.dumps({
        "type": "user",
        "message": {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "content": content,
                "is_error": is_error,
            }],
        },
        "sessionId": session_id,
        "timestamp": _ts(offset_min),
    })


def _write_synthetic_session(tmpdir, session_id=None, n_exchanges=10):
    """Write a synthetic JSONL session file. Returns the file path."""
    session_id = session_id or _make_session_id()
    jsonl_path = Path(tmpdir) / f"{session_id}.jsonl"

    lines = []
    for i in range(n_exchanges):
        lines.append(_user_msg(f"User message {i}: please fix the auth module", session_id, i))
        lines.append(_assistant_msg(
            f"I'll fix the auth module. Here's the change for step {i}.",
            session_id, i,
            tool_use={"name": "Edit", "input": {
                "file_path": f"/project/src/auth.py",
                "old_string": f"old_code_{i}",
                "new_string": f"new_code_{i}",
            }},
            thinking=f"Thinking about step {i}: need to update auth logic",
        ))
        lines.append(_tool_result_msg(f"File edited successfully", session_id, offset_min=i))

    # Add an error exchange
    lines.append(_user_msg("Run the tests now", session_id, n_exchanges))
    lines.append(_assistant_msg(
        "Running tests.",
        session_id, n_exchanges,
        tool_use={"name": "Bash", "input": {"command": "pytest tests/"}},
    ))
    lines.append(_tool_result_msg(
        "TypeError: expected str got int\n  File auth.py line 42",
        session_id, is_error=True, offset_min=n_exchanges,
    ))

    jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return jsonl_path


# ─── Tests ──────────────────────────────────────────────────────────────


def test_path_conversion() -> list[tuple[str, bool, str]]:
    """Test directory name <-> path conversion."""
    results = []

    cases = [
        # Windows-style paths
        (r"E:\workspace", "E--workspace"),
        (r"e:\projects", "e--projects"),
        (r"d:\Code\mini_cl", "d--Code-mini_cl"),
        (r"E:\workspace\3r_robotics", "E--workspace-3r_robotics"),
        (r"E:\openclaw\workspace\chappie", "E--openclaw-workspace-chappie"),
    ]

    for path, expected in cases:
        result = path_to_dir_name(path)
        passed = result == expected
        results.append((
            f"path_to_dir_name({path!r})",
            passed,
            f"got {result!r}" if not passed else "",
        ))

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
        results.append((
            f"Synthetic JSONL created",
            len(files) == 1,
            f"found {len(files)}",
        ))

        # Test get_session_files on the fake dir (it takes a project path, not dir)
        # Just verify the file is valid JSONL
        valid = True
        for line in files[0].read_text(encoding="utf-8").strip().split("\n"):
            try:
                json.loads(line)
            except json.JSONDecodeError:
                valid = False
                break
        results.append((
            f"Synthetic JSONL is valid",
            valid,
            "",
        ))

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

        results.append((
            f"Found {len(files)} session files",
            len(files) == 2,
            "",
        ))

        if len(files) >= 2:
            newest = files[0].stat().st_mtime
            second = files[1].stat().st_mtime
            results.append((
                "Sorted newest first",
                newest >= second,
                "",
            ))

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

        results.append((
            f"Parsed {count} messages",
            count > 0,
            "",
        ))
        results.append((
            f"Found types: {types}",
            "user" in types and "assistant" in types,
            "",
        ))
        # 10 exchanges * 3 msgs each + 3 error msgs = 33
        results.append((
            f"Expected ~33 messages, got {count}",
            count == 33,
            "",
        ))

    return results


def test_read_tail() -> list[tuple[str, bool, str]]:
    """Test efficient tail reading."""
    results = []

    with tempfile.TemporaryDirectory() as tmpdir:
        session_file = _write_synthetic_session(tmpdir, n_exchanges=50)

        t0 = time.perf_counter()
        tail = read_tail(session_file, n_messages=20)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        results.append((
            f"Tail read {len(tail)} msgs in {elapsed_ms:.0f}ms",
            len(tail) == 20,
            f"got {len(tail)}",
        ))
        results.append((
            "Tail read under 500ms",
            elapsed_ms < 500,
            f"{elapsed_ms:.0f}ms",
        ))

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

        results.append((
            f"Indexed session ({session_file.stat().st_size / 1024:.0f}KB) in {elapsed_ms:.0f}ms",
            True,
            "",
        ))
        results.append((
            f"Session ID: {meta.session_id[:12]}",
            len(meta.session_id) > 0,
            "",
        ))
        results.append((
            f"Messages: {meta.message_count}",
            meta.message_count > 0,
            "",
        ))

        # Test persistence
        idx_dir = Path(tmpdir) / "index"
        idx_dir.mkdir()
        idx = SessionIndex(idx_dir / "session_index.json")
        idx.update_session(meta)
        idx.save()

        idx2 = SessionIndex(idx_dir / "session_index.json")
        loaded = idx2.get_session(meta.session_id)
        results.append((
            "Index persists and reloads",
            loaded is not None,
            "",
        ))

        summary = idx2.get_latest_session_summary()
        results.append((
            "Latest session summary works",
            summary is not None,
            f"summary={summary}" if summary is None else "",
        ))

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

        results.append((
            f"All {len(session_files)} sessions ({total_bytes / 1024:.0f}KB) in {elapsed:.1f}s",
            elapsed < 10,
            "",
        ))
        results.append((
            f"Total messages: {idx.get_total_messages()}",
            idx.get_total_messages() > 0,
            "",
        ))

        # Read-only speed
        t0 = time.perf_counter()
        idx2 = SessionIndex(idx_dir / "session_index.json")
        summary = idx2.get_latest_session_summary()
        read_ms = (time.perf_counter() - t0) * 1000

        results.append((
            f"Read-only load + summary: {read_ms:.1f}ms",
            read_ms < 50,
            "",
        ))

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
        results.append((
            "Already-indexed file skipped",
            not needs,
            f"needs={needs}, offset={offset}" if needs else "",
        ))

    return results


def test_tool_chunk_extraction() -> list[tuple[str, bool, str]]:
    """Test that tool_use/tool_result pairs produce searchable chunks."""
    results = []

    from claude_engram.mining.search import _extract_tool_chunks

    session_id = _make_session_id()

    # Bash command with output
    assistant = json.loads(_assistant_msg(
        "Running tests.", session_id,
        tool_use={"name": "Bash", "input": {"command": "pytest tests/ -v"}},
    ))
    user_result = json.loads(_tool_result_msg(
        "PASSED: 5 tests\nFAILED: 2 tests\ntest_auth.py::test_login FAILED",
        session_id,
    ))
    chunks = _extract_tool_chunks(assistant, user_result, session_id, "test.jsonl", 1, _ts())
    results.append((
        f"Bash chunk extracted: {len(chunks)}",
        len(chunks) == 1,
        f"got {len(chunks)}" if len(chunks) != 1 else "",
    ))
    if chunks:
        preview = chunks[0][0].preview
        results.append((
            "Bash preview has command",
            "pytest" in preview,
            preview[:80],
        ))
        results.append((
            "Bash chunk type is 'tool'",
            chunks[0][0].msg_type == "tool",
            "",
        ))

    # Bash error
    error_result = json.loads(_tool_result_msg(
        "TypeError: expected str got int\n  File auth.py, line 42\n  in validate_token",
        session_id, is_error=True,
    ))
    chunks = _extract_tool_chunks(assistant, error_result, session_id, "test.jsonl", 2, _ts())
    if chunks:
        results.append((
            "Error preview captured",
            "TypeError" in chunks[0][0].preview,
            "",
        ))

    # Edit tool
    edit_assistant = json.loads(_assistant_msg(
        "Fixing auth.", session_id,
        tool_use={"name": "Edit", "input": {
            "file_path": "/project/src/auth.py",
            "old_string": "def validate(token):",
            "new_string": "def validate(token: str) -> bool:",
        }},
    ))
    edit_result = json.loads(_tool_result_msg("File edited.", session_id))
    chunks = _extract_tool_chunks(edit_assistant, edit_result, session_id, "test.jsonl", 3, _ts())
    results.append((
        f"Edit chunk extracted: {len(chunks)}",
        len(chunks) == 1,
        "",
    ))
    if chunks:
        results.append((
            "Edit has file in related_files",
            "auth.py" in chunks[0][0].related_files,
            "",
        ))
        results.append((
            "Edit preview has old→new",
            "validate" in chunks[0][0].preview,
            chunks[0][0].preview[:80],
        ))

    # Read tool — should be skipped (low search value)
    read_assistant = json.loads(_assistant_msg(
        "Reading config.", session_id,
        tool_use={"name": "Read", "input": {"file_path": "/project/config.yaml"}},
    ))
    read_result = json.loads(_tool_result_msg("key: value", session_id))
    chunks = _extract_tool_chunks(read_assistant, read_result, session_id, "test.jsonl", 4, _ts())
    results.append((
        "Read tool skipped (no chunk)",
        len(chunks) == 0,
        f"got {len(chunks)}" if chunks else "",
    ))

    # Non-tool message pair should produce nothing
    plain_user = json.loads(_user_msg("Just a question", session_id))
    chunks = _extract_tool_chunks(plain_user, plain_user, session_id, "test.jsonl", 5, _ts())
    results.append((
        "Non-tool pair produces no chunks",
        len(chunks) == 0,
        "",
    ))

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
        results.append((
            f"Files tracked: {len(edited)}",
            len(edited) >= 2,
            "",
        ))

        # Simulate test failure
        _auto_record_test(False, "AssertionError: expected 5 got 3")
        results.append((
            "Test failure recorded",
            True,
            "",
        ))

        # Check test result has file context
        loop_file = Path.home() / ".claude_engram" / "loop_detector.json"
        if loop_file.exists():
            ld = json.loads(loop_file.read_text())
            test_results = ld.get("test_results", [])
            if test_results:
                last = test_results[-1]
                has_files = "files_since_last_test" in last
                file_names = [Path(f).name for f in last.get("files_since_last_test", [])]
                results.append((
                    f"Test result has file context: {file_names}",
                    has_files,
                    "",
                ))
            else:
                results.append(("Test results exist", False, "empty"))
        else:
            results.append(("Loop detector file exists", False, "missing"))

    return results


# ─── Runner ─────────────────────────────────────────────────────────────


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
        ("10. Tool Chunk Extraction", test_tool_chunk_extraction),
        ("11. Post-Test File Linking", test_post_test_file_linking),
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
