"""
Memory - Persistent Knowledge Store for Mini Claude

Allows mini_claude to remember:
- Project understanding (structure, patterns, key files)
- Previous discoveries and searches
- Priorities and important notes
- Claude's preferences

v2: Smart memory management with:
- Auto-tagging and indexing
- Deduplication
- Memory decay
- Contextual search
- Clustering
"""

import json
import math
import os
import re
import time
import hashlib
from pathlib import Path
from typing import Optional
from collections import defaultdict
from pydantic import BaseModel, Field


class MemoryEntry(BaseModel):
    """A single memory entry with smart features."""
    content: str
    category: str  # "rule", "mistake", "context", "discovery", "priority", "note", "decision"
    created_at: float = Field(default_factory=time.time)
    source: Optional[str] = None  # What operation created this memory
    relevance: int = 5  # 1-10, higher = more important

    # v2: Smart memory fields
    id: str = Field(default="")  # Unique identifier (set on creation)
    last_accessed: float = Field(default_factory=time.time)  # For decay tracking
    access_count: int = 1  # How often this memory was relevant
    tags: list[str] = Field(default_factory=list)  # Auto-extracted: ["auth", "bootstrap"]
    related_files: list[str] = Field(default_factory=list)  # Files this memory relates to
    cluster_id: Optional[str] = None  # Which cluster this belongs to

    # v3: Archive support
    archived_at: Optional[float] = None  # When moved to archive; None = active


# Scoring weights for memory relevance ranking
SCORE_WEIGHTS = {
    "file_match": 0.35,
    "tag_overlap": 0.20,
    "recency": 0.20,
    "relevance": 0.15,
    "access_freq": 0.10,
}
CATEGORY_BONUSES = {"rule": 0.3, "mistake": 0.2}
RECENCY_HALF_LIFE_DAYS = 30


class MemoryCluster(BaseModel):
    """A group of related memories."""
    cluster_id: str
    name: str  # "Bootstrap Discoveries", "Auth Memories"
    memory_ids: list[str] = Field(default_factory=list)
    summary: str = ""  # LLM-generated or auto-generated summary
    tags: list[str] = Field(default_factory=list)  # Common tags across memories
    created_at: float = Field(default_factory=time.time)
    relevance: int = 5  # Average relevance of memories


class ProjectMemory(BaseModel):
    """Memory about a specific project/directory."""
    project_path: str
    project_name: str

    # Core understanding
    summary: Optional[str] = None
    language: Optional[str] = None
    framework: Optional[str] = None

    # Key locations
    key_files: dict[str, str] = Field(default_factory=dict)  # path -> description
    key_directories: dict[str, str] = Field(default_factory=dict)

    # Discoveries and notes
    entries: list[MemoryEntry] = Field(default_factory=list)

    # Search history (for avoiding redundant searches)
    recent_searches: list[dict] = Field(default_factory=list)

    last_updated: float = Field(default_factory=time.time)

    # v2: Smart memory indexes
    file_memory_index: dict[str, list[str]] = Field(default_factory=dict)  # file -> memory IDs
    tag_memory_index: dict[str, list[str]] = Field(default_factory=dict)  # tag -> memory IDs
    clusters: dict[str, MemoryCluster] = Field(default_factory=dict)  # cluster_id -> cluster
    last_cleanup: float = Field(default_factory=time.time)  # Track when last cleaned


