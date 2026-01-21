"""
Git Helper - Intelligent commit message generation

Features:
1. Generate commit messages from work logs and git changes
2. Auto-commit with context-aware messages
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
