"""
Git Helper - Intelligent commit message generation and diff review

Features:
1. Generate commit messages from work logs and git changes
2. Review diffs for issues BEFORE committing (diff_review)
3. Auto-commit with context-aware messages
"""

import subprocess
import re
from pathlib import Path
from typing import Optional

from ..schema import MiniClaudeResponse, WorkLog


class GitHelper:
    """Generate intelligent commit messages from context."""

    def __init__(self, memory_store=None, work_tracker=None):
        self.memory = memory_store
        self.work_tracker = work_tracker

    def get_changed_files(self, project_dir: str) -> list[str]:
        """Get list of changed files in git."""
        try:
            result = subprocess.run(
                ["git", "-C", project_dir, "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return []

            files = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    # Format is "XY filename"
                    parts = line.strip().split(maxsplit=1)
                    if len(parts) == 2:
                        files.append(parts[1])
            return files
        except Exception:
            return []

    def get_diff_summary(self, project_dir: str) -> dict:
        """Get summary of changes from git diff."""
        try:
            result = subprocess.run(
                ["git", "-C", project_dir, "diff", "--stat"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return {}

            # Parse diff stat
            lines = result.stdout.strip().split("\n")
            if not lines:
                return {}

            # Last line has summary: "X files changed, Y insertions(+), Z deletions(-)"
            summary_line = lines[-1]

            return {
                "stat": result.stdout,
                "summary": summary_line,
                "files_count": len(lines) - 1,  # -1 for summary line
            }
        except Exception:
            return {}

    def generate_commit_message(
        self,
        project_dir: str,
        session_summary: Optional[dict] = None,
    ) -> MiniClaudeResponse:
        """
        Generate commit message from work logs and git changes.

        Args:
            project_dir: Project directory
            session_summary: Optional session summary from work_tracker
        """
        work_log = WorkLog()
        work_log.what_i_tried.append("Generating commit message from context")

        # Get changed files
        changed_files = self.get_changed_files(project_dir)
        if not changed_files:
            return MiniClaudeResponse(
                status="failed",
                confidence="high",
                reasoning="No files changed - nothing to commit",
                work_log=work_log,
                suggestions=["Make some changes first", "Check git status"],
            )

        work_log.what_worked.append(f"Found {len(changed_files)} changed files")

        # Get diff summary
        diff_info = self.get_diff_summary(project_dir)

        # Build commit message
        message_parts = []

        # 1. Generate summary line from files and work
        if session_summary and "decisions" in session_summary:
            # Use first decision as summary if available
            decisions = session_summary.get("decisions", [])
            if decisions:
                first_decision = decisions[0]
                summary = first_decision.get("decision", "")[:72]  # 72 char limit
                message_parts.append(summary)
            else:
                # Fallback to file-based summary
                message_parts.append(self._generate_summary_from_files(changed_files))
        else:
            message_parts.append(self._generate_summary_from_files(changed_files))

        # 2. Add blank line
        message_parts.append("")

        # 3. Add detailed description from work logs
        if session_summary:
            if "decisions" in session_summary and session_summary["decisions"]:
                message_parts.append("Changes:")
                for decision in session_summary["decisions"][:3]:  # Max 3 decisions
                    dec = decision.get("decision", "")
                    reason = decision.get("reason", "")
                    if dec:
                        message_parts.append(f"- {dec}")
                        if reason:
                            message_parts.append(f"  Reason: {reason}")
                message_parts.append("")

            if "mistakes" in session_summary and session_summary["mistakes"]:
                message_parts.append("Fixes:")
                for mistake in session_summary["mistakes"][:3]:
                    desc = mistake.get("description", "")
                    if desc:
                        message_parts.append(f"- Fixed: {desc}")
                message_parts.append("")

        # 4. Add file changes summary
        if diff_info.get("summary"):
            message_parts.append(diff_info["summary"])
            message_parts.append("")

        # 5. Add co-authored-by
        message_parts.append("Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>")

        commit_message = "\n".join(message_parts)

        return MiniClaudeResponse(
            status="success",
            confidence="medium",
            reasoning="Generated commit message from work logs and git changes",
            work_log=work_log,
            data={
                "commit_message": commit_message,
                "files_changed": changed_files,
                "diff_summary": diff_info.get("summary", ""),
            },
            suggestions=[
                "Review the message before committing",
                "Use: git commit -F <(echo \"$MESSAGE\")",
                "Or copy the message from data.commit_message",
            ],
        )

    def _generate_summary_from_files(self, files: list[str]) -> str:
        """Generate a summary line from changed files."""
        if not files:
            return "Update files"

        # Categorize files
        tests = [f for f in files if "test" in f.lower()]
        docs = [f for f in files if any(f.endswith(ext) for ext in [".md", ".rst", ".txt"])]
        configs = [f for f in files if any(name in f.lower() for name in ["config", "settings", ".json", ".yml", ".yaml", ".toml"])]
        code_files = [f for f in files if f not in tests + docs + configs]

        # Generate summary based on what changed
        parts = []

        if len(files) == 1:
            # Single file - use filename
            file = Path(files[0])
            return f"Update {file.name}"

        if code_files and not tests and not docs:
            return f"Add/update {len(code_files)} file(s)"

        if tests and code_files:
            return f"Implement features with tests"

        if tests and not code_files:
            return f"Add/update tests"

        if docs and not code_files:
            return f"Update documentation"

        if configs:
            return f"Update configuration"

        return f"Update {len(files)} files"

    def auto_commit(
        self,
        project_dir: str,
        message: Optional[str] = None,
        files: Optional[list[str]] = None,
    ) -> MiniClaudeResponse:
        """
        Automatically commit changes with generated message.

        Args:
            project_dir: Project directory
            message: Explicit message (generate if None)
            files: Specific files to commit (all if None)
        """
        work_log = WorkLog()

        # Generate message if not provided
        if not message:
            msg_response = self.generate_commit_message(project_dir)
            if msg_response.status != "success":
                return msg_response
            message = msg_response.data.get("commit_message", "")

        work_log.what_i_tried.append("Creating git commit")

        try:
            # Add files
            if files:
                for file in files:
                    result = subprocess.run(
                        ["git", "-C", project_dir, "add", file],
                        capture_output=True,
                        timeout=5,
                    )
                    if result.returncode != 0:
                        work_log.what_failed.append(f"Failed to add {file}")
                        return MiniClaudeResponse(
                            status="failed",
                            confidence="high",
                            reasoning=f"Git add failed for {file}",
                            work_log=work_log,
                        )
            else:
                # Add all changed files
                result = subprocess.run(
                    ["git", "-C", project_dir, "add", "-A"],
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode != 0:
                    work_log.what_failed.append("Failed to add files")
                    return MiniClaudeResponse(
                        status="failed",
                        confidence="high",
                        reasoning="Git add failed",
                        work_log=work_log,
                    )

            # Commit
            result = subprocess.run(
                ["git", "-C", project_dir, "commit", "-m", message],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                work_log.what_failed.append("Commit failed")
                return MiniClaudeResponse(
                    status="failed",
                    confidence="high",
                    reasoning=f"Git commit failed: {result.stderr}",
                    work_log=work_log,
                    data={"stderr": result.stderr},
                )

            work_log.what_worked.append("Commit created successfully")

            # Get commit hash
            hash_result = subprocess.run(
                ["git", "-C", project_dir, "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            commit_hash = hash_result.stdout.strip()[:8] if hash_result.returncode == 0 else "unknown"

            return MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning=f"Committed as {commit_hash}",
                work_log=work_log,
                data={
                    "commit_hash": commit_hash,
                    "commit_message": message,
                },
                suggestions=["Use git push to push changes to remote"],
            )

        except Exception as e:
            work_log.what_failed.append(f"Git operation failed: {str(e)}")
            return MiniClaudeResponse(
                status="failed",
                confidence="high",
                reasoning=f"Git operation failed: {str(e)}",
                work_log=work_log,
            )

    def review_diff(
        self,
        project_dir: str,
        staged_only: bool = False,
    ) -> MiniClaudeResponse:
        """
        Review git diff for issues BEFORE committing.

        Catches:
        - Silent failures (except: pass, empty catch blocks)
        - Missing error handling
        - Debug code left in (print, console.log, debugger)
        - Hardcoded secrets/credentials
        - TODO/FIXME comments
        - Convention violations
        - Breaking changes (removed exports, changed signatures)

        Args:
            project_dir: Project directory
            staged_only: If True, only review staged changes (git diff --staged)
        """
        work_log = WorkLog()
        work_log.what_i_tried.append("Reviewing git diff for issues")

        # Get the diff
        try:
            cmd = ["git", "-C", project_dir, "diff"]
            if staged_only:
                cmd.append("--staged")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                return MiniClaudeResponse(
                    status="failed",
                    confidence="high",
                    reasoning=f"Git diff failed: {result.stderr}",
                    work_log=work_log,
                )

            diff_content = result.stdout

            if not diff_content.strip():
                return MiniClaudeResponse(
                    status="success",
                    confidence="high",
                    reasoning="No changes to review",
                    work_log=work_log,
                    suggestions=["Stage changes with 'git add' first" if not staged_only else "No staged changes"],
                )

        except Exception as e:
            work_log.what_failed.append(f"Failed to get diff: {str(e)}")
            return MiniClaudeResponse(
                status="failed",
                confidence="high",
                reasoning=f"Failed to get diff: {str(e)}",
                work_log=work_log,
            )

        # Analyze the diff
        issues = self._analyze_diff(diff_content)
        work_log.what_worked.append(f"Analyzed {len(diff_content.splitlines())} diff lines")

        # Categorize issues by severity
        critical = [i for i in issues if i["severity"] == "critical"]
        warnings = [i for i in issues if i["severity"] == "warning"]
        info = [i for i in issues if i["severity"] == "info"]

        # Build result
        if critical:
            status = "failed"
            confidence = "high"
            reasoning = f"Found {len(critical)} critical issue(s) - DO NOT COMMIT"
        elif warnings:
            status = "partial"
            confidence = "medium"
            reasoning = f"Found {len(warnings)} warning(s) - review before committing"
        else:
            status = "success"
            confidence = "high"
            reasoning = "No major issues found"

        # Format warnings for display
        warning_messages = []
        for issue in critical + warnings:
            warning_messages.append(
                f"[{issue['severity'].upper()}] {issue['file']}:{issue.get('line', '?')} - {issue['message']}"
            )

        suggestions = []
        for issue in issues:
            if issue.get("suggestion"):
                suggestions.append(issue["suggestion"])

        return MiniClaudeResponse(
            status=status,
            confidence=confidence,
            reasoning=reasoning,
            work_log=work_log,
            data={
                "critical_count": len(critical),
                "warning_count": len(warnings),
                "info_count": len(info),
                "issues": issues[:20],  # Limit to 20 issues
                "diff_lines": len(diff_content.splitlines()),
            },
            warnings=warning_messages[:10],  # Top 10 issues
            suggestions=suggestions[:5],
        )

    def _analyze_diff(self, diff_content: str) -> list[dict]:
        """Analyze diff content for common issues."""
        issues = []
        current_file = None
        line_num = 0
        in_docstring = False  # Track if we're inside a docstring

        # Patterns to check for - only on actual code lines
        patterns = [
            # Critical - Silent failures (only match actual code, not descriptions)
            (r'^\+\s*(except:\s*pass)', "critical", "Silent exception - errors will be swallowed", "Add proper error handling or logging"),
            (r'^\+\s*(except\s+\w+:\s*pass)', "critical", "Silent exception handler", "Log the error or handle it properly"),
            (r'^\+\s*(catch\s*\([^)]*\)\s*\{\s*\})', "critical", "Empty catch block", "Add error handling or logging"),

            # Critical - Security issues (only on assignment lines)
            (r'^\+[^"\'#]*\b(password|secret|api_key|apikey|token)\s*=\s*["\'][^"\']+["\']', "critical", "Hardcoded credential/secret", "Use environment variables"),
            (r'^\+[^#]*\beval\s*\(', "critical", "eval() usage - potential security risk", "Avoid eval() - use safer alternatives"),

            # Warning - Debug code
            (r'^\+\s*print\s*\(', "warning", "print() statement left in code", "Remove debug print statements"),
            (r'^\+.*console\.(log|debug|info)\s*\(', "warning", "console.log left in code", "Remove debug console statements"),
            (r'^\+\s*debugger\s*;?\s*$', "warning", "debugger statement left in code", "Remove debugger statement"),
            (r'^\+\s*breakpoint\s*\(\)', "warning", "breakpoint() left in code", "Remove debug breakpoint"),

            # Warning - Code quality (must be actual comments, not in strings)
            (r'^\+[^"\']*#\s*type:\s*ignore', "warning", "type: ignore comment", "Fix the type issue instead of ignoring"),
            (r'^\+[^"\']*//\s*@ts-ignore', "warning", "@ts-ignore comment", "Fix the TypeScript issue"),
            (r'^\+[^"\']*//\s*eslint-disable', "warning", "eslint-disable comment", "Fix the linting issue"),

            # Warning - Potential bugs (only in code, not strings)
            (r'^\+[^"\'#]*\s==\s*None\b', "warning", "Using == None instead of 'is None'", "Use 'is None' for None comparisons"),
            (r'^\+[^"\'#]*\s!=\s*None\b', "warning", "Using != None instead of 'is not None'", "Use 'is not None' for None comparisons"),

            # Info - Removed code
            (r'^-\s*def\s+\w+\s*\(', "info", "Function removed - may break dependents", "Verify no other code depends on this"),
            (r'^-\s*class\s+\w+', "info", "Class removed - may break dependents", "Verify no other code depends on this"),
            (r'^-.*\bexport\s+(default\s+)?(function|class|const|let|var)', "info", "Export removed - may break imports", "Verify no other code imports this"),
        ]

        # TODO/FIXME pattern - check separately to avoid false positives in descriptions
        todo_pattern = r'^\+[^"\']*#.*\b(TODO|FIXME|XXX|HACK)\b'

        for line in diff_content.splitlines():
            # Track current file
            if line.startswith("+++"):
                match = re.match(r"\+\+\+ [ab]/(.+)", line)
                if match:
                    current_file = match.group(1)
                    line_num = 0
                    in_docstring = False
                continue

            # Track line numbers (from @@ -X,Y +A,B @@)
            if line.startswith("@@"):
                match = re.search(r"\+(\d+)", line)
                if match:
                    line_num = int(match.group(1))
                continue

            # Only check added/removed lines
            if not (line.startswith("+") or line.startswith("-")):
                if line and not line.startswith("\\"):
                    line_num += 1
                continue

            # Skip documentation files for certain checks
            is_doc_file = current_file and any(
                current_file.endswith(ext) for ext in ['.md', '.txt', '.rst']
            )

            # Track docstrings (triple quotes)
            stripped = line[1:].strip() if len(line) > 1 else ""
            if '"""' in stripped or "'''" in stripped:
                # Count quotes - odd number means entering/exiting docstring
                triple_double = stripped.count('"""')
                triple_single = stripped.count("'''")
                if triple_double % 2 == 1 or triple_single % 2 == 1:
                    in_docstring = not in_docstring

            # Skip lines that appear to be inside docstrings or are description strings
            if in_docstring:
                if line.startswith("+"):
                    line_num += 1
                continue

            # Skip lines that are clearly string definitions (description=, name=, etc.)
            if re.match(r'^\+\s*(description|name|message|help|doc)\s*=\s*["\']', line[1:] if line else ""):
                if line.startswith("+"):
                    line_num += 1
                continue

            # Check patterns (skip doc files for code patterns)
            if not is_doc_file:
                for pattern, severity, message, suggestion in patterns:
                    if re.search(pattern, line, re.IGNORECASE):
                        issues.append({
                            "file": current_file or "unknown",
                            "line": line_num,
                            "severity": severity,
                            "message": message,
                            "suggestion": suggestion,
                            "code": line[:100],
                        })

                # Check TODO separately - only in actual comments
                if re.search(todo_pattern, line):
                    issues.append({
                        "file": current_file or "unknown",
                        "line": line_num,
                        "severity": "warning",
                        "message": "TODO/FIXME comment found",
                        "suggestion": "Address TODO before committing or create an issue",
                        "code": line[:100],
                    })

            if line.startswith("+"):
                line_num += 1

        return issues
