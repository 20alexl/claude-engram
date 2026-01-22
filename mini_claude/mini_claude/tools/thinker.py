"""
Thinker - A thinking partner for Claude Code

Helps Claude overcome tunnel vision and shallow research by:
- Deep web research with reasoning
- Comparing multiple approaches
- Challenging assumptions
- Exploring solution spaces
- Finding best practices

Uses web search + local LLM reasoning to think before coding.
"""

import json
from typing import Optional
from pathlib import Path

import httpx

from ..llm import LLMClient
from ..schema import MiniClaudeResponse, WorkLog
from .scout import SearchEngine
from .memory import MemoryStore


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
        if char == '\\' and i + 1 < len(line):
            i += 2  # Skip escaped character
            continue

        # Handle triple quotes (simplified - just check if we're starting one)
        if i + 2 < len(line):
            triple = line[i:i+3]
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
    "node_modules", "__pycache__", ".git", "venv", ".venv",
    "dist", "build", ".next", "coverage", "site-packages",
    "env", ".env", "Lib", "lib", ".tox", "eggs", "*.egg-info",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
]


class Thinker:
    """
    Think before you code.

    Provides research, reasoning, and exploration capabilities
    to help Claude make better decisions.
    """

    def __init__(self, memory: MemoryStore, search_engine: SearchEngine, llm: LLMClient):
        self.memory = memory
        self.search = search_engine
        self.llm = llm
        self.httpx_client = httpx.Client(timeout=30.0)

    def _is_codebase_question(self, question: str) -> bool:
        """Detect if the question is about THIS codebase specifically."""
        codebase_indicators = [
            "in this codebase", "in this project", "in the codebase",
            "how does", "how do", "where is", "where are", "what file",
            "which file", "find the", "show me", "how is .* implemented",
            "implementation of", "how .* works"
        ]
        question_lower = question.lower()
        return any(indicator in question_lower for indicator in codebase_indicators)

    def _read_file_for_research(self, file_path: str, max_lines: int = 200) -> str:
        """Read a file for research purposes, with line numbers."""
        try:
            content = Path(file_path).read_text(errors="ignore")
            lines = content.split("\n")[:max_lines]
            numbered = [f"{i+1:4d}| {line}" for i, line in enumerate(lines)]
            return "\n".join(numbered)
        except Exception:
            return ""

    def research(
        self,
        question: str,
        context: Optional[str] = None,
        depth: str = "medium",
        project_path: Optional[str] = None,
    ) -> MiniClaudeResponse:
        """
        Deep research on a question using web + codebase + reasoning.

        IMPROVED: For codebase questions, reads actual code instead of generic web results.

        Args:
            question: The question to research
            context: Optional context about why you're asking
            depth: quick | medium | deep (how thorough to be)
            project_path: Optional project to search for existing patterns

        Returns:
            Research findings with sources, reasoning, and suggestions
        """
        work_log = WorkLog()
        work_log.what_worked.append(f"Researching: {question}")

        findings = []
        sources = []
        code_context = []  # Actual code to send to LLM

        # Detect if this is a codebase-specific question
        is_codebase_q = project_path and self._is_codebase_question(question)

        # Step 1: Web search (SKIP for codebase questions - it's just noise)
        if not is_codebase_q:
            try:
                web_results = self._web_search(question, max_results=5 if depth == "quick" else 10)
                if web_results:
                    findings.append("## Web Research")
                    for result in web_results[:3]:
                        findings.append(f"- {result['title']}: {result['snippet']}")
                        sources.append(result['url'])
                    work_log.what_worked.append(f"Found {len(web_results)} web results")
            except Exception as e:
                work_log.what_failed.append(f"Web search failed: {str(e)}")
        else:
            work_log.what_worked.append("Skipped web search (codebase-specific question)")

        # Step 2: Search codebase for existing patterns (if project provided)
        if project_path:
            try:
                codebase_results = self.search.search(
                    query=question,
                    directory=project_path,
                    max_results=5 if depth == "quick" else 10,
                )
                # Access findings from the response
                if codebase_results.findings:
                    findings.append("\n## Relevant Files in Codebase")
                    for finding in codebase_results.findings[:5]:
                        findings.append(f"- {finding.file}: {finding.summary}")

                        # FOR CODEBASE QUESTIONS: Actually read the relevant files
                        if is_codebase_q and len(code_context) < 3:
                            file_path = Path(project_path) / finding.file
                            if file_path.exists():
                                code_content = self._read_file_for_research(str(file_path))
                                if code_content:
                                    code_context.append(f"=== {finding.file} ===\n{code_content}")
                                    work_log.what_worked.append(f"Read {finding.file} for analysis")

                    work_log.what_worked.append(f"Found {len(codebase_results.findings)} relevant files")
            except Exception as e:
                work_log.what_failed.append(f"Codebase search failed: {str(e)}")

        # Step 3: Use LLM to reason about findings (WITH ACTUAL CODE for codebase questions)
        reasoning_prompt = self._build_research_prompt(
            question, context, findings, depth,
            code_context=code_context if is_codebase_q else None
        )

        try:
            result = self.llm.generate(reasoning_prompt)
            if result.get("success"):
                reasoning = result.get("response", "")
                findings.append("\n## Analysis")
                findings.append(reasoning)
                work_log.what_worked.append("Generated reasoning with LLM")
                if code_context:
                    work_log.what_worked.append(f"LLM analyzed {len(code_context)} code file(s)")
            else:
                findings.append("\n## Analysis")
                findings.append(f"(LLM error: {result.get('error', 'unknown')})")
        except Exception as e:
            work_log.what_failed.append(f"LLM reasoning failed: {str(e)}")
            findings.append("\n## Analysis")
            findings.append("(LLM reasoning unavailable)")

        # Step 4: Remember this research for future
        if project_path:
            self.memory.remember_discovery(
                project_path=project_path,
                content=f"Researched: {question}. Key finding: {findings[0] if findings else 'No findings'}",
                relevance=7,
            )

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning=f"Researched question with {depth} depth",
            work_log=work_log,
            data={
                "question": question,
                "findings": "\n".join(findings),
                "sources": sources,
                "depth": depth,
            },
            suggestions=self._extract_suggestions_from_findings(findings),
        )

    def compare(
        self,
        options: list[str],
        context: str,
        criteria: Optional[list[str]] = None,
    ) -> MiniClaudeResponse:
        """
        Compare multiple approaches with pros/cons analysis.

        Args:
            options: List of options to compare (e.g., ["SQLite", "PostgreSQL"])
            context: Context for the decision (e.g., "local-first MCP server")
            criteria: Optional criteria to evaluate (e.g., ["performance", "complexity"])

        Returns:
            Comparison with pros/cons for each option
        """
        work_log = WorkLog()
        work_log.what_worked.append(f"Comparing {len(options)} options")

        if not criteria:
            criteria = ["complexity", "performance", "maintainability", "ecosystem"]

        # Build comparison prompt
        prompt = f"""Compare these options for the following use case:

Context: {context}

Options to compare:
{chr(10).join(f"- {opt}" for opt in options)}

Evaluation criteria:
{chr(10).join(f"- {c}" for c in criteria)}

For each option, provide:
1. Brief description
2. Pros (3-5 points)
3. Cons (3-5 points)
4. Best suited for...
5. Avoid if...

Then provide a recommendation based on the context.

Format as clear markdown with headers."""

        try:
            result = self.llm.generate(prompt)
            if result.get("success"):
                comparison = result.get("response", "")
                work_log.what_worked.append("Generated comparison with LLM")
            else:
                comparison = f"LLM error: {result.get('error', 'unknown')}"
                work_log.what_failed.append(comparison)
        except Exception as e:
            work_log.what_failed.append(f"LLM comparison failed: {str(e)}")
            comparison = "LLM comparison unavailable"

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning=f"Compared {len(options)} options across {len(criteria)} criteria",
            work_log=work_log,
            data={
                "options": options,
                "context": context,
                "criteria": criteria,
                "comparison": comparison,
            },
        )

    def challenge(
        self,
        assumption: str,
        context: Optional[str] = None,
    ) -> MiniClaudeResponse:
        """
        Challenge an assumption with devil's advocate reasoning.

        Args:
            assumption: The assumption to challenge (e.g., "We need sub-1ms latency")
            context: Optional context about the assumption

        Returns:
            Analysis challenging the assumption
        """
        work_log = WorkLog()
        work_log.what_worked.append(f"Challenging assumption: {assumption}")

        prompt = f"""Act as a devil's advocate and challenge this assumption:

Assumption: {assumption}
{f'Context: {context}' if context else ''}

Please analyze:
1. Is this assumption actually necessary?
2. What are the hidden costs of this assumption?
3. What simpler alternatives might work?
4. What questions should be asked before accepting this?
5. What's the worst case if this assumption is wrong?

Be direct and critical. Point out if this seems like premature optimization,
over-engineering, or tunnel vision."""

        try:
            result = self.llm.generate(prompt)
            if result.get("success"):
                challenge = result.get("response", "")
                work_log.what_worked.append("Generated challenge with LLM")
            else:
                challenge = f"LLM error: {result.get('error', 'unknown')}"
                work_log.what_failed.append(challenge)
        except Exception as e:
            work_log.what_failed.append(f"LLM challenge failed: {str(e)}")
            challenge = "LLM challenge unavailable"

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning="Challenged assumption with critical analysis",
            work_log=work_log,
            data={
                "assumption": assumption,
                "challenge": challenge,
            },
            warnings=["This is devil's advocate analysis - consider carefully"],
        )

    def explore(
        self,
        problem: str,
        constraints: Optional[list[str]] = None,
        project_path: Optional[str] = None,
    ) -> MiniClaudeResponse:
        """
        Broad exploration of solution space for a problem.

        Args:
            problem: The problem to solve
            constraints: Optional constraints (e.g., ["must be local-first", "under 1MB"])
            project_path: Optional project to check for existing patterns

        Returns:
            Multiple possible approaches with trade-offs
        """
        work_log = WorkLog()
        work_log.what_worked.append(f"Exploring solutions for: {problem}")

        # FIRST: Check for existing patterns in codebase (before LLM call)
        existing_patterns = []
        existing_patterns_text = ""
        if project_path:
            try:
                search_result = self.search.search(
                    query=problem,
                    directory=project_path,
                    max_results=5,
                )
                if search_result.data and search_result.data.get("findings"):
                    existing_patterns = [
                        f"{f.get('file', 'unknown')}: {f.get('summary', '')}"
                        for f in search_result.data["findings"]
                    ]
                    work_log.what_worked.append(f"Found {len(existing_patterns)} existing patterns")
                    existing_patterns_text = "\n".join(f"- {p}" for p in existing_patterns)
            except Exception as e:
                work_log.what_failed.append(f"Pattern search failed: {str(e)}")

        # Build prompt WITH existing patterns context
        prompt = f"""Explore different approaches to solve this problem:

Problem: {problem}

{f'Constraints:{chr(10)}{chr(10).join(f"- {c}" for c in constraints)}' if constraints else 'No specific constraints'}

{f'Existing patterns found in codebase:{chr(10)}{existing_patterns_text}{chr(10)}{chr(10)}Consider how these existing patterns might inform your suggestions.' if existing_patterns_text else ''}

Brainstorm 4-6 different approaches FOR THIS SPECIFIC PROBLEM, ranging from:
- Simple/naive (quick to implement, might not scale)
- Standard (what most people do)
- Creative (unusual but potentially better)
- Ideal (if resources were unlimited)

For each approach:
- Name it clearly
- Describe how it works (2-3 sentences) - BE SPECIFIC to this problem
- Trade-offs (what you gain/lose)
- Implementation complexity (low/medium/high)

IMPORTANT: Don't give generic textbook answers. Analyze THIS specific problem and give concrete suggestions that apply to it. Reference the existing patterns if found."""

        try:
            result = self.llm.generate(prompt)
            if result.get("success"):
                exploration = result.get("response", "")
                work_log.what_worked.append("Generated exploration with LLM")
            else:
                exploration = f"LLM error: {result.get('error', 'unknown')}"
                work_log.what_failed.append(exploration)
        except Exception as e:
            work_log.what_failed.append(f"LLM exploration failed: {str(e)}")
            exploration = "LLM exploration unavailable"

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning=f"Explored solution space for problem",
            work_log=work_log,
            data={
                "problem": problem,
                "constraints": constraints,
                "exploration": exploration,
                "existing_patterns": existing_patterns,
            },
        )

    def best_practice(
        self,
        topic: str,
        language_or_framework: Optional[str] = None,
        year: int = 2026,
    ) -> MiniClaudeResponse:
        """
        Find current best practices for a topic.

        Args:
            topic: What to find best practices for (e.g., "error handling")
            language_or_framework: Optional language/framework context (e.g., "Python", "React")
            year: Year for recency (default: 2026)

        Returns:
            Best practices with sources
        """
        work_log = WorkLog()

        # Build search query
        query = f"{topic} best practices {year}"
        if language_or_framework:
            query += f" {language_or_framework}"

        work_log.what_worked.append(f"Searching for: {query}")

        findings = []
        sources = []

        # Web search for current best practices
        try:
            web_results = self._web_search(query, max_results=8)
            if web_results:
                findings.append("## Recent Best Practices")
                for result in web_results[:5]:
                    findings.append(f"- {result['title']}")
                    findings.append(f"  {result['snippet']}")
                    sources.append(result['url'])
                work_log.what_worked.append(f"Found {len(web_results)} sources")
        except Exception as e:
            work_log.what_failed.append(f"Web search failed: {str(e)}")

        # Use LLM to synthesize best practices
        synthesis_prompt = f"""Based on these search results about {topic} best practices:

{chr(10).join(findings)}

Synthesize the current best practices (as of {year}) into a clear, actionable list.
Focus on:
- What to do (and why)
- What to avoid (and why)
- Common pitfalls
- Tools/libraries that help

Be specific and practical."""

        try:
            result = self.llm.generate(synthesis_prompt)
            if result.get("success"):
                synthesis = result.get("response", "")
                findings.append("\n## Synthesis")
                findings.append(synthesis)
                work_log.what_worked.append("Synthesized best practices")
            else:
                findings.append("\n## Synthesis")
                findings.append(f"(LLM error: {result.get('error', 'unknown')})")
        except Exception as e:
            work_log.what_failed.append(f"LLM synthesis failed: {str(e)}")

        return MiniClaudeResponse(
            status="success",
            confidence="medium",
            reasoning=f"Found best practices for {topic}",
            work_log=work_log,
            data={
                "topic": topic,
                "language_or_framework": language_or_framework,
                "year": year,
                "findings": "\n".join(findings),
                "sources": sources,
            },
            warnings=["Always verify best practices match your specific context"],
        )

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _web_search(self, query: str, max_results: int = 10) -> list[dict]:
        """
        Perform web search using DuckDuckGo.

        Returns list of {title, snippet, url}
        """
        # Use DuckDuckGo Instant Answer API (no key required)
        try:
            response = self.httpx_client.get(
                "https://api.duckduckgo.com/",
                params={
                    "q": query,
                    "format": "json",
                    "no_html": 1,
                    "skip_disambig": 1,
                }
            )
            response.raise_for_status()
            data = response.json()

            results = []

            # Add abstract as first result
            if data.get("Abstract"):
                results.append({
                    "title": data.get("Heading", "Overview"),
                    "snippet": data.get("Abstract", ""),
                    "url": data.get("AbstractURL", ""),
                })

            # Add related topics
            for topic in data.get("RelatedTopics", [])[:max_results - 1]:
                if isinstance(topic, dict) and "Text" in topic:
                    results.append({
                        "title": topic.get("Text", "").split(" - ")[0],
                        "snippet": topic.get("Text", ""),
                        "url": topic.get("FirstURL", ""),
                    })

            return results[:max_results]

        except Exception:
            # Fallback: return empty (don't crash on web search failure)
            return []

    def _build_research_prompt(
        self,
        question: str,
        context: Optional[str],
        findings: list[str],
        depth: str,
        code_context: Optional[list[str]] = None,
    ) -> str:
        """Build prompt for LLM reasoning about research."""

        # For codebase questions, include actual code
        code_section = ""
        if code_context:
            code_section = f"""

ACTUAL CODE FROM CODEBASE (analyze this to answer the question):
{chr(10).join(code_context)}

"""

        prompt = f"""Analyze this research question:

Question: {question}
{f'Context: {context}' if context else ''}
{code_section}
Research findings:
{chr(10).join(findings) if findings else 'No findings available'}

Provide a thoughtful analysis that:
1. Directly answers the question {"based on the actual code provided" if code_context else ""}
2. {"Reference specific line numbers and functions from the code" if code_context else "Synthesize the findings"}
3. Points out trade-offs and considerations
4. Suggests what to do next

Depth: {depth} ({"brief overview" if depth == "quick" else "thorough analysis" if depth == "deep" else "balanced analysis"})"""

        return prompt

    def _extract_suggestions_from_findings(self, findings: list[str]) -> list[str]:
        """Extract actionable suggestions from findings."""
        suggestions = []

        # Simple heuristic: look for action words
        action_words = ["use ", "try ", "consider ", "avoid ", "check ", "implement "]

        for finding in findings:
            lower = finding.lower()
            for word in action_words:
                if word in lower:
                    # Extract sentence containing action word
                    sentences = finding.split(".")
                    for sent in sentences:
                        if word in sent.lower():
                            suggestions.append(sent.strip())
                            break

        return suggestions[:5]  # Max 5 suggestions

    def audit(
        self,
        file_path: str,
        focus_areas: Optional[list[str]] = None,
        min_severity: Optional[str] = None,
    ) -> MiniClaudeResponse:
        """
        Audit a file for common issues and anti-patterns.

        Detects:
        - Silent failures (except: pass, empty catch)
        - Missing error handling
        - Hardcoded values that should be configurable
        - TODO/FIXME items
        - Fail-fast violations
        - Type safety issues
        - Security concerns

        Args:
            file_path: Path to the file to audit
            focus_areas: Optional areas to focus on (e.g., ["error_handling", "security"])
            min_severity: Optional minimum severity to report ("critical", "warning", "info")
                          If "critical", only critical issues are shown
                          If "warning", critical + warning issues are shown
                          If "info" or None, all issues are shown

        Returns:
            Audit report with issues, severity, and suggested fixes
        """
        import re
        work_log = WorkLog()
        work_log.what_i_tried.append(f"Auditing {Path(file_path).name}")

        # Read the file
        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="ignore")
            lines = content.splitlines()
            work_log.what_worked.append(f"Read {len(lines)} lines")
        except Exception as e:
            work_log.what_failed.append(f"Failed to read file: {str(e)}")
            return MiniClaudeResponse(
                status="failed",
                confidence="high",
                reasoning=f"Could not read file: {str(e)}",
                work_log=work_log,
            )

        # Determine language from extension
        ext = Path(file_path).suffix.lower()
        language = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".jsx": "javascript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
        }.get(ext, "unknown")

        # Run pattern-based analysis
        issues = self._pattern_audit(content, lines, language)
        work_log.what_worked.append(f"Found {len(issues)} pattern-based issues")

        # Use LLM for deeper analysis if we have context
        llm_analysis = None
        if len(content) < 10000:  # Only for reasonably sized files
            prompt = self._build_audit_prompt(content, language, focus_areas, issues)
            try:
                result = self.llm.generate(prompt)
                if result.get("success"):
                    llm_analysis = result.get("response", "")
                    work_log.what_worked.append("LLM analysis complete")
            except Exception as e:
                work_log.what_failed.append(f"LLM analysis failed: {str(e)}")

        # Filter by minimum severity if specified
        severity_levels = {"critical": 3, "warning": 2, "info": 1}
        if min_severity and min_severity in severity_levels:
            min_level = severity_levels[min_severity]
            issues = [i for i in issues if severity_levels.get(i["severity"], 0) >= min_level]
            work_log.what_worked.append(f"Filtered to {min_severity}+ severity: {len(issues)} issues")

        # Categorize issues
        critical = [i for i in issues if i["severity"] == "critical"]
        warnings = [i for i in issues if i["severity"] == "warning"]
        info = [i for i in issues if i["severity"] == "info"]

        # Determine status
        if critical:
            status = "failed"
            reasoning = f"Found {len(critical)} critical issue(s) that need immediate attention"
        elif warnings:
            status = "partial"
            reasoning = f"Found {len(warnings)} warning(s) to review"
        else:
            status = "success"
            reasoning = "No major issues found"

        # Format warnings for display
        warning_messages = []
        for issue in (critical + warnings)[:10]:
            warning_messages.append(
                f"[{issue['severity'].upper()}] Line {issue['line']}: {issue['message']}"
            )

        # Extract suggestions (quick_fix)
        suggestions = []
        for issue in issues[:5]:
            if issue.get("fix"):
                suggestions.append(f"Line {issue['line']}: {issue['fix']}")

        return MiniClaudeResponse(
            status=status,
            confidence="high" if not llm_analysis else "medium",
            reasoning=reasoning,
            work_log=work_log,
            data={
                "file": file_path,
                "language": language,
                "lines_analyzed": len(lines),
                "critical_count": len(critical),
                "warning_count": len(warnings),
                "info_count": len(info),
                "issues": issues[:20],
                "llm_analysis": llm_analysis,
            },
            warnings=warning_messages,
            suggestions=suggestions,
        )

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
            if '*' in path or '?' in path:
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
                    ".py": "python", ".js": "javascript", ".ts": "typescript",
                    ".tsx": "typescript", ".jsx": "javascript", ".go": "go",
                }.get(ext, "unknown")

                issues = self._pattern_audit(content, lines, language)

                # Filter by severity
                severity_levels = {"critical": 3, "warning": 2, "info": 1}
                if min_severity and min_severity in severity_levels:
                    min_level = severity_levels[min_severity]
                    issues = [i for i in issues if severity_levels.get(i["severity"], 0) >= min_level]

                if issues:
                    files_with_issues.append({
                        "file": file_path,
                        "issue_count": len(issues),
                        "critical": len([i for i in issues if i["severity"] == "critical"]),
                        "warning": len([i for i in issues if i["severity"] == "warning"]),
                        "issues": issues[:5],  # Top 5 issues per file
                    })
                    all_issues.extend([{**i, "file": file_path} for i in issues])
                else:
                    files_clean.append(file_path)

            except Exception as e:
                work_log.what_failed.append(f"Failed to audit {file_path}: {str(e)}")

        # Sort by severity
        critical_files = [f for f in files_with_issues if f["critical"] > 0]
        warning_files = [f for f in files_with_issues if f["critical"] == 0 and f["warning"] > 0]

        total_critical = sum(f["critical"] for f in files_with_issues)
        total_warning = sum(f["warning"] for f in files_with_issues)

        if total_critical > 0:
            status = "failed"
            reasoning = f"Found {total_critical} critical issue(s) across {len(critical_files)} file(s)"
        elif total_warning > 0:
            status = "partial"
            reasoning = f"Found {total_warning} warning(s) across {len(warning_files)} file(s)"
        else:
            status = "success"
            reasoning = f"All {len(files_clean)} file(s) passed audit"

        # Format warnings
        warning_messages = []
        for f in sorted(files_with_issues, key=lambda x: x["critical"], reverse=True)[:10]:
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
            suggestions=[
                f"Fix critical issues in: {', '.join(Path(f['file']).name for f in critical_files[:3])}"
            ] if critical_files else [],
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
            file_extensions = [".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".java", ".rs"]

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
                    content = Path(file_path).read_text(encoding="utf-8", errors="ignore")
                    lines = content.splitlines()

                    for line_num, line in enumerate(lines, 1):
                        match = re.search(issue_pattern, line, re.IGNORECASE)
                        if match:
                            # Skip matches inside string literals
                            if exclude_strings and _is_inside_string_literal(line, match.start()):
                                continue

                            matches.append({
                                "file": file_path,
                                "line": line_num,
                                "code": line.strip()[:100],
                            })

                            if len(matches) >= 100:  # Limit matches
                                break

                except Exception:
                    continue

                if len(matches) >= 100:
                    break
            if len(matches) >= 100:
                break

        work_log.what_worked.append(f"Searched {files_searched} files, found {len(matches)} matches")
        if files_skipped > 0:
            work_log.what_worked.append(f"Skipped {files_skipped} files in excluded paths")

        # Group by file
        files_affected = {}
        for match in matches:
            file = match["file"]
            if file not in files_affected:
                files_affected[file] = []
            files_affected[file].append(match)

        if matches:
            status = "partial"
            reasoning = f"Found {len(matches)} occurrences in {len(files_affected)} file(s)"
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
                for f, m in sorted(files_affected.items(), key=lambda x: len(x[1]), reverse=True)[:10]
            ],
            suggestions=[
                f"Fix pattern in {len(files_affected)} file(s) to prevent similar issues"
            ] if matches else [],
        )

    def _pattern_audit(self, content: str, lines: list[str], language: str) -> list[dict]:
        """Run pattern-based analysis on code."""
        import re
        issues = []

        # Track multiline string state (for skipping docstrings)
        in_multiline_string = False
        multiline_char = None  # '"""' or "'''"

        # Python-specific patterns
        python_patterns = [
            (r"except:\s*pass", "critical", "Silent exception - errors swallowed", "Add error logging: except Exception as e: logger.error(e)"),
            (r"except\s+\w+:\s*pass", "critical", "Silent exception handler", "Log or re-raise the exception"),
            (r"except\s+Exception\s*:", "warning", "Catching broad Exception", "Catch specific exceptions instead"),
            (r"^\s*print\s*\(", "info", "print() statement - consider using logging", "Replace with logging.info() or remove"),
            (r"#\s*(TODO|FIXME|XXX|HACK)", "warning", "TODO/FIXME comment", "Address or create issue to track"),
            (r"open\s*\([^)]+\)\s*(?!\.)", "warning", "File opened without context manager", "Use 'with open(...) as f:' instead"),
            (r"==\s*None\b", "info", "Using == None", "Use 'is None' for None comparisons"),
            (r"!=\s*None\b", "info", "Using != None", "Use 'is not None' for None comparisons"),
            (r"\beval\s*\(", "critical", "eval() usage - security risk", "Avoid eval(), use ast.literal_eval() for data"),
            (r"\bexec\s*\(", "critical", "exec() usage - security risk", "Avoid exec(), find safer alternatives"),
            (r"import\s+pickle", "warning", "pickle import - security risk with untrusted data", "Use json for serialization if possible"),
            (r"subprocess\.(call|run|Popen)\s*\([^)]*shell\s*=\s*True", "critical", "subprocess with shell=True - injection risk", "Use shell=False with list of arguments"),
        ]

        # JavaScript/TypeScript patterns
        js_patterns = [
            (r"catch\s*\([^)]*\)\s*\{\s*\}", "critical", "Empty catch block", "Add error handling or logging"),
            (r"console\.(log|debug|info)\s*\(", "info", "console.log - remove for production", "Use proper logging or remove"),
            (r"\beval\s*\(", "critical", "eval() usage - XSS risk", "Avoid eval(), use JSON.parse() for data"),
            (r"innerHTML\s*=", "warning", "innerHTML assignment - XSS risk", "Use textContent or sanitize input"),
            (r"document\.write\s*\(", "critical", "document.write - XSS risk", "Use DOM manipulation methods"),
            (r"//\s*(TODO|FIXME|XXX|HACK)", "warning", "TODO/FIXME comment", "Address or create issue"),
            (r"@ts-ignore", "warning", "@ts-ignore - type error suppressed", "Fix the type error instead"),
            (r"any\s*[;,\)]", "info", "'any' type used", "Use specific types for better safety"),
            (r"as\s+any\b", "warning", "Type assertion to 'any'", "Use proper type assertion"),
        ]

        # Go patterns
        go_patterns = [
            (r"_\s*=\s*\w+\.\w+\(", "warning", "Error ignored with _", "Handle or explicitly ignore with comment"),
            (r"//\s*(TODO|FIXME|XXX)", "warning", "TODO/FIXME comment", "Address or create issue"),
            (r"panic\s*\(", "warning", "panic() call - use sparingly", "Return error instead if possible"),
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
                (r"TODO|FIXME|XXX|HACK", "warning", "TODO/FIXME comment", "Address before committing"),
                (r"password\s*=\s*['\"][^'\"]+['\"]", "critical", "Hardcoded password", "Use environment variable"),
                (r"api_?key\s*=\s*['\"][^'\"]+['\"]", "critical", "Hardcoded API key", "Use environment variable"),
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

                    issues.append({
                        "line": line_num,
                        "severity": severity,
                        "message": message,
                        "fix": fix,
                        "code": line.strip()[:80],
                    })

        return issues

    def _build_audit_prompt(
        self,
        content: str,
        language: str,
        focus_areas: Optional[list[str]],
        existing_issues: list[dict],
    ) -> str:
        """Build prompt for LLM audit analysis."""
        focus_text = ""
        if focus_areas:
            focus_text = f"\n\nFocus especially on: {', '.join(focus_areas)}"

        existing_text = ""
        if existing_issues:
            existing_text = "\n\nAlready found issues:\n" + "\n".join(
                f"- Line {i['line']}: {i['message']}"
                for i in existing_issues[:5]
            )

        # Add line numbers to help LLM give accurate references
        lines = content.split('\n')
        numbered_content = '\n'.join(
            f"{i+1:4d}| {line}" for i, line in enumerate(lines[:200])  # Limit to 200 lines
        )
        if len(lines) > 200:
            numbered_content += f"\n... ({len(lines) - 200} more lines truncated)"

        return f"""Audit this {language} code for issues I might have missed.

CODE (with line numbers):
```{language}
{numbered_content}
```
{existing_text}

Look for:
1. Silent failures (errors being swallowed)
2. Missing error handling for I/O operations
3. Security vulnerabilities
4. Logic errors
5. Code that could fail silently
6. Hardcoded values that should be configurable
{focus_text}

IMPORTANT: Only reference line numbers that appear in the code above. Do NOT make up line numbers.

For each issue found, provide EXACTLY this format:
- Line [NUMBER]: [SEVERITY] - [DESCRIPTION]. Fix: [SUGGESTION]

Example: "Line 42: warning - Exception caught but not logged. Fix: Add logging.error(e)"

Be concise. Only report real issues, not style preferences.
If the code looks fine, say "No additional issues found." """
