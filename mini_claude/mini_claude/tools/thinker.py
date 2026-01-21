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

    def research(
        self,
        question: str,
        context: Optional[str] = None,
        depth: str = "medium",
        project_path: Optional[str] = None,
    ) -> MiniClaudeResponse:
        """
        Deep research on a question using web + codebase + reasoning.

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

        # Step 1: Web search for current best practices
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

        # Step 2: Search codebase for existing patterns (if project provided)
        if project_path:
            try:
                codebase_results = self.search.search(
                    query=question,
                    directory=project_path,
                    max_results=5,
                )
                if codebase_results.data and codebase_results.data.get("findings"):
                    findings.append("\n## Existing Patterns in Codebase")
                    for finding in codebase_results.data["findings"][:3]:
                        if isinstance(finding, dict):
                            findings.append(f"- {finding.get('file', 'unknown')}: {finding.get('summary', '')}")
                        else:
                            findings.append(f"- {str(finding)}")
                    work_log.what_worked.append("Found existing patterns in codebase")
            except Exception as e:
                work_log.what_failed.append(f"Codebase search failed: {str(e)}")

        # Step 3: Use LLM to reason about findings
        reasoning_prompt = self._build_research_prompt(question, context, findings, depth)

        try:
            result = self.llm.generate(reasoning_prompt)
            if result.get("success"):
                reasoning = result.get("response", "")
                findings.append("\n## Analysis")
                findings.append(reasoning)
                work_log.what_worked.append("Generated reasoning with LLM")
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
    ) -> str:
        """Build prompt for LLM reasoning about research."""
        prompt = f"""Analyze this research question:

Question: {question}
{f'Context: {context}' if context else ''}

Research findings:
{chr(10).join(findings) if findings else 'No web/codebase findings available'}

Provide a thoughtful analysis that:
1. Directly answers the question
2. Synthesizes the findings
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
