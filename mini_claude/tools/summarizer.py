"""
File Summarizer - Quick understanding of files for Mini Claude

Provides:
1. Quick one-line summaries
2. Detailed breakdowns of file structure
3. Key facts extraction (exports, functions, classes, etc.)
"""

import os
import re
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..llm import LLMClient

from ..schema import MiniClaudeResponse, WorkLog


class FileSummarizer:
    """
    Quickly understand what a file does.

    Two modes:
    - quick: One-line summary using pattern matching (fast, no LLM)
    - detailed: Full breakdown using LLM (slower, more context)
    """

    def __init__(self, llm: "LLMClient"):
        self.llm = llm

    def summarize(
        self,
        file_path: str,
        mode: str = "quick",  # "quick" or "detailed"
    ) -> MiniClaudeResponse:
        """
        Summarize a file's purpose and contents.
        """
        work_log = WorkLog()
        work_log.what_i_tried.append(f"{mode} summarization")

        # Validate file exists
        path = Path(file_path)
        if not path.exists():
            return MiniClaudeResponse(
                status="failed",
                confidence="high",
                reasoning=f"File does not exist: {file_path}",
                work_log=work_log,
            )

        if not path.is_file():
            return MiniClaudeResponse(
                status="failed",
                confidence="high",
                reasoning=f"Path is not a file: {file_path}",
                work_log=work_log,
            )

        try:
            content = path.read_text(errors="ignore")
            work_log.files_examined = 1
        except Exception as e:
            return MiniClaudeResponse(
                status="failed",
                confidence="high",
                reasoning=f"Could not read file: {e}",
                work_log=work_log,
            )

        # Extract basic facts first (fast, no LLM)
        facts = self._extract_facts(content, path.suffix.lower())
        work_log.what_worked.append(f"extracted {len(facts)} facts")

        if mode == "quick":
            # Quick mode: pattern-based summary
            summary = self._quick_summary(content, path, facts)
            return MiniClaudeResponse(
                status="success",
                confidence="medium",
                reasoning=summary,
                work_log=work_log,
                data={
                    "file": str(path),
                    "size_lines": content.count("\n") + 1,
                    "facts": facts,
                },
            )

        else:
            # Detailed mode: use LLM
            work_log.what_i_tried.append("LLM analysis")

            result = self.llm.summarize_file(content, str(path))

            if result.get("success"):
                work_log.what_worked.append("LLM summary generated")
                work_log.time_taken_ms = result.get("time_taken_ms", 0)

                return MiniClaudeResponse(
                    status="success",
                    confidence="high",
                    reasoning=result["response"].strip(),
                    work_log=work_log,
                    data={
                        "file": str(path),
                        "size_lines": content.count("\n") + 1,
                        "facts": facts,
                    },
                )
            else:
                work_log.what_failed.append(result.get("error", "LLM failed"))
                # Fall back to quick mode
                summary = self._quick_summary(content, path, facts)
                return MiniClaudeResponse(
                    status="partial",
                    confidence="medium",
                    reasoning=f"LLM unavailable, quick summary: {summary}",
                    work_log=work_log,
                    data={"facts": facts},
                )

    def _extract_facts(self, content: str, extension: str) -> dict:
        """Extract structural facts from code."""
        facts = {
            "lines": content.count("\n") + 1,
            "functions": [],
            "classes": [],
            "imports": [],
            "exports": [],
        }

        # Python
        if extension == ".py":
            # Functions
            facts["functions"] = re.findall(r"^def (\w+)\(", content, re.MULTILINE)
            # Classes
            facts["classes"] = re.findall(r"^class (\w+)", content, re.MULTILINE)
            # Imports
            facts["imports"] = re.findall(r"^(?:from|import) ([\w.]+)", content, re.MULTILINE)

        # JavaScript/TypeScript
        elif extension in (".js", ".ts", ".jsx", ".tsx"):
            # Functions
            facts["functions"] = re.findall(r"(?:function|const|let|var)\s+(\w+)\s*(?:=\s*(?:async\s*)?\(|=\s*function|\()", content)
            # Classes
            facts["classes"] = re.findall(r"class\s+(\w+)", content)
            # Imports
            facts["imports"] = re.findall(r"import\s+.*?from\s+['\"]([^'\"]+)['\"]", content)
            # Exports
            facts["exports"] = re.findall(r"export\s+(?:default\s+)?(?:function|class|const|let|var|async)?\s*(\w+)", content)

        # Go
        elif extension == ".go":
            facts["functions"] = re.findall(r"func\s+(?:\([^)]+\)\s+)?(\w+)\(", content)
            facts["imports"] = re.findall(r'"([^"]+)"', content[:2000])  # Usually at top

        # Java/Kotlin
        elif extension in (".java", ".kt"):
            facts["classes"] = re.findall(r"class\s+(\w+)", content)
            facts["functions"] = re.findall(r"(?:public|private|protected|static|\s)+\w+\s+(\w+)\s*\(", content)

        # Rust
        elif extension == ".rs":
            facts["functions"] = re.findall(r"fn\s+(\w+)", content)
            facts["imports"] = re.findall(r"use\s+([\w:]+)", content)

        # Clean up
        for key in ["functions", "classes", "imports", "exports"]:
            facts[key] = list(set(facts[key]))[:20]  # Dedupe and limit

        return facts

    def _quick_summary(self, content: str, path: Path, facts: dict) -> str:
        """Generate a quick pattern-based summary."""
        parts = []

        # File type hint
        ext = path.suffix.lower()
        if ext == ".py":
            parts.append("Python file")
        elif ext in (".js", ".jsx"):
            parts.append("JavaScript file")
        elif ext in (".ts", ".tsx"):
            parts.append("TypeScript file")
        elif ext == ".go":
            parts.append("Go file")
        elif ext == ".rs":
            parts.append("Rust file")
        elif ext == ".java":
            parts.append("Java file")
        else:
            parts.append(f"{ext} file")

        # Size
        lines = facts.get("lines", 0)
        if lines > 500:
            parts.append("(large)")
        elif lines < 50:
            parts.append("(small)")

        # Main contents
        if facts.get("classes"):
            if len(facts["classes"]) == 1:
                parts.append(f"defining class '{facts['classes'][0]}'")
            else:
                parts.append(f"with {len(facts['classes'])} classes")

        if facts.get("functions"):
            if len(facts["functions"]) <= 3:
                parts.append(f"functions: {', '.join(facts['functions'][:3])}")
            else:
                parts.append(f"{len(facts['functions'])} functions")

        # Common patterns
        if "test" in path.name.lower() or "spec" in path.name.lower():
            parts.append("(test file)")
        elif "config" in path.name.lower():
            parts.append("(configuration)")
        elif "util" in path.name.lower() or "helper" in path.name.lower():
            parts.append("(utilities)")

        return " ".join(parts) if parts else f"File with {lines} lines"
