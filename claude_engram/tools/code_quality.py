"""
Code Quality Checker - Lint for structure and naming before writing code

The problem: I (Claude) write monolithic functions with vague names like
'process_data', 'handle_request', 'do_thing'. Users complain about "AI slop".

The solution: Check code BEFORE writing it. Flag:
- Functions that are too long
- Vague/generic names
- Too many parameters
- Deep nesting
- Multiple responsibilities in one function
"""

import re
from dataclasses import dataclass
from typing import Optional
from ..schema import MiniClaudeResponse, WorkLog


# Names that are too vague/generic
VAGUE_NAMES = {
    "data", "result", "temp", "tmp", "var", "val", "value",
    "item", "items", "thing", "things", "obj", "object",
    "handle", "process", "do", "run", "execute", "perform",
    "manage", "helper", "util", "utils", "misc", "stuff",
    "foo", "bar", "baz", "test", "x", "y", "z", "i", "j", "k",
    "info", "details", "params", "args", "kwargs", "options",
    "input", "output", "ret", "res", "response", "request",
}

# Prefixes that often indicate vague naming
VAGUE_PREFIXES = [
    "do_", "handle_", "process_", "manage_", "run_",
    "perform_", "execute_", "my_", "the_", "get_data",
]


@dataclass
class QualityIssue:
    """A single code quality issue."""
    severity: str  # "error", "warning", "info"
    category: str  # "naming", "length", "complexity", "structure"
    message: str
    line: Optional[int] = None
    suggestion: Optional[str] = None


