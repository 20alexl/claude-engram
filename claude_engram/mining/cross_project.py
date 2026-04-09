"""
Cross-project learning — patterns that hold across ALL projects.

Aggregates session indexes from all projects to find:
  - Universal struggle patterns (e.g., "always struggles with path normalization")
  - Common error types across projects
  - Workflow patterns (tool usage ratios, session durations)
  - Skills that transfer (file types, frameworks seen across projects)
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class CrossProjectInsight:
    """An insight derived from multiple projects."""
    insight_type: str     # "error_pattern" | "struggle" | "workflow" | "tool_preference"
    description: str
    projects_affected: list[str] = field(default_factory=list)
    frequency: int = 0
    confidence: float = 0.0


@dataclass
class CrossProjectReport:
    """Aggregated insights across all projects."""
    total_projects: int = 0
    total_sessions: int = 0
    total_messages: int = 0
    insights: list[CrossProjectInsight] = field(default_factory=list)
    common_errors: list[dict] = field(default_factory=list)
    tool_usage: dict[str, int] = field(default_factory=dict)


def analyze_cross_project(
    engram_storage_dir: str = "~/.claude_engram",
) -> CrossProjectReport:
    """
    Analyze patterns across all projects.

    Reads session indexes from all project directories in the manifest
    and aggregates insights.
    """
    storage = Path(engram_storage_dir).expanduser()
    manifest_path = storage / "manifest.json"
    if not manifest_path.exists():
        return CrossProjectReport()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    projects = manifest.get("projects", {})

    report = CrossProjectReport()
    report.total_projects = len(projects)

    # Aggregate across all projects
    all_errors: Counter = Counter()       # error_type -> count
    error_projects: dict[str, set] = {}   # error_type -> set of project names
    all_struggles: Counter = Counter()     # filename -> count
    struggle_projects: dict[str, set] = {}
    all_tools: Counter = Counter()        # tool -> count
    all_file_types: Counter = Counter()   # extension -> count

    for proj_path, proj_info in projects.items():
        proj_name = proj_info.get("name", Path(proj_path).name)
        hash_dir = storage / "projects" / proj_info["hash"]

        # Read session index
        idx_path = hash_dir / "session_index.json"
        if not idx_path.exists():
            continue

        try:
            idx_data = json.loads(idx_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        sessions = idx_data.get("sessions", {})
        report.total_sessions += len(sessions)

        for sid, meta in sessions.items():
            report.total_messages += meta.get("message_count", 0)

            # Aggregate tool usage
            for tool, count in meta.get("tools_used", {}).items():
                all_tools[tool] += count

            # Aggregate file types
            for fp in meta.get("files_edited", []):
                ext = Path(fp).suffix
                if ext:
                    all_file_types[ext] += 1

            # Track files edited in error sessions
            if meta.get("error_count", 0) > 0:
                for fp in meta.get("files_edited", []):
                    name = Path(fp).name
                    all_struggles[name] += 1
                    struggle_projects.setdefault(name, set()).add(proj_name)

        # Read extractions for error patterns
        ext_dir = hash_dir / "extractions"
        if ext_dir.exists():
            for ext_file in ext_dir.glob("*.json"):
                try:
                    ext_data = json.loads(ext_file.read_text(encoding="utf-8"))
                    for mistake in ext_data.get("mistakes", []):
                        error_type = mistake.get("error_type", "")
                        if error_type:
                            all_errors[error_type] += 1
                            error_projects.setdefault(error_type, set()).add(proj_name)
                except Exception:
                    continue

    # Build insights

    # Common errors across projects
    for error_type, count in all_errors.most_common(10):
        projs = error_projects.get(error_type, set())
        if len(projs) >= 2:
            report.insights.append(CrossProjectInsight(
                insight_type="error_pattern",
                description=f"{error_type} occurs across {len(projs)} projects ({count} total)",
                projects_affected=sorted(projs),
                frequency=count,
                confidence=min(len(projs) / report.total_projects, 1.0),
            ))
        report.common_errors.append({
            "error_type": error_type,
            "count": count,
            "projects": sorted(projs),
        })

    # Cross-project struggles (files that cause problems everywhere)
    for name, count in all_struggles.most_common(10):
        projs = struggle_projects.get(name, set())
        if len(projs) >= 2:
            report.insights.append(CrossProjectInsight(
                insight_type="struggle",
                description=f"{name} involved in errors across {len(projs)} projects",
                projects_affected=sorted(projs),
                frequency=count,
                confidence=min(len(projs) / report.total_projects, 1.0),
            ))

    # Tool usage patterns
    report.tool_usage = dict(all_tools.most_common(20))

    # Workflow insight: Read/Edit ratio
    reads = all_tools.get("Read", 0)
    edits = all_tools.get("Edit", 0) + all_tools.get("Write", 0)
    if reads > 0 and edits > 0:
        ratio = reads / edits
        if ratio > 3:
            report.insights.append(CrossProjectInsight(
                insight_type="workflow",
                description=f"Read/Edit ratio is {ratio:.1f}:1 — lots of exploration before editing",
                frequency=reads + edits,
                confidence=0.8,
            ))

    return report
