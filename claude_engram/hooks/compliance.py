"""
The compliance trail: rules with detectors, matched against tool calls.

Rules are natural language and stay that way. A rule MAY carry a detector,
hand-written, never inferred:

    {"tools": ["Bash", "PowerShell"],      # tool names; empty = any tool
     "command": "<regex>",                 # against tool_input.command
     "paths": ["design/**", "*.pem"],      # globs against tool_input.file_path
     "input": "<regex>",                   # against the JSON of tool_input
     "note": "what it catches"}            # for the report

A rule with a detector gets every match recorded: the call, an excerpt of
its input, the turn, the permission mode at the time, and a verdict that
is only what the hooks can actually see:

    unattended -- bypassPermissions / dontAsk / auto: nobody at the prompt
                  approved this call. For an ask-first rule that is the
                  violation; for a never-do rule it is the violation.
    prompted   -- default / acceptEdits: Claude Code's own permission
                  prompt stood between the model and the call, so a person
                  saw it. Recorded, not judged.
    plan       -- plan mode; nothing runs.

A rule WITHOUT a detector is advisory, and the report says so per rule.
Detector health is reported too: a regex that fails to compile is
"broken", visible, and never silently ignored. No LLM in this path.

Where it runs: PreToolUse on Bash / PowerShell (`pre_bash_json`) matches,
records, and injects the rule text before the command runs -- in an
interactive session that is the reminder at the moment it matters; in an
unattended run it is the record. PostToolBatch records matches on every
other tool (path globs on edits, MCP tools by name). Matches are keyed by
tool_use_id so the two never double-count.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import time
from typing import Any, Optional

MATCHES_KEEP = 200
EXCERPT = 200

_UNATTENDED = frozenset({"bypasspermissions", "dontask", "auto"})
_SHELL_TOOLS = frozenset({"Bash", "PowerShell"})


# ---------------------------------------------------------------------------
# Detector shape
# ---------------------------------------------------------------------------


def normalize_detector(d: Any) -> Optional[dict]:
    """Validate and normalize a detector dict; None when it has no teeth."""
    if not isinstance(d, dict):
        return None
    out: dict = {}
    tools = d.get("tools")
    if isinstance(tools, str):
        tools = [tools]
    if isinstance(tools, list):
        out["tools"] = [str(t) for t in tools if str(t).strip()]
    for key in ("command", "input"):
        v = d.get(key)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()
    paths = d.get("paths")
    if isinstance(paths, str):
        paths = [paths]
    if isinstance(paths, list):
        out["paths"] = [str(p) for p in paths if str(p).strip()]
    note = d.get("note")
    if isinstance(note, str) and note.strip():
        out["note"] = note.strip()[:200]
    # What to do with a match when nobody is at the prompt (autonomy mode):
    # "record" (default) or "deny" -- an ask-first rule cannot be asked, so
    # the call is refused and the model must stop and say what it needs.
    un = str(d.get("unattended") or "").strip().lower()
    if un in ("deny", "record"):
        out["unattended"] = un
    if not any(k in out for k in ("command", "input", "paths")) and not out.get("tools"):
        return None
    return out


def compile_detector(d: Optional[dict]) -> tuple[Optional[dict], str]:
    """(compiled, error). A compiled detector carries regex objects."""
    d = normalize_detector(d)
    if not d:
        return None, "empty"
    c: dict = {
        "tools": set(d.get("tools") or []),
        "paths": list(d.get("paths") or []),
        "note": d.get("note", ""),
        "unattended": d.get("unattended", "record"),
    }
    for key in ("command", "input"):
        if key in d:
            try:
                c[key] = re.compile(d[key], re.IGNORECASE | re.MULTILINE)
            except re.error as e:
                return None, f"{key} regex: {e}"
    return c, ""


def _path_hits(paths: list[str], p: str) -> bool:
    if not p:
        return False
    norm = p.replace("\\", "/")
    base = norm.rsplit("/", 1)[-1]
    for g in paths:
        g2 = g.replace("\\", "/")
        if fnmatch.fnmatch(norm, g2) or fnmatch.fnmatch(base, g2):
            return True
        # "design/**" should also match "E:/ws/proj/design/x.md"
        if "/" in g2 and fnmatch.fnmatch(norm, "*/" + g2):
            return True
    return False


def call_matches(c: dict, tool_name: str, tool_input: Any) -> Optional[str]:
    """Does one compiled detector match this call? Returns what matched."""
    ti = tool_input if isinstance(tool_input, dict) else {}
    tools = c.get("tools") or set()
    if tools and tool_name not in tools:
        return None
    rx = c.get("command")
    if rx is not None:
        if tool_name not in _SHELL_TOOLS:
            return None
        m = rx.search(str(ti.get("command") or ""))
        return f"command ~ {m.group(0)[:60]!r}" if m else None
    paths = c.get("paths") or []
    if paths:
        for key in ("file_path", "path", "notebook_path"):
            if _path_hits(paths, str(ti.get(key) or "")):
                return f"path {str(ti.get(key))[-60:]!r}"
        return None
    rx = c.get("input")
    if rx is not None:
        try:
            blob = json.dumps(ti, ensure_ascii=False)
        except Exception:
            blob = str(ti)
        m = rx.search(blob)
        return f"input ~ {m.group(0)[:60]!r}" if m else None
    # tools-only detector: the tool name is the match
    return f"tool {tool_name}"


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def rules_with_detectors(project_memory: dict) -> list[dict]:
    """Every active rule in scope (this project plus inherited), with its
    detector compiled where it has one. Shape:
    {id, content, detector, compiled, error}."""
    out: list[dict] = []
    seen: set[str] = set()
    for e in project_memory.get("entries", []) or []:
        if not isinstance(e, dict) or e.get("category") != "rule" or e.get("archived_at"):
            continue
        rid = str(e.get("id") or "")
        if rid in seen:
            continue
        seen.add(rid)
        det = e.get("detector")
        compiled, err = (None, "")
        if det:
            compiled, err = compile_detector(det)
        out.append(
            {
                "id": rid,
                "content": str(e.get("content") or ""),
                "detector": normalize_detector(det),
                "compiled": compiled,
                "error": err if det else "",
            }
        )
    return out


def match_call(rules: list[dict], tool_name: str, tool_input: Any) -> list[dict]:
    hits: list[dict] = []
    for r in rules:
        c = r.get("compiled")
        if not c:
            continue
        what = call_matches(c, tool_name, tool_input)
        if what:
            hits.append(
                {
                    "rule_id": r["id"],
                    "rule": r["content"],
                    "what": what,
                    "note": c.get("note", ""),
                    "unattended": c.get("unattended", "record"),
                }
            )
    return hits


def should_deny(hits: list[dict], permission_mode: str, state: Optional[dict] = None) -> list[dict]:
    """The hits that refuse the call: detectors marked ``unattended: deny``,
    in autonomy mode only. A person's own bypass-mode session is attended --
    they are at the terminal and see the rule injected -- so the permission
    mode alone never denies; only the launcher's flag does."""
    try:
        from claude_engram.hooks.stall import autonomy_on
    except Exception:  # pragma: no cover
        return []
    if not autonomy_on(state):
        return []
    return [h for h in hits if h.get("unattended") == "deny"]