class MemoryStore:
    """
    Mini Claude's memory system.

    Persists knowledge across sessions so I don't have to rediscover
    the same things repeatedly.

    v2: Smart memory management with auto-tagging, deduplication, and contextual search.
    """

    # Tag extraction patterns
    TAG_PATTERNS = {
        r"BOOTSTRAP|bootstrap": "bootstrap",
        r"ROUND\s*\d+|round-?\d+": "bootstrap",
        r"MISTAKE|mistake": "mistake",
        r"DECISION|decision": "decision",
        r"\bauth\b|login|password|authentication|authorization": "auth",
        r"test|pytest|unittest|jest|mocha": "testing",
        r"config|settings|\.env": "config",
        r"database|db|sql|migration": "database",
        r"api|endpoint|route|handler": "api",
        r"security|vulnerability|CVE": "security",
        r"performance|optimize|slow|fast": "performance",
        r"bug|fix|error|crash": "bugfix",
        r"refactor|cleanup|improve": "refactor",
        r"install|setup|dependency": "setup",
    }

    def __init__(self, storage_dir: str = "~/.mini_claude"):
        self.storage_dir = Path(storage_dir).expanduser()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.memory_file = self.storage_dir / "memory.json"
        self.archive_file = self.storage_dir / "archive.json"

        # In-memory cache
        self._projects: dict[str, ProjectMemory] = {}
        self._global_entries: list[MemoryEntry] = []
        self._load_error: str | None = None  # Track if memory file was corrupted
        self._save_error: str | None = None  # Track if save failed

        # v3: Archive tier (lazy-loaded, never on hot path)
        self._archive_projects: dict[str, ProjectMemory] = {}
        self._archive_loaded: bool = False
        self.archive_after_days: int = int(os.environ.get("MINI_CLAUDE_ARCHIVE_DAYS", "14"))

        # Load existing memory
        self._load()

    def _load(self):
        """Load memory from disk with v1 -> v2 migration support."""
        if self.memory_file.exists():
            try:
                data = json.loads(self.memory_file.read_text())
                version = data.get("version", 1)

                needs_save = False
                for path, proj_data in data.get("projects", {}).items():
                    # Migrate entries if needed
                    if version == 1:
                        proj_data = self._migrate_project_v1_to_v2(proj_data)

                    # Normalize path to prevent duplicates (d:/ vs D:/, \ vs /)
                    norm_path = self._normalize_path(path)
                    if norm_path != path:
                        needs_save = True  # Path changed, need to re-save

                    if norm_path in self._projects:
                        # Merge entries from duplicate path into existing project
                        existing = self._projects[norm_path]
                        new_proj = ProjectMemory(**proj_data)
                        existing_ids = {e.id for e in existing.entries}
                        for entry in new_proj.entries:
                            if entry.id not in existing_ids:
                                existing.entries.append(entry)
                        needs_save = True
                    else:
                        proj_data["project_path"] = norm_path
                        self._projects[norm_path] = ProjectMemory(**proj_data)

                for entry_data in data.get("global", []):
                    if version == 1:
                        entry_data = self._migrate_entry_v1_to_v2(entry_data)
                    self._global_entries.append(MemoryEntry(**entry_data))

                # Save migrated data (version upgrade or path normalization)
                if version == 1 or needs_save:
                    self._save()

            except Exception as e:
                # Memory file is corrupted - log it and start fresh
                self._load_error = f"Memory file corrupted, starting fresh: {e}"
                # Try to backup corrupted file
                try:
                    backup_path = self.memory_file.with_suffix(".json.corrupted")
                    self.memory_file.replace(backup_path)  # .replace() works on Windows
                except Exception:
                    pass

    def _migrate_entry_v1_to_v2(self, entry_data: dict) -> dict:
        """Migrate a v1 entry to v2 format."""
        content = entry_data.get("content", "")

        # Add ID if missing (include created_at to avoid collisions for same-content entries)
        if not entry_data.get("id"):
            created = str(entry_data.get("created_at", ""))
            entry_data["id"] = hashlib.md5(f"{content}{created}".encode()).hexdigest()[:12]

        # Add tags if missing
        if "tags" not in entry_data:
            entry_data["tags"] = self._extract_tags(content)

        # Add related_files if missing
        if "related_files" not in entry_data:
            entry_data["related_files"] = self._extract_file_refs(content)

        # Add last_accessed if missing
        if "last_accessed" not in entry_data:
            entry_data["last_accessed"] = entry_data.get("created_at", time.time())

        # Add access_count if missing
        if "access_count" not in entry_data:
            entry_data["access_count"] = 1

        return entry_data

    def _migrate_project_v1_to_v2(self, proj_data: dict) -> dict:
        """Migrate a v1 project to v2 format."""
        # Migrate all entries
        entries = proj_data.get("entries", [])
        for i, entry in enumerate(entries):
            entries[i] = self._migrate_entry_v1_to_v2(entry)

        # Build indexes
        file_index = defaultdict(list)
        tag_index = defaultdict(list)

        for entry in entries:
            entry_id = entry.get("id", "")
            for f in entry.get("related_files", []):
                if entry_id not in file_index[f]:
                    file_index[f].append(entry_id)
            for t in entry.get("tags", []):
                if entry_id not in tag_index[t]:
                    tag_index[t].append(entry_id)

        proj_data["file_memory_index"] = dict(file_index)
        proj_data["tag_memory_index"] = dict(tag_index)
        proj_data["clusters"] = proj_data.get("clusters", {})
        proj_data["last_cleanup"] = proj_data.get("last_cleanup", time.time())

        return proj_data

    def _extract_tags(self, content: str) -> list[str]:
        """Extract tags from memory content using pattern matching."""
        tags = set()
        content_lower = content.lower()

        for pattern, tag in self.TAG_PATTERNS.items():
            if re.search(pattern, content, re.IGNORECASE):
                tags.add(tag)

        # Extract round numbers for bootstrap memories
        round_match = re.search(r"round\s*(\d+)", content_lower)
        if round_match:
            tags.add(f"round-{round_match.group(1)}")

        return list(tags)

    def _extract_file_refs(self, content: str) -> list[str]:
        """Extract file references from memory content."""
        files = set()

        # Match common file patterns
        patterns = [
            r"[\w/\\.-]+\.(py|js|ts|tsx|jsx|go|rs|java|cpp|c|h|md|json|yaml|yml|toml)",
            r"[\w-]+\.py",
            r"handlers\.py|server\.py|memory\.py|remind\.py",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, content)
            for match in matches:
                if isinstance(match, tuple):
                    match = match[0]
                # Clean up the match
                if "." in match:
                    files.add(match)

        return list(files)

    def _generate_entry_id(self, content: str) -> str:
        """Generate a unique ID for a memory entry based on content."""
        # Use content-only hash for deterministic IDs; add counter suffix on collision
        base_id = hashlib.md5(content.encode()).hexdigest()[:12]
        # Check for collision across all projects
        all_ids = set()
        for proj in self._projects.values():
            all_ids.update(e.id for e in proj.entries)
        all_ids.update(e.id for e in self._global_entries)
        if base_id not in all_ids:
            return base_id
        # Collision: append counter
        counter = 1
        while f"{base_id}_{counter}" in all_ids:
            counter += 1
        return f"{base_id}_{counter}"

    def _is_duplicate(self, content: str, entries: list[MemoryEntry], threshold: float = 0.85) -> Optional[MemoryEntry]:
        """
        Check if content is a duplicate of an existing memory.
        Uses Jaccard similarity on word sets.
        Returns the duplicate entry if found, None otherwise.
        """
        new_words = set(content.lower().split())
        if not new_words:
            return None

        for entry in entries:
            existing_words = set(entry.content.lower().split())
            if not existing_words:
                continue

            # Jaccard similarity
            intersection = len(new_words & existing_words)
            union = len(new_words | existing_words)

            if union > 0 and intersection / union >= threshold:
                return entry

        return None

    def _update_indexes(self, proj: ProjectMemory, entry: MemoryEntry):
        """Update file and tag indexes for a new entry."""
        for f in entry.related_files:
            if f not in proj.file_memory_index:
                proj.file_memory_index[f] = []
            if entry.id not in proj.file_memory_index[f]:
                proj.file_memory_index[f].append(entry.id)

        for t in entry.tags:
            if t not in proj.tag_memory_index:
                proj.tag_memory_index[t] = []
            if entry.id not in proj.tag_memory_index[t]:
                proj.tag_memory_index[t].append(entry.id)

    def _save(self) -> bool:
        """
        Save memory to disk with version marker.

        Returns:
            True if save succeeded, False otherwise
        """
        data = {
            "version": 2,
            "projects": {
                path: proj.model_dump()
                for path, proj in self._projects.items()
            },
            "global": [e.model_dump() for e in self._global_entries]
        }
        try:
            # Write to temp file first, then rename (atomic operation)
            temp_file = self.memory_file.with_suffix(".json.tmp")
            temp_file.write_text(json.dumps(data, indent=2))
            temp_file.replace(self.memory_file)  # .replace() works on both Windows and Linux
            return True
        except Exception as e:
            # Log the error but don't crash - memory operations should be resilient
            self._save_error = f"Failed to save memory: {e}"
            return False

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Normalize project path for consistent dict keys (lowercase drive, forward slashes)."""
        normalized = str(Path(path).resolve()).replace("\\", "/")
        if len(normalized) >= 2 and normalized[1] == ":":
            normalized = normalized[0].lower() + normalized[1:]
        return normalized

    def get_project(self, project_path: str) -> Optional[ProjectMemory]:
        """Get memory for a project, if it exists."""
        project_path = self._normalize_path(project_path)
        return self._projects.get(project_path)

    def remember_project(
        self,
        project_path: str,
        summary: Optional[str] = None,
        language: Optional[str] = None,
        framework: Optional[str] = None,
    ) -> ProjectMemory:
        """Create or update project memory."""
        project_path = self._normalize_path(project_path)
        if project_path not in self._projects:
            project_name = Path(project_path).name
            self._projects[project_path] = ProjectMemory(
                project_path=project_path,
                project_name=project_name,
            )

        proj = self._projects[project_path]

        if summary:
            proj.summary = summary
        if language:
            proj.language = language
        if framework:
            proj.framework = framework

        proj.last_updated = time.time()
        self._save()

        return proj

    def remember_key_file(
        self,
        project_path: str,
        file_path: str,
        description: str,
    ):
        """Remember an important file in a project."""
        proj = self.remember_project(project_path)
        proj.key_files[file_path] = description
        proj.last_updated = time.time()
        self._save()

    def remember_discovery(
        self,
        project_path: str,
        content: str,
        source: Optional[str] = None,
        relevance: int = 5,
        tags: Optional[list[str]] = None,
        related_files: Optional[list[str]] = None,
        category: str = "discovery",  # Can override: "mistake", "decision", "context", etc.
    ) -> tuple[bool, str]:
        """
        Remember something discovered about a project.

        Returns:
            (added, message) - whether memory was added and a status message
        """
        proj = self.remember_project(project_path)

        # Check for duplicates
        duplicate = self._is_duplicate(content, proj.entries)
        if duplicate:
            # Update access count and relevance of existing entry
            duplicate.access_count += 1
            duplicate.last_accessed = time.time()
            if relevance > duplicate.relevance:
                duplicate.relevance = relevance
            self._save()
            return (False, f"Duplicate of existing memory (id={duplicate.id}), updated access count")

        # Auto-extract tags and files if not provided
        auto_tags = self._extract_tags(content)
        auto_files = self._extract_file_refs(content)

        entry = MemoryEntry(
            id=self._generate_entry_id(content),
            content=content,
            category=category,
            source=source,
            relevance=relevance,
            tags=list(set((tags or []) + auto_tags)),
            related_files=list(set((related_files or []) + auto_files)),
        )

        proj.entries.append(entry)
        self._update_indexes(proj, entry)
        proj.last_updated = time.time()
        self._save()

        return (True, f"Memory added with id={entry.id}, tags={entry.tags}")

    def add_priority(
        self,
        content: str,
        project_path: Optional[str] = None,
        relevance: int = 8,
    ):
        """Add a priority note (something important to remember)."""
        entry = MemoryEntry(
            content=content,
            category="priority",
            relevance=relevance,
        )

        if project_path:
            proj = self.remember_project(project_path)
            proj.entries.append(entry)
            proj.last_updated = time.time()
        else:
            self._global_entries.append(entry)

        self._save()

    def log_search(
        self,
        project_path: str,
        query: str,
        results_count: int,
        top_files: list[str],
    ):
        """Log a search to avoid redundant future searches."""
        proj = self.remember_project(project_path)

        # Keep only last 20 searches
        proj.recent_searches = proj.recent_searches[-19:]
        proj.recent_searches.append({
            "query": query,
            "results_count": results_count,
            "top_files": top_files[:5],
            "timestamp": time.time(),
        })

        self._save()

    def recall(
        self,
        project_path: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> dict:
        """
        Recall what we know.

        Returns a summary of memories, optionally filtered by project or category.
        """
        result = {
            "global_priorities": [],
            "project": None,
        }

        # Global priorities (always include top ones)
        priorities = sorted(
            [e for e in self._global_entries if e.category == "priority"],
            key=lambda x: x.relevance,
            reverse=True,
        )
        result["global_priorities"] = [
            {"content": e.content, "relevance": e.relevance}
            for e in priorities[:5]
        ]

        # Project-specific memories
        if project_path:
            project_path = self._normalize_path(project_path)
        if project_path and project_path in self._projects:
            proj = self._projects[project_path]

            entries = proj.entries
            if category:
                entries = [e for e in entries if e.category == category]

            # Sort by relevance
            entries = sorted(entries, key=lambda x: x.relevance, reverse=True)

            result["project"] = {
                "name": proj.project_name,
                "summary": proj.summary,
                "language": proj.language,
                "framework": proj.framework,
                "key_files": proj.key_files,
                "key_directories": proj.key_directories,
                "discoveries": [
                    {
                        "id": e.id,
                        "content": e.content,
                        "relevance": e.relevance,
                        "category": e.category,
                        "created_at": e.created_at,
                    }
                    for e in entries[:limit]
                ],
                "recent_searches": proj.recent_searches[-5:],
            }

        return result

    def forget_project(self, project_path: str):
        """Clear memory for a project."""
        norm = self._normalize_path(project_path)
        if norm in self._projects:
            del self._projects[norm]
            self._save()

    def clear_all(self):
        """Clear all memory (use with caution)."""
        self._projects = {}
        self._global_entries = []
        self._save()

    def get_stats(self) -> dict:
        """Get memory statistics."""
        total_entries = sum(len(p.entries) for p in self._projects.values())
        total_entries += len(self._global_entries)

        stats = {
            "projects_tracked": len(self._projects),
            "total_entries": total_entries,
            "global_entries": len(self._global_entries),
            "storage_path": str(self.memory_file),
        }

        # Report any errors
        if self._load_error:
            stats["load_error"] = self._load_error
        if self._save_error:
            stats["save_error"] = self._save_error

        return stats

    def get_health(self) -> dict:
        """
        Get memory system health status.
        Reports any errors that occurred during load/save.
        """
        health = {
            "healthy": not (self._load_error or self._save_error),
            "storage_path": str(self.memory_file),
            "storage_exists": self.memory_file.exists(),
        }

        if self._load_error:
            health["load_error"] = self._load_error
            health["backup_created"] = self.memory_file.with_suffix(".json.corrupted").exists()

        if self._save_error:
            health["save_error"] = self._save_error

        return health

    def clear_errors(self):
        """Clear error state after user acknowledges."""
        self._load_error = None
        self._save_error = None

    def get_memory_summary(self, project_path: str) -> dict:
        """
        Get a summary of memories for session start display.
        Shows counts by category, stale warnings, and suggestions.
        """
        proj = self.get_project(project_path)
        if not proj:
            return {"total": 0, "categories": {}, "stale": [], "suggestions": []}

        now = time.time()
        categories = {}
        stale = []
        suggestions = []

        for entry in proj.entries:
            # Count by category
            cat = entry.category
            if cat not in categories:
                categories[cat] = 0
            categories[cat] += 1

            # Check for stale memories (not accessed in 60+ days)
            age_days = (now - entry.last_accessed) / 86400
            if age_days > 60 and entry.category not in ("rule", "mistake"):
                stale.append({
                    "id": entry.id,
                    "age_days": int(age_days),
                    "category": entry.category,
                    "preview": entry.content[:50] + "..." if len(entry.content) > 50 else entry.content,
                })

        # Count decisions separately (they have DECISION: prefix or decision category)
        decision_count = 0
        recent_decisions = []
        for entry in proj.entries:
            is_decision = (
                entry.content.upper().startswith("DECISION:") or
                entry.category == "decision"
            )
            if is_decision:
                decision_count += 1
                # Get recent decisions (last 24 hours)
                age_hours = (now - entry.created_at) / 3600
                if age_hours < 24:
                    content = entry.content
                    if content.upper().startswith("DECISION:"):
                        content = content[9:].strip()
                    recent_decisions.append({
                        "content": content[:100],
                        "age_hours": int(age_hours),
                    })

        # Generate suggestions
        if len(stale) > 3:
            suggestions.append(f"{len(stale)} memories haven't been accessed in 60+ days - consider reviewing with memory(cleanup, dry_run=true)")

        if categories.get("discovery", 0) > 20:
            suggestions.append("Many discoveries stored - consider promoting important ones to rules")

        if categories.get("mistake", 0) > 10:
            suggestions.append("Learning from many mistakes! Review if patterns have emerged")

        # Memory management hints
        total = len(proj.entries)
        if total > 30:
            suggestions.append("Manage memories: memory(modify/delete/promote, memory_id='...')")

        return {
            "total": total,
            "categories": categories,
            "stale_count": len(stale),
            "stale": stale[:5],  # Show top 5 stale
            "decision_count": decision_count,
            "recent_decisions": recent_decisions[:3],  # Show last 3 recent decisions
            "suggestions": suggestions,
        }

    def get_memories_for_files(
        self,
        project_path: str,
        file_paths: list[str],
        include_rules: bool = True,
        include_mistakes: bool = True,
    ) -> dict:
        """
        Get memories relevant to specific files (for curated context).

        Used at session_start to show only memories related to last session's files,
        reducing noise while keeping context relevant.

        Args:
            project_path: The project to search
            file_paths: List of file paths to find memories for
            include_rules: Always include rules (they apply regardless of files)
            include_mistakes: Always include mistakes (important to remember)

        Returns:
            Dict with: rules, mistakes, file_memories, other
        """
        proj = self.get_project(project_path)
        if not proj:
            return {"rules": [], "mistakes": [], "file_memories": [], "other": []}

        rules = []
        mistakes = []
        file_memories = []
        other = []

        # Normalize file paths for matching
        file_names = set(Path(f).name for f in file_paths)
        file_paths_set = set(file_paths)

        for entry in proj.entries:
            content = entry.content

            # Always include rules
            if entry.category == "rule":
                rules.append(entry)
                continue

            # Always include mistakes
            if content.upper().startswith("MISTAKE:") or entry.category == "mistake":
                mistakes.append(entry)
                continue

            # Check if memory relates to any of the files
            related = False

            # Check related_files
            for rf in entry.related_files:
                if rf in file_paths_set or Path(rf).name in file_names:
                    related = True
                    break

            # Check if file name appears in content
            if not related:
                for fn in file_names:
                    if fn in content:
                        related = True
                        break

            if related:
                file_memories.append(entry)
            else:
                other.append(entry)

        return {
            "rules": rules,
            "mistakes": mistakes,
            "file_memories": file_memories,
            "other": other,
        }

    # =========================================================================
    # v2: Smart Memory Methods
    # =========================================================================

    def search_memories(
        self,
        project_path: str,
        file_path: Optional[str] = None,
        tags: Optional[list[str]] = None,
        query: Optional[str] = None,
        limit: int = 5,
    ) -> list[MemoryEntry]:
        """
        Search memories contextually.

        Args:
            project_path: The project to search in
            file_path: Find memories related to this file
            tags: Find memories with these tags
            query: Keyword search in memory content
            limit: Maximum number of results

        Returns:
            List of matching MemoryEntry objects, sorted by relevance
        """
        proj = self.get_project(project_path)
        if not proj:
            return []

        results = []
        seen_ids = set()

        # Search by file
        if file_path:
            file_name = Path(file_path).name
            # Check both full path and filename
            for f in [file_path, file_name]:
                for entry_id in proj.file_memory_index.get(f, []):
                    if entry_id not in seen_ids:
                        entry = self._get_entry_by_id(proj, entry_id)
                        if entry:
                            results.append(entry)
                            seen_ids.add(entry_id)

        # Search by tags
        if tags:
            for tag in tags:
                for entry_id in proj.tag_memory_index.get(tag, []):
                    if entry_id not in seen_ids:
                        entry = self._get_entry_by_id(proj, entry_id)
                        if entry:
                            results.append(entry)
                            seen_ids.add(entry_id)

        # Search by keyword query
        if query:
            query_words = set(query.lower().split())
            for entry in proj.entries:
                if entry.id in seen_ids:
                    continue
                content_words = set(entry.content.lower().split())
                if query_words & content_words:
                    results.append(entry)
                    seen_ids.add(entry.id)

        # Update access tracking for returned results
        for entry in results:
            entry.last_accessed = time.time()
            entry.access_count += 1

        # Sort by relevance and limit
        results = sorted(results, key=lambda x: x.relevance, reverse=True)[:limit]

        if results:
            self._save()

        return results

    def _get_entry_by_id(self, proj: ProjectMemory, entry_id: str) -> Optional[MemoryEntry]:
        """Get an entry by ID from a project."""
        for entry in proj.entries:
            if entry.id == entry_id:
                return entry
        return None

    def cleanup_memories(
        self,
        project_path: str,
        dry_run: bool = True,
        min_relevance: int = 3,
        max_age_days: int = 30,
        apply_decay: bool = True,
    ) -> dict:
        """
        Clean up and consolidate memories.

        Actions:
        1. Find and remove broken/incomplete memories
        2. Find and optionally merge duplicates
        3. Archive old inactive memories to cold tier (instead of deleting)
        4. Decay old low-relevance memories (if apply_decay=True)
        5. Create clusters from related memories

        Args:
            project_path: The project to clean up
            dry_run: If True, only report what would be done
            min_relevance: Minimum relevance to keep after decay
            max_age_days: Days after which unused memories start decaying
            apply_decay: If False, skip decay/removal (useful for auto-cleanup)

        Returns:
            Cleanup report with actions taken/proposed
        """
        proj = self.get_project(project_path)
        if not proj:
            return {"error": "Project not found"}

        report = {
            "broken_found": [],
            "duplicates_found": [],
            "duplicates_merged": [],
            "archived": [],
            "decayed": [],
            "removed": [],
            "clusters_created": [],
            "dry_run": dry_run,
            "total_memories": len(proj.entries),
        }

        # Find broken/incomplete memories
        for entry in proj.entries:
            reason = self._is_broken_memory(entry.content)
            if reason:
                report["broken_found"].append({
                    "entry_id": entry.id,
                    "reason": reason,
                    "content_preview": entry.content[:60] + "..." if len(entry.content) > 60 else entry.content,
                })
                report["removed"].append({
                    "entry_id": entry.id,
                    "reason": f"Broken memory: {reason}",
                })

        # Find duplicates
        seen_content = {}
        for entry in proj.entries:
            # Skip entries already marked for removal
            if any(r["entry_id"] == entry.id for r in report["removed"]):
                continue
            dup = self._is_duplicate(entry.content, list(seen_content.values()), threshold=0.85)
            if dup:
                report["duplicates_found"].append({
                    "entry_id": entry.id,
                    "duplicate_of": dup.id,
                    "content_preview": entry.content[:50] + "...",
                })
            else:
                seen_content[entry.id] = entry

        # Archive old inactive memories (before decay, so they're preserved not deleted)
        if apply_decay:
            for entry in proj.entries:
                if any(r["entry_id"] == entry.id for r in report["removed"]):
                    continue
                if any(d["entry_id"] == entry.id for d in report["duplicates_found"]):
                    continue
                if self._is_archivable(entry):
                    report["archived"].append({
                        "entry_id": entry.id,
                        "age_days": int((time.time() - entry.last_accessed) / 86400),
                        "content_preview": entry.content[:50] + "...",
                    })

        # Calculate decay for old memories (only if apply_decay is True)
        # PROTECTED CATEGORIES: rules and mistakes NEVER decay
        protected_categories = {"rule", "mistake"}

        if apply_decay:
            now = time.time()
            for entry in proj.entries:
                # Skip entries already marked for removal
                if any(r["entry_id"] == entry.id for r in report["removed"]):
                    continue

                # NEVER decay rules or mistakes - they're permanent learning
                if entry.category in protected_categories:
                    continue
                age_days = (now - entry.last_accessed) / 86400
                if age_days > max_age_days and entry.relevance < 7:
                    # Calculate decay
                    decay_amount = int((age_days - max_age_days) / 7)  # -1 per week over threshold
                    new_relevance = max(1, entry.relevance - decay_amount)

                    if new_relevance < entry.relevance:
                        report["decayed"].append({
                            "entry_id": entry.id,
                            "old_relevance": entry.relevance,
                            "new_relevance": new_relevance,
                            "age_days": int(age_days),
                            "content_preview": entry.content[:50] + "...",
                        })

                        if new_relevance < min_relevance:
                            report["removed"].append({
                                "entry_id": entry.id,
                                "reason": f"Relevance decayed to {new_relevance} (below {min_relevance})",
                            })

        # Auto-cluster by common tags
        tag_groups = defaultdict(list)
        for entry in proj.entries:
            for tag in entry.tags:
                tag_groups[tag].append(entry.id)

        for tag, entry_ids in tag_groups.items():
            if len(entry_ids) >= 3:
                # Check if cluster already exists
                existing = any(
                    c.name == f"{tag.title()} Memories"
                    for c in proj.clusters.values()
                )
                if not existing:
                    report["clusters_created"].append({
                        "name": f"{tag.title()} Memories",
                        "tag": tag,
                        "memory_count": len(entry_ids),
                    })

        # Generate summary
        actions = []
        if report["broken_found"]:
            actions.append(f"{len(report['broken_found'])} broken")
        if report["duplicates_found"]:
            actions.append(f"{len(report['duplicates_found'])} duplicates")
        if report["archived"]:
            actions.append(f"{len(report['archived'])} archived")
        if report["decayed"]:
            actions.append(f"{len(report['decayed'])} decayed")
        if report["clusters_created"]:
            actions.append(f"{len(report['clusters_created'])} new clusters")

        if actions:
            action_word = "would be cleaned" if dry_run else "cleaned"
            report["summary"] = f"Found: {', '.join(actions)}. {len(report['removed'])} entries {action_word}."
        else:
            report["summary"] = f"All {len(proj.entries)} memories are clean. No action needed."

        # Apply changes if not dry run
        if not dry_run:
            self._apply_cleanup(proj, report)
            proj.last_cleanup = time.time()
            self._save()

        return report

    def _is_broken_memory(self, content: str) -> Optional[str]:
        """
        Check if a memory is broken/incomplete and should be removed.
        Returns the reason if broken, None if OK.
        """
        if not content or not content.strip():
            return "Empty content"

        # Too short to be useful
        if len(content.strip()) < 20:
            return "Too short (< 20 chars)"

        # Truncated mid-sentence (ends with common truncation patterns)
        truncation_patterns = [
            "...\n##",  # Truncated before heading
            ". Key finding: \n",  # Incomplete research
            "Key finding: \n##",  # Another incomplete pattern
            ": \n##",  # Colon then heading
        ]
        for pattern in truncation_patterns:
            if pattern in content:
                return f"Truncated content (contains '{pattern.strip()}')"

        # Ends abruptly (no punctuation, just whitespace)
        stripped = content.rstrip()
        if stripped and stripped[-1] not in ".!?\"')]:;":
            # Check if it ends mid-word or mid-sentence
            last_line = stripped.split("\n")[-1]
            if len(last_line) > 10 and " " in last_line[-20:]:
                # Has spaces near end but no ending punctuation - likely truncated
                words = content.split()
                if len(words) > 5:  # Only flag if substantial content
                    # Check if last word looks incomplete (very short non-word)
                    last_word = words[-1] if words else ""
                    if last_word and not last_word[-1].isalnum():
                        pass  # Has some punctuation, likely OK
                    elif len(last_word) == 1 and last_word.isalpha():
                        return "Truncated (ends with single letter)"

        # Contains placeholder text
        placeholder_patterns = [
            "TODO:",
            "FIXME:",
            "...",  # Only if it's the main content
            "[placeholder]",
            "[TBD]",
        ]
        for pattern in placeholder_patterns:
            if content.strip() == pattern or content.strip().endswith(pattern):
                return f"Placeholder content ({pattern})"

        return None

    def _apply_cleanup(self, proj: ProjectMemory, report: dict):
        """Apply cleanup actions from a report."""
        # Merge duplicates (keep the one with higher relevance)
        ids_to_remove = set()
        for dup in report["duplicates_found"]:
            entry = self._get_entry_by_id(proj, dup["entry_id"])
            original = self._get_entry_by_id(proj, dup["duplicate_of"])
            if entry and original:
                # Merge metadata into original, keeping higher-quality content
                original.tags = list(set(original.tags + entry.tags))
                original.related_files = list(set(original.related_files + entry.related_files))
                original.access_count += entry.access_count
                if entry.relevance > original.relevance:
                    original.relevance = entry.relevance
                    # Keep the higher-relevance entry's content (likely more refined)
                    original.content = entry.content
                ids_to_remove.add(entry.id)
                report["duplicates_merged"].append(dup["entry_id"])

        # Archive old entries (move to cold tier instead of deleting)
        if report.get("archived"):
            self._load_archive()
            norm_path = self._normalize_path(proj.project_path)
            if norm_path not in self._archive_projects:
                self._archive_projects[norm_path] = ProjectMemory(
                    project_path=norm_path,
                    project_name=proj.project_name,
                )
            archive_proj = self._archive_projects[norm_path]
            archive_ids = {e.id for e in archive_proj.entries}

            for arch_info in report["archived"]:
                entry = self._get_entry_by_id(proj, arch_info["entry_id"])
                if entry and entry.id not in archive_ids:
                    entry.archived_at = time.time()
                    archive_proj.entries.append(entry)
                    ids_to_remove.add(entry.id)

            self._save_archive()

        # Apply decay
        for decay_info in report["decayed"]:
            entry = self._get_entry_by_id(proj, decay_info["entry_id"])
            if entry:
                entry.relevance = decay_info["new_relevance"]

        # Remove low-relevance entries
        for removal in report["removed"]:
            ids_to_remove.add(removal["entry_id"])

        # Remove entries
        proj.entries = [e for e in proj.entries if e.id not in ids_to_remove]

        # Rebuild indexes
        proj.file_memory_index = defaultdict(list)
        proj.tag_memory_index = defaultdict(list)
        for entry in proj.entries:
            self._update_indexes(proj, entry)

        # Create clusters
        for cluster_info in report["clusters_created"]:
            tag = cluster_info["tag"]
            cluster_id = f"cluster_{tag}_{int(time.time())}"

            # Get entries with this tag
            entry_ids = [e.id for e in proj.entries if tag in e.tags]

            # Generate summary
            contents = [e.content[:100] for e in proj.entries if e.id in entry_ids][:5]
            summary = f"Memories about {tag}: " + "; ".join(contents)

            proj.clusters[cluster_id] = MemoryCluster(
                cluster_id=cluster_id,
                name=cluster_info["name"],
                memory_ids=entry_ids,
                summary=summary[:200],
                tags=[tag],
                relevance=5,
            )

            # Update entries with cluster_id
            for entry in proj.entries:
                if entry.id in entry_ids:
                    entry.cluster_id = cluster_id

    def get_clusters(self, project_path: str, cluster_id: Optional[str] = None) -> dict:
        """
        Get memory clusters for a project.

        Args:
            project_path: The project to get clusters for
            cluster_id: Optional specific cluster to expand

        Returns:
            Cluster information with summaries
        """
        proj = self.get_project(project_path)
        if not proj:
            return {"error": "Project not found", "clusters": []}

        if cluster_id:
            # Return specific cluster with full memories
            cluster = proj.clusters.get(cluster_id)
            if not cluster:
                return {"error": f"Cluster {cluster_id} not found", "clusters": []}

            memories = [
                self._get_entry_by_id(proj, mid)
                for mid in cluster.memory_ids
            ]
            memories = [m for m in memories if m]

            return {
                "cluster": {
                    "id": cluster.cluster_id,
                    "name": cluster.name,
                    "summary": cluster.summary,
                    "tags": cluster.tags,
                    "memory_count": len(memories),
                    "memories": [
                        {
                            "id": m.id,
                            "content": m.content,
                            "relevance": m.relevance,
                            "tags": m.tags,
                        }
                        for m in sorted(memories, key=lambda x: x.relevance, reverse=True)
                    ],
                }
            }

        # Return all cluster summaries
        clusters = []
        for cluster in proj.clusters.values():
            clusters.append({
                "id": cluster.cluster_id,
                "name": cluster.name,
                "summary": cluster.summary,
                "tags": cluster.tags,
                "memory_count": len(cluster.memory_ids),
                "relevance": cluster.relevance,
            })

        # Also include unclustered memories count
        clustered_ids = set()
        for c in proj.clusters.values():
            clustered_ids.update(c.memory_ids)

        unclustered = [e for e in proj.entries if e.id not in clustered_ids]

        return {
            "clusters": sorted(clusters, key=lambda x: x["relevance"], reverse=True),
            "unclustered_count": len(unclustered),
            "total_memories": len(proj.entries),
        }

    def get_contextual_memories(
        self,
        project_path: str,
        file_path: str,
        limit: int = 3,
    ) -> list[MemoryEntry]:
        """
        Get memories relevant to a specific file context.
        Used by hooks for contextual injection.

        Args:
            project_path: The project
            file_path: The file being edited
            limit: Max memories to return

        Returns:
            List of relevant memories
        """
        # Extract potential tags from file path
        path_lower = file_path.lower()
        inferred_tags = []

        for pattern, tag in self.TAG_PATTERNS.items():
            if re.search(pattern, path_lower):
                inferred_tags.append(tag)

        # Search by file and inferred tags
        return self.search_memories(
            project_path=project_path,
            file_path=file_path,
            tags=inferred_tags if inferred_tags else None,
            limit=limit,
        )

    # =========================================================================
    # v3: Rules and Memory Management
    # =========================================================================

    def add_rule(
        self,
        project_path: str,
        content: str,
        reason: Optional[str] = None,
        relevance: int = 9,
    ) -> tuple[bool, str]:
        """
        Add a global rule that should always be followed.
        Rules are always shown at session start and have high priority.

        Args:
            project_path: The project this rule applies to
            content: The rule content (e.g., "Always use strict TypeScript")
            reason: Why this rule exists
            relevance: Importance (default 9 - rules are important)

        Returns:
            (added, message)
        """
        proj = self.remember_project(project_path)

        # Include reason in content if provided
        full_content = content
        if reason:
            full_content = f"{content} (Reason: {reason})"

        # Check for duplicate rules
        existing_rules = [e for e in proj.entries if e.category == "rule"]
        duplicate = self._is_duplicate(full_content, existing_rules)
        if duplicate:
            return (False, f"Similar rule already exists (id={duplicate.id})")

        entry = MemoryEntry(
            id=self._generate_entry_id(full_content),
            content=full_content,
            category="rule",
            source="add_rule",
            relevance=relevance,
            tags=self._extract_tags(full_content) + ["rule"],
            related_files=self._extract_file_refs(full_content),
        )

        proj.entries.append(entry)
        self._update_indexes(proj, entry)
        proj.last_updated = time.time()
        self._save()

        return (True, f"Rule added with id={entry.id}")

    def get_rules(self, project_path: str) -> list[MemoryEntry]:
        """
        Get all rules for a project, sorted by relevance.
        Rules should always be displayed at session start.
        """
        proj = self.get_project(project_path)
        if not proj:
            return []

        rules = [e for e in proj.entries if e.category == "rule"]
        return sorted(rules, key=lambda x: x.relevance, reverse=True)

    def get_recent_memories(
        self,
        project_path: str,
        category: Optional[str] = None,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """
        Get recent memories, newest first.
        Useful for showing context of where you left off.

        Args:
            project_path: The project
            category: Optional filter by category
            limit: Max memories to return
        """
        proj = self.get_project(project_path)
        if not proj:
            return []

        entries = proj.entries
        if category:
            entries = [e for e in entries if e.category == category]

        # Sort by created_at descending (newest first)
        entries = sorted(entries, key=lambda x: x.created_at, reverse=True)
        return entries[:limit]

    def modify_memory(
        self,
        project_path: str,
        memory_id: str,
        content: Optional[str] = None,
        relevance: Optional[int] = None,
        category: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        Modify an existing memory.

        Args:
            project_path: The project
            memory_id: ID of memory to modify
            content: New content (optional)
            relevance: New relevance (optional)
            category: New category (optional)

        Returns:
            (success, message)
        """
        proj = self.get_project(project_path)
        if not proj:
            return (False, "Project not found")

        entry = self._get_entry_by_id(proj, memory_id)
        if not entry:
            return (False, f"Memory {memory_id} not found")

        changes = []
        if content is not None:
            entry.content = content
            entry.tags = self._extract_tags(content)
            entry.related_files = self._extract_file_refs(content)
            changes.append("content")

        if relevance is not None:
            entry.relevance = relevance
            changes.append("relevance")

        if category is not None:
            entry.category = category
            changes.append("category")

        if changes:
            # Rebuild indexes if content changed
            if "content" in changes:
                self._rebuild_indexes(proj)
            self._save()
            return (True, f"Modified: {', '.join(changes)}")

        return (False, "No changes specified")

    def delete_memory(
        self,
        project_path: str,
        memory_id: str,
    ) -> tuple[bool, str]:
        """
        Delete a memory by ID.

        Args:
            project_path: The project
            memory_id: ID of memory to delete

        Returns:
            (success, message)
        """
        proj = self.get_project(project_path)
        if not proj:
            return (False, "Project not found")

        entry = self._get_entry_by_id(proj, memory_id)
        if not entry:
            return (False, f"Memory {memory_id} not found")

        # Remove from entries
        proj.entries = [e for e in proj.entries if e.id != memory_id]

        # Rebuild indexes
        self._rebuild_indexes(proj)
        self._save()

        return (True, f"Deleted memory {memory_id}")

    def batch_delete(
        self,
        project_path: str,
        memory_ids: Optional[list[str]] = None,
        category: Optional[str] = None,
    ) -> tuple[int, str]:
        """
        Delete multiple memories by IDs or by category.

        Args:
            project_path: The project
            memory_ids: List of memory IDs to delete
            category: Delete all memories in this category (e.g. "context", "discovery")

        Returns:
            (count_deleted, message)
        """
        proj = self.get_project(project_path)
        if not proj:
            return (0, "Project not found")

        before = len(proj.entries)

        if memory_ids:
            id_set = set(memory_ids)
            proj.entries = [e for e in proj.entries if e.id not in id_set]
        elif category:
            if category in ("rule", "mistake"):
                return (0, f"Cannot bulk-delete '{category}' memories (protected). Use delete with specific memory_ids instead.")
            proj.entries = [e for e in proj.entries if e.category != category]
        else:
            return (0, "Specify memory_ids or category")

        deleted = before - len(proj.entries)
        if deleted > 0:
            self._rebuild_indexes(proj)
            self._save()

        return (deleted, f"Deleted {deleted} memories")

    def promote_to_rule(
        self,
        project_path: str,
        memory_id: str,
        reason: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        Promote a memory to a rule.
        Useful when a discovery turns out to be important enough to always follow.

        Args:
            project_path: The project
            memory_id: ID of memory to promote
            reason: Why this is now a rule

        Returns:
            (success, message)
        """
        proj = self.get_project(project_path)
        if not proj:
            return (False, "Project not found")

        entry = self._get_entry_by_id(proj, memory_id)
        if not entry:
            return (False, f"Memory {memory_id} not found")

        if entry.category == "rule":
            return (False, "Already a rule")

        # Promote
        entry.category = "rule"
        entry.relevance = max(entry.relevance, 8)  # Rules should be high relevance
        if "rule" not in entry.tags:
            entry.tags.append("rule")

        if reason:
            entry.content = f"{entry.content} (Promoted to rule: {reason})"

        self._save()
        return (True, f"Promoted {memory_id} to rule")

    def _rebuild_indexes(self, proj: ProjectMemory):
        """Rebuild file and tag indexes from scratch."""
        proj.file_memory_index = {}
        proj.tag_memory_index = {}
        for entry in proj.entries:
            self._update_indexes(proj, entry)

    # =========================================================================
    # v3: Archive Tier & Smart Scoring
    # =========================================================================

    def _load_archive(self):
        """Lazy-load archive data. Only called by archive operations, never on hot path."""
        if self._archive_loaded:
            return
        if self.archive_file.exists():
            try:
                data = json.loads(self.archive_file.read_text())
                for path, proj_data in data.get("projects", {}).items():
                    norm_path = self._normalize_path(path)
                    proj_data["project_path"] = norm_path
                    self._archive_projects[norm_path] = ProjectMemory(**proj_data)
            except Exception:
                pass  # Archive is best-effort
        self._archive_loaded = True

    def _save_archive(self) -> bool:
        """Save archive to disk. Same atomic pattern as _save()."""
        data = {
            "version": 2,
            "projects": {
                path: proj.model_dump()
                for path, proj in self._archive_projects.items()
            },
        }
        try:
            temp_file = self.archive_file.with_suffix(".json.tmp")
            temp_file.write_text(json.dumps(data, indent=2))
            temp_file.replace(self.archive_file)
            return True
        except Exception:
            return False

    def _is_archivable(self, entry: MemoryEntry) -> bool:
        """Check if an entry should be moved to archive."""
        # Rules and mistakes are NEVER archived
        if entry.category in ("rule", "mistake"):
            return False
        # High relevance entries stay hot longer
        if entry.relevance >= 7:
            return False
        age_days = (time.time() - entry.last_accessed) / 86400
        return age_days > self.archive_after_days

    def archive_old_memories(
        self,
        project_path: str,
        dry_run: bool = True,
    ) -> dict:
        """
        Move old inactive memories from hot to archive tier.

        Returns report with counts and previews.
        """
        proj = self.get_project(project_path)
        if not proj:
            return {"archived_count": 0, "entries": [], "dry_run": dry_run}

        to_archive = [e for e in proj.entries if self._is_archivable(e)]

        report = {
            "archived_count": len(to_archive),
            "entries": [
                {"id": e.id, "category": e.category, "age_days": int((time.time() - e.last_accessed) / 86400),
                 "preview": e.content[:60] + "..." if len(e.content) > 60 else e.content}
                for e in to_archive
            ],
            "dry_run": dry_run,
        }

        if not dry_run and to_archive:
            self._load_archive()
            norm_path = self._normalize_path(project_path)

            # Ensure archive project exists
            if norm_path not in self._archive_projects:
                self._archive_projects[norm_path] = ProjectMemory(
                    project_path=norm_path,
                    project_name=proj.project_name,
                )

            archive_proj = self._archive_projects[norm_path]
            archive_ids = {e.id for e in archive_proj.entries}

            # Move entries
            for entry in to_archive:
                entry.archived_at = time.time()
                if entry.id not in archive_ids:
                    archive_proj.entries.append(entry)

            # Remove from hot
            archived_ids = {e.id for e in to_archive}
            proj.entries = [e for e in proj.entries if e.id not in archived_ids]
            self._rebuild_indexes(proj)

            self._save()
            self._save_archive()

        return report

    def restore_from_archive(
        self,
        project_path: str,
        memory_id: str,
    ) -> tuple[bool, str]:
        """Move a memory from archive back to active hot tier."""
        self._load_archive()
        norm_path = self._normalize_path(project_path)
        archive_proj = self._archive_projects.get(norm_path)

        if not archive_proj:
            return (False, "No archive for this project")

        entry = self._get_entry_by_id(archive_proj, memory_id)
        if not entry:
            return (False, f"Memory {memory_id} not found in archive")

        # Move to hot
        entry.archived_at = None
        entry.last_accessed = time.time()
        entry.access_count += 1

        proj = self.remember_project(project_path)
        proj.entries.append(entry)
        self._update_indexes(proj, entry)

        # Remove from archive
        archive_proj.entries = [e for e in archive_proj.entries if e.id != memory_id]

        self._save()
        self._save_archive()
        return (True, f"Restored memory {memory_id} to active")

    def search_archive(
        self,
        project_path: str,
        query: Optional[str] = None,
        tags: Optional[list[str]] = None,
        limit: int = 5,
    ) -> list[MemoryEntry]:
        """Search archived memories. Read-only — does not update access counts."""
        self._load_archive()
        norm_path = self._normalize_path(project_path)
        archive_proj = self._archive_projects.get(norm_path)
        if not archive_proj:
            return []

        results = []
        for entry in archive_proj.entries:
            matched = False
            if query:
                query_words = set(query.lower().split())
                content_words = set(entry.content.lower().split())
                if query_words & content_words:
                    matched = True
            if tags:
                if set(tags) & set(entry.tags):
                    matched = True
            if not query and not tags:
                matched = True  # Return all if no filter
            if matched:
                results.append(entry)

        return sorted(results, key=lambda x: x.relevance, reverse=True)[:limit]

    def get_archive_stats(self, project_path: str) -> dict:
        """Get hot vs archived memory counts."""
        self._load_archive()
        norm_path = self._normalize_path(project_path)

        hot_proj = self.get_project(project_path)
        archive_proj = self._archive_projects.get(norm_path)

        hot_entries = hot_proj.entries if hot_proj else []
        archive_entries = archive_proj.entries if archive_proj else []

        # Count by category
        hot_cats = {}
        for e in hot_entries:
            hot_cats[e.category] = hot_cats.get(e.category, 0) + 1

        archive_cats = {}
        for e in archive_entries:
            archive_cats[e.category] = archive_cats.get(e.category, 0) + 1

        return {
            "hot_total": len(hot_entries),
            "hot_categories": hot_cats,
            "archive_total": len(archive_entries),
            "archive_categories": archive_cats,
        }

    def _score_memory_relevance(self, entry: MemoryEntry, context: dict) -> float:
        """
        Score a memory's relevance to the current context.

        Context dict: {"file_path": str, "tool_name": str, "command": str, "tags": list[str]}
        Returns 0.0-1.0 score.
        """
        score = 0.0

        # File path match
        file_score = 0.0
        ctx_file = context.get("file_path", "")
        if ctx_file:
            ctx_name = Path(ctx_file).name
            ctx_dir = str(Path(ctx_file).parent)
            ctx_ext = Path(ctx_file).suffix

            for rf in entry.related_files:
                rf_name = Path(rf).name
                if rf == ctx_file or rf_name == ctx_name:
                    file_score = 1.0
                    break
                elif str(Path(rf).parent) == ctx_dir:
                    file_score = max(file_score, 0.6)
                elif Path(rf).suffix == ctx_ext:
                    file_score = max(file_score, 0.2)

            if file_score < 0.4 and ctx_name in entry.content:
                file_score = max(file_score, 0.4)

        score += SCORE_WEIGHTS["file_match"] * file_score

        # Tag overlap
        ctx_tags = set(context.get("tags", []))
        if ctx_file:
            for pattern, tag in self.TAG_PATTERNS.items():
                if re.search(pattern, ctx_file, re.IGNORECASE):
                    ctx_tags.add(tag)

        if ctx_tags and entry.tags:
            tag_score = len(ctx_tags & set(entry.tags)) / len(ctx_tags)
        else:
            tag_score = 0.0
        score += SCORE_WEIGHTS["tag_overlap"] * tag_score

        # Recency (exponential decay)
        age_days = (time.time() - entry.last_accessed) / 86400
        recency_score = math.exp(-age_days / RECENCY_HALF_LIFE_DAYS)
        score += SCORE_WEIGHTS["recency"] * recency_score

        # Relevance score
        score += SCORE_WEIGHTS["relevance"] * (entry.relevance / 10.0)

        # Access frequency
        score += SCORE_WEIGHTS["access_freq"] * min(entry.access_count / 10.0, 1.0)

        # Category bonuses
        score += CATEGORY_BONUSES.get(entry.category, 0.0)

        return min(score, 1.0)

    def score_and_rank(
        self,
        project_path: str,
        context: dict,
        limit: int = 3,
        include_archive: bool = False,
    ) -> list[tuple[MemoryEntry, float]]:
        """
        Score and rank memories by relevance to context.

        Returns list of (entry, score) tuples, sorted descending.
        """
        proj = self.get_project(project_path)
        if not proj:
            return []

        entries = list(proj.entries)

        if include_archive:
            self._load_archive()
            norm_path = self._normalize_path(project_path)
            archive_proj = self._archive_projects.get(norm_path)
            if archive_proj:
                entries.extend(archive_proj.entries)

        scored = [(e, self._score_memory_relevance(e, context)) for e in entries]
        scored.sort(key=lambda x: x[1], reverse=True)

        # Update access tracking for returned results (hot only)
        for entry, _ in scored[:limit]:
            if entry.archived_at is None:
                entry.last_accessed = time.time()
                entry.access_count += 1

        if scored[:limit]:
            self._save()

        return scored[:limit]

    # =========================================================================
    # v4: LLM-Powered Memory Consolidation
    # =========================================================================

    def consolidate_memories(
        self,
        project_path: str,
        llm_client,
        tag: Optional[str] = None,
        dry_run: bool = True,
    ) -> dict:
        """
        Use LLM to intelligently consolidate related memories.

        Instead of just merging duplicates, this:
        1. Groups memories by tag or similarity
        2. Uses LLM to summarize groups into coherent consolidated memories
        3. Preserves important details while reducing redundancy

        Args:
            project_path: The project
            llm_client: LLMClient instance for summarization
            tag: Optional specific tag to consolidate (e.g., "bootstrap")
            dry_run: If True, show what would be consolidated without doing it

        Returns:
            Consolidation report
        """
        proj = self.get_project(project_path)
        if not proj:
            return {"error": "Project not found"}

        report = {
            "groups_found": [],
            "consolidated": [],
            "dry_run": dry_run,
            "original_count": len(proj.entries),
        }

        # Group memories by tag
        tag_groups = {}
        for entry in proj.entries:
            # Skip rules and mistakes - don't consolidate these
            if entry.category in ("rule", "mistake"):
                continue

            for t in entry.tags:
                if tag and t != tag:
                    continue
                if t not in tag_groups:
                    tag_groups[t] = []
                tag_groups[t].append(entry)

        # Find groups with 3+ entries that could benefit from consolidation
        for t, entries in tag_groups.items():
            if len(entries) < 3:
                continue

            # Skip if already a cluster
            if any(e.cluster_id for e in entries):
                continue

            group_info = {
                "tag": t,
                "count": len(entries),
                "entries": [
                    {"id": e.id, "preview": e.content[:60] + "..." if len(e.content) > 60 else e.content}
                    for e in entries[:5]  # Show first 5
                ],
            }

            if not dry_run and llm_client:
                # Use LLM to create consolidated summary
                consolidated = self._consolidate_group_with_llm(entries, t, llm_client)
                if consolidated:
                    group_info["consolidated_to"] = consolidated
                    report["consolidated"].append({
                        "tag": t,
                        "original_count": len(entries),
                        "new_memory_id": consolidated["id"],
                    })

            report["groups_found"].append(group_info)

        # Summary
        if report["groups_found"]:
            if dry_run:
                report["summary"] = f"Found {len(report['groups_found'])} groups that could be consolidated"
            else:
                report["summary"] = f"Consolidated {len(report['consolidated'])} groups"
                report["new_count"] = len(proj.entries)
        else:
            report["summary"] = "No groups found that need consolidation"

        return report

    def _consolidate_group_with_llm(
        self,
        entries: list[MemoryEntry],
        tag: str,
        llm_client,
    ) -> Optional[dict]:
        """Use LLM to consolidate a group of memories into one."""
        # Build prompt with all memory contents
        memories_text = "\n\n".join([
            f"Memory {i+1} (relevance {e.relevance}):\n{e.content}"
            for i, e in enumerate(entries)
        ])

        prompt = f"""You are consolidating related memories about "{tag}".

These {len(entries)} memories are related and contain overlapping information:

{memories_text}

Create ONE consolidated memory that:
1. Preserves all important facts and decisions
2. Removes redundancy
3. Is clear and actionable
4. Keeps the most important details

Output ONLY the consolidated memory text (no explanation):"""

        result = llm_client.generate(
            prompt=prompt,
            system="You are a memory consolidation assistant. Output only the consolidated memory.",
            temperature=0.1,
        )

        if not result.get("success"):
            return None

        consolidated_content = result["response"].strip()
        if not consolidated_content or len(consolidated_content) < 20:
            return None

        # Find the project this belongs to
        proj = None
        for p in self._projects.values():
            if entries[0] in p.entries:
                proj = p
                break

        if not proj:
            return None

        # Calculate max relevance from group
        max_relevance = max(e.relevance for e in entries)

        # Create new consolidated entry
        new_entry = MemoryEntry(
            id=self._generate_entry_id(consolidated_content),
            content=f"[Consolidated from {len(entries)} memories] {consolidated_content}",
            category="discovery",
            source="consolidation",
            relevance=max_relevance,
            tags=list(set(t for e in entries for t in e.tags)),
            related_files=list(set(f for e in entries for f in e.related_files)),
        )

        # Remove old entries
        old_ids = {e.id for e in entries}
        proj.entries = [e for e in proj.entries if e.id not in old_ids]

        # Add new entry
        proj.entries.append(new_entry)
        self._rebuild_indexes(proj)
        self._save()

        return {
            "id": new_entry.id,
            "content": new_entry.content[:100] + "...",
            "removed_count": len(old_ids),
        }


# =============================================================================
# HotMemoryReader — Lightweight reader for hook-time injection
# =============================================================================

# Tag patterns duplicated from MemoryStore for standalone use in hooks
_HOOK_TAG_PATTERNS = {
    r"\bauth\b|login|password|authentication": "auth",
    r"test|pytest|unittest|jest": "testing",
    r"config|settings|\.env": "config",
    r"database|db|sql|migration": "database",
    r"api|endpoint|route|handler": "api",
    r"security|vulnerability": "security",
    r"performance|optimize|slow": "performance",
    r"bug|fix|error|crash": "bugfix",
}


class HotMemoryReader:
    """
    Lightweight, read-only reader for hook-time memory injection.

    Reads only memory.json (hot tier), never archive.
    Works on raw dicts (no Pydantic parsing) for speed.
    Designed to be instantiated per hook call — no caching.
    """

    def __init__(self, storage_dir: str = "~/.mini_claude"):
        self.memory_file = Path(storage_dir).expanduser() / "memory.json"

    def get_scored_memories(
        self,
        project_path: str,
        context: dict,
        limit: int = 3,
    ) -> list[dict]:
        """
        Score and rank hot memories for injection.

        Args:
            project_path: Project directory
            context: {"file_path": str, "tool_name": str, "command": str, "tags": list[str]}
            limit: Max memories to return

        Returns:
            List of raw entry dicts sorted by score descending.
        """
        if not self.memory_file.exists():
            return []

        try:
            data = json.loads(self.memory_file.read_text())
        except Exception:
            return []

        # Find project — check exact path, then walk up parent paths
        # This handles the workspace case: memories stored under e:/workspace
        # are found when the hook resolves e:/workspace/mini_claude as the project
        normalized = str(Path(project_path).resolve()).replace("\\", "/")
        if len(normalized) >= 2 and normalized[1] == ":":
            normalized = normalized[0].lower() + normalized[1:]

        projects = data.get("projects", {})

        # Collect entries from this project AND all ancestor projects
        # (e.g., workspace-level memories apply to sub-projects too)
        all_entries = []
        check_path = normalized
        while check_path:
            if check_path in projects:
                all_entries.extend(projects[check_path].get("entries", []))
            # Move up one directory
            parent = str(Path(check_path).parent).replace("\\", "/")
            if parent == check_path:
                break  # Hit root
            check_path = parent

        # Also try name-based fallback for the primary project
        if not all_entries:
            project_name = Path(project_path).name
            for path, p in projects.items():
                if Path(path).name == project_name:
                    all_entries.extend(p.get("entries", []))
                    break

        if not all_entries:
            return []

        entries = all_entries
        if not entries:
            return []

        # Score each entry
        scored = []
        for entry in entries:
            score = self._score_entry(entry, context)
            if score > 0.1:  # Skip completely irrelevant
                scored.append((entry, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [e for e, _ in scored[:limit]]

    @staticmethod
    def _score_entry(entry: dict, context: dict) -> float:
        """Score a raw entry dict against context. Fast, no Pydantic."""
        score = 0.0
        ctx_file = context.get("file_path", "")
        related_files = entry.get("related_files", [])
        content = entry.get("content", "")
        entry_tags = set(entry.get("tags", []))

        # File match (0.35)
        file_score = 0.0
        if ctx_file:
            ctx_name = Path(ctx_file).name
            for rf in related_files:
                if Path(rf).name == ctx_name:
                    file_score = 1.0
                    break
            if file_score < 0.4 and ctx_name in content:
                file_score = 0.4
        score += SCORE_WEIGHTS["file_match"] * file_score

        # Tag overlap (0.20)
        ctx_tags = set(context.get("tags", []))
        if ctx_file:
            for pattern, tag in _HOOK_TAG_PATTERNS.items():
                if re.search(pattern, ctx_file, re.IGNORECASE):
                    ctx_tags.add(tag)
        if ctx_tags and entry_tags:
            tag_score = len(ctx_tags & entry_tags) / len(ctx_tags)
        else:
            tag_score = 0.0
        score += SCORE_WEIGHTS["tag_overlap"] * tag_score

        # Recency (0.20)
        last_accessed = entry.get("last_accessed", entry.get("created_at", 0))
        age_days = (time.time() - last_accessed) / 86400 if last_accessed else 999
        recency_score = math.exp(-age_days / RECENCY_HALF_LIFE_DAYS)
        score += SCORE_WEIGHTS["recency"] * recency_score

        # Relevance (0.15)
        score += SCORE_WEIGHTS["relevance"] * (entry.get("relevance", 5) / 10.0)

        # Access frequency (0.10)
        score += SCORE_WEIGHTS["access_freq"] * min(entry.get("access_count", 1) / 10.0, 1.0)

        # Category bonuses
        category = entry.get("category", "")
        score += CATEGORY_BONUSES.get(category, 0.0)

        return min(score, 1.0)
