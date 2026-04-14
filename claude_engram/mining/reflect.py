"""
Reflect — synthesize new insights from existing memories and patterns.

Inspired by Hindsight's reflect operation. Instead of just storing and
retrieving memories, this actively reasons over them to find root causes,
connections, and actionable insights.

Uses Ollama (local LLM) for synthesis. Optional — if Ollama isn't running,
reflect operations are skipped silently.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Insight:
    """A synthesized insight from reflecting on memories."""

    content: str  # The insight text
    insight_type: str  # "root_cause" | "pattern" | "recommendation" | "connection"
    source_memories: list[str] = field(
        default_factory=list
    )  # Memory IDs that led to this
    confidence: float = 0.0
    related_files: list[str] = field(default_factory=list)


def reflect_on_mistakes(
    project_path: str,
    engram_storage_dir: str = "~/.claude_engram",
) -> list[Insight]:
    """
    Analyze recurring mistakes to find root causes.

    Groups mistakes by file/error type, then uses LLM to synthesize
    why they keep happening and what the underlying fix is.
    """
    storage = Path(engram_storage_dir).expanduser()
    manifest_path = storage / "manifest.json"
    if not manifest_path.exists():
        return []

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    norm_path = _normalize_path(project_path)

    # Collect mistakes from this project + parent workspace
    all_mistakes = []
    current = norm_path
    while True:
        if current in manifest.get("projects", {}):
            hash_dir = storage / "projects" / manifest["projects"][current]["hash"]
            mem_file = hash_dir / "memory.json"
            if mem_file.exists():
                data = json.loads(mem_file.read_text(encoding="utf-8"))
                for e in data.get("entries", []):
                    if e.get("category") == "mistake":
                        all_mistakes.append(e)
        parent = str(Path(current).parent).replace("\\", "/")
        if parent == current:
            break
        current = parent

    if len(all_mistakes) < 3:
        return []

    # Group by error type (first word after "MISTAKE:")
    import re

    groups: dict[str, list[dict]] = {}
    for m in all_mistakes:
        content = m.get("content", "")
        match = re.match(
            r"MISTAKE:\s*(\w+Error|Import error|Syntax error|Type error|Attribute error)",
            content,
        )
        if match:
            key = match.group(1)
        else:
            key = "other"
        groups.setdefault(key, []).append(m)

    # Only reflect on groups with 3+ mistakes (recurring)
    insights = []
    llm = _get_llm()
    if not llm:
        return []

    for error_type, mistakes in groups.items():
        if len(mistakes) < 3:
            continue

        # Build context for LLM
        mistake_texts = "\n".join(
            f"- {m.get('content', '')[:150]}"
            for m in mistakes[:10]  # Cap at 10 to keep prompt short
        )
        files = set()
        for m in mistakes:
            for f in m.get("related_files", []):
                files.add(Path(f).name)

        prompt = f"""These {len(mistakes)} errors keep recurring in this project:

{mistake_texts}

Files involved: {', '.join(files) if files else 'various'}

In 2-3 sentences: What's the likely root cause? What should be done differently to prevent these?
Output ONLY the analysis, no preamble."""

        result = llm.generate(prompt=prompt, temperature=0.1)
        if result.get("success") and result.get("response"):
            response = result["response"].strip()
            if len(response) > 20:
                insights.append(
                    Insight(
                        content=response[:500],
                        insight_type="root_cause",
                        source_memories=[m.get("id", "") for m in mistakes[:10]],
                        confidence=min(len(mistakes) / 10, 1.0),
                        related_files=sorted(files)[:10],
                    )
                )

    return insights


def reflect_on_patterns(
    project_path: str,
    engram_storage_dir: str = "~/.claude_engram",
) -> list[Insight]:
    """
    Analyze edit correlations and struggles to find architectural insights.
    """
    storage = Path(engram_storage_dir).expanduser()
    manifest = json.loads((storage / "manifest.json").read_text(encoding="utf-8"))
    norm_path = _normalize_path(project_path)

    # Walk up to find patterns.json
    current = norm_path
    patterns_data = None
    while True:
        if current in manifest.get("projects", {}):
            hash_dir = storage / "projects" / manifest["projects"][current]["hash"]
            patterns_file = hash_dir / "patterns.json"
            if patterns_file.exists():
                patterns_data = json.loads(patterns_file.read_text(encoding="utf-8"))
                break
        parent = str(Path(current).parent).replace("\\", "/")
        if parent == current:
            break
        current = parent

    if not patterns_data:
        return []

    insights = []
    llm = _get_llm()
    if not llm:
        return []

    # Reflect on struggles
    struggles = patterns_data.get("struggles", [])[:5]
    correlations = patterns_data.get("correlations", [])[:5]

    if struggles:
        struggle_text = "\n".join(
            f"- {s['file_path']}: {s['sessions_affected']} sessions, {s['errors_nearby']} with errors"
            for s in struggles
        )

        prompt = f"""These files are repeatedly problematic in this project:

