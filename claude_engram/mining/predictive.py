"""
Predictive Context — predict what context you'll need based on past patterns.

Uses edit correlations and session history to predict:
  - What files you'll also need to edit (co-edit patterns)
  - What errors you're likely to hit (per-file error history)
  - What memories are relevant before you even start
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Prediction:
    """A context prediction for a file edit."""

    prediction_type: str  # "related_file" | "likely_error" | "relevant_memory"
    content: str
    confidence: float = 0.0
    source: str = ""  # What data backed this prediction


@dataclass
class EditPrediction:
    """Predictions for an upcoming file edit."""

    target_file: str
    related_files: list[Prediction] = field(default_factory=list)
    likely_errors: list[Prediction] = field(default_factory=list)
    tips: list[str] = field(default_factory=list)


def predict_for_file(
    file_path: str,
    project_path: str,
    engram_storage_dir: str = "~/.claude_engram",
) -> EditPrediction:
    """
    Predict what context you'll need for editing a file.

    Based on:
    1. Edit correlations — what files are usually edited together
    2. Error history — what errors happened when this file was edited before
    3. Session patterns — what the workflow looked like last time
    """
    target_name = Path(file_path).name
    prediction = EditPrediction(target_file=target_name)

    storage = Path(engram_storage_dir).expanduser()
    manifest_path = storage / "manifest.json"
    if not manifest_path.exists():
        return prediction

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    norm_path = _normalize_path(project_path)
    proj_info = manifest.get("projects", {}).get(norm_path)
    if not proj_info:
        return prediction

    hash_dir = storage / "projects" / proj_info["hash"]

    # 1. Edit correlations — what files are co-edited
    _predict_related_files(prediction, target_name, hash_dir)

    # 2. Error history — what errors happen with this file
    _predict_errors(prediction, target_name, hash_dir)

    # 3. Tips from session history
    _predict_tips(prediction, target_name, hash_dir)

    return prediction


def _predict_related_files(
    prediction: EditPrediction,
    target_name: str,
    hash_dir: Path,
):
    """Predict related files from edit correlations."""
    patterns_path = hash_dir / "patterns.json"
    if not patterns_path.exists():
        return

    try:
        data = json.loads(patterns_path.read_text(encoding="utf-8"))
    except Exception:
        return

    for corr in data.get("correlations", []):
        other = None
        if corr.get("file_a") == target_name:
            other = corr.get("file_b")
        elif corr.get("file_b") == target_name:
            other = corr.get("file_a")

        if other:
            strength = corr.get("strength", 0)
            prediction.related_files.append(
                Prediction(
                    prediction_type="related_file",
                    content=other,
                    confidence=strength,
                    source=f"co-edited in {corr.get('co_occurrence', 0)} sessions",
                )
            )

    prediction.related_files.sort(key=lambda p: -p.confidence)


def _predict_errors(
    prediction: EditPrediction,
    target_name: str,
    hash_dir: Path,
):
    """Predict likely errors from extraction history."""
    ext_dir = hash_dir / "extractions"
    if not ext_dir.exists():
        return

    error_counts: dict[str, int] = {}

    for ext_file in ext_dir.glob("*.json"):
        try:
            data = json.loads(ext_file.read_text(encoding="utf-8"))
            for mistake in data.get("mistakes", []):
                files = mistake.get("related_files", [])
                file_names = [Path(f).name for f in files]
                if target_name in file_names:
                    error_type = mistake.get("error_type", "")
                    desc = mistake.get("description", "")[:100]
                    key = error_type or desc[:40]
                    error_counts[key] = error_counts.get(key, 0) + 1
        except Exception:
            continue

    for error_key, count in sorted(error_counts.items(), key=lambda x: -x[1])[:5]:
        prediction.likely_errors.append(
            Prediction(
                prediction_type="likely_error",
                content=error_key,
                confidence=min(count / 3, 1.0),  # 3+ occurrences = high confidence
                source=f"occurred {count} times with this file",
            )
        )


def _predict_tips(
    prediction: EditPrediction,
    target_name: str,
    hash_dir: Path,
):
    """Generate tips from session history."""
    # Check if this is a struggle file
    patterns_path = hash_dir / "patterns.json"
    if not patterns_path.exists():
        return

    try:
        data = json.loads(patterns_path.read_text(encoding="utf-8"))
    except Exception:
        return

    for struggle in data.get("struggles", []):
        if struggle.get("file_path") == target_name:
            sessions = struggle.get("sessions_affected", 0)
            errors = struggle.get("errors_nearby", 0)
            if errors > 0:
                prediction.tips.append(
                    f"This file has caused issues in {sessions} sessions ({errors} with errors). Check tests after editing."
                )
            break

    # Suggest related files
    if prediction.related_files:
        names = [p.content for p in prediction.related_files[:3]]
        prediction.tips.append(f"Usually edited with: {', '.join(names)}")


def format_prediction(pred: EditPrediction) -> str:
    """Format prediction for injection into context."""
    lines = []

    if pred.tips:
        for tip in pred.tips[:3]:
            lines.append(f"  Tip: {tip}")

    if pred.likely_errors:
        for err in pred.likely_errors[:2]:
            lines.append(f"  Watch for: {err.content} ({err.source})")

    return "\n".join(lines)


def _normalize_path(project_path: str) -> str:
    """Normalize project path for manifest lookup."""
    norm = str(Path(project_path).resolve()).replace("\\", "/")
    if len(norm) >= 2 and norm[1] == ":":
        norm = norm[0].lower() + norm[1:]
    return norm
