"""
Context Guard - Prevents context loss and ensures task continuity

The problems:
1. Context compaction loses important task state
2. Sessions end abruptly, losing what was in progress
3. Instructions in CLAUDE.md get ignored as context grows
4. Claude claims 100% completion when work is incomplete

The solutions:
1. context_checkpoint - Save task state that survives compaction
2. task_handoff - Structured session handoff
3. instruction_reinforce - Re-inject critical instructions
4. self_check - Verify claimed work was actually done
"""

import json
import time
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path
from ..schema import MiniClaudeResponse, WorkLog


@dataclass
class TaskCheckpoint:
    """A saved checkpoint of task state."""
    task_id: str
    task_description: str
    current_step: str
    completed_steps: list[str]
    pending_steps: list[str]
    files_involved: list[str]
    key_decisions: list[str]
    blockers: list[str]
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)
    # Optional handoff fields (merged from create_handoff)
    handoff_summary: str = ""
    handoff_context_needed: list[str] = field(default_factory=list)
    handoff_warnings: list[str] = field(default_factory=list)


@dataclass
class CriticalInstruction:
    """An instruction that must not be forgotten."""
    instruction: str
    reason: str
    last_reinforced: float = field(default_factory=time.time)
    reinforce_count: int = 0
    importance: int = 10  # 1-10


