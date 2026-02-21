"""
Output Validator - Check code and outputs for signs of fake/hallucinated results.

Catches common AI slop patterns like:
- Silent failures (empty catches, pass-only handlers)
- Placeholder outputs (Lorem ipsum, TODO, etc.)
- Fake data in outputs
"""

import re
from ..schema import MiniClaudeResponse


class OutputValidator:
    """Validate code and command outputs for signs of fake or broken results."""

    def validate_code(self, code: str, context: str | None = None) -> MiniClaudeResponse:
        """Check code for silent failures and fake patterns."""
        issues = []

        # Silent failure patterns
        if re.search(r'except\s*:\s*pass', code):
            issues.append("Bare 'except: pass' - silently swallows all errors")
        if re.search(r'except\s+\w+(\s*,\s*\w+)*\s*:\s*pass', code):
            issues.append("Exception caught but silently ignored with pass")

        # Placeholder patterns
        placeholders = ['TODO', 'FIXME', 'HACK', 'XXX', 'PLACEHOLDER', 'NotImplemented']
        for p in placeholders:
            if p in code:
                issues.append(f"Found placeholder: '{p}'")

        # Fake/stub patterns
        if re.search(r'return\s+None\s*$', code, re.MULTILINE) and code.count('return None') > 2:
            issues.append("Multiple 'return None' - possible stub implementation")
        if re.search(r'print\(["\'].*(?:test|debug|hello)', code, re.I):
            issues.append("Debug/test print statement found")

        # Hardcoded secrets
        if re.search(r'(password|secret|api_key|token)\s*=\s*["\'][^"\']+["\']', code, re.I):
            issues.append("Possible hardcoded secret/credential")

        if issues:
            return MiniClaudeResponse(
                status="partial",
                confidence="medium",
                reasoning=f"Found {len(issues)} potential issue(s)",
                warnings=issues,
                suggestions=["Review flagged patterns before committing"],
            )

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning="No obvious issues detected",
        )

    def validate_output(
        self,
        output: str,
        expected_format: str | None = None,
        should_contain: list[str] | None = None,
        should_not_contain: list[str] | None = None,
    ) -> MiniClaudeResponse:
        """Check command/function output for signs of fake results."""
        issues = []

        # Check for fake/placeholder output
        fake_patterns = [
            'lorem ipsum', 'foo bar', 'example.com', 'test@test',
            'placeholder', 'sample data', 'dummy',
        ]
        output_lower = output.lower()
        for pattern in fake_patterns:
            if pattern in output_lower:
                issues.append(f"Possible fake data: '{pattern}'")

        # Check should_contain
        if should_contain:
            for expected in should_contain:
                if expected not in output:
                    issues.append(f"Missing expected content: '{expected}'")

        # Check should_not_contain
        if should_not_contain:
            for unexpected in should_not_contain:
                if unexpected in output:
                    issues.append(f"Found unexpected content: '{unexpected}'")

        # Check if output is suspiciously empty
        if len(output.strip()) == 0:
            issues.append("Output is empty")

        if issues:
            return MiniClaudeResponse(
                status="partial",
                confidence="medium",
                reasoning=f"Found {len(issues)} concern(s) with output",
                warnings=issues,
            )

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning="Output looks valid",
        )
