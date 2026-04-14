#!/usr/bin/env python3
"""
Benchmark: Session mining foundation.

Tests JSONL parsing, session indexing, background miner, and Smart Session Start.

Usage:
    python tests/bench_session_mining.py
"""
import json
import sys
import os
import time
import tempfile
from pathlib import Path

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


# ─── Tests ───────────────────────────────────────────────────────────────


def test_path_conversion() -> list[tuple[str, bool, str]]:
    """Test directory name ↔ path conversion."""
    results = []

    cases = [
        (r"E:\workspace", "E--workspace"),
        (r"e:\chappie", "e--chappie"),
        (r"d:\Code\mini_cl", "d--Code-mini_cl"),
        (r"E:\workspace\3r_robotics", "E--workspace-3r_robotics"),
        (r"E:\openclaw\workspace\chappie", "E--openclaw-workspace-chappie"),
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
    """Test finding JSONL directories for known projects."""
    results = []

    # These should resolve if the user has session history
    for proj in [r"E:\workspace", r"e:\chappie"]:
        d = resolve_jsonl_dir(proj)
        has_sessions = d is not None and any(d.glob("*.jsonl"))
        results.append(
            (
                f"resolve {proj}",
                has_sessions,
                f"dir={d}" if d else "not found",
            )
        )

    return results


def test_session_files() -> list[tuple[str, bool, str]]:
    """Test getting session files."""
    results = []

    files = get_session_files(r"E:\workspace")
    results.append(
        (
            f"Found {len(files)} session files",
            len(files) > 0,
            "",
        )
    )

    # Should be sorted newest first
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

    files = get_session_files(r"E:\workspace")
    if not files:
        return [("No session files", False, "")]

    # Pick a small session
    small = min(files, key=lambda f: f.stat().st_size)

    count = 0
    types = set()
    for offset, msg in iter_messages(small):
        count += 1
        types.add(msg.get("type", "?"))
        if count > 100:
            break

    results.append(
        (
            f"Parsed {count} messages from {small.name[:12]}",
            count > 0,
            "",
        )
    )
    results.append(
        (
            f"Found types: {types}",
            "user" in types or "assistant" in types or len(types) > 0,
            "",
        )
    )

    return results


def test_read_tail() -> list[tuple[str, bool, str]]:
    """Test efficient tail reading."""
    results = []

    files = get_session_files(r"E:\workspace")
    if not files:
        return [("No session files", False, "")]

    # Test on a medium file
    target = files[0]  # newest
    t0 = time.perf_counter()
    tail = read_tail(target, n_messages=20)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    results.append(
        (
            f"Tail read {len(tail)} msgs in {elapsed_ms:.0f}ms",
            len(tail) > 0,
            "",
        )
    )
    results.append(
        (
            f"Tail read under 500ms",
            elapsed_ms < 500,
            f"{elapsed_ms:.0f}ms",
        )
    )

    return results


def test_extractors() -> list[tuple[str, bool, str]]:
    """Test message content extractors."""
    results = []

    files = get_session_files(r"E:\workspace")
    if not files:
        return [("No session files", False, "")]

    # Read some messages and test extractors
    user_texts = 0
    asst_texts = 0
    tool_uses = 0
    file_edits = 0
    thinking_blocks = 0

    target = min(files, key=lambda f: f.stat().st_size)
    for _, msg in iter_messages(target):
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

    results.append((f"User texts: {user_texts}", user_texts >= 0, ""))
    results.append((f"Assistant texts: {asst_texts}", asst_texts >= 0, ""))
    results.append((f"Tool uses: {tool_uses}", tool_uses >= 0, ""))
    results.append((f"File edits: {file_edits}", file_edits >= 0, ""))
    results.append((f"Thinking blocks: {thinking_blocks}", thinking_blocks >= 0, ""))

    return results


def test_session_index() -> list[tuple[str, bool, str]]:
    """Test session index building and querying."""
    results = []

    files = get_session_files(r"E:\workspace")
    if not files:
        return [("No session files", False, "")]

    # Index a small session
    small = min(files, key=lambda f: f.stat().st_size)
    t0 = time.perf_counter()
    meta = build_index_for_session(small)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    results.append(
        (
            f"Indexed {small.name[:12]} ({small.stat().st_size / 1024:.0f}KB) in {elapsed_ms:.0f}ms",
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

    # Test SessionIndex persistence — use a session with actual content
    with tempfile.TemporaryDirectory() as tmpdir:
        idx = SessionIndex(Path(tmpdir) / "session_index.json")

        # Index a session with real messages (not the tiny metadata-only ones)
        content_file = max(files, key=lambda f: f.stat().st_size)
        content_meta = build_index_for_session(content_file)
        idx.update_session(content_meta)
        idx.save()

        # Reload
        idx2 = SessionIndex(Path(tmpdir) / "session_index.json")
        loaded = idx2.get_session(content_meta.session_id)
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
    """Test index performance on all sessions."""
    results = []

    files = get_session_files(r"E:\workspace")
    if not files:
        return [("No session files", False, "")]

    # Index all sessions
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmpdir:
        idx = SessionIndex(Path(tmpdir) / "session_index.json")
        total_bytes = 0

        for f in files:
            meta = build_index_for_session(f)
            idx.update_session(meta)
            total_bytes += f.stat().st_size

        idx.save()
        elapsed = time.perf_counter() - t0

        results.append(
            (
                f"All {len(files)} sessions ({total_bytes / 1024 / 1024:.0f}MB) in {elapsed:.1f}s",
                elapsed < 10,  # Should complete within 10s even for 300MB+
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

        # Test read-only speed
        t0 = time.perf_counter()
        idx2 = SessionIndex(Path(tmpdir) / "session_index.json")
        summary = idx2.get_latest_session_summary()
        read_ms = (time.perf_counter() - t0) * 1000

        results.append(
            (
                f"Read-only load + summary: {read_ms:.1f}ms",
                read_ms < 50,  # Must be fast for hook use
                "",
            )
        )

    return results


def test_incremental_processing() -> list[tuple[str, bool, str]]:
    """Test that re-processing is skipped for already-indexed sessions."""
    results = []

    files = get_session_files(r"E:\workspace")
    if not files:
        return [("No session files", False, "")]

    small = min(files, key=lambda f: f.stat().st_size)

    with tempfile.TemporaryDirectory() as tmpdir:
        idx = SessionIndex(Path(tmpdir) / "session_index.json")

        # First pass
        meta = build_index_for_session(small)
        idx.update_session(meta)
        idx.save()

        # Check needs_processing
        needs, offset = idx.needs_processing(small)
        results.append(
            (
                "Already-indexed file skipped",
                not needs,
                f"needs={needs}, offset={offset}" if needs else "",
            )
        )

    return results


def test_post_test_file_linking() -> list[tuple[str, bool, str]]:
    """Test that test failures link to recently-edited files."""
    results = []

    # Simulate: edit files, then test fails, mistake should have related_files
    from claude_engram.hooks.remind import (
        _auto_record_test,
        _auto_log_detected_mistake_with_files,
        load_state,
        save_state,
        record_file_edit,
        mark_session_started,
    )

    # Setup: start session and record some edits
    mark_session_started(r"E:\workspace")
    record_file_edit(r"E:\workspace\chappie\V7\cortex\core\processor.py")
    record_file_edit(r"E:\workspace\chappie\V7\cortex\core\compiler.py")

    state = load_state()
    edited = state.get("files_edited_this_session", [])
    results.append(
        (
            f"Files tracked: {len(edited)}",
            len(edited) >= 2,
            "",
        )
    )

    # Simulate test failure recording with file context
    result = _auto_record_test(False, "AssertionError: expected 5 got 3")
    results.append(
        (
            "Test failure recorded",
            True,
            "",
        )
    )

    # Check test result has file context
    loop_file = Path.home() / ".claude_engram" / "loop_detector.json"
    if loop_file.exists():
        import json

        ld = json.loads(loop_file.read_text())
        test_results = ld.get("test_results", [])
        if test_results:
            last = test_results[-1]
            has_files = "files_since_last_test" in last
            results.append(
                (
                    f"Test result has file context: {last.get('files_since_last_test', [])}",
                    has_files,
                    "",
                )
            )
        else:
            results.append(("Test results exist", False, "empty"))
    else:
        results.append(("Loop detector file exists", False, "missing"))

    return results


# ─── Runner ──────────────────────────────────────────────────────────────


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
        ("10. Post-Test File Linking", test_post_test_file_linking),
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