class ContextGuard:
    """
    Guards against context loss and ensures task continuity.

    Key features:
    1. Checkpoint saving - preserves task state for recovery
    2. Instruction reinforcement - keeps critical rules active
    3. Self-verification - checks if claimed work was done
    4. Task handoff - structured session transitions
    """

    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = storage_dir or Path.home() / ".mini_claude" / "checkpoints"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self._current_checkpoint: Optional[TaskCheckpoint] = None
        self._critical_instructions: list[CriticalInstruction] = []
        self._claimed_completions: list[dict] = []  # Track what Claude claims to have done
        self._actual_verifications: list[dict] = []  # Track what was verified

    def save_checkpoint(
        self,
        task_description: str,
        current_step: str,
        completed_steps: list[str],
        pending_steps: list[str],
        files_involved: list[str],
        key_decisions: Optional[list[str]] = None,
        blockers: Optional[list[str]] = None,
        project_path: Optional[str] = None,
        # Optional handoff fields (merged from create_handoff)
        handoff_summary: Optional[str] = None,
        handoff_context_needed: Optional[list[str]] = None,
        handoff_warnings: Optional[list[str]] = None,
    ) -> MiniClaudeResponse:
        """
        Save a checkpoint of current task state.

        Call this:
        - Before a long operation that might fail
        - When context is getting long (approaching compaction)
        - At natural breakpoints in multi-step tasks
        - Before ending a session

        Optionally include handoff info (summary, context_needed, warnings)
        for the next session - this merges checkpoint + handoff into one call.
        """
        work_log = WorkLog()
        work_log.what_i_tried.append("saving task checkpoint")

        task_id = f"task_{int(time.time())}"

        checkpoint = TaskCheckpoint(
            task_id=task_id,
            task_description=task_description,
            current_step=current_step,
            completed_steps=completed_steps,
            pending_steps=pending_steps,
            files_involved=files_involved,
            key_decisions=key_decisions or [],
            blockers=blockers or [],
            metadata={"project_path": project_path} if project_path else {},
            handoff_summary=handoff_summary or "",
            handoff_context_needed=handoff_context_needed or [],
            handoff_warnings=handoff_warnings or [],
        )

        self._current_checkpoint = checkpoint

        # Persist to disk
        checkpoint_file = self.storage_dir / f"{task_id}.json"
        checkpoint_data = {
            "task_id": checkpoint.task_id,
            "task_description": checkpoint.task_description,
            "current_step": checkpoint.current_step,
            "completed_steps": checkpoint.completed_steps,
            "pending_steps": checkpoint.pending_steps,
            "files_involved": checkpoint.files_involved,
            "key_decisions": checkpoint.key_decisions,
            "blockers": checkpoint.blockers,
            "timestamp": checkpoint.timestamp,
            "metadata": checkpoint.metadata,
            # Include handoff fields
            "handoff_summary": checkpoint.handoff_summary,
            "handoff_context_needed": checkpoint.handoff_context_needed,
            "handoff_warnings": checkpoint.handoff_warnings,
        }

        with open(checkpoint_file, "w") as f:
            json.dump(checkpoint_data, f, indent=2)

        # Also save as "latest" for easy recovery
        latest_file = self.storage_dir / "latest_checkpoint.json"
        with open(latest_file, "w") as f:
            json.dump(checkpoint_data, f, indent=2)

        work_log.what_worked.append(f"checkpoint saved: {task_id}")

        progress_pct = len(completed_steps) / (len(completed_steps) + len(pending_steps)) * 100 if (completed_steps or pending_steps) else 0

        has_handoff = bool(handoff_summary or handoff_context_needed or handoff_warnings)
        reasoning = f"Checkpoint saved. Task is {progress_pct:.0f}% complete. {len(pending_steps)} steps remaining."
        if has_handoff:
            reasoning += " Includes handoff info for next session."

        suggestions = ["Call restore_checkpoint at session start to continue"]
        if not has_handoff:
            suggestions.append("Add handoff_summary for clearer session transitions")

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning=reasoning,
            work_log=work_log,
            data={
                "task_id": task_id,
                "checkpoint_file": str(checkpoint_file),
                "progress_percent": round(progress_pct, 1),
                "completed": len(completed_steps),
                "pending": len(pending_steps),
                "has_handoff": has_handoff,
            },
            suggestions=suggestions,
        )

    def restore_checkpoint(
        self,
        task_id: Optional[str] = None,
    ) -> MiniClaudeResponse:
        """
        Restore task state from a checkpoint.

        Call this at the start of a session to continue previous work.
        If no task_id provided, restores the latest checkpoint.
        """
        work_log = WorkLog()
        work_log.what_i_tried.append("restoring checkpoint")

        if task_id:
            checkpoint_file = self.storage_dir / f"{task_id}.json"
        else:
            checkpoint_file = self.storage_dir / "latest_checkpoint.json"

        if not checkpoint_file.exists():
            return MiniClaudeResponse(
                status="not_found",
                confidence="high",
                reasoning="No checkpoint found to restore",
                work_log=work_log,
                suggestions=["Start fresh with save_checkpoint when you begin a task"],
            )

        with open(checkpoint_file) as f:
            data = json.load(f)

        # Calculate how old the checkpoint is
        age_hours = (time.time() - data.get("timestamp", 0)) / 3600

        work_log.what_worked.append(f"checkpoint restored from {age_hours:.1f} hours ago")

        warnings = []
        if age_hours > 24:
            warnings.append(f"⚠️ Checkpoint is {age_hours:.0f} hours old - verify it's still relevant")

        # Build a summary for easy re-orientation
        summary_lines = [
            f"**Task:** {data['task_description']}",
            f"**Current step:** {data['current_step']}",
            f"**Progress:** {len(data['completed_steps'])}/{len(data['completed_steps']) + len(data['pending_steps'])} steps",
        ]

        if data.get("blockers"):
            summary_lines.append(f"**Blockers:** {', '.join(data['blockers'])}")

        if data.get("key_decisions"):
            summary_lines.append(f"**Key decisions:** {len(data['key_decisions'])} recorded")

        # Include handoff info if present
        handoff_summary = data.get("handoff_summary")
        handoff_context = data.get("handoff_context_needed", [])
        handoff_warnings = data.get("handoff_warnings", [])

        if handoff_summary:
            summary_lines.extend([
                "",
                "## Handoff from previous session:",
                handoff_summary,
            ])

        if handoff_context:
            summary_lines.append(f"**Context needed:** {', '.join(handoff_context[:3])}")

        # Add handoff warnings to main warnings
        warnings.extend(handoff_warnings)

        suggestions = [
            f"Continue with: {data['current_step']}",
            f"Remaining steps: {', '.join(data['pending_steps'][:3])}{'...' if len(data['pending_steps']) > 3 else ''}",
        ]

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning="\n".join(summary_lines),
            work_log=work_log,
            data=data,
            warnings=warnings,
            suggestions=suggestions,
        )

    def add_critical_instruction(
        self,
        instruction: str,
        reason: str,
        importance: int = 10,
    ) -> MiniClaudeResponse:
        """
        Register an instruction that must not be forgotten.

        These get re-injected into context periodically to combat
        the tendency to ignore CLAUDE.md instructions as context grows.
        """
        work_log = WorkLog()
        work_log.what_i_tried.append("registering critical instruction")

        ci = CriticalInstruction(
            instruction=instruction,
            reason=reason,
            importance=max(1, min(10, importance)),
        )

        self._critical_instructions.append(ci)

        # Persist to disk
        instructions_file = self.storage_dir / "critical_instructions.json"
        existing = []
        if instructions_file.exists():
            with open(instructions_file) as f:
                existing = json.load(f)

        existing.append({
            "instruction": instruction,
            "reason": reason,
            "importance": importance,
            "added": time.time(),
        })

        with open(instructions_file, "w") as f:
            json.dump(existing, f, indent=2)

        work_log.what_worked.append("instruction registered")

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning=f"Critical instruction registered (importance: {importance}/10)",
            work_log=work_log,
            data={"instruction_count": len(self._critical_instructions)},
        )

    def get_reinforcement(self) -> MiniClaudeResponse:
        """
        Get critical instructions that need reinforcement.

        Call this periodically (every few messages) to re-inject
        important instructions that might have faded from attention.
        """
        work_log = WorkLog()
        work_log.what_i_tried.append("getting instruction reinforcement")

        # Load from disk
        instructions_file = self.storage_dir / "critical_instructions.json"
        if not instructions_file.exists():
            return MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning="No critical instructions registered",
                work_log=work_log,
                suggestions=["Use add_critical_instruction to register important rules"],
            )

        with open(instructions_file) as f:
            instructions = json.load(f)

        if not instructions:
            return MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning="No critical instructions to reinforce",
                work_log=work_log,
            )

        # Sort by importance and build reinforcement message
        sorted_instructions = sorted(instructions, key=lambda x: x.get("importance", 5), reverse=True)

        reinforcement_lines = ["## ⚠️ CRITICAL REMINDERS (Do not ignore!)"]
        for inst in sorted_instructions[:5]:  # Top 5 most important
            reinforcement_lines.append(f"- **{inst['instruction']}** (Why: {inst['reason']})")

        work_log.what_worked.append(f"generated reinforcement for {len(sorted_instructions[:5])} instructions")

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning="\n".join(reinforcement_lines),
            work_log=work_log,
            data={
                "instruction_count": len(instructions),
                "reinforced": len(sorted_instructions[:5]),
            },
        )

    def claim_completion(
        self,
        task: str,
        evidence: Optional[list[str]] = None,
    ) -> MiniClaudeResponse:
        """
        Record a claim that a task is complete.

        This creates an audit trail for self_check to verify later.
        Forces explicit recording of what was supposedly done.
        """
        work_log = WorkLog()
        work_log.what_i_tried.append("recording completion claim")

        claim = {
            "task": task,
            "evidence": evidence or [],
            "timestamp": time.time(),
            "verified": False,
        }

        self._claimed_completions.append(claim)

        work_log.what_worked.append("claim recorded")

        warnings = []
        if not evidence:
            warnings.append("⚠️ No evidence provided - this claim may be hard to verify")

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning=f"Completion claimed for: {task}",
            work_log=work_log,
            data={"claim": claim},
            warnings=warnings,
            suggestions=[
                "Use self_check to verify this claim",
                "Provide evidence (file paths, test results) for better verification",
            ],
        )

    def self_check(
        self,
        task: str,
        verification_steps: list[str],
    ) -> MiniClaudeResponse:
        """
        Verify that claimed work was actually completed.

        This combats the tendency to claim 100% completion when
        work is actually incomplete. Forces explicit verification.

        verification_steps should include concrete checks like:
        - "File X exists and contains Y"
        - "Test Z passes"
        - "Function W is called in file V"
        """
        work_log = WorkLog()
        work_log.what_i_tried.append("self-checking completion")

        # Find the claim for this task
        claim = None
        for c in self._claimed_completions:
            if c["task"] == task:
                claim = c
                break

        if not claim:
            return MiniClaudeResponse(
                status="warning",
                confidence="medium",
                reasoning=f"No completion claim found for '{task}'. Verifying anyway.",
                work_log=work_log,
            )

        # Record verification attempt
        verification = {
            "task": task,
            "steps": verification_steps,
            "timestamp": time.time(),
        }
        self._actual_verifications.append(verification)

        # Build verification checklist
        checklist = ["## Self-Check Verification", f"**Task:** {task}", "", "**Verification steps to perform:**"]
        for i, step in enumerate(verification_steps, 1):
            checklist.append(f"- [ ] {step}")

        checklist.extend([
            "",
            "**Instructions:** Go through each step above and verify it's actually done.",
            "If any step fails, the task is NOT complete.",
        ])

        work_log.what_worked.append(f"generated {len(verification_steps)} verification steps")

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning="\n".join(checklist),
            work_log=work_log,
            data={
                "task": task,
                "verification_steps": verification_steps,
                "claim_evidence": claim.get("evidence", []) if claim else [],
            },
            warnings=["⚠️ You MUST actually verify each step - don't just mark as done!"],
        )

    def verify_completion(
        self,
        task: str,
        verification_steps: list[str],
        evidence: Optional[list[str]] = None,
    ) -> MiniClaudeResponse:
        """
        Unified completion verification: claim + verify in one step.

        This actually verifies:
        1. Checks if evidence files exist
        2. Validates each verification step where possible
        3. Returns pass/fail for each check

        Args:
            task: What task is being claimed as complete
            verification_steps: Concrete steps to verify completion
            evidence: Optional evidence (file paths, test results)
        """
        work_log = WorkLog()
        work_log.what_i_tried.append("verifying task completion")

        # Record the claim
        claim = {
            "task": task,
            "evidence": evidence or [],
            "timestamp": time.time(),
            "verified": False,
        }
        self._claimed_completions.append(claim)

        # ACTUALLY VERIFY - check evidence files exist
        evidence_results = []
        if evidence:
            for ev in evidence:
                # Check if it looks like a file path
                if "/" in ev or "\\" in ev or ev.endswith((".py", ".js", ".ts", ".md", ".json", ".yaml", ".yml")):
                    path = Path(ev)
                    if path.exists():
                        evidence_results.append({"item": ev, "status": "✅ exists", "valid": True})
                    else:
                        evidence_results.append({"item": ev, "status": "❌ NOT FOUND", "valid": False})
                else:
                    # Not a file path - just note it
                    evidence_results.append({"item": ev, "status": "📝 noted", "valid": True})

        # ACTUALLY VERIFY - check verification steps where possible
        step_results = []
        for step in verification_steps:
            result = self._verify_step(step)
            step_results.append(result)

        # Count passes/fails
        evidence_passed = sum(1 for r in evidence_results if r["valid"])
        evidence_failed = sum(1 for r in evidence_results if not r["valid"])
        steps_passed = sum(1 for r in step_results if r["valid"])
        steps_failed = sum(1 for r in step_results if not r["valid"])
        steps_manual = sum(1 for r in step_results if r["status"] == "manual")

        all_passed = evidence_failed == 0 and steps_failed == 0

        # Record verification attempt
        verification = {
            "task": task,
            "steps": verification_steps,
            "timestamp": time.time(),
            "passed": all_passed,
        }
        self._actual_verifications.append(verification)

        # Build response
        lines = [
            "## Completion Verification",
            f"**Task:** {task}",
            "",
        ]

        if evidence_results:
            lines.append("**Evidence check:**")
            for r in evidence_results:
                lines.append(f"  {r['status']} {r['item']}")
            lines.append("")

        lines.append("**Verification steps:**")
        for r in step_results:
            if r["status"] == "passed":
                lines.append(f"  ✅ {r['step']}")
            elif r["status"] == "failed":
                lines.append(f"  ❌ {r['step']} - {r.get('reason', 'failed')}")
            else:
                lines.append(f"  ⏳ {r['step']} (needs manual check)")
        lines.append("")

        # Summary
        if all_passed and steps_manual == 0:
            lines.append("**Result: ✅ ALL CHECKS PASSED**")
            claim["verified"] = True
            status = "success"
        elif all_passed and steps_manual > 0:
            lines.append(f"**Result: ⏳ {steps_manual} steps need manual verification**")
            status = "success"
        else:
            lines.append(f"**Result: ❌ VERIFICATION FAILED** ({evidence_failed + steps_failed} checks failed)")
            status = "failed"

        work_log.what_worked.append(f"verified {len(verification_steps)} steps: {steps_passed} passed, {steps_failed} failed, {steps_manual} manual")

        warnings = []
        if steps_manual > 0:
            warnings.append(f"⚠️ {steps_manual} steps require manual verification")
        if evidence_failed > 0:
            warnings.append(f"⚠️ {evidence_failed} evidence files not found!")

        return MiniClaudeResponse(
            status=status,
            confidence="high" if steps_manual == 0 else "medium",
            reasoning="\n".join(lines),
            work_log=work_log,
            data={
                "task": task,
                "verification_steps": verification_steps,
                "evidence": evidence or [],
                "evidence_results": evidence_results,
                "step_results": step_results,
                "all_passed": all_passed,
                "needs_manual": steps_manual > 0,
            },
            warnings=warnings if warnings else None,
        )

    def _verify_step(self, step: str) -> dict:
        """
        Try to automatically verify a step.
        Returns: {"step": str, "status": "passed"|"failed"|"manual", "valid": bool, "reason": str}
        """
        step_lower = step.lower()

        # Check for file existence patterns
        file_patterns = [
            "file exists", "file created", "created file", "added file",
            "exists at", "saved to", "wrote to", "created at"
        ]
        if any(p in step_lower for p in file_patterns):
            # Try to extract file path from step
            import re
            # Look for paths like /foo/bar.py or foo/bar.py or "filename.ext"
            path_match = re.search(r'["\']?([a-zA-Z0-9_/\\.-]+\.[a-zA-Z0-9]+)["\']?', step)
            if path_match:
                path = Path(path_match.group(1))
                if path.exists():
                    return {"step": step, "status": "passed", "valid": True}
                else:
                    return {"step": step, "status": "failed", "valid": False, "reason": f"file not found: {path}"}

        # Check for "no errors" patterns - can't auto-verify
        error_patterns = ["no errors", "no warnings", "compiles", "builds successfully"]
        if any(p in step_lower for p in error_patterns):
            return {"step": step, "status": "manual", "valid": True}

        # Check for test patterns - can't auto-verify without running tests
        test_patterns = ["tests pass", "test passes", "all tests", "unit tests"]
        if any(p in step_lower for p in test_patterns):
            return {"step": step, "status": "manual", "valid": True}

        # Default: needs manual verification
        return {"step": step, "status": "manual", "valid": True}

    def create_handoff(
        self,
        summary: str,
        next_steps: list[str],
        context_needed: list[str],
        warnings: Optional[list[str]] = None,
        project_path: Optional[str] = None,
    ) -> MiniClaudeResponse:
        """
        Create a structured handoff document for the next session.

        This ensures nothing is lost when:
        - Session ends
        - Context gets compacted
        - A different Claude instance takes over
        """
        work_log = WorkLog()
        work_log.what_i_tried.append("creating session handoff")

        handoff = {
            "created": time.time(),
            "summary": summary,
            "next_steps": next_steps,
            "context_needed": context_needed,
            "warnings": warnings or [],
            "project_path": project_path,
        }

        # Save to disk
        handoff_file = self.storage_dir / "latest_handoff.json"
        with open(handoff_file, "w") as f:
            json.dump(handoff, f, indent=2)

        # Also create a markdown version for easy reading
        md_lines = [
            "# Session Handoff",
            f"*Created: {time.strftime('%Y-%m-%d %H:%M')}*",
            "",
            "## Summary",
            summary,
            "",
            "## Next Steps",
        ]
        for i, step in enumerate(next_steps, 1):
            md_lines.append(f"{i}. {step}")

        if context_needed:
            md_lines.extend(["", "## Context Needed"])
            for ctx in context_needed:
                md_lines.append(f"- {ctx}")

        if warnings:
            md_lines.extend(["", "## ⚠️ Warnings"])
            for warn in warnings:
                md_lines.append(f"- {warn}")

        handoff_md = self.storage_dir / "HANDOFF.md"
        with open(handoff_md, "w") as f:
            f.write("\n".join(md_lines))

        work_log.what_worked.append("handoff document created")

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning=f"Handoff created with {len(next_steps)} next steps",
            work_log=work_log,
            data={
                "handoff_file": str(handoff_file),
                "markdown_file": str(handoff_md),
                "next_steps": next_steps,
            },
            suggestions=["Share HANDOFF.md content at the start of next session"],
        )

    def get_handoff(self) -> MiniClaudeResponse:
        """
        Retrieve the latest handoff document.

        Call this at session start to see what the previous session left.
        """
        work_log = WorkLog()
        work_log.what_i_tried.append("retrieving handoff")

        handoff_file = self.storage_dir / "latest_handoff.json"

        if not handoff_file.exists():
            return MiniClaudeResponse(
                status="not_found",
                confidence="high",
                reasoning="No handoff document found from previous session",
                work_log=work_log,
            )

        with open(handoff_file) as f:
            handoff = json.load(f)

        age_hours = (time.time() - handoff.get("created", 0)) / 3600

        work_log.what_worked.append(f"retrieved handoff from {age_hours:.1f} hours ago")

        warnings = handoff.get("warnings", [])
        if age_hours > 48:
            warnings.append(f"⚠️ Handoff is {age_hours:.0f} hours old - may be outdated")

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning=handoff.get("summary", "No summary"),
            work_log=work_log,
            data=handoff,
            warnings=warnings,
            suggestions=[f"First step: {handoff['next_steps'][0]}" if handoff.get("next_steps") else "Review context_needed items"],
        )

    def list_checkpoints(self) -> MiniClaudeResponse:
        """List all saved checkpoints."""
        work_log = WorkLog()
        work_log.what_i_tried.append("listing checkpoints")

        checkpoints = []
        for f in self.storage_dir.glob("task_*.json"):
            try:
                with open(f) as file:
                    data = json.load(file)
                    checkpoints.append({
                        "task_id": data.get("task_id"),
                        "description": data.get("task_description", "")[:50],
                        "progress": f"{len(data.get('completed_steps', []))}/{len(data.get('completed_steps', [])) + len(data.get('pending_steps', []))}",
                        "age_hours": round((time.time() - data.get("timestamp", 0)) / 3600, 1),
                    })
            except (json.JSONDecodeError, KeyError):
                continue

        # Sort by age
        checkpoints.sort(key=lambda x: x["age_hours"])

        work_log.what_worked.append(f"found {len(checkpoints)} checkpoints")

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning=f"Found {len(checkpoints)} saved checkpoints",
            work_log=work_log,
            data={"checkpoints": checkpoints},
        )