{struggle_text}

In 2-3 sentences: What does this pattern suggest about the architecture? What would reduce the churn?
Output ONLY the analysis."""

        result = llm.generate(prompt=prompt, temperature=0.1)
        if result.get("success") and result.get("response"):
            response = result["response"].strip()
            if len(response) > 20:
                insights.append(
                    Insight(
                        content=response[:500],
                        insight_type="pattern",
                        related_files=[s["file_path"] for s in struggles],
                        confidence=0.7,
                    )
                )

    if correlations:
        corr_text = "\n".join(
            f"- {c['file_a']} <-> {c['file_b']}: {c['strength']:.0%} correlation"
            for c in correlations
        )

        prompt = f"""These files are almost always edited together:

{corr_text}

In 1-2 sentences: What does this suggest? Should any be merged or refactored?
Output ONLY the analysis."""

        result = llm.generate(prompt=prompt, temperature=0.1)
        if result.get("success") and result.get("response"):
            response = result["response"].strip()
            if len(response) > 20:
                insights.append(
                    Insight(
                        content=response[:500],
                        insight_type="connection",
                        confidence=0.6,
                    )
                )

    return insights


def reflect_on_decisions(
    project_path: str,
    engram_storage_dir: str = "~/.claude_engram",
) -> list[Insight]:
    """
    Analyze decisions to find conflicts or patterns.
    """
    storage = Path(engram_storage_dir).expanduser()
    manifest = json.loads((storage / "manifest.json").read_text(encoding="utf-8"))
    norm_path = _normalize_path(project_path)

    all_decisions = []
    current = norm_path
    while True:
        if current in manifest.get("projects", {}):
            hash_dir = storage / "projects" / manifest["projects"][current]["hash"]
            mem_file = hash_dir / "memory.json"
            if mem_file.exists():
                data = json.loads(mem_file.read_text(encoding="utf-8"))
                for e in data.get("entries", []):
                    if e.get("category") == "decision":
                        all_decisions.append(e)
        parent = str(Path(current).parent).replace("\\", "/")
        if parent == current:
            break
        current = parent

    if len(all_decisions) < 3:
        return []

    llm = _get_llm()
    if not llm:
        return []

    decision_texts = "\n".join(
        f"- {d.get('content', '')[:150]}" for d in all_decisions[:15]
    )

    prompt = f"""These decisions have been made in this project:

{decision_texts}

In 2-3 sentences: Are any contradictory? Any patterns? Any that should be revisited?
Output ONLY the analysis."""

    result = llm.generate(prompt=prompt, temperature=0.1)
    insights = []
    if result.get("success") and result.get("response"):
        response = result["response"].strip()
        if len(response) > 20:
            insights.append(
                Insight(
                    content=response[:500],
                    insight_type="recommendation",
                    source_memories=[d.get("id", "") for d in all_decisions[:15]],
                    confidence=0.6,
                )
            )

    return insights


def reflect_all(
    project_path: str,
    engram_storage_dir: str = "~/.claude_engram",
) -> list[Insight]:
    """
    Run all reflect operations in a single LLM call.

    Gathers all data (mistakes, patterns, decisions), builds one comprehensive
    prompt, makes one Ollama call. ~4-6s instead of 12-16s with separate calls.
    """
    storage = Path(engram_storage_dir).expanduser()
    manifest_path = storage / "manifest.json"
    if not manifest_path.exists():
        return []

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    norm_path = _normalize_path(project_path)

    # Collect all data
    all_mistakes = []
    all_decisions = []
    patterns_data = None

    current = norm_path
    while True:
        if current in manifest.get("projects", {}):
            hash_dir = storage / "projects" / manifest["projects"][current]["hash"]
            mem_file = hash_dir / "memory.json"
            if mem_file.exists():
                data = json.loads(mem_file.read_text(encoding="utf-8"))
                for e in data.get("entries", []):
                    if e.get("category") == "mistake":
                        all_mistakes.append(e)
                    elif e.get("category") == "decision":
                        all_decisions.append(e)
            patterns_file = hash_dir / "patterns.json"
            if patterns_file.exists() and not patterns_data:
                patterns_data = json.loads(patterns_file.read_text(encoding="utf-8"))
        parent = str(Path(current).parent).replace("\\", "/")
        if parent == current:
            break
        current = parent

    if len(all_mistakes) < 3 and not patterns_data and len(all_decisions) < 3:
        return []

    llm = _get_llm()
    if not llm:
        return []

    # Build one comprehensive prompt
    import re

    sections = []

    # Group mistakes by error type
    error_groups: dict[str, list[str]] = {}
    for m in all_mistakes:
        content = m.get("content", "")
        match = re.match(r"MISTAKE:\s*(\w+\s*error|\w+Error)", content, re.I)
        key = match.group(1) if match else "other"
        error_groups.setdefault(key, []).append(content[:100])

    recurring = {k: v for k, v in error_groups.items() if len(v) >= 3}
    if recurring:
        sections.append("RECURRING ERRORS:")
        for error_type, items in list(recurring.items())[:5]:
            sections.append(f"  {error_type} ({len(items)} times):")
            for item in items[:3]:
                sections.append(f"    - {item}")

    if patterns_data:
        struggles = patterns_data.get("struggles", [])[:5]
        if struggles:
            sections.append("\nSTRUGGLE FILES:")
            for s in struggles:
                sections.append(
                    f"  - {s['file_path']}: {s['sessions_affected']} sessions, {s['errors_nearby']} errors"
                )

        correlations = patterns_data.get("correlations", [])[:5]
        if correlations:
            sections.append("\nFILES ALWAYS EDITED TOGETHER:")
            for c in correlations:
                sections.append(
                    f"  - {c['file_a']} <-> {c['file_b']}: {c['strength']:.0%}"
                )

    if all_decisions:
        sections.append("\nKEY DECISIONS:")
        for d in all_decisions[:10]:
            sections.append(f"  - {d.get('content', '')[:120]}")

    if not sections:
        return []

    prompt = f"""Analyze this project's history and provide insights:

