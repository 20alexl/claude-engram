"""
Impact Analyzer - Predict what might break before edits

One of my biggest failure modes is making changes without understanding
the ripple effects. This tool helps me:
1. Identify files that import/depend on the target
2. Find exported symbols (functions, classes, constants)
3. Track where those symbols are used
4. Estimate risk level for changes
"""

import os
import re
from pathlib import Path
from typing import Optional, TYPE_CHECKING
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from ..llm import LLMClient

from ..schema import MiniClaudeResponse, WorkLog


@dataclass
class ExportedSymbol:
    """A function, class, or constant exported from a file."""
    name: str
    kind: str  # "function", "class", "constant", "variable"
    line: int
    is_public: bool = True


@dataclass
class SymbolUsage:
    """Where a symbol is used in dependent files."""
    file: str
    line: int
    context: str  # The line of code where it's used


@dataclass
class ImpactReport:
    """Summary of potential impact from changing a file."""
    file: str
    dependents: list[str] = field(default_factory=list)
    exported_symbols: list[ExportedSymbol] = field(default_factory=list)
    symbol_usages: dict[str, list[SymbolUsage]] = field(default_factory=dict)
    risk_level: str = "low"  # "low", "medium", "high", "critical"
    risk_reasons: list[str] = field(default_factory=list)


