"""
Thinker - deterministic code audit engine.

Backs the audit_batch and find_similar_issues tools with pure regex/AST
pattern analysis: no LLM, no network. (The old web-research / compare /
challenge / explore methods were removed with the `think` tool; the LLM
audit commentary was cut when usage data showed zero recorded calls.)
"""

import json
from typing import Optional
from pathlib import Path

from ..schema import MiniClaudeResponse, WorkLog


def _is_inside_string_literal(line: str, match_start: int) -> bool:
    """
    Check if a match position is inside a string literal.

    This detects:
    - Single-quoted strings: 'text'
    - Double-quoted strings: "text"
    - Raw strings: r"text" or r'text'
    - Triple-quoted strings (basic detection)

    Args:
        line: The line of code
        match_start: The position where the match starts

    Returns:
        True if the match is inside a string literal
    """
    # Track whether we're inside a string
    in_single = False
    in_double = False
    i = 0

    while i < match_start and i < len(line):
        char = line[i]

        # Handle escape sequences
        if char == "\\" and i + 1 < len(line):
            i += 2  # Skip escaped character
            continue

        # Handle triple quotes (simplified - just check if we're starting one)
        if i + 2 < len(line):
            triple = line[i : i + 3]
            if triple == '"""' and not in_single:
                in_double = not in_double
                i += 3
                continue
            elif triple == "'''" and not in_double:
                in_single = not in_single
                i += 3
                continue

        # Handle single quotes (only if not in double quote)
        if char == "'" and not in_double:
            in_single = not in_single
        # Handle double quotes (only if not in single quote)
        elif char == '"' and not in_single:
            in_double = not in_double

        i += 1

    return in_single or in_double


# Default paths to exclude when searching for issues
DEFAULT_EXCLUDE_PATHS = [
    "node_modules",
    "__pycache__",
    ".git",
    "venv",
    ".venv",
    "dist",
    "build",
    ".next",
    "coverage",
    "site-packages",
    "env",
    ".env",
    "Lib",
    "lib",
    ".tox",
    "eggs",
    "*.egg-info",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
]


