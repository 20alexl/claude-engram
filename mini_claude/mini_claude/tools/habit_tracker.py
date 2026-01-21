"""
Habit Tracker - Track tool usage patterns and provide habit formation feedback.

Solves the problem: Claude doesn't develop good habits because there's no feedback loop.

Features:
- Track when Thinker tools are used (or NOT used) before risky work
- Show habit formation metrics
- Gamify good practices
- Provide specific encouragement or warnings based on patterns
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict


@dataclass
class HabitEvent:
    """Record of a habit-relevant event."""
    timestamp: str
    event_type: str  # "thinker_used", "risky_edit_without_thinking", "loop_avoided", etc.
    context: str  # What was happening (e.g., "editing auth.py", "implementing payment")
    tool_used: Optional[str] = None  # Which tool was used (if any)


class HabitTracker:
    """Track and analyze tool usage habits."""

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.habit_file = self.state_dir / "habits.json"

        # Within-session tracking (in-memory, not persisted until session end)
        self._session_tools_used: List[Dict] = []  # Tools called this session
        self._session_files_edited: List[str] = []  # Files edited this session
        self._session_decisions_logged: int = 0
        self._session_mistakes_logged: int = 0
        self._session_start_time: Optional[datetime] = None

    def start_session(self):
        """Start a new session for tracking."""
        self._session_tools_used = []
        self._session_files_edited = []
        self._session_decisions_logged = 0
        self._session_mistakes_logged = 0
        self._session_start_time = datetime.now()

    def record_session_tool_use(self, tool_name: str, context: str = ""):
        """Record a tool being used in the current session."""
        self._session_tools_used.append({
            "tool": tool_name,
            "context": context,
            "timestamp": datetime.now().isoformat()
        })

    def record_session_file_edit(self, file_path: str):
        """Record a file being edited in the current session."""
        if file_path not in self._session_files_edited:
            self._session_files_edited.append(file_path)

    def record_session_decision(self):
        """Record a decision being logged in the current session."""
        self._session_decisions_logged += 1

    def record_session_mistake(self):
        """Record a mistake being logged in the current session."""
        self._session_mistakes_logged += 1

    def get_session_stats(self) -> Dict:
        """Get statistics for the current session."""
        # Categorize tools used
        thinker_tools = [t for t in self._session_tools_used
                        if t["tool"].startswith("think_")]
        memory_tools = [t for t in self._session_tools_used
                       if t["tool"] in ["memory_remember", "memory_recall", "session_start"]]
        work_tools = [t for t in self._session_tools_used
                     if t["tool"].startswith("work_")]
        safety_tools = [t for t in self._session_tools_used
                       if t["tool"].startswith(("loop_", "scope_", "diff_review", "think_audit"))]

        return {
            "session_active": self._session_start_time is not None,
            "session_duration_minutes": (
                (datetime.now() - self._session_start_time).total_seconds() / 60
                if self._session_start_time else 0
            ),
            "total_tools_used": len(self._session_tools_used),
            "thinker_tools_used": len(thinker_tools),
            "memory_tools_used": len(memory_tools),
            "work_tools_used": len(work_tools),
            "safety_tools_used": len(safety_tools),
            "files_edited": len(self._session_files_edited),
            "decisions_logged": self._session_decisions_logged,
            "mistakes_logged": self._session_mistakes_logged,
            "tools_breakdown": self._get_tool_counts(),
        }

    def _get_tool_counts(self) -> Dict[str, int]:
        """Get counts of each tool used this session."""
        counts = {}
        for t in self._session_tools_used:
            tool = t["tool"]
            counts[tool] = counts.get(tool, 0) + 1
        return counts

    def _load_habits(self) -> Dict:
        """Load habit history."""
        if not self.habit_file.exists():
            return {
                "events": [],
                "stats": {
                    "thinker_before_risky": 0,
                    "risky_without_thinking": 0,
                    "loops_avoided": 0,
                    "loops_hit": 0,
                }
            }

        try:
            with open(self.habit_file) as f:
                return json.load(f)
        except Exception:
            return {"events": [], "stats": {}}

    def _save_habits(self, data: Dict):
        """Save habit history."""
        with open(self.habit_file, 'w') as f:
            json.dump(data, f, indent=2)

    def record_thinker_use(self, tool: str, context: str):
        """Record that a Thinker tool was used."""
        data = self._load_habits()

        event = HabitEvent(
            timestamp=datetime.now().isoformat(),
            event_type="thinker_used",
            context=context,
            tool_used=tool
        )

        data["events"].append(asdict(event))
        data["stats"]["thinker_before_risky"] = data["stats"].get("thinker_before_risky", 0) + 1

        self._save_habits(data)

    def record_risky_edit_without_thinking(self, file_path: str, risk_reason: str):
        """Record that a risky file was edited without using Thinker tools."""
        data = self._load_habits()

        event = HabitEvent(
            timestamp=datetime.now().isoformat(),
            event_type="risky_edit_without_thinking",
            context=f"{file_path} ({risk_reason})"
        )

        data["events"].append(asdict(event))
        data["stats"]["risky_without_thinking"] = data["stats"].get("risky_without_thinking", 0) + 1

        self._save_habits(data)

    def record_loop_avoided(self, file_path: str):
        """Record that a potential loop was avoided (used Thinker after warning)."""
        data = self._load_habits()

        event = HabitEvent(
            timestamp=datetime.now().isoformat(),
            event_type="loop_avoided",
            context=file_path
        )

        data["events"].append(asdict(event))
        data["stats"]["loops_avoided"] = data["stats"].get("loops_avoided", 0) + 1

        self._save_habits(data)

    def record_loop_hit(self, file_path: str, edit_count: int):
        """Record that a loop was actually hit (3+ edits)."""
        data = self._load_habits()

        event = HabitEvent(
            timestamp=datetime.now().isoformat(),
            event_type="loop_hit",
            context=f"{file_path} ({edit_count} edits)"
        )

        data["events"].append(asdict(event))
        data["stats"]["loops_hit"] = data["stats"].get("loops_hit", 0) + 1

        self._save_habits(data)

    def get_habit_stats(self, days: int = 7) -> Dict:
        """Get habit statistics for the last N days, including current session."""
        data = self._load_habits()

        # Filter events to last N days
        cutoff = datetime.now() - timedelta(days=days)
        recent_events = [
            e for e in data["events"]
            if datetime.fromisoformat(e["timestamp"]) > cutoff
        ]

        # Calculate historical stats
        thinker_used = len([e for e in recent_events if e["event_type"] == "thinker_used"])
        risky_without = len([e for e in recent_events if e["event_type"] == "risky_edit_without_thinking"])
        loops_avoided = len([e for e in recent_events if e["event_type"] == "loop_avoided"])
        loops_hit = len([e for e in recent_events if e["event_type"] == "loop_hit"])

        # Calculate percentages
        risky_total = thinker_used + risky_without
        think_rate = (thinker_used / risky_total * 100) if risky_total > 0 else 0

        loop_total = loops_avoided + loops_hit
        loop_avoid_rate = (loops_avoided / loop_total * 100) if loop_total > 0 else 0

        # Include current session stats
        session_stats = self.get_session_stats()

        return {
            "days": days,
            "thinker_used": thinker_used,
            "risky_without_thinking": risky_without,
            "think_rate": think_rate,
            "loops_avoided": loops_avoided,
            "loops_hit": loops_hit,
            "loop_avoid_rate": loop_avoid_rate,
            "total_stats": data["stats"],
            "current_session": session_stats,  # Include session data
        }

    def get_recent_thinker_usage(self, context_pattern: str, limit: int = 5) -> List[Dict]:
        """
        Get recent Thinker tool usage for a specific context (e.g., "auth", "payment").

        Returns list of recent events matching the pattern.
        """
        data = self._load_habits()

        matching = [
            e for e in data["events"]
            if context_pattern.lower() in e.get("context", "").lower()
        ]

        # Return most recent first
        matching.reverse()
        return matching[:limit]

    def get_habit_feedback(self) -> str:
        """
        Generate encouraging or warning feedback based on habits.

        Returns formatted feedback string for display.
        """
        stats = self.get_habit_stats(days=7)
        session_stats = self.get_session_stats()

        lines = []

        # Check if this is first-time use (no historical data)
        total_historical = (stats["thinker_used"] + stats["risky_without_thinking"] +
                           stats["loops_avoided"] + stats["loops_hit"])

        # If no historical data, show session-based feedback instead
        if total_historical == 0:
            return self._get_session_feedback(session_stats)

        lines.append("📊 Your Habits (last 7 days):")
        lines.append("")

        # Thinking before risky work
        think_rate = stats["think_rate"]
        if think_rate >= 80:
            lines.append(f"✅ Excellent! You used Thinker tools {think_rate:.0f}% of the time before risky work")
            lines.append("   Keep building this habit!")
        elif think_rate >= 50:
            lines.append(f"⚠️  You used Thinker tools {think_rate:.0f}% of the time before risky work")
            lines.append("   Goal: 80%+ for better quality")
        elif think_rate > 0:
            lines.append(f"🔴 You only used Thinker tools {think_rate:.0f}% of the time before risky work")
            lines.append("   This is why bugs happen. Try to think before coding!")
        else:
            if stats["risky_without_thinking"] > 0:
                lines.append("🔴 You haven't used Thinker tools at all before risky work")
                lines.append("   Start small: try think_explore on your next architectural task")

        lines.append("")

        # Loop avoidance
        loop_avoid_rate = stats["loop_avoid_rate"]
        if stats["loops_hit"] == 0 and stats["loops_avoided"] > 0:
            lines.append(f"🌟 Perfect! You avoided {stats['loops_avoided']} potential loop(s)")
        elif loop_avoid_rate >= 75:
            lines.append(f"✅ Good loop awareness! {loop_avoid_rate:.0f}% avoided")
        elif stats["loops_hit"] > 0:
            lines.append(f"⚠️  Hit {stats['loops_hit']} loop(s). When stuck, step back and think!")

        lines.append("")

        # Show which specific Thinker tools were used
        data = self._load_habits()
        cutoff = datetime.now() - timedelta(days=7)
        recent_thinker_events = [
            e for e in data["events"]
            if e["event_type"] == "thinker_used" and
            datetime.fromisoformat(e["timestamp"]) > cutoff
        ]

        if recent_thinker_events:
            # Count tool usage
            tool_counts = {}
            for event in recent_thinker_events:
                tool = event.get("tool_used", "unknown")
                tool_counts[tool] = tool_counts.get(tool, 0) + 1

            lines.append("🧠 Thinker Tools Used:")
            for tool, count in sorted(tool_counts.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"  • {tool}: {count}x")
            lines.append("")
        elif stats["risky_without_thinking"] > 0:
            # No Thinker tools used but risky work done
            lines.append("💡 Thinker Tools You Should Try:")
            lines.append("  • think_best_practice: Check 2026 standards before implementing")
            lines.append("  • think_explore: See all options before choosing")
            lines.append("  • think_compare: Weigh pros/cons of approaches")
            lines.append("  • think_challenge: Question your assumptions")
            lines.append("")

        return "\n".join(lines)

    def _get_session_feedback(self, session_stats: Dict) -> str:
        """
        Generate feedback based on current session activity.

        Used when there's no historical data yet - gives immediate feedback
        instead of "Just getting started!".
        """
        lines = []
        lines.append("📊 This Session:")
        lines.append("")

        total_tools = session_stats.get("total_tools_used", 0)

        if total_tools == 0:
            # Session just started, no activity yet
            lines.append("🌱 Session just started!")
            lines.append("")
            lines.append("Mini Claude will track your habits as you work:")
            lines.append("  • Using Thinker tools before risky work")
            lines.append("  • Logging decisions and mistakes")
            lines.append("  • Building good coding practices")
            lines.append("")
            lines.append("💡 Quick Start:")
            lines.append("  1. On your next architectural task, try think_explore")
            lines.append("  2. When editing auth/security files, use think_best_practice")
            lines.append("  3. If you edit the same file 3+ times, check think_challenge")
        else:
            # We have session activity - show it!
            thinker_count = session_stats.get("thinker_tools_used", 0)
            files_edited = session_stats.get("files_edited", 0)
            decisions = session_stats.get("decisions_logged", 0)
            mistakes = session_stats.get("mistakes_logged", 0)
            duration = session_stats.get("session_duration_minutes", 0)

            # Duration info
            if duration > 1:
                lines.append(f"⏱️  Session duration: {duration:.0f} minutes")
                lines.append("")

            # Thinker tools feedback
            if thinker_count > 0:
                lines.append(f"✅ Great! You used Thinker tools {thinker_count}x this session")
                # Show which ones
                tool_counts = session_stats.get("tools_breakdown", {})
                thinker_tools = {k: v for k, v in tool_counts.items() if k.startswith("think_")}
                if thinker_tools:
                    for tool, count in sorted(thinker_tools.items(), key=lambda x: x[1], reverse=True):
                        lines.append(f"   • {tool}: {count}x")
            elif files_edited > 0:
                lines.append(f"⚠️  You've edited {files_edited} file(s) without using Thinker tools")
                lines.append("   Consider: think_explore, think_best_practice, or think_challenge")

            lines.append("")

            # Decision logging feedback
            if decisions > 0:
                lines.append(f"📝 Logged {decisions} decision(s) - future you will thank you!")
            elif files_edited >= 2:
                lines.append("💡 Tip: Use work_log_decision to explain WHY you made choices")

            # Mistake logging feedback
            if mistakes > 0:
                lines.append(f"🔧 Logged {mistakes} mistake(s) - you won't repeat them!")

            # Overall assessment
            lines.append("")
            if thinker_count > 0 and decisions > 0:
                lines.append("🌟 Excellent habits this session! Keep it up!")
            elif thinker_count > 0:
                lines.append("👍 Good use of Thinker tools! Consider logging decisions too.")
            elif decisions > 0:
                lines.append("👍 Good decision logging! Try Thinker tools before risky edits.")
            else:
                lines.append("💡 Build good habits: think before editing, log decisions")

        return "\n".join(lines)

    def suggest_tool_for_context(self, context: str, risk_reason: str = "") -> Tuple[str, str]:
        """
        Suggest the BEST Thinker tool for a specific context.

        Returns (tool_name, reason) tuple.
        """
        context_lower = context.lower()

        # Authentication/Security work
        if any(kw in context_lower for kw in ["auth", "login", "password", "security", "token", "session"]):
            return ("think_best_practice", "Security is critical - learn the 2026 best practices first")

        # Payment/Financial
        if any(kw in context_lower for kw in ["payment", "billing", "transaction", "money", "price"]):
            return ("think_best_practice", "Financial code requires industry standards - check best practices")

        # Architecture/Design
        if any(kw in context_lower for kw in ["architecture", "design", "refactor", "structure"]):
            return ("think_explore", "Architecture has many valid approaches - explore the solution space")

        # Integration/API work
        if any(kw in context_lower for kw in ["integrate", "api", "endpoint", "webhook"]):
            return ("think_compare", "Multiple integration approaches exist - compare the trade-offs")

        # Performance/Optimization
        if any(kw in context_lower for kw in ["performance", "optimize", "slow", "cache"]):
            return ("think_research", "Performance work needs data - research the bottleneck first")

        # Database/Schema
        if any(kw in context_lower for kw in ["database", "schema", "migration", "sql"]):
            return ("think_challenge", "Schema changes are hard to reverse - challenge your assumptions")

        # Config/Infrastructure
        if "config" in context_lower or "infrastructure" in context_lower:
            return ("think_best_practice", "Config affects everything - check what's standard")

        # Default: explore solution space
        return ("think_explore", "Explore different approaches before picking the first idea")


# Singleton state directory
_state_dir = Path.home() / ".mini_claude"
_habit_tracker = HabitTracker(_state_dir)


def get_habit_tracker() -> HabitTracker:
    """Get the global habit tracker instance."""
    return _habit_tracker


# Public API functions for handlers
def record_thinker_use(tool: str, context: str):
    """Record that a Thinker tool was used."""
    _habit_tracker.record_thinker_use(tool, context)


def record_risky_edit_without_thinking(file_path: str, risk_reason: str):
    """Record that a risky file was edited without thinking."""
    _habit_tracker.record_risky_edit_without_thinking(file_path, risk_reason)


def record_loop_avoided(file_path: str):
    """Record that a loop was avoided."""
    _habit_tracker.record_loop_avoided(file_path)


def record_loop_hit(file_path: str, edit_count: int):
    """Record that a loop was hit."""
    _habit_tracker.record_loop_hit(file_path, edit_count)


def get_habit_stats(days: int = 7) -> Dict:
    """Get habit statistics."""
    return _habit_tracker.get_habit_stats(days)


def get_habit_feedback() -> str:
    """Get habit feedback message."""
    return _habit_tracker.get_habit_feedback()


def suggest_tool_for_context(context: str, risk_reason: str = "") -> Tuple[str, str]:
    """Suggest best Thinker tool for context."""
    return _habit_tracker.suggest_tool_for_context(context, risk_reason)


def get_recent_thinker_usage(context_pattern: str, limit: int = 5) -> List[Dict]:
    """Get recent Thinker usage for context."""
    return _habit_tracker.get_recent_thinker_usage(context_pattern, limit)


# Session tracking API functions
def start_session():
    """Start a new tracking session."""
    _habit_tracker.start_session()


def record_session_tool_use(tool_name: str, context: str = ""):
    """Record a tool being used in the current session."""
    _habit_tracker.record_session_tool_use(tool_name, context)


def record_session_file_edit(file_path: str):
    """Record a file being edited in the current session."""
    _habit_tracker.record_session_file_edit(file_path)


def record_session_decision():
    """Record a decision being logged."""
    _habit_tracker.record_session_decision()


def record_session_mistake():
    """Record a mistake being logged."""
    _habit_tracker.record_session_mistake()


def get_session_stats() -> Dict:
    """Get current session statistics."""
    return _habit_tracker.get_session_stats()
