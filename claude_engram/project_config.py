"""Per-project engram configuration: ``<project>/.engram/config.json``.

One file, a handful of booleans, so the defaults engram ships (rotation, the
default rule pack, the project structure) are each one line to turn off.
Environment variables override the file for scripted runs.

    {"rotation": "auto", "default_rules": false, "structure": true,
     "rotation_log_days": 30, "rotation_learn_days": 90,
     "rotation_learn_max_lines": 500}

``rotation`` accepts ``true`` (plan at SessionEnd, announce at SessionStart,
apply on request), ``"auto"`` (apply at SessionEnd), or ``false``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONFIG_DIR = ".engram"
CONFIG_FILE = "config.json"

DEFAULTS: dict[str, Any] = {
    "rotation": True,
    "default_rules": True,
    "workflow_rules": True,
    "code_rules": True,
    "structure": True,
    "compliance": True,  # rules with detectors matched against tool calls
    "alert_command": "",  # shell command for out-of-session alerts; {message} is replaced
    "goal_turn_cap": 150,  # turns under a /goal before engram halts the run (a person then /goal clears)
    "rotation_log_days": 30,
    "rotation_learn_days": 90,  # ERRORS.md: dated fixes age out
    "rotation_learnings_days": 0,  # LEARNINGS.md: patterns don't; 0 = cap only
    "rotation_learn_max_lines": 500,
}

_ENV = {
    "rotation": "CLAUDE_ENGRAM_ROTATION",
    "default_rules": "CLAUDE_ENGRAM_DEFAULT_RULES",
    "workflow_rules": "CLAUDE_ENGRAM_WORKFLOW_RULES",
    "code_rules": "CLAUDE_ENGRAM_CODE_RULES",
    "structure": "CLAUDE_ENGRAM_STRUCTURE",
    "compliance": "CLAUDE_ENGRAM_COMPLIANCE",
}


def config_path(project_dir: str) -> Path:
    return Path(project_dir) / CONFIG_DIR / CONFIG_FILE


def _coerce(key: str, raw: str) -> Any:
    s = raw.strip().lower()
    if key == "rotation" and s == "auto":
        return "auto"
    if s in ("0", "false", "no", "off"):
        return False
    if s in ("1", "true", "yes", "on"):
        return True
    return DEFAULTS[key]


def load(project_dir: str) -> dict:
    """Defaults, then the file, then the environment. Never raises."""
    cfg = dict(DEFAULTS)
    try:
        p = config_path(project_dir)
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k in DEFAULTS:
                    if k in data:
                        cfg[k] = data[k]
    except Exception:
        pass
    for key, var in _ENV.items():
        raw = os.environ.get(var, "")
        if raw:
            cfg[key] = _coerce(key, raw)
    # Normalise the rotation mode.
    r = cfg.get("rotation")
    if isinstance(r, str):
        cfg["rotation"] = "auto" if r.strip().lower() == "auto" else bool(r.strip().lower() in ("true", "1", "on", "yes"))
    for k in ("rotation_log_days", "rotation_learn_days", "rotation_learnings_days", "rotation_learn_max_lines", "goal_turn_cap"):
        try:
            cfg[k] = max(0 if k == "rotation_learnings_days" else 1, int(cfg[k]))
        except Exception:
            cfg[k] = DEFAULTS[k]
    return cfg


def enabled(cfg: dict, key: str) -> bool:
    v = cfg.get(key)
    return bool(v) if not isinstance(v, str) else v.lower() not in ("false", "0", "off", "no")
