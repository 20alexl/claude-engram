"""
Dependency Mapper - Understand code relationships for Claude Engram

Maps out:
1. What a file imports
2. What imports a file (reverse dependencies)
3. Dependency graph for a module
"""

import os
import re
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..llm import LLMClient

from ..schema import MiniClaudeResponse, WorkLog


class DependencyMapper:
    """
    Map dependencies between files and modules.

    Helps answer questions like:
    - What does this file depend on?
    - What would break if I changed this file?
    - What's the dependency graph for this module?
    """

    def __init__(self, llm: "LLMClient"):
        self.llm = llm

    def map_file(
        self,
        file_path: str,
        project_root: Optional[str] = None,
        include_reverse: bool = False,
    ) -> MiniClaudeResponse:
        """
        Map dependencies for a single file.

        Args:
            file_path: Path to the file to analyze
            project_root: Root directory to search for reverse deps
            include_reverse: Whether to find what imports this file
        """
        work_log = WorkLog()
        work_log.what_i_tried.append("dependency extraction")

        path = Path(file_path)
        if not path.exists():
            return MiniClaudeResponse(
                status="failed",
                confidence="high",
                reasoning=f"File does not exist: {file_path}",
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

        # Extract imports
        ext = path.suffix.lower()
        imports = self._extract_imports(content, ext)
        work_log.what_worked.append(f"found {len(imports)} imports")

        # Categorize imports
        categorized = self._categorize_imports(imports, ext)

        data = {
            "file": str(path),
            "imports": {
                "all": imports,
                "stdlib": categorized.get("stdlib", []),
                "external": categorized.get("external", []),
                "internal": categorized.get("internal", []),
            },
        }

        # Find reverse dependencies if requested
        if include_reverse and project_root:
            work_log.what_i_tried.append("reverse dependency search")
            reverse_deps = self._find_reverse_deps(path, project_root, ext)
            data["imported_by"] = reverse_deps
            work_log.files_examined += reverse_deps.get("files_scanned", 0)
            work_log.what_worked.append(f"found {len(reverse_deps.get('files', []))} reverse deps")

        return MiniClaudeResponse(
            status="success",
            confidence="high" if imports else "medium",
            reasoning=f"Found {len(imports)} imports for {path.name}",
            work_log=work_log,
            data=data,
            suggestions=self._generate_suggestions(data),
        )

    def _extract_imports(self, content: str, extension: str) -> list[str]:
        """Extract import statements based on file type."""
        imports = []

        # Python
        if extension == ".py":
            # from x import y
            imports.extend(re.findall(r"^from\s+([\w.]+)\s+import", content, re.MULTILINE))
            # import x
            imports.extend(re.findall(r"^import\s+([\w.]+)", content, re.MULTILINE))

        # JavaScript/TypeScript
        elif extension in (".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"):
            # import from 'x' or require('x')
            imports.extend(re.findall(r"import\s+.*?from\s+['\"]([^'\"]+)['\"]", content))
            imports.extend(re.findall(r"require\(['\"]([^'\"]+)['\"]\)", content))

        # Go
        elif extension == ".go":
            # import "x" or in import block
            imports.extend(re.findall(r'import\s+["\(]([^"\)]+)', content))
            imports.extend(re.findall(r'"([^"]+)"', content[:3000]))  # Imports at top

        # Rust
        elif extension == ".rs":
            imports.extend(re.findall(r"use\s+([\w:]+)", content))

        # Java
        elif extension == ".java":
            imports.extend(re.findall(r"import\s+([\w.]+);", content))

        # C/C++
        elif extension in (".c", ".cpp", ".h", ".hpp"):
            imports.extend(re.findall(r'#include\s*[<"]([^>"]+)[>"]', content))

        return list(set(imports))

    def _categorize_imports(self, imports: list[str], extension: str) -> dict:
        """Categorize imports as stdlib, external, or internal."""
        categorized = {
            "stdlib": [],
            "external": [],
            "internal": [],
        }

        # Python standard library (incomplete but common ones)
        python_stdlib = {
            "os", "sys", "re", "json", "time", "datetime", "collections",
            "itertools", "functools", "pathlib", "typing", "asyncio",
            "subprocess", "threading", "multiprocessing", "logging",
            "unittest", "pytest", "argparse", "dataclasses", "enum",
            "abc", "io", "hashlib", "random", "math", "copy", "pickle",
        }

        for imp in imports:
            if extension == ".py":
                base_module = imp.split(".")[0]
                if base_module in python_stdlib:
                    categorized["stdlib"].append(imp)
                elif imp.startswith("."):
                    categorized["internal"].append(imp)
                else:
                    # Single-segment packages without dots are likely external (requests, flask, etc.)
                    categorized["external"].append(imp)

            elif extension in (".js", ".ts", ".jsx", ".tsx"):
                if imp.startswith(".") or imp.startswith("/"):
                    categorized["internal"].append(imp)
                elif imp.startswith("@"):
                    categorized["external"].append(imp)
                else:
                    categorized["external"].append(imp)

            else:
                # Default: just put in external
                categorized["external"].append(imp)

        return categorized

    def _find_reverse_deps(
        self,
        target_path: Path,
        project_root: str,
        extension: str,
    ) -> dict:
        """Find files that import the target file."""
        result = {
            "files": [],
            "files_scanned": 0,
        }

        root = Path(project_root)
        target_name = target_path.stem
        target_rel = str(target_path.relative_to(root)) if target_path.is_relative_to(root) else str(target_path)

        # Directories to skip
        skip_dirs = {"node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build"}

        # Extensions to search
        search_extensions = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java"}

        for root_dir, dirs, files in os.walk(root):
            # Skip unwanted directories
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]

            for filename in files:
                filepath = Path(root_dir) / filename
                if filepath.suffix.lower() not in search_extensions:
                    continue
                if filepath == target_path:
                    continue

                result["files_scanned"] += 1

                try:
                    content = filepath.read_text(errors="ignore")

                    # Check if this file imports our target
                    # This is a heuristic - not perfect
                    if target_name in content:
                        # More specific check
                        imports_target = False

                        if extension == ".py":
                            patterns = [
                                rf"from\s+[\w.]*{target_name}\s+import",
                                rf"import\s+[\w.]*{target_name}",
                            ]
                        elif extension in (".js", ".ts", ".jsx", ".tsx"):
                            patterns = [
                                rf"from\s+['\"].*{target_name}['\"]",
                                rf"require\(['\"].*{target_name}['\"]\)",
                            ]
                        else:
                            patterns = [rf"\b{target_name}\b"]

                        for pattern in patterns:
                            if re.search(pattern, content):
                                imports_target = True
                                break

                        if imports_target:
                            rel_path = str(filepath.relative_to(root))
                            result["files"].append(rel_path)

                except Exception:
                    continue

        return result

    def _generate_suggestions(self, data: dict) -> list[str]:
        """Generate suggestions based on dependency analysis."""
        suggestions = []

        imports = data.get("imports", {})

        # Many external deps
        external = imports.get("external", [])
        if len(external) > 10:
            suggestions.append(f"This file has {len(external)} external dependencies - consider if all are needed")

        # Circular dependency warning
        internal = imports.get("internal", [])
        if internal:
            suggestions.append("Check for circular dependencies in internal imports")

        # Reverse deps
        imported_by = data.get("imported_by", {})
        if imported_by.get("files"):
            count = len(imported_by["files"])
            if count > 5:
                suggestions.append(f"This file is imported by {count} other files - changes may have wide impact")

        return suggestions