class CodeQualityChecker:
    """
    Checks code for quality issues before it gets written.

    This is NOT a linter for syntax - it's a structural quality checker
    focused on the issues I (Claude) commonly create:
    - Monolithic functions
    - Vague naming
    - Over-complicated structure
    """

    def __init__(
        self,
        max_function_lines: int = 50,
        max_parameters: int = 5,
        max_nesting_depth: int = 3,
        max_line_length: int = 100,
    ):
        self.max_function_lines = max_function_lines
        self.max_parameters = max_parameters
        self.max_nesting_depth = max_nesting_depth
        self.max_line_length = max_line_length

    def check(
        self,
        code: str,
        language: str = "python",
        context: Optional[str] = None,
    ) -> MiniClaudeResponse:
        """
        Check code for quality issues.

        Args:
            code: The code to check
            language: Programming language (python, javascript, typescript, etc.)
            context: Optional context about what the code does

        Returns:
            MiniClaudeResponse with issues found
        """
        work_log = WorkLog()
        work_log.what_i_tried.append("checking code quality")

        issues: list[QualityIssue] = []

        # Run all checks
        issues.extend(self._check_function_length(code, language))
        issues.extend(self._check_naming(code, language))
        issues.extend(self._check_parameters(code, language))
        issues.extend(self._check_nesting(code, language))
        issues.extend(self._check_line_length(code))
        issues.extend(self._check_complexity_indicators(code, language))

        # Categorize by severity
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        infos = [i for i in issues if i.severity == "info"]

        # Build response
        if errors:
            status = "failed"
            confidence = "high"
            reasoning = f"Found {len(errors)} serious issues that should be fixed"
        elif warnings:
            status = "success"
            confidence = "medium"
            reasoning = f"Found {len(warnings)} warnings to consider"
        else:
            status = "success"
            confidence = "high"
            reasoning = "Code looks structurally sound"

        work_log.what_worked.append(f"found {len(issues)} issues")

        # Format issues for display
        formatted_issues = []
        for issue in issues:
            formatted = {
                "severity": issue.severity,
                "category": issue.category,
                "message": issue.message,
            }
            if issue.line:
                formatted["line"] = issue.line
            if issue.suggestion:
                formatted["suggestion"] = issue.suggestion
            formatted_issues.append(formatted)

        # Build warnings list for response
        warning_messages = []
        for issue in errors + warnings:
            prefix = "ERROR:" if issue.severity == "error" else "WARNING:"
            msg = f"{prefix} {issue.message}"
            if issue.suggestion:
                msg += f" → {issue.suggestion}"
            warning_messages.append(msg)

        return MiniClaudeResponse(
            status=status,
            confidence=confidence,
            reasoning=reasoning,
            work_log=work_log,
            data={
                "issues": formatted_issues,
                "summary": {
                    "errors": len(errors),
                    "warnings": len(warnings),
                    "info": len(infos),
                    "total": len(issues),
                },
            },
            warnings=warning_messages[:10],  # Top 10 issues
            suggestions=[
                "Break long functions into smaller, focused ones",
                "Use descriptive names that explain WHAT and WHY",
                "Consider if this function is doing too many things",
            ] if issues else [],
        )

    def _check_function_length(
        self,
        code: str,
        language: str,
    ) -> list[QualityIssue]:
        """Check for functions that are too long."""
        issues = []

        # Pattern to find function definitions
        if language in ("python",):
            pattern = r'^(\s*)(def|async def)\s+(\w+)\s*\('
        elif language in ("javascript", "typescript", "js", "ts"):
            pattern = r'^\s*(async\s+)?function\s+(\w+)\s*\(|^\s*(const|let|var)\s+(\w+)\s*=\s*(async\s*)?\([^)]*\)\s*=>'
        else:
            # Generic - look for function-like patterns
            pattern = r'^\s*(def|function|fn|func)\s+(\w+)'

        lines = code.split('\n')
        i = 0
        while i < len(lines):
            match = re.match(pattern, lines[i], re.MULTILINE)
            if match:
                # Extract function name
                func_name = None
                for group in match.groups():
                    if group and group not in ('def', 'async def', 'function', 'async', 'const', 'let', 'var', 'fn', 'func'):
                        func_name = group
                        break

                if not func_name:
                    i += 1
                    continue

                # Count lines in function
                start_line = i
                func_lines = self._count_function_lines(lines, i, language)

                if func_lines > self.max_function_lines:
                    severity = "error" if func_lines > self.max_function_lines * 2 else "warning"
                    issues.append(QualityIssue(
                        severity=severity,
                        category="length",
                        message=f"Function '{func_name}' is {func_lines} lines (max: {self.max_function_lines})",
                        line=start_line + 1,
                        suggestion=f"Break into {func_lines // 20 + 1} smaller functions",
                    ))

                i += func_lines
            else:
                i += 1

        return issues

    def _count_function_lines(
        self,
        lines: list[str],
        start: int,
        language: str,
    ) -> int:
        """Count lines in a function starting at start index."""
        if language == "python":
            # Python: count by indentation
            if start >= len(lines):
                return 0

            # Get base indentation
            first_line = lines[start]
            base_indent = len(first_line) - len(first_line.lstrip())

            count = 1
            for i in range(start + 1, len(lines)):
                line = lines[i]
                stripped = line.strip()

                # Skip empty lines and comments
                if not stripped or stripped.startswith('#'):
                    count += 1
                    continue

                # Check indentation
                current_indent = len(line) - len(line.lstrip())
                if current_indent <= base_indent and stripped:
                    # Back to same or less indentation = function ended
                    break

                count += 1

            return count
        else:
            # JavaScript/etc: count by braces
            brace_count = 0
            started = False
            count = 0

            for i in range(start, len(lines)):
                line = lines[i]
                count += 1

                for char in line:
                    if char == '{':
                        brace_count += 1
                        started = True
                    elif char == '}':
                        brace_count -= 1

                if started and brace_count == 0:
                    break

            return count

    def _check_naming(
        self,
        code: str,
        language: str,
    ) -> list[QualityIssue]:
        """Check for vague or generic names."""
        issues = []

        # Find function/method names
        if language == "python":
            func_pattern = r'def\s+(\w+)\s*\('
        else:
            func_pattern = r'function\s+(\w+)\s*\(|(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>'

        for match in re.finditer(func_pattern, code):
            name = match.group(1) or match.group(2)
            if not name:
                continue

            # Check for vague names
            name_lower = name.lower()

            # Exact match to vague name
            if name_lower in VAGUE_NAMES:
                issues.append(QualityIssue(
                    severity="warning",
                    category="naming",
                    message=f"Function name '{name}' is too vague",
                    suggestion="Name should describe WHAT it does specifically",
                ))

            # Starts with vague prefix
            for prefix in VAGUE_PREFIXES:
                if name_lower.startswith(prefix):
                    issues.append(QualityIssue(
                        severity="info",
                        category="naming",
                        message=f"Function '{name}' has vague prefix '{prefix}'",
                        suggestion="Consider more specific name like 'validate_user_email' instead of 'handle_email'",
                    ))
                    break

            # Too short (single letter or two letters)
            if len(name) <= 2 and name_lower not in ('id', 'ok'):
                issues.append(QualityIssue(
                    severity="warning",
                    category="naming",
                    message=f"Function name '{name}' is too short",
                    suggestion="Use a descriptive name",
                ))

        # Check variable names in assignments (only actual assignments, not kwargs)
        var_pattern = r'^[ \t]*(\w+)\s*=[^=]'
        for match in re.finditer(var_pattern, code, re.MULTILINE):
            name = match.group(1)
            name_lower = name.lower()

            if name_lower in VAGUE_NAMES and name_lower not in ('i', 'j', 'k', 'x', 'y', 'z'):
                # Only flag if not a common loop variable
                issues.append(QualityIssue(
                    severity="info",
                    category="naming",
                    message=f"Variable '{name}' is vague",
                    suggestion="What kind of data/result/value is this?",
                ))

        return issues

    def _check_parameters(
        self,
        code: str,
        language: str,
    ) -> list[QualityIssue]:
        """Check for functions with too many parameters."""
        issues = []

        # Find function signatures
        if language == "python":
            pattern = r'def\s+(\w+)\s*\(([^)]*)\)'
        else:
            pattern = r'function\s+(\w+)\s*\(([^)]*)\)|(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>'

        for match in re.finditer(pattern, code, re.DOTALL):
            groups = match.groups()
            name = groups[0] or groups[2]
            params_str = groups[1] or groups[3]

            if not name or not params_str:
                continue

            # Count parameters (split by comma, filter empty)
            params = [p.strip() for p in params_str.split(',') if p.strip()]

            # Don't count self/cls in Python
            if language == "python":
                params = [p for p in params if p not in ('self', 'cls')]

            # Don't count *args, **kwargs
            params = [p for p in params if not p.startswith('*')]

            if len(params) > self.max_parameters:
                issues.append(QualityIssue(
                    severity="warning",
                    category="structure",
                    message=f"Function '{name}' has {len(params)} parameters (max: {self.max_parameters})",
                    suggestion="Consider using a config object or dataclass",
                ))

        return issues

    def _check_nesting(
        self,
        code: str,
        language: str,
    ) -> list[QualityIssue]:
        """Check for deeply nested code."""
        issues = []
        lines = code.split('\n')

        for i, line in enumerate(lines):
            if not line.strip():
                continue

            # Count nesting by indentation
            stripped = line.lstrip()
            if not stripped:
                continue

            if language == "python":
                # Python: count by indentation (assuming 4 spaces)
                indent = len(line) - len(stripped)
                nesting = indent // 4
            else:
                # Other: count leading braces/keywords up to this point
                nesting = 0
                for prev_line in lines[:i]:
                    nesting += prev_line.count('{') - prev_line.count('}')

            if nesting > self.max_nesting_depth:
                # Only report once per deeply nested block
                if i == 0 or self._get_nesting(lines[i-1], language) <= self.max_nesting_depth:
                    issues.append(QualityIssue(
                        severity="warning",
                        category="complexity",
                        message=f"Code is nested {nesting} levels deep at line {i+1}",
                        line=i + 1,
                        suggestion="Extract nested logic into separate functions",
                    ))

        return issues

    def _get_nesting(self, line: str, language: str) -> int:
        """Get nesting level of a line."""
        stripped = line.lstrip()
        if not stripped:
            return 0

        if language == "python":
            indent = len(line) - len(stripped)
            return indent // 4
        return 0

    def _check_line_length(self, code: str) -> list[QualityIssue]:
        """Check for lines that are too long."""
        issues = []

        for i, line in enumerate(code.split('\n')):
            if len(line) > self.max_line_length:
                # Only report egregious violations
                if len(line) > self.max_line_length * 1.5:
                    issues.append(QualityIssue(
                        severity="info",
                        category="structure",
                        message=f"Line {i+1} is {len(line)} characters",
                        line=i + 1,
                        suggestion="Break into multiple lines",
                    ))

        return issues

    def _check_complexity_indicators(
        self,
        code: str,
        language: str,
    ) -> list[QualityIssue]:
        """Check for signs of overly complex code."""
        issues = []

        # Count conditionals in a function
        if_count = len(re.findall(r'\bif\b', code))
        elif_count = len(re.findall(r'\belif\b|\belse if\b', code))

        # Rough cyclomatic complexity indicator
        complexity = if_count + elif_count

        if complexity > 10:
            issues.append(QualityIssue(
                severity="warning",
                category="complexity",
                message=f"High cyclomatic complexity ({complexity} branches)",
                suggestion="Consider breaking into smaller functions or using early returns",
            ))

        # Check for god functions (doing too many things)
        # Indicators: many different operations, lots of comments explaining sections
        section_comments = len(re.findall(r'#\s*-+|#\s*\w+:', code))
        if section_comments > 3:
            issues.append(QualityIssue(
                severity="info",
                category="structure",
                message="Multiple section comments suggest this function does many things",
                suggestion="Each section could be its own function",
            ))

        return issues

    def quick_check_name(self, name: str) -> Optional[str]:
        """
        Quick check if a name is problematic.

        Returns warning message if name is bad, None if OK.
        """
        name_lower = name.lower()

        if name_lower in VAGUE_NAMES:
            return f"'{name}' is too vague - what specifically does it do/contain?"

        for prefix in VAGUE_PREFIXES:
            if name_lower.startswith(prefix):
                return f"'{name}' has vague prefix - be more specific"

        if len(name) <= 2 and name_lower not in ('id', 'ok', 'db', 'io'):
            return f"'{name}' is too short - use a descriptive name"

        return None