class Thinker:
    """
    Think before you code.

    Provides research, reasoning, and exploration capabilities
    to help Claude make better decisions.
    """

    def __init__(self):
        """Audit engine is pure regex/AST -- no LLM, no network, no stores."""

    def audit_batch(
        self,
        file_paths: list[str],
        min_severity: Optional[str] = None,
    ) -> MiniClaudeResponse:
        """
        Audit multiple files at once.

        Args:
            file_paths: List of file paths to audit
            min_severity: Minimum severity to report ("critical", "warning", "info")

        Returns:
            Aggregated audit results across all files
        """
        import glob as glob_module

        work_log = WorkLog()
        work_log.what_i_tried.append(f"Batch auditing {len(file_paths)} files")

        # Expand glob patterns
        expanded_paths = []
        for path in file_paths:
            if "*" in path or "?" in path:
                expanded_paths.extend(glob_module.glob(path, recursive=True))
            else:
                expanded_paths.append(path)

        # Remove duplicates and filter to existing files
        expanded_paths = list(set(expanded_paths))
        expanded_paths = [p for p in expanded_paths if Path(p).is_file()]

        if not expanded_paths:
            return MiniClaudeResponse(
                status="failed",
                confidence="high",
                reasoning="No valid files found to audit",
                work_log=work_log,
            )

        work_log.what_worked.append(f"Found {len(expanded_paths)} files to audit")

        # Audit each file (pattern-based only for speed)
        all_issues = []
        files_with_issues = []
        files_clean = []

        for file_path in expanded_paths[:50]:  # Limit to 50 files
            try:
                content = Path(file_path).read_text(encoding="utf-8", errors="ignore")
                lines = content.splitlines()

                ext = Path(file_path).suffix.lower()
                language = {
                    ".py": "python",
                    ".js": "javascript",
                    ".ts": "typescript",
                    ".tsx": "typescript",
                    ".jsx": "javascript",
                    ".go": "go",
                }.get(ext, "unknown")

                issues = self._pattern_audit(content, lines, language)

                # Filter by severity
                severity_levels = {"critical": 3, "warning": 2, "info": 1}
                if min_severity and min_severity in severity_levels:
                    min_level = severity_levels[min_severity]
                    issues = [
                        i
                        for i in issues
                        if severity_levels.get(i["severity"], 0) >= min_level
                    ]

                if issues:
                    files_with_issues.append(
                        {
                            "file": file_path,
                            "issue_count": len(issues),
                            "critical": len(
                                [i for i in issues if i["severity"] == "critical"]
                            ),
                            "warning": len(
                                [i for i in issues if i["severity"] == "warning"]
                            ),
                            "issues": issues[:5],  # Top 5 issues per file
                        }
                    )
                    all_issues.extend([{**i, "file": file_path} for i in issues])
                else:
                    files_clean.append(file_path)

            except Exception as e:
                work_log.what_failed.append(f"Failed to audit {file_path}: {str(e)}")

        # Sort by severity
        critical_files = [f for f in files_with_issues if f["critical"] > 0]
        warning_files = [
            f for f in files_with_issues if f["critical"] == 0 and f["warning"] > 0
        ]

        total_critical = sum(f["critical"] for f in files_with_issues)
        total_warning = sum(f["warning"] for f in files_with_issues)

        if total_critical > 0:
            status = "failed"
            reasoning = f"Found {total_critical} critical issue(s) across {len(critical_files)} file(s)"
        elif total_warning > 0:
            status = "partial"
            reasoning = (
                f"Found {total_warning} warning(s) across {len(warning_files)} file(s)"
            )
        else:
            status = "success"
            reasoning = f"All {len(files_clean)} file(s) passed audit"

        # Format warnings
        warning_messages = []
        for f in sorted(files_with_issues, key=lambda x: x["critical"], reverse=True)[
            :10
        ]:
            warning_messages.append(
                f"{Path(f['file']).name}: {f['critical']} critical, {f['warning']} warnings"
            )

        return MiniClaudeResponse(
            status=status,
            confidence="high",
            reasoning=reasoning,
            work_log=work_log,
            data={
                "files_audited": len(expanded_paths),
                "files_with_issues": len(files_with_issues),
                "files_clean": len(files_clean),
                "total_critical": total_critical,
                "total_warning": total_warning,
                "critical_files": critical_files,
                "warning_files": warning_files,
                "all_issues": all_issues[:50],  # Limit total issues
            },
            warnings=warning_messages,
            suggestions=(
                [
                    f"Fix critical issues in: {', '.join(Path(f['file']).name for f in critical_files[:3])}"
                ]
                if critical_files
                else []
            ),
        )

    def find_similar_issues(
        self,
        issue_pattern: str,
        project_path: str,
        file_extensions: Optional[list[str]] = None,
        exclude_paths: Optional[list[str]] = None,
        exclude_strings: bool = True,
    ) -> MiniClaudeResponse:
        """
        Search codebase for code similar to a found issue pattern.

        Args:
            issue_pattern: The pattern to search for (e.g., "except: pass", "eval(")
            project_path: Root directory to search in
            file_extensions: File extensions to search (e.g., [".py", ".js"])
            exclude_paths: Paths to exclude (default: vendor dirs, envs, site-packages)
            exclude_strings: Skip matches inside string literals (default: True)

        Returns:
            List of files and locations with similar patterns
        """
        import re
        import glob as glob_module

        work_log = WorkLog()
        work_log.what_i_tried.append(f"Searching for pattern: {issue_pattern}")

        if not Path(project_path).exists():
            return MiniClaudeResponse(
                status="failed",
                confidence="high",
                reasoning=f"Project path does not exist: {project_path}",
                work_log=work_log,
            )

        # Default extensions
        if not file_extensions:
            file_extensions = [
                ".py",
                ".js",
                ".ts",
                ".tsx",
                ".jsx",
                ".go",
                ".java",
                ".rs",
            ]

        # Use default exclusions if not specified
        if exclude_paths is None:
            exclude_paths = DEFAULT_EXCLUDE_PATHS

        # Build glob patterns
        matches = []
        files_searched = 0
        files_skipped = 0

        for ext in file_extensions:
            pattern = f"{project_path}/**/*{ext}"
            for file_path in glob_module.glob(pattern, recursive=True):
                # Skip excluded directories
                if any(skip in file_path for skip in exclude_paths):
                    files_skipped += 1
                    continue

                files_searched += 1
                try:
                    content = Path(file_path).read_text(
                        encoding="utf-8", errors="ignore"
                    )
                    lines = content.splitlines()

                    for line_num, line in enumerate(lines, 1):
                        match = re.search(issue_pattern, line, re.IGNORECASE)
                        if match:
                            # Skip matches inside string literals
                            if exclude_strings and _is_inside_string_literal(
                                line, match.start()
                            ):
                                continue

                            matches.append(
                                {
                                    "file": file_path,
                                    "line": line_num,
                                    "code": line.strip()[:100],
                                }
                            )

                            if len(matches) >= 100:  # Limit matches
                                break

                except Exception:
                    continue

                if len(matches) >= 100:
                    break
            if len(matches) >= 100:
                break

        work_log.what_worked.append(
            f"Searched {files_searched} files, found {len(matches)} matches"
        )
        if files_skipped > 0:
            work_log.what_worked.append(
                f"Skipped {files_skipped} files in excluded paths"
            )

        # Group by file
        files_affected = {}
        for match in matches:
            file = match["file"]
            if file not in files_affected:
                files_affected[file] = []
            files_affected[file].append(match)

        if matches:
            status = "partial"
            reasoning = (
                f"Found {len(matches)} occurrences in {len(files_affected)} file(s)"
            )
        else:
            status = "success"
            reasoning = f"Pattern not found in {files_searched} files searched"

        return MiniClaudeResponse(
            status=status,
            confidence="high",
            reasoning=reasoning,
            work_log=work_log,
            data={
                "pattern": issue_pattern,
                "files_searched": files_searched,
                "files_skipped": files_skipped,
                "total_matches": len(matches),
                "files_affected": len(files_affected),
                "matches": matches[:50],
                "by_file": {k: v for k, v in list(files_affected.items())[:20]},
            },
            warnings=[
                f"{Path(f).name}: {len(m)} occurrence(s)"
                for f, m in sorted(
                    files_affected.items(), key=lambda x: len(x[1]), reverse=True
                )[:10]
            ],
            suggestions=(
                [
                    f"Fix pattern in {len(files_affected)} file(s) to prevent similar issues"
                ]
                if matches
                else []
            ),
        )

    def _pattern_audit(
        self, content: str, lines: list[str], language: str
    ) -> list[dict]:
        """Run pattern-based analysis on code."""
        import re

        issues = []

        # Track multiline string state (for skipping docstrings)
        in_multiline_string = False
        multiline_char = None  # '"""' or "'''"

        # Python-specific patterns
        python_patterns = [
            (
                r"except:\s*pass",
                "critical",
                "Silent exception - errors swallowed",
                "Add error logging: except Exception as e: logger.error(e)",
            ),
            (
                r"except\s+\w+:\s*pass",
                "critical",
                "Silent exception handler",
                "Log or re-raise the exception",
            ),
            (
                r"except\s+Exception\s*:",
                "warning",
                "Catching broad Exception",
                "Catch specific exceptions instead",
            ),
            (
                r"^\s*print\s*\(",
                "info",
                "print() statement - consider using logging",
                "Replace with logging.info() or remove",
            ),
            (
                r"#\s*(TODO|FIXME|XXX|HACK)",
                "warning",
                "TODO/FIXME comment",
                "Address or create issue to track",
            ),
            (
                r"open\s*\([^)]+\)\s*(?!\.)",
                "warning",
                "File opened without context manager",
                "Use 'with open(...) as f:' instead",
            ),
            (
                r"==\s*None\b",
                "info",
                "Using == None",
                "Use 'is None' for None comparisons",
            ),
            (
                r"!=\s*None\b",
                "info",
                "Using != None",
                "Use 'is not None' for None comparisons",
            ),
            (
                r"\beval\s*\(",
                "critical",
                "eval() usage - security risk",
                "Avoid eval(), use ast.literal_eval() for data",
            ),
            (
                r"\bexec\s*\(",
                "critical",
                "exec() usage - security risk",
                "Avoid exec(), find safer alternatives",
            ),
            (
                r"import\s+pickle",
                "warning",
                "pickle import - security risk with untrusted data",
                "Use json for serialization if possible",
            ),
            (
                r"subprocess\.(call|run|Popen)\s*\([^)]*shell\s*=\s*True",
                "critical",
                "subprocess with shell=True - injection risk",
                "Use shell=False with list of arguments",
            ),
        ]

        # JavaScript/TypeScript patterns
        js_patterns = [
            (
                r"catch\s*\([^)]*\)\s*\{\s*\}",
                "critical",
                "Empty catch block",
                "Add error handling or logging",
            ),
            (
                r"console\.(log|debug|info)\s*\(",
                "info",
                "console.log - remove for production",
                "Use proper logging or remove",
            ),
            (
                r"\beval\s*\(",
                "critical",
                "eval() usage - XSS risk",
                "Avoid eval(), use JSON.parse() for data",
            ),
            (
                r"innerHTML\s*=",
                "warning",
                "innerHTML assignment - XSS risk",
                "Use textContent or sanitize input",
            ),
            (
                r"document\.write\s*\(",
                "critical",
                "document.write - XSS risk",
                "Use DOM manipulation methods",
            ),
            (
                r"//\s*(TODO|FIXME|XXX|HACK)",
                "warning",
                "TODO/FIXME comment",
                "Address or create issue",
            ),
            (
                r"@ts-ignore",
                "warning",
                "@ts-ignore - type error suppressed",
                "Fix the type error instead",
            ),
            (
                r"any\s*[;,\)]",
                "info",
                "'any' type used",
                "Use specific types for better safety",
            ),
            (
                r"as\s+any\b",
                "warning",
                "Type assertion to 'any'",
                "Use proper type assertion",
            ),
        ]

        # Go patterns
        go_patterns = [
            (
                r"_\s*=\s*\w+\.\w+\(",
                "warning",
                "Error ignored with _",
                "Handle or explicitly ignore with comment",
            ),
            (
                r"//\s*(TODO|FIXME|XXX)",
                "warning",
                "TODO/FIXME comment",
                "Address or create issue",
            ),
            (
                r"panic\s*\(",
                "warning",
                "panic() call - use sparingly",
                "Return error instead if possible",
            ),
        ]

        # Select patterns based on language
        patterns = []
        if language == "python":
            patterns = python_patterns
        elif language in ("javascript", "typescript"):
            patterns = js_patterns
        elif language == "go":
            patterns = go_patterns
        else:
            # Generic patterns for any language
            patterns = [
                (
                    r"TODO|FIXME|XXX|HACK",
                    "warning",
                    "TODO/FIXME comment",
                    "Address before committing",
                ),
                (
                    r"password\s*=\s*['\"][^'\"]+['\"]",
                    "critical",
                    "Hardcoded password",
                    "Use environment variable",
                ),
                (
                    r"api_?key\s*=\s*['\"][^'\"]+['\"]",
                    "critical",
                    "Hardcoded API key",
                    "Use environment variable",
                ),
            ]

        # Run patterns
        for line_num, line in enumerate(lines, 1):
            # Track multiline docstring state
            stripped = line.strip()

            # Check for docstring start/end (Python)
            if language == "python":
                # Count triple quotes to toggle state
                for quote_type in ['"""', "'''"]:
                    count = line.count(quote_type)
                    if count > 0:
                        if not in_multiline_string:
                            # Starting a multiline string
                            if count == 1:
                                in_multiline_string = True
                                multiline_char = quote_type
                            # count == 2 means open and close on same line (not multiline)
                        elif multiline_char == quote_type:
                            # Ending the multiline string
                            if count >= 1:
                                in_multiline_string = False
                                multiline_char = None

            # Skip lines inside multiline docstrings
            if in_multiline_string:
                continue

            for pattern, severity, message, fix in patterns:
                # Special case: skip "open without context manager" if line has "with"
                if "File opened without context manager" in message:
                    # Skip if line uses context manager (with ... open)
                    if re.search(r"\bwith\b", line) and re.search(r"\bopen\s*\(", line):
                        continue  # Line uses context manager correctly

                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    # Skip matches inside string literals (prevents false positives in docs/regex)
                    if _is_inside_string_literal(line, match.start()):
                        continue

                    issues.append(
                        {
                            "line": line_num,
                            "severity": severity,
                            "message": message,
                            "fix": fix,
                            "code": line.strip()[:80],
                        }
                    )

        return issues