def deny_text(denied: list[dict]) -> str:
    """The reason the model sees for a refused call."""
    if not denied:
        return ""
    h = denied[0]
    more = f" (+{len(denied) - 1} more rule{'s' if len(denied) > 2 else ''})" if len(denied) > 1 else ""
    return (
        f"engram: refused by rule [{h['rule_id']}] {h['rule'][:200]} -- {h['what']}{more}. "
        "This run is unattended: nobody can approve an ask-first action, so it is not taken. "
        "Do not work around it. Bank a context(checkpoint_save) that says what you need "
        "approved and why, send a PushNotification, and continue with work the rules allow "
        "or stop."
    )


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


def verdict(permission_mode: str) -> str:
    m = (permission_mode or "").strip().lower()
    if m == "plan":
        return "plan"
    if m in _UNATTENDED:
        return "unattended"
    return "prompted"


def compliance_state(state: dict) -> dict:
    st = state.get("compliance")
    if not isinstance(st, dict):
        st = {}
        state["compliance"] = st
    st.setdefault("matches", [])
    st.setdefault("seen_ids", [])
    st.setdefault("health", {})
    return st


def _excerpt(tool_input: Any) -> str:
    ti = tool_input if isinstance(tool_input, dict) else {}
    for key in ("command", "file_path", "path", "notebook_path", "prompt", "description"):
        v = ti.get(key)
        if v:
            return " ".join(str(v).split())[:EXCERPT]
    try:
        return json.dumps(ti, ensure_ascii=False)[:EXCERPT]
    except Exception:
        return str(ti)[:EXCERPT]


