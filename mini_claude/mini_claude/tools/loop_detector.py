"""
Loop Detector - Detect when Claude is stuck in an edit loop

The problem: I (Claude) sometimes get stuck in "death spirals" where I keep
trying the same fix over and over, or keep editing the same file without
making progress. Users call this the "Ralph Wiggum loop".

The solution: Track edits and detect patterns that indicate I'm stuck:
- Same file edited 3+ times without tests passing
- Same error appearing repeatedly
- Oscillating between two approaches
"""

import time
import json
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict
from pathlib import Path
from ..schema import MiniClaudeResponse, WorkLog


@dataclass
class EditEvent:
    """A single edit event."""
    file_path: str
    timestamp: float
    description: str
    success: Optional[bool] = None  # Did tests pass after this edit?


@dataclass
class LoopPattern:
    """A detected loop pattern."""
    pattern_type: str  # "repeated_edit", "oscillation", "test_failure_loop"
    severity: str  # "warning", "critical"
    message: str
    file_path: Optional[str] = None
    count: int = 0
    suggestion: str = ""


class LoopDetector:
    """
    Detects when Claude is stuck in an unproductive edit loop.

    Tracks:
    - How many times each file has been edited
    - Whether edits are making progress (tests passing)
    - Patterns that indicate being stuck

    Raises warnings when loops are detected.
    """

    def __init__(
        self,
        max_edits_per_file: int = 3,
        loop_window_seconds: int = 300,  # 5 minutes
        oscillation_threshold: int = 4,
    ):
        self.max_edits_per_file = max_edits_per_file
        self.loop_window_seconds = loop_window_seconds
        self.oscillation_threshold = oscillation_threshold

        self._edits: list[EditEvent] = []
        self._test_results: list[tuple[float, bool]] = []  # (timestamp, passed)
        self._errors: list[tuple[float, str]] = []  # (timestamp, error_message)
        self._file_edit_counts: dict[str, int] = defaultdict(int)

        # Persistence for hooks to read
        self._state_file = Path.home() / ".mini_claude" / "loop_detector.json"
        self._state_file.parent.mkdir(parents=True, exist_ok=True)

    def _persist_state(self):
        """Save state to disk for hooks to read."""
        state = {
            "edit_counts": dict(self._file_edit_counts),
            "total_edits": len(self._edits),
            "recent_edits": [
                {"file": e.file_path, "time": e.timestamp, "success": e.success}
                for e in self._edits[-10:]
            ],
            "updated": time.time(),
        }
        try:
            self._state_file.write_text(json.dumps(state, indent=2))
        except Exception:
            pass  # Non-critical

    def reset(self):
        """Reset tracking for a new task."""
        self._edits = []
        self._test_results = []
        self._errors = []
        self._file_edit_counts = defaultdict(int)
        self._persist_state()

    def record_edit(
        self,
        file_path: str,
        description: str = "",
    ) -> MiniClaudeResponse:
        """
        Record that a file was edited.

        Returns warning if a loop is detected.
        """
        work_log = WorkLog()
        work_log.what_i_tried.append("recording edit")

        now = time.time()

        self._edits.append(EditEvent(
            file_path=file_path,
            timestamp=now,
            description=description,
        ))
        self._file_edit_counts[file_path] += 1
        self._persist_state()  # Save for hooks to read

        # Check for loops
        patterns = self._detect_loops()

        if patterns:
            critical = [p for p in patterns if p.severity == "critical"]
            warnings = [p for p in patterns if p.severity == "warning"]

            work_log.what_worked.append(f"detected {len(patterns)} loop patterns")

            warning_messages = []
            for pattern in patterns:
                prefix = "CRITICAL:" if pattern.severity == "critical" else "WARNING:"
                warning_messages.append(f"{prefix} {pattern.message}")
                if pattern.suggestion:
                    warning_messages.append(f"   → {pattern.suggestion}")

            return MiniClaudeResponse(
                status="warning" if critical else "success",
                confidence="high" if critical else "medium",
                reasoning=f"Detected {len(patterns)} potential loop patterns",
                work_log=work_log,
                data={
                    "patterns_detected": [
                        {
                            "type": p.pattern_type,
                            "severity": p.severity,
                            "message": p.message,
                            "file": p.file_path,
                            "count": p.count,
                        }
                        for p in patterns
                    ],
                    "file_edit_counts": dict(self._file_edit_counts),
                },
                warnings=warning_messages,
                suggestions=[
                    "STOP and reconsider your approach",
                    "Try a completely different strategy",
                    "Ask the user for guidance",
                ] if critical else [
                    "Consider if you're making progress",
                    "Maybe try a different approach",
                ],
            )

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning=f"Edit recorded. File '{file_path}' edited {self._file_edit_counts[file_path]} times",
            work_log=work_log,
            data={
                "file_edit_counts": dict(self._file_edit_counts),
                "total_edits": len(self._edits),
            },
        )

    def record_test_result(self, passed: bool, error_message: str = ""):
        """Record the result of running tests."""
        now = time.time()
        self._test_results.append((now, passed))

        if not passed and error_message:
            self._errors.append((now, error_message))

        # Update last edit with test result
        if self._edits:
            self._edits[-1].success = passed

    def record_error(self, error_message: str):
        """Record an error that occurred."""
        self._errors.append((time.time(), error_message))

    def check_before_edit(self, file_path: str) -> MiniClaudeResponse:
        """
        Check if editing this file might put us in a loop.

        Call this BEFORE making an edit to get a warning.
        """
        work_log = WorkLog()
        work_log.what_i_tried.append(f"checking loop risk for {file_path}")

        edit_count = self._file_edit_counts.get(file_path, 0)
        recent_edits = self._get_recent_edits(file_path)

        warnings = []
        risk_level = "low"

        if edit_count >= self.max_edits_per_file:
            risk_level = "high"
            warnings.append(f"Already edited '{file_path}' {edit_count} times!")
            warnings.append("   → Consider a different approach")

        elif edit_count >= self.max_edits_per_file - 1:
            risk_level = "medium"
            warnings.append(f"About to edit '{file_path}' for the {edit_count + 1}th time")
            warnings.append("   → Make sure this edit is different from previous attempts")

        # Check recent test failures after edits to this file
        file_edits_with_failures = [
            e for e in self._edits
            if e.file_path == file_path and e.success is False
        ]

        if len(file_edits_with_failures) >= 2:
            risk_level = "high"
            warnings.append(f"Previous {len(file_edits_with_failures)} edits to this file failed tests")
            warnings.append("   → The issue might be elsewhere")

        work_log.what_worked.append(f"risk level: {risk_level}")

        return MiniClaudeResponse(
            status="warning" if risk_level == "high" else "success",
            confidence="high",
            reasoning=f"Loop risk for '{file_path}': {risk_level}",
            work_log=work_log,
            data={
                "file_path": file_path,
                "edit_count": edit_count,
                "risk_level": risk_level,
                "recent_edits": [
                    {"time": e.timestamp, "description": e.description, "success": e.success}
                    for e in recent_edits
                ],
            },
            warnings=warnings,
            suggestions=[
                "Try fixing a different file",
                "Re-read the error message carefully",
                "Check if the root cause is elsewhere",
            ] if risk_level == "high" else [],
        )

    def get_status(self) -> MiniClaudeResponse:
        """Get current loop detection status."""
        work_log = WorkLog()
        work_log.what_i_tried.append("getting loop status")

        patterns = self._detect_loops()

        # Files edited most
        top_files = sorted(
            self._file_edit_counts.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:5]

        # Recent test pass rate
        recent_tests = [t for t in self._test_results if time.time() - t[0] < self.loop_window_seconds]
        if recent_tests:
            pass_rate = sum(1 for _, passed in recent_tests if passed) / len(recent_tests)
        else:
            pass_rate = None

        warnings = []
        if patterns:
            for p in patterns:
                warnings.append(f"{p.severity.upper()}: {p.message}")

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning=f"Tracking {len(self._edits)} edits across {len(self._file_edit_counts)} files",
            work_log=work_log,
            data={
                "total_edits": len(self._edits),
                "files_edited": len(self._file_edit_counts),
                "top_edited_files": dict(top_files),
                "test_pass_rate": pass_rate,
                "patterns_detected": len(patterns),
            },
            warnings=warnings,
        )

    def _detect_loops(self) -> list[LoopPattern]:
        """Detect loop patterns in recent activity."""
        patterns = []
        now = time.time()

        # Pattern 1: Same file edited too many times
        for file_path, count in self._file_edit_counts.items():
            if count >= self.max_edits_per_file:
                severity = "critical" if count >= self.max_edits_per_file + 2 else "warning"
                patterns.append(LoopPattern(
                    pattern_type="repeated_edit",
                    severity=severity,
                    message=f"File '{file_path}' edited {count} times",
                    file_path=file_path,
                    count=count,
                    suggestion="Try a completely different approach or fix a different file",
                ))

        # Pattern 2: Tests keep failing after edits
        recent_tests = [
            (t, passed) for t, passed in self._test_results
            if now - t < self.loop_window_seconds
        ]
        recent_failures = [t for t, passed in recent_tests if not passed]

        if len(recent_failures) >= 3 and len(recent_tests) >= 3:
            fail_rate = len(recent_failures) / len(recent_tests)
            if fail_rate >= 0.7:
                patterns.append(LoopPattern(
                    pattern_type="test_failure_loop",
                    severity="critical",
                    message=f"Tests failed {len(recent_failures)}/{len(recent_tests)} times recently",
                    count=len(recent_failures),
                    suggestion="STOP. Re-read the error. The bug might be elsewhere.",
                ))

        # Pattern 3: Same error repeating
        recent_errors = [
            (t, msg) for t, msg in self._errors
            if now - t < self.loop_window_seconds
        ]

        if len(recent_errors) >= 2:
            # Check for similar errors
            error_groups = self._group_similar_errors(recent_errors)
            for error_pattern, count in error_groups.items():
                if count >= 2:
                    patterns.append(LoopPattern(
                        pattern_type="repeated_error",
                        severity="warning" if count < 3 else "critical",
                        message=f"Same error appeared {count} times: {error_pattern[:50]}...",
                        count=count,
                        suggestion="Your fix isn't working. Try something different.",
                    ))

        # Pattern 4: Oscillation (editing same 2-3 files back and forth)
        if len(self._edits) >= self.oscillation_threshold:
            recent_files = [e.file_path for e in self._edits[-self.oscillation_threshold:]]
            unique_files = set(recent_files)

            if len(unique_files) <= 2 and len(recent_files) >= 4:
                patterns.append(LoopPattern(
                    pattern_type="oscillation",
                    severity="warning",
                    message=f"Oscillating between {len(unique_files)} files: {', '.join(unique_files)}",
                    count=len(recent_files),
                    suggestion="You might be fixing symptoms, not the root cause",
                ))

        return patterns

    def _get_recent_edits(self, file_path: str) -> list[EditEvent]:
        """Get recent edits to a specific file."""
        now = time.time()
        return [
            e for e in self._edits
            if e.file_path == file_path and now - e.timestamp < self.loop_window_seconds
        ]

    def _group_similar_errors(
        self,
        errors: list[tuple[float, str]],
    ) -> dict[str, int]:
        """Group similar error messages and count occurrences."""
        groups: dict[str, int] = defaultdict(int)

        for _, msg in errors:
            # Normalize error message (remove line numbers, specific values)
            normalized = msg.lower()
            # Remove numbers that might be line numbers or counts
            normalized = ' '.join(
                word for word in normalized.split()
                if not word.isdigit()
            )
            # Truncate for grouping
            normalized = normalized[:100]
            groups[normalized] += 1

        return dict(groups)