{chr(10).join(sections)}

For each category present, give 1-2 sentences of analysis:
1. ROOT CAUSES: Why do errors recur? What's the underlying issue?
2. ARCHITECTURE: What do struggle files and correlations suggest?
3. DECISIONS: Any contradictions or patterns to revisit?

Be specific and actionable. Output ONLY the analysis, no preamble."""

    result = llm.generate(prompt=prompt, temperature=0.1, timeout=30)
    if not result.get("success") or not result.get("response"):
        # Fall back to individual calls if single prompt fails
        insights = []
        insights.extend(reflect_on_mistakes(project_path, engram_storage_dir))
        insights.extend(reflect_on_patterns(project_path, engram_storage_dir))
        insights.extend(reflect_on_decisions(project_path, engram_storage_dir))
        return insights

    # Parse response into insights by splitting on section headers
    response = result["response"].strip()
    insights = []

    # Split response into sections by numbered headers or keywords
    import re as _re

    sections = _re.split(
        r"\n\s*(?=\d+\.\s*\*?\*?(?:ROOT|ARCHITECTURE|DECISION))",
        response,
        flags=_re.IGNORECASE,
    )

    for section in sections:
        section = section.strip()
        if len(section) < 20:
            continue

        lower = section.lower()
        if "root cause" in lower or "error" in lower[:50]:
            insights.append(
                Insight(
                    content=section[:500],
                    insight_type="root_cause",
                    source_memories=[m.get("id", "") for m in all_mistakes[:10]],
                    confidence=min(len(all_mistakes) / 10, 1.0),
                )
            )
        elif (
            "architecture" in lower
            or "struggle" in lower[:50]
            or "correlation" in lower[:50]
        ):
            insights.append(
                Insight(
                    content=section[:500],
                    insight_type="pattern",
                    related_files=[
                        s["file_path"]
                        for s in (patterns_data or {}).get("struggles", [])[:5]
                    ],
                    confidence=0.7,
                )
            )
        elif "decision" in lower or "contradict" in lower[:50]:
            insights.append(
                Insight(
                    content=section[:500],
                    insight_type="recommendation",
                    source_memories=[d.get("id", "") for d in all_decisions[:10]],
                    confidence=0.6,
                )
            )

    # If parsing found nothing, store the whole response as one insight
    if not insights and len(response) > 20:
        insights.append(
            Insight(
                content=response[:500],
                insight_type="root_cause",
                confidence=0.5,
            )
        )

    return insights


def _get_llm():
    """Get Ollama LLM client. Returns None if unavailable."""
    try:
        from claude_engram.llm import LLMClient

        llm = LLMClient()
        health = llm.health_check()
        if health.get("healthy"):
            return llm
        llm.close()
    except Exception:
        pass
    return None


def _normalize_path(project_path: str) -> str:
    norm = str(Path(project_path).resolve()).replace("\\", "/")
    if len(norm) >= 2 and norm[1] == ":":
        norm = norm[0].lower() + norm[1:]
    return norm