def record(
    state: dict,
    rules: list[dict],
    hits: list[dict],
    tool_name: str,
    tool_input: Any,
    tool_use_id: str = "",
    turn: int = 0,
    permission_mode: str = "",
    agent_id: str = "",
) -> list[dict]:
    """Append the matches for one call (deduped by tool_use_id) and refresh
    detector health. Returns the matches that were new."""
    st = compliance_state(state)
    for r in rules:
        if r.get("detector"):
            h = st["health"].setdefault(r["id"], {"ok": True, "error": "", "hits": 0})
            h["ok"] = not r.get("error")
            h["error"] = r.get("error", "")
    if not hits:
        return []
    key = tool_use_id or ""
    if key and key in st["seen_ids"]:
        return []
    if key:
        st["seen_ids"] = (st["seen_ids"] + [key])[-MATCHES_KEEP:]
    v = verdict(permission_mode)
    new: list[dict] = []
    for h in hits:
        rec = {
            "rule_id": h["rule_id"],
            "rule": h["rule"][:160],
            "what": h["what"],
            "tool": tool_name,
            "input": _excerpt(tool_input),
            "tool_use_id": key,
            "turn": int(turn),
            "at": time.time(),
            "mode": permission_mode or "",
            "verdict": v,
            "subagent": bool(agent_id),
            "unattended": h.get("unattended", "record"),
        }
        new.append(rec)
        hh = st["health"].setdefault(h["rule_id"], {"ok": True, "error": "", "hits": 0})
        hh["hits"] = int(hh.get("hits", 0)) + 1
    st["matches"] = (st["matches"] + new)[-MATCHES_KEEP:]
    return new


def rule_text(hits: list[dict], permission_mode: str) -> str:
    """Injected before the command runs."""
    if not hits:
        return ""
    v = verdict(permission_mode)
    lines = ["<engram-rule>This call matches a rule with a detector:"]
    for h in hits[:3]:
        note = f" ({h['note']})" if h.get("note") else ""
        lines.append(f"  [{h['rule_id']}] {h['rule'][:200]}{note} -- {h['what']}")
    if v == "unattended":
        lines.append(
            "  Permission mode is unattended: no person approves this call. If the rule "
            "says ask first, this is the moment to stop and ask; the match is recorded "
            "in the run report either way."
        )
    else:
        lines.append("  Recorded for the run report. A permission prompt stands between you and the call.")
    lines.append("</engram-rule>")
    return "\n".join(lines)


def summary(state: dict, project_memory: Optional[dict] = None) -> dict:
    """For the run report: per-rule coverage and every match."""
    st = compliance_state(state)
    rules = rules_with_detectors(project_memory or {}) if project_memory is not None else []
    per_rule = []
    for r in rules:
        h = st["health"].get(r["id"], {})
        per_rule.append(
            {
                "id": r["id"],
                "rule": r["content"][:160],
                "detector": bool(r.get("detector")),
                "ok": (not r.get("error")) if r.get("detector") else None,
                "error": r.get("error", ""),
                "note": (r.get("detector") or {}).get("note", ""),
                "hits": int(h.get("hits", 0)),
            }
        )
    matches = list(st.get("matches") or [])
    return {
        "rules": per_rule,
        "with_detector": sum(1 for r in per_rule if r["detector"]),
        "advisory": sum(1 for r in per_rule if not r["detector"]),
        "broken": sum(1 for r in per_rule if r["detector"] and r["ok"] is False),
        "matches": matches,
        "unattended": sum(1 for m in matches if m.get("verdict") == "unattended"),
        "prompted": sum(1 for m in matches if m.get("verdict") == "prompted"),
    }


def enabled(project_dir: str) -> bool:
    raw = os.environ.get("CLAUDE_ENGRAM_COMPLIANCE", "").strip().lower()
    if raw in ("0", "off", "false", "no"):
        return False
    if raw in ("1", "on", "true", "yes"):
        return True
    try:
        from claude_engram import project_config as _pc

        return bool(_pc.enabled(_pc.load(project_dir), "compliance"))
    except Exception:
        return True
