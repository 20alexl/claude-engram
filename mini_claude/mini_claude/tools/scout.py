"""
Scout - Search Tool for Mini Claude

The core search functionality. Combines:
1. Fast file/text search (grep-like)
2. LLM-powered semantic understanding
3. Structured response formatting
"""

import os
import re
import time
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..llm import LLMClient

from ..schema import MiniClaudeResponse, SearchResult, WorkLog


# File extensions we care about for code search
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".swift",
    ".kt", ".scala", ".vue", ".svelte", ".html", ".css", ".scss",
    ".json", ".yaml", ".yml", ".toml", ".xml", ".md", ".sql",
    ".sh", ".bash", ".zsh", ".dockerfile", ".prisma", ".graphql"
}

# Directories to skip
SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".nuxt", "target", "coverage",
    ".pytest_cache", ".mypy_cache", ".tox", "eggs", "*.egg-info"
}


class SearchEngine:
    """
    Scout - Mini Claude's search capability.

    Finds code and understands it using the local LLM.
    """

    def __init__(self, llm: "LLMClient"):
        self.llm = llm

    def search(
        self,
        query: str,
        directory: str,
        max_results: int = 10,
        use_llm: bool = True,
    ) -> MiniClaudeResponse:
        """
        Search for code matching a query.

        This is the main entry point. It:
        1. Searches for literal matches
        2. Uses the LLM to understand semantic queries
        3. Returns a rich response with context
        """
        start_time = time.time()
        work_log = WorkLog()

        # Validate directory
        if not os.path.isdir(directory):
            return MiniClaudeResponse(
                status="failed",
                confidence="high",
                reasoning=f"Directory does not exist: {directory}",
                work_log=work_log,
            )

        work_log.what_i_tried.append("scanning directory structure")

        # Get all searchable files
        files = self._get_searchable_files(directory)
        work_log.files_examined = len(files)

        if not files:
            return MiniClaudeResponse(
                status="failed",
                confidence="high",
                reasoning="No code files found in directory",
                work_log=work_log,
                suggestions=["Check if the directory path is correct"]
            )

        work_log.what_worked.append(f"found {len(files)} code files")

        # Determine search strategy based on query
        findings = []
        questions = []
        suggestions = []

        # Strategy 1: Literal/regex search for specific terms
        literal_results = self._literal_search(query, files, directory)
        if literal_results:
            findings.extend(literal_results)
            work_log.what_worked.append(f"literal search found {len(literal_results)} matches")

        # Strategy 2: Semantic search using LLM
        if use_llm and len(findings) < max_results:
            work_log.what_i_tried.append("semantic search with LLM")
            semantic_results = self._semantic_search(query, files, directory, max_results - len(findings))
            if semantic_results:
                # Deduplicate
                existing_files = {f.file for f in findings}
                for result in semantic_results:
                    if result.file not in existing_files:
                        findings.append(result)
                work_log.what_worked.append(f"semantic search added {len(semantic_results)} results")

        # Analyze connections between findings
        connections = None
        if len(findings) > 1 and use_llm:
            connections = self._analyze_connections(findings, query)

        # Generate follow-up suggestions
        if findings:
            suggestions = self._generate_suggestions(findings, query, directory)

        # Determine confidence
        if len(findings) >= 3:
            confidence = "high"
        elif len(findings) >= 1:
            confidence = "medium"
        else:
            confidence = "low"
            questions.append("Could you be more specific about what you're looking for?")

        work_log.time_taken_ms = int((time.time() - start_time) * 1000)

        return MiniClaudeResponse(
            status="success" if findings else "partial",
            work_log=work_log,
            confidence=confidence,
            reasoning=f"Searched {len(files)} files using literal and semantic matching",
            findings=findings[:max_results],
            connections=connections,
            questions=questions,
            suggestions=suggestions,
        )

    def _get_searchable_files(self, directory: str) -> list[Path]:
        """Get all code files in directory, respecting skip patterns."""
        files = []
        directory = Path(directory)

        for root, dirs, filenames in os.walk(directory):
            # Filter out directories we should skip
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]

            for filename in filenames:
                filepath = Path(root) / filename
                if filepath.suffix.lower() in CODE_EXTENSIONS:
                    files.append(filepath)

        return files

    def _literal_search(
        self,
        query: str,
        files: list[Path],
        base_dir: str,
    ) -> list[SearchResult]:
        """Search for literal text matches."""
        results = []

        # Extract potential search terms from query
        search_terms = self._extract_search_terms(query)

        if not search_terms:
            return results

        for filepath in files:
            try:
                content = filepath.read_text(errors="ignore")
                rel_path = str(filepath.relative_to(base_dir))

                for term in search_terms:
                    # Case-insensitive search
                    pattern = re.compile(re.escape(term), re.IGNORECASE)
                    matches = list(pattern.finditer(content))

                    if matches:
                        # Find line number of first match
                        first_match = matches[0]
                        line_num = content[:first_match.start()].count("\n") + 1

                        # Get snippet around match
                        lines = content.split("\n")
                        start_line = max(0, line_num - 2)
                        end_line = min(len(lines), line_num + 2)
                        snippet = "\n".join(lines[start_line:end_line])

                        results.append(SearchResult(
                            file=rel_path,
                            line=line_num,
                            relevance="high" if len(matches) > 1 else "medium",
                            summary=f"Found '{term}' ({len(matches)} occurrences)",
                            snippet=snippet[:300],
                        ))
                        break  # One result per file

            except Exception:
                continue

        return results

    def _extract_search_terms(self, query: str) -> list[str]:
        """Extract literal search terms from a natural language query."""
        terms = []

        # Extract quoted strings
        quoted = re.findall(r'"([^"]+)"', query)
        terms.extend(quoted)

        # Extract likely code identifiers (camelCase, snake_case, etc.)
        identifiers = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*(?:[A-Z][a-z]+)+\b", query)
        terms.extend(identifiers)

        identifiers = re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", query)
        terms.extend(identifiers)

        # Common code-related keywords
        code_keywords = ["auth", "login", "user", "api", "route", "model", "controller",
                        "service", "middleware", "handler", "util", "helper", "config"]
        for word in query.lower().split():
            if word in code_keywords:
                terms.append(word)

        return list(set(terms))

    def _get_file_preview(self, filepath: Path, max_lines: int = 30) -> str:
        """Get a preview of a file's content (first N lines + key patterns)."""
        try:
            content = filepath.read_text(errors="ignore")
            lines = content.split("\n")

            # Get first N lines
            preview_lines = lines[:max_lines]

            # Also extract key patterns: class/function definitions, imports
            key_patterns = []
            for i, line in enumerate(lines):
                stripped = line.strip()
                # Capture class and function definitions
                if stripped.startswith(("class ", "def ", "function ", "const ", "export ")):
                    key_patterns.append(f"L{i+1}: {stripped[:80]}")
                # Capture imports (first 5)
                elif stripped.startswith(("import ", "from ", "require(", "#include")):
                    if len([p for p in key_patterns if "import" in p.lower() or "from" in p.lower()]) < 5:
                        key_patterns.append(f"L{i+1}: {stripped[:60]}")

            preview = "\n".join(preview_lines)
            if key_patterns:
                preview += "\n...\nKey definitions:\n" + "\n".join(key_patterns[:10])

            return preview[:1500]  # Limit total size
        except Exception:
            return ""

    def _semantic_search(
        self,
        query: str,
        files: list[Path],
        base_dir: str,
        max_results: int,
    ) -> list[SearchResult]:
        """Use LLM to understand semantic queries with ACTUAL CODE CONTEXT."""
        results = []

        # Build file list WITH code previews for the LLM
        file_list = []  # Just paths for matching later
        file_previews = []  # Paths + content for LLM
        for filepath in files[:50]:  # Reduced from 100 to fit more content
            rel_path = str(filepath.relative_to(base_dir))
            file_list.append(rel_path)
            preview = self._get_file_preview(filepath, max_lines=15)
            if preview:
                file_previews.append(f"=== {rel_path} ===\n{preview}\n")
            else:
                file_previews.append(f"=== {rel_path} ===\n(could not read)\n")

        # Ask LLM which files are likely relevant - NOW WITH CODE CONTEXT
        prompt = f"""I need to find code related to: "{query}"

Here are the files with their content previews:

{chr(10).join(file_previews)}

Based on the ACTUAL CODE CONTENT above, which files (up to {max_results}) are most relevant to my query?
List ONLY the file paths, one per line. No explanations."""

        response = self.llm.generate(prompt, temperature=0.0)

        if not response.get("success"):
            return results

        # Parse LLM response for file paths
        suggested_files = []
        for line in response["response"].split("\n"):
            line = line.strip().strip("-").strip("*").strip()
            if line and any(line.endswith(ext) for ext in CODE_EXTENSIONS):
                for f in file_list:
                    if f in line or line in f:
                        suggested_files.append(f)
                        break

        # Analyze each suggested file
        for rel_path in suggested_files[:max_results]:
            filepath = Path(base_dir) / rel_path
            if not filepath.exists():
                continue

            try:
                content = filepath.read_text(errors="ignore")
                summary_response = self.llm.summarize_file(content, rel_path)

                if summary_response.get("success"):
                    results.append(SearchResult(
                        file=rel_path,
                        relevance="medium",
                        summary=summary_response["response"].strip()[:200],
                    ))
            except Exception:
                continue

        return results

    def _analyze_connections(self, findings: list[SearchResult], query: str) -> Optional[str]:
        """Analyze how the findings relate to each other."""
        if len(findings) < 2:
            return None

        file_list = [f.file for f in findings]
        prompt = f"""These files were found for the query "{query}":
{chr(10).join(f"- {f}" for f in file_list)}

In ONE sentence, explain how these files might be connected or work together:"""

        response = self.llm.generate(prompt, temperature=0.0)

        if response.get("success"):
            return response["response"].strip()

        return None

    def _generate_suggestions(
        self,
        findings: list[SearchResult],
        query: str,
        directory: str,
    ) -> list[str]:
        """Generate follow-up suggestions based on findings."""
        suggestions = []

        dirs_found = set()
        for f in findings:
            parts = Path(f.file).parts
            if len(parts) > 1:
                dirs_found.add(parts[0])

        for d in list(dirs_found)[:2]:
            suggestions.append(f"Explore the '{d}/' directory for related code")

        return suggestions