class ImpactAnalyzer:
    """
    Analyze the potential impact of changing a file.

    Before I edit a file, this helps me understand:
    - How many files depend on it
    - What symbols it exports
    - Where those symbols are used
    - The overall risk of changes
    """

    def __init__(self, llm: "LLMClient"):
        self.llm = llm

    def analyze(
        self,
        file_path: str,
        project_root: str,
        proposed_changes: Optional[str] = None,
    ) -> MiniClaudeResponse:
        """
        Analyze potential impact of changing a file.

        Args:
            file_path: The file being considered for changes
            project_root: Root directory to search for dependents
            proposed_changes: Optional description of what might change
        """
        work_log = WorkLog()
        work_log.what_i_tried.append("impact analysis")

        path = Path(file_path)
        root = Path(project_root)

        # Validate paths
        if not path.exists():
            return self._error_response(f"File does not exist: {file_path}", work_log)

        if not root.exists():
            return self._error_response(f"Project root does not exist: {project_root}", work_log)

        try:
            content = path.read_text(errors="ignore")
        except Exception as e:
            return self._error_response(f"Could not read file: {e}", work_log)

        ext = path.suffix.lower()
        report = ImpactReport(file=str(path))

        # Step 1: Find exported symbols
        work_log.what_i_tried.append("extract exports")
        report.exported_symbols = self._extract_exports(content, ext)
        work_log.what_worked.append(f"found {len(report.exported_symbols)} exports")

        # Step 2: Find dependent files
        work_log.what_i_tried.append("find dependents")
        report.dependents = self._find_dependents(path, root, ext)
        work_log.files_examined = len(report.dependents) + 1
        work_log.what_worked.append(f"found {len(report.dependents)} dependent files")

        # Step 3: Track symbol usages in dependents
        if report.exported_symbols and report.dependents:
            work_log.what_i_tried.append("track symbol usages")
            report.symbol_usages = self._track_symbol_usages(
                report.exported_symbols,
                report.dependents,
                root,
            )
            usage_count = sum(len(usages) for usages in report.symbol_usages.values())
            work_log.what_worked.append(f"tracked {usage_count} symbol usages")

        # Step 4: Assess risk level
        report.risk_level, report.risk_reasons = self._assess_risk(report, proposed_changes)

        # Build response
        return self._build_response(report, work_log)

    # -------------------------------------------------------------------------
    # Export Extraction
    # -------------------------------------------------------------------------

    def _extract_exports(self, content: str, ext: str) -> list[ExportedSymbol]:
        """Extract exported symbols from file content."""
        if ext == ".py":
            return self._extract_python_exports(content)
        elif ext in (".js", ".ts", ".jsx", ".tsx"):
            return self._extract_js_exports(content)
        elif ext == ".go":
            return self._extract_go_exports(content)
        else:
            return []

    def _extract_python_exports(self, content: str) -> list[ExportedSymbol]:
        """Extract public functions, classes, and constants from Python."""
        exports = []
        lines = content.split("\n")

        for i, line in enumerate(lines, 1):
            # Functions
            match = re.match(r"^def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", line)
            if match:
                name = match.group(1)
                is_public = not name.startswith("_")
                exports.append(ExportedSymbol(
                    name=name,
                    kind="function",
                    line=i,
                    is_public=is_public,
                ))

            # Classes
            match = re.match(r"^class\s+([a-zA-Z_][a-zA-Z0-9_]*)", line)
            if match:
                name = match.group(1)
                is_public = not name.startswith("_")
                exports.append(ExportedSymbol(
                    name=name,
                    kind="class",
                    line=i,
                    is_public=is_public,
                ))

            # Constants (ALL_CAPS at module level)
            match = re.match(r"^([A-Z][A-Z0-9_]+)\s*=", line)
            if match:
                exports.append(ExportedSymbol(
                    name=match.group(1),
                    kind="constant",
                    line=i,
                    is_public=True,
                ))

        return exports

    def _extract_js_exports(self, content: str) -> list[ExportedSymbol]:
        """Extract exported functions, classes, and constants from JS/TS."""
        exports = []

        # export function/const/class
        for match in re.finditer(
            r"export\s+(default\s+)?(function|const|let|class|async function)\s+([a-zA-Z_$][a-zA-Z0-9_$]*)",
            content
        ):
            kind = match.group(2)
            name = match.group(3)
            line = content[:match.start()].count("\n") + 1

            if kind in ("const", "let"):
                kind = "constant"
            elif kind == "async function":
                kind = "function"

            exports.append(ExportedSymbol(
                name=name,
                kind=kind,
                line=line,
                is_public=True,
            ))

        # export { name1, name2 }
        for match in re.finditer(r"export\s*\{([^}]+)\}", content):
            names = [n.strip().split(" as ")[0].strip() for n in match.group(1).split(",")]
            line = content[:match.start()].count("\n") + 1
            for name in names:
                if name:
                    exports.append(ExportedSymbol(
                        name=name,
                        kind="variable",
                        line=line,
                        is_public=True,
                    ))

        return exports

    def _extract_go_exports(self, content: str) -> list[ExportedSymbol]:
        """Extract exported (capitalized) functions and types from Go."""
        exports = []

        # Functions
        for match in re.finditer(r"^func\s+(?:\([^)]+\)\s+)?([A-Z][a-zA-Z0-9_]*)\s*\(", content, re.MULTILINE):
            line = content[:match.start()].count("\n") + 1
            exports.append(ExportedSymbol(
                name=match.group(1),
                kind="function",
                line=line,
                is_public=True,
            ))

        # Types
        for match in re.finditer(r"^type\s+([A-Z][a-zA-Z0-9_]*)\s+", content, re.MULTILINE):
            line = content[:match.start()].count("\n") + 1
            exports.append(ExportedSymbol(
                name=match.group(1),
                kind="class",
                line=line,
                is_public=True,
            ))

        return exports

    # -------------------------------------------------------------------------
    # Dependent Finding
    # -------------------------------------------------------------------------

    def _find_dependents(self, target: Path, root: Path, ext: str) -> list[str]:
        """Find files that import/depend on the target file."""
        dependents = []
        target_name = target.stem
        target_rel = str(target.relative_to(root)) if target.is_relative_to(root) else target.name

        skip_dirs = {"node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build", ".next"}
        search_extensions = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java"}

        for root_dir, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]

            for filename in files:
                filepath = Path(root_dir) / filename
                if filepath.suffix.lower() not in search_extensions:
                    continue
                if filepath == target:
                    continue

                try:
                    content = filepath.read_text(errors="ignore")
                    if self._imports_target(content, target_name, target_rel, ext):
                        rel_path = str(filepath.relative_to(root))
                        dependents.append(rel_path)
                except Exception:
                    continue

        return dependents

    def _imports_target(self, content: str, target_name: str, target_rel: str, ext: str) -> bool:
        """Check if content imports the target file."""
        if target_name not in content:
            return False

        if ext == ".py":
            patterns = [
                rf"from\s+[\w.]*{re.escape(target_name)}\s+import",
                rf"import\s+[\w.]*{re.escape(target_name)}",
            ]
        elif ext in (".js", ".ts", ".jsx", ".tsx"):
            patterns = [
                rf"from\s+['\"].*{re.escape(target_name)}['\"]",
                rf"require\(['\"].*{re.escape(target_name)}['\"]\)",
            ]
        else:
            patterns = [rf"\b{re.escape(target_name)}\b"]

        return any(re.search(p, content) for p in patterns)

    # -------------------------------------------------------------------------
    # Symbol Usage Tracking
    # -------------------------------------------------------------------------

    def _track_symbol_usages(
        self,
        symbols: list[ExportedSymbol],
        dependents: list[str],
        root: Path,
    ) -> dict[str, list[SymbolUsage]]:
        """Find where exported symbols are used in dependent files."""
        usages: dict[str, list[SymbolUsage]] = {}

        # Only track public symbols
        public_symbols = [s for s in symbols if s.is_public]

        for dep_path in dependents:
            try:
                full_path = root / dep_path
                content = full_path.read_text(errors="ignore")
                lines = content.split("\n")

                for symbol in public_symbols:
                    pattern = rf"\b{re.escape(symbol.name)}\b"
                    for i, line in enumerate(lines, 1):
                        if re.search(pattern, line):
                            if symbol.name not in usages:
                                usages[symbol.name] = []
                            usages[symbol.name].append(SymbolUsage(
                                file=dep_path,
                                line=i,
                                context=line.strip()[:100],
                            ))
            except Exception:
                continue

        return usages

    # -------------------------------------------------------------------------
    # Risk Assessment
    # -------------------------------------------------------------------------

    def _assess_risk(
        self,
        report: ImpactReport,
        proposed_changes: Optional[str],
    ) -> tuple[str, list[str]]:
        """Assess the risk level of changing this file."""
        reasons = []
        score = 0

        # Dependent count
        dep_count = len(report.dependents)
        if dep_count == 0:
            reasons.append("No files depend on this - changes are isolated")
        elif dep_count <= 2:
            score += 1
            reasons.append(f"{dep_count} file(s) depend on this")
        elif dep_count <= 5:
            score += 2
            reasons.append(f"{dep_count} files depend on this - moderate reach")
        else:
            score += 3
            reasons.append(f"{dep_count} files depend on this - wide impact")

        # Export count
        export_count = len([s for s in report.exported_symbols if s.is_public])
        if export_count > 10:
            score += 1
            reasons.append(f"File exports {export_count} public symbols")

        # Usage count
        total_usages = sum(len(u) for u in report.symbol_usages.values())
        if total_usages > 20:
            score += 2
            reasons.append(f"Symbols are used {total_usages} times across dependents")
        elif total_usages > 5:
            score += 1
            reasons.append(f"Symbols are used {total_usages} times")

        # Check for specific high-risk patterns in proposed changes
        if proposed_changes:
            high_risk_words = ["rename", "delete", "remove", "signature", "parameter", "return type"]
            for word in high_risk_words:
                if word.lower() in proposed_changes.lower():
                    score += 1
                    reasons.append(f"Proposed change involves '{word}' - may break callers")
                    break

        # Determine level
        if score == 0:
            level = "low"
        elif score <= 2:
            level = "medium"
        elif score <= 4:
            level = "high"
        else:
            level = "critical"

        return level, reasons

    # -------------------------------------------------------------------------
    # Response Building
    # -------------------------------------------------------------------------

    def _build_response(self, report: ImpactReport, work_log: WorkLog) -> MiniClaudeResponse:
        """Build the response from an impact report."""
        # Format exports for output
        exports_data = [
            {
                "name": s.name,
                "kind": s.kind,
                "line": s.line,
                "public": s.is_public,
            }
            for s in report.exported_symbols
        ]

        # Format usages (limit to avoid huge output)
        usages_data = {}
        for symbol, usages in report.symbol_usages.items():
            usages_data[symbol] = [
                {"file": u.file, "line": u.line, "context": u.context}
                for u in usages[:5]  # Limit per symbol
            ]

        data = {
            "file": report.file,
            "risk_level": report.risk_level,
            "risk_reasons": report.risk_reasons,
            "dependents": report.dependents,
            "exports": exports_data,
            "symbol_usages": usages_data,
            "summary": {
                "dependent_count": len(report.dependents),
                "export_count": len(report.exported_symbols),
                "public_export_count": len([s for s in report.exported_symbols if s.is_public]),
                "total_usages": sum(len(u) for u in report.symbol_usages.values()),
            },
        }

        suggestions = self._generate_suggestions(report)
        warnings = []
        if report.risk_level in ("high", "critical"):
            warnings.append(f"Risk level is {report.risk_level.upper()} - consider the impact carefully")

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning=f"Impact analysis complete. Risk level: {report.risk_level}",
            work_log=work_log,
            data=data,
            suggestions=suggestions,
            warnings=warnings,
        )

    def _generate_suggestions(self, report: ImpactReport) -> list[str]:
        """Generate actionable suggestions based on analysis."""
        suggestions = []

        if report.dependents:
            suggestions.append(f"Review these files before changing: {', '.join(report.dependents[:3])}")

        if report.risk_level in ("high", "critical"):
            suggestions.append("Consider adding tests for dependent code before making changes")
            suggestions.append("Make changes incrementally and test after each step")

        # Most-used symbols
        if report.symbol_usages:
            most_used = sorted(
                report.symbol_usages.items(),
                key=lambda x: len(x[1]),
                reverse=True
            )[:3]
            for name, usages in most_used:
                if len(usages) > 2:
                    suggestions.append(f"'{name}' is used {len(usages)} times - changes will have wide effect")

        return suggestions

    def _error_response(self, message: str, work_log: WorkLog) -> MiniClaudeResponse:
        """Return an error response."""
        return MiniClaudeResponse(
            status="failed",
            confidence="high",
            reasoning=message,
            work_log=work_log,
        )
