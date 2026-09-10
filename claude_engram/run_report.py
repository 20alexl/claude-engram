"""Run report: one auditable artifact per session, from data engram already has.

Written to ``<project>/.engram/runs/<date>-<session8>.md`` and ``.json`` at
SessionEnd (and on demand via ``session_mine(run_report)`` or
``python -m claude_engram.run_report``). Every number here is captured by a
hook or read from the transcript -- nothing is self-reported by the model.

Sources, all verified against real data on this machine:

  * per-session hook state (``sessions/<id>.json``): files edited with
    per-file edit counts, test runs and results, prompts, tool usage, the
    context-pressure block (compaction cycles, restored checkpoints, stops),
    the run block written at SessionStart (start commit, permission mode,
    transcript path).
  * the transcript (``*.jsonl``): model, branch, first/last timestamps,
    ``/goal`` command text, tool errors, and every compaction with its
    ``compactMetadata`` (trigger, preTokens, postTokens, dropped, duration).
  * the checkpoint ring: this session's deliberate and automatic entries.
  * the statusline mirror: final token count and cost.
  * git: end commit.
  * ``patterns.json``: which of this run's errors were already known.

What is NOT measured yet is listed in the report rather than omitted: stall
strikes (Phase 4) and rules compliance (Phase 5). Goal evaluator verdicts are
not parsed: no local transcript has ever carried a ``/goal`` run, so their
shape is unverified, and this module does not guess.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA = 1
RUNS_DIR = Path(".engram") / "runs"
_GOAL_CMD = re.compile(r"<command-name>/goal</command-name>.*?<command-args>(.*?)</command-args>", re.S)
_ERR_PREFIX = re.compile(r"^\s*(?:Error|Traceback|Exception|FAILED|fatal|error):?", re.I)


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def _dict(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


def _list(v: Any) -> list:
    return v if isinstance(v, list) else []


def _git(project_dir: str, *args: str) -> str:
    try:
        r = subprocess.run(
            ["git", "--no-optional-locks", "-C", project_dir, *args],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _iso(ts: float) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> float:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _first_line(text: str, n: int = 160) -> str:
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return line[:n]


def _norm_err(text: str) -> str:
    """Signature for recurrence counting: first line, numbers and hex ids
    blanked, lowercased."""
    s = _first_line(text, 200).lower()
    s = re.sub(r"0x[0-9a-f]+|\b[0-9a-f]{7,}\b|\d+", "#", s)
    return s.strip()


def find_transcript(session_id: str, project_dir: str, hint: str = "") -> Optional[Path]:
    """The session's transcript. The hook-recorded path wins; else the file
    named by the session id anywhere under Claude's projects dir (a session
    started from a workspace root lives under THAT dir, not the sub-project's,
    so a project-scoped lookup misses it); else the project's live transcript."""
    if hint:
        p = Path(hint)
        if p.is_file():
            return p
    if session_id:
        try:
            from claude_engram.mining.jsonl_reader import _get_claude_projects_dir

            root = _get_claude_projects_dir()
            hits = sorted(root.glob(f"*/{session_id}.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
            if hits:
                return hits[0]
        except Exception:
            pass
    try:
        from claude_engram.mining.jsonl_reader import get_live_transcript

        return get_live_transcript(project_dir)
    except Exception:
        return None


def _read_transcript(path: Optional[Path], session_id: str, since: float = 0.0) -> dict:
    """Model, branch, timestamps, /goal text, compactions, tool errors.

    ``since``: skip records older than this epoch. A session id that is
    resumed for months carries every compaction and error since its first
    day; the run is the life of the hook state's ``run`` block, so the
    report reads the transcript from there (2026-09-10: a report listed
    compactions from June under a run that started the day before)."""
    out: dict[str, Any] = {
        "models": [],  # in order of first appearance; a session can switch
        "branch": "",
        "first_ts": 0.0,
        "last_ts": 0.0,
        "goal_text": None,
        # Verified on real /goal runs (2.1.267): attachment.type == "goal_status".
        # The first entry is the sentinel (goal set: met=false, sentinel=true,
        # condition); each later one is an evaluator verdict (met, reason,
        # iterations, durationMs, tokens), and a goal judged impossible adds
        # "failed": true. Any other flag is carried through under "flags".
        "goal_set_at": "",
        "goal_verdicts": [],
        "compactions": [],
        "errors": [],
        "prompts": 0,
        "assistant_messages": 0,
        "edits": {},  # file path -> Edit/Write count, from the tool_use blocks
        # Scheduled work: /loop and the cron tools. Verified on a live /loop
        # session: the skill creates a cron job (CronCreate), each fire arrives
        # as a user prompt, and the job is deleted (CronDelete) when done.
        "scheduled": {"cron_created": 0, "cron_deleted": 0, "wakeups": 0},
    }
    if not path or not path.is_file():
        return out
    try:
        from claude_engram.mining.jsonl_reader import iter_messages
    except Exception:
        return out
    pending_tool_errors: dict[str, str] = {}
    try:
        for _, msg in iter_messages(path):
            if session_id and msg.get("sessionId") and msg.get("sessionId") != session_id:
                continue
            ts = _parse_iso(str(msg.get("timestamp", "")))
            if since and ts and ts < since:
                continue
            if ts:
                if not out["first_ts"]:
                    out["first_ts"] = ts
                out["last_ts"] = max(out["last_ts"], ts)
            if not out["branch"] and msg.get("gitBranch"):
                out["branch"] = str(msg.get("gitBranch"))
            mtype = msg.get("type")
            if mtype == "attachment":
                att = msg.get("attachment") or {}
                if isinstance(att, dict) and att.get("type") == "goal_status":
                    cond = str(att.get("condition") or "")
                    if att.get("sentinel"):
                        out["goal_text"] = cond or out["goal_text"]
                        out["goal_set_at"] = _iso(ts)
                    else:
                        extra = {
                            k: v
                            for k, v in att.items()
                            if k not in ("type", "condition", "met", "reason", "iterations", "durationMs", "tokens", "sentinel")
                        }
                        out["goal_verdicts"].append(
                            {
                                "at": _iso(ts),
                                "met": bool(att.get("met")),
                                "reason": str(att.get("reason") or ""),
                                "iterations": att.get("iterations"),
                                "duration_ms": att.get("durationMs"),
                                "tokens": att.get("tokens"),
                                **({"flags": extra} if extra else {}),
                            }
                        )
                        if not out["goal_text"] and cond:
                            out["goal_text"] = cond
                continue
            if mtype == "system" and msg.get("subtype") == "compact_boundary":
                meta = msg.get("compactMetadata") or {}
                out["compactions"].append(
                    {
                        "at": _iso(ts),
                        "ts": ts,
                        "trigger": str(meta.get("trigger", "")),
                        "pre_tokens": meta.get("preTokens"),
                        "post_tokens": meta.get("postTokens"),
                        "dropped_tokens": meta.get("cumulativeDroppedTokens"),
                        "duration_ms": meta.get("durationMs"),
                    }
                )
                continue
            message = msg.get("message") or {}
            if mtype == "assistant":
                out["assistant_messages"] += 1
                m = str(message.get("model") or "")
                # "<synthetic>" marks Claude Code's own injected turns, not a model.
                if m and not m.startswith("<") and m not in out["models"]:
                    out["models"].append(m)
                content = message.get("content")
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict) or block.get("type") != "tool_use":
                            continue
                        name = str(block.get("name") or "")
                        if name == "CronCreate":
                            out["scheduled"]["cron_created"] += 1
                        elif name == "CronDelete":
                            out["scheduled"]["cron_deleted"] += 1
                        elif name == "ScheduleWakeup" and not (block.get("input") or {}).get("stop"):
                            out["scheduled"]["wakeups"] += 1
                        if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
                            fp = str((block.get("input") or {}).get("file_path") or (block.get("input") or {}).get("notebook_path") or "")
                            if fp:
                                key = fp.replace("\\", "/")
                                out["edits"][key] = out["edits"].get(key, 0) + 1
                continue
            if mtype != "user":
                continue
            content = message.get("content")
            if isinstance(content, str):
                if content.startswith("<command-name>"):
                    m = _GOAL_CMD.search(content)
                    if m:
                        out["goal_text"] = m.group(1).strip() or None
                elif content.strip():
                    out["prompts"] += 1
                continue
            # tool results: error blocks, or a toolUseResult that is an error string
            tur = msg.get("toolUseResult")
            if isinstance(tur, str) and _ERR_PREFIX.match(tur):
                out["errors"].append({"at": _iso(ts), "text": _first_line(tur)})
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue
                    if not block.get("is_error"):
                        continue
                    bc = block.get("content")
                    if isinstance(bc, list):
                        bc = " ".join(
                            str(b.get("text", "")) for b in bc if isinstance(b, dict)
                        )
                    text = _first_line(str(bc or ""))
                    tid = str(block.get("tool_use_id", ""))
                    if tid in pending_tool_errors:
                        continue
                    pending_tool_errors[tid] = text
                    if not (isinstance(tur, str) and _ERR_PREFIX.match(tur)):
                        out["errors"].append({"at": _iso(ts), "text": text})
    except Exception:
        pass
    return out


def _known_error_signatures(project_dir: str) -> list[dict]:
    """Recurring errors the miner already knew before this run."""
    try:
        from claude_engram.hooks.remind import _project_hash_dir

        hd = _project_hash_dir(project_dir)
        if not hd:
            return []
        p = Path(hd) / "patterns.json"
        if not p.is_file():
            return []
        d = json.loads(p.read_text(encoding="utf-8"))
        return [e for e in d.get("recurring_errors", []) if isinstance(e, dict)]
    except Exception:
        return []


def _summarize_errors(errors: list[dict], known: list[dict]) -> dict:
    groups: dict[str, dict] = {}
    for e in errors:
        sig = _norm_err(e.get("text", ""))
        if not sig:
            continue
        g = groups.setdefault(sig, {"text": e.get("text", ""), "count": 0, "first_at": e.get("at", "")})
        g["count"] += 1
    known_types = [
        str(k.get("error_type") or k.get("message_pattern") or "").lower() for k in known
    ]
    known_types = [k for k in known_types if k]
    top = []
    for g in sorted(groups.values(), key=lambda x: -x["count"])[:10]:
        low = g["text"].lower()
        g["known_before"] = any(kt in low for kt in known_types)
        top.append(g)
    return {
        "count": len(errors),
        "distinct": len(groups),
        "recurring": sum(1 for g in groups.values() if g["count"] > 1),
        "top": top,
    }


def _session_checkpoints(project_dir: str, session_id: str) -> list[dict]:
    """This session's ring entries, deliberate and automatic, oldest first."""
    try:
        from claude_engram import handoff_store as hs
        from claude_engram.hooks.remind import _handoff_candidate_dirs
    except Exception:
        return []
    seen: set[str] = set()
    out = []
    try:
        dirs = [d for d in _handoff_candidate_dirs(project_dir) if d]
        for entry in hs.read_ordered(dirs):
            if not isinstance(entry, dict):
                continue
            if str(entry.get("session_id", "")) != session_id:
                continue
            key = f"{entry.get('task_id', '')}|{entry.get('created', 0)}"
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "kind": entry.get("kind", "auto"),
                    "created": _iso(float(entry.get("created") or entry.get("timestamp") or 0)),
                    "task_id": entry.get("task_id", ""),
                    "summary": str(entry.get("summary") or entry.get("task_description") or "")[:160],
                }
            )
    except Exception:
        return out
    out.sort(key=lambda e: e["created"])
    return out


def collect(session_id: str, project_dir: str, state: Optional[dict] = None) -> dict:
    """Assemble the report dict for one session. Never raises; missing
    sources leave empty fields and are named under ``not_measured``."""
    from claude_engram.hooks import remind
    from claude_engram.hooks import context_pressure as cp

    if state is None:
        remind._session_id = session_id
        state = remind.load_state()
    run = _dict(state.get("run"))
    ps = _dict(state.get("pressure"))
    loop = _dict(state.get("loop"))

    transcript_path = find_transcript(session_id, project_dir, str(run.get("transcript_path") or ""))

    # Clocks: the hook state is authoritative for both ends (SessionEnd stamps
    # last_session_end before writing); the transcript only fills a missing
    # start. The run block's started_at survives compaction-triggered
    # SessionStarts; last_session_start is the most recent (re)start. A live
    # (unended) session reads as "until now". The transcript is read from
    # the run's start (with a minute of slack for clock skew between the
    # hook state and the transcript's timestamps).
    started_state = float(run.get("started_at") or 0) or float(state.get("last_session_start") or 0)
    since = 0.0
    if started_state and transcript_path:
        # Only when the transcript demonstrably spans past the run's start:
        # records both before and after it. A clock mismatch between the
        # hook state and the transcript must never empty the report.
        first, last = _transcript_bounds(transcript_path)
        cut = started_state - 60.0
        if first and last and first < cut <= last:
            since = cut
    tr = _read_transcript(transcript_path, session_id, since=since)
    started = started_state or tr["first_ts"]
    ended = float(state.get("last_session_end") or 0) or time.time()
    if ended < started:
        # A stale end from before a resume of the same session id.
        ended = time.time()
    mirror = cp.read_mirror(session_id) or {}

    # Compactions: the transcript is the source of truth for sizes; the hook
    # state adds which checkpoint each one restored, joined by TIME (nearest
    # PostCompact record within five minutes), not by order -- a session may
    # carry compactions from before the hook started recording.
    restored = [r for r in _list(ps.get("compactions")) if isinstance(r, dict)]
    compactions = []
    used: set[int] = set()
    for c in tr["compactions"]:
        rec = dict(c)
        cts = float(rec.pop("ts", 0) or 0)
        best_i, best_d = -1, 300.0
        for i, r in enumerate(restored):
            if i in used:
                continue
            d = abs(float(r.get("at") or 0) - cts)
            if d < best_d:
                best_i, best_d = i, d
        if best_i >= 0:
            used.add(best_i)
            rec["restored"] = restored[best_i].get("restored")
        compactions.append(rec)
    if not tr["compactions"] and restored:
        # No transcript (or it lagged): keep what the hooks saw.
        for r in restored:
            compactions.append({"at": _iso(float(r.get("at") or 0)), "trigger": "", "restored": r.get("restored")})

    # Files touched: the transcript's Edit/Write tool_use blocks are the
    # complete record (the hook's per-file counter resets on git commit, and
    # the session's file list can be wiped by a SessionStart); the hook state
    # fills in anything the transcript lacks.
    edit_counts = _dict(loop.get("edit_counts"))
    merged: dict[str, dict] = {}

    def _add(path: str, n: int) -> None:
        p = str(path).replace("\\", "/")
        key = p.lower()
        row = merged.setdefault(key, {"path": p, "edits": 0})
        row["edits"] = max(row["edits"], int(n or 0))

    for p, n in _dict(tr["edits"]).items():
        _add(p, n)
    for f in _list(state.get("files_edited_this_session")):
        n = 0
        for k, v in edit_counts.items():
            if str(k).replace("\\", "/").lower() == str(f).replace("\\", "/").lower():
                n = int(v or 0)
        _add(str(f), n)
    file_rows = sorted(merged.values(), key=lambda r: (-r["edits"], r["path"]))

    results = [
        r
        for r in _list(loop.get("test_results"))
        if isinstance(r, dict) and float(r.get("timestamp") or 0) >= started
    ]
    tests = {
        "runs": int(state.get("test_runs_this_session") or 0),
        "first": results[0].get("passed") if results else None,
        "last": state.get("last_test_passed"),
        "failures": sum(1 for r in results if not r.get("passed")),
    }

    checkpoints = _session_checkpoints(project_dir, session_id)
    errors = _summarize_errors(tr["errors"], _known_error_signatures(project_dir))

    not_measured: list[str] = []
    try:
        from claude_engram.hooks import stall as _stall

        stalls = _stall.summary(state)
    except Exception:
        stalls = None
        not_measured.append("stall strikes (state unreadable)")
    try:
        from claude_engram.hooks import compliance as _cpl
        from claude_engram.hooks.storage import load_project_memory as _lpm

        compliance = _cpl.summary(state, _lpm(project_dir))
        if compliance["advisory"]:
            not_measured.append(
                f"{compliance['advisory']} rule(s) without a detector: advisory only, never matched"
            )
    except Exception:
        compliance = None
        not_measured.append("rules compliance (state or rules unreadable)")
    verdicts = tr["goal_verdicts"]
    goal_outcome = ""
    if tr["goal_text"] is not None:
        # Verified shapes: met -> {"met": true, ...}; judged impossible ->
        # {"met": false, "failed": true, ...} (the docs' "failed entry").
        if any(v.get("met") for v in verdicts):
            goal_outcome = "met"
        elif any((v.get("flags") or {}).get("failed") for v in verdicts):
            goal_outcome = "failed"
        elif verdicts:
            goal_outcome = "unresolved"
        else:
            goal_outcome = "set, no verdict recorded"
    if not transcript_path:
        not_measured.append("transcript (not found): model, compaction sizes, errors")
    # The transcript's gitBranch is the cwd's (a session started from a
    # workspace root reports the root's branch); the project's own branch
    # wins when git can answer.
    branch = _git(project_dir, "rev-parse", "--abbrev-ref", "HEAD") or tr["branch"]
    models = tr["models"] or [str(mirror.get("model_id") or mirror.get("model_name") or "")]
    models = [m for m in models if m]
    # Turns are Stop events. Before the hook counted them, prompts are the
    # honest fallback -- assistant messages are per API response, not turns.
    turns = int(ps.get("stops_total") or 0) or int(state.get("prompts_this_session") or 0) or tr["prompts"]
    if not mirror:
        not_measured.append("final token count and cost (no statusline mirror)")

    end_commit = _git(project_dir, "rev-parse", "--short", "HEAD")
    date = datetime.fromtimestamp(started or time.time()).strftime("%Y-%m-%d")
    run_id = f"{date}-{session_id[:8] or 'nosession'}"
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "session_id": session_id,
        "project": str(project_dir).replace("\\", "/"),
        "generated_at": _iso(time.time()),
        "goal_text": tr["goal_text"],
        "goal_set_at": tr["goal_set_at"],
        "goal_verdicts": verdicts,
        "goal_outcome": goal_outcome,
        "model": " → ".join(models) if models else "",
        "models": models,
        "permission_mode": str(run.get("permission_mode") or ""),
        "branch": branch,
        "start_commit": str(run.get("start_commit") or ""),
        "end_commit": end_commit,
        "started_at": _iso(started),
        "ended_at": _iso(ended),
        "wall_seconds": int(max(0.0, ended - started)) if started else 0,
        "turns": turns,
        # The transcript, scoped to the run, is the truth for prompts; the
        # state's counter resets on a startup-source SessionStart (a live
        # report said "prompts 2" for a day-long run).
        "prompts": tr["prompts"] or int(state.get("prompts_this_session") or 0),
        "tokens": {
            "final_input": mirror.get("total_input_tokens"),
            "context_window": mirror.get("context_window_size"),
            "cost_usd": mirror.get("total_cost_usd"),
        },
        "compactions": compactions,
        "scheduled": tr["scheduled"],
        "files": file_rows,
        "tests": tests,
        "errors": errors,
        "checkpoints": checkpoints,
        "checkpoint_counts": {
            "deliberate": sum(1 for c in checkpoints if c["kind"] == "manual"),
            "auto": sum(1 for c in checkpoints if c["kind"] != "manual"),
        },
        "stalls": stalls,
        "compliance": compliance,
        "end_reason": str(run.get("end_reason") or ""),
        "failures": [f for f in (run.get("failures") or []) if isinstance(f, dict)],
        "alerts": [a for a in (state.get("alerts") or []) if isinstance(a, dict)],
        "autorun": _autorun_summary(state),
        "not_measured": not_measured,
        "transcript_path": str(transcript_path) if transcript_path else "",
    }


# ---------------------------------------------------------------------------
# Rendering and writing
# ---------------------------------------------------------------------------


def _hms(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else (f"{m}m{s:02d}s" if m else f"{s}s")


def _k(n) -> str:
    try:
        return f"{int(n) / 1000:.0f}K"
    except Exception:
        return "?"


def render_md(r: dict) -> str:
    lines = [f"# Run {r['run_id']}", ""]
    lines.append(f"- **Project:** {r['project']}")
    lines.append(f"- **Session:** {r['session_id']}")
    if r.get("goal_text"):
        lines.append(f"- **Goal:** {r['goal_text']} — **{r.get('goal_outcome') or '?'}**")
    lines.append(f"- **Model:** {r.get('model') or '?'} · permission mode: {r.get('permission_mode') or '?'}")
    lines.append(
        f"- **Commits:** {r.get('start_commit') or '?'} → {r.get('end_commit') or '?'}"
        f" (branch {r.get('branch') or '?'})"
    )
    lines.append(
        f"- **Wall time:** {_hms(r.get('wall_seconds', 0))} · turns {r.get('turns', 0)} · prompts {r.get('prompts', 0)}"
    )
    tok = r.get("tokens") or {}
    if tok.get("final_input"):
        cost = tok.get("cost_usd")
        lines.append(
            f"- **Context at end:** {_k(tok['final_input'])} of {_k(tok.get('context_window') or 0)}"
            + (f" · ${cost:.2f}" if isinstance(cost, (int, float)) else "")
        )
    sch = r.get("scheduled") or {}
    if any(sch.values()):
        lines.append(
            f"- **Scheduled work:** cron jobs created {sch.get('cron_created', 0)}, "
            f"deleted {sch.get('cron_deleted', 0)}, self-paced wakeups {sch.get('wakeups', 0)}"
        )
    if r.get("end_reason"):
        lines.append(f"- **Ended:** {r['end_reason']}")
    for f in (r.get("failures") or [])[-5:]:
        at = f.get("at")
        try:
            at_s = time.strftime("%H:%M", time.localtime(float(at))) if at else "?"
        except Exception:
            at_s = "?"
        extra = ""
        if f.get("error_type") == "rate_limit":
            reset = f.get("five_hour_resets_at") or f.get("seven_day_resets_at")
            pct = f.get("five_hour_pct")
            try:
                reset_s = time.strftime("%a %H:%M", time.localtime(float(reset))) if reset else ""
            except Exception:
                reset_s = ""
            if reset_s:
                extra = f"; 5-hour window at {pct}%, resets {reset_s}" if pct is not None else f"; window resets {reset_s}"
        msg = str(f.get("error") or "")[:120].replace("|", "/")
        lines.append(f"- **API failure at {at_s}:** {f.get('error_type', '?')}{extra}{' -- ' + msg if msg else ''}")
    lines.append("")

    verdicts = r.get("goal_verdicts") or []
    if r.get("goal_text"):
        lines.append(f"## Goal ({len(verdicts)} evaluator verdict{'s' if len(verdicts) != 1 else ''})")
        lines.append("")
        lines.append(f"- **Condition:** {r['goal_text']}")
        if r.get("goal_set_at"):
            lines.append(f"- **Set:** {r['goal_set_at']}")
        lines.append(f"- **Outcome:** {r.get('goal_outcome') or '?'}")
        if verdicts:
            lines.append("")
            lines.append("| At | Met | Iterations | Reason |")
            lines.append("|---|---|---|---|")
            for v in verdicts:
                flags = v.get("flags") or {}
                met = "yes" if v.get("met") else ("failed" if flags.get("failed") else "no")
                lines.append(
                    f"| {v.get('at', '')} | {met} | {v.get('iterations') if v.get('iterations') is not None else '-'} | {str(v.get('reason', '')).replace('|', '/')[:300]} |"
                )
        lines.append("")

    comps = r.get("compactions") or []
    lines.append(f"## Compactions ({len(comps)})")
    if comps:
        lines.append("")
        lines.append("| # | At | Trigger | Before → after | Restored |")
        lines.append("|---|---|---|---|---|")
        for i, c in enumerate(comps, 1):
            res = c.get("restored") or {}
            res_s = f"{res.get('kind', '')} {res.get('task_id', '')}".strip() or "-"
            size = (
                f"{_k(c['pre_tokens'])} → {_k(c['post_tokens'])}"
                if c.get("pre_tokens") is not None
                else "?"
            )
            lines.append(f"| {i} | {c.get('at', '')} | {c.get('trigger') or '?'} | {size} | {res_s} |")
    else:
        lines.append("")
        lines.append("None.")
    lines.append("")

    files = r.get("files") or []
    lines.append(f"## Files touched ({len(files)})")
    if files:
        lines.append("")
        lines.append("| Edits | File |")
        lines.append("|---|---|")
        for f in files[:40]:
            lines.append(f"| {f['edits']} | {f['path']} |")
        if len(files) > 40:
            lines.append(f"| … | {len(files) - 40} more |")
    else:
        lines.append("")
        lines.append("None.")
    lines.append("")

    t = r.get("tests") or {}
    fmt = lambda v: "pass" if v is True else ("fail" if v is False else "none")  # noqa: E731
    lines.append("## Tests")
    lines.append("")
    lines.append(
        f"- runs {t.get('runs', 0)} · first {fmt(t.get('first'))} · last {fmt(t.get('last'))} · failing runs {t.get('failures', 0)}"
    )
    lines.append("")

    e = r.get("errors") or {}
    lines.append(f"## Errors ({e.get('count', 0)}; {e.get('distinct', 0)} distinct, {e.get('recurring', 0)} recurring)")
    if e.get("top"):
        lines.append("")
        lines.append("| n | Known before | Error |")
        lines.append("|---|---|---|")
        for g in e["top"]:
            lines.append(
                f"| {g['count']} | {'yes' if g.get('known_before') else 'no'} | {g['text'].replace('|', '/')} |"
            )
    lines.append("")

    cps = r.get("checkpoints") or []
    cc = r.get("checkpoint_counts") or {}
    lines.append(f"## Checkpoints ({cc.get('deliberate', 0)} deliberate, {cc.get('auto', 0)} auto)")
    lines.append("")
    lines.append(
        "Deliberate checkpoints are the ring's record. Automatic per-turn saves only "
        "contend for the latest pointer, so at most the surviving one is listed."
    )
    if cps:
        lines.append("")
        lines.append("| At | Kind | Task | Summary |")
        lines.append("|---|---|---|---|")
        for c in cps:
            lines.append(
                f"| {c['created']} | {c['kind']} | {c.get('task_id') or '-'} | {c['summary'].replace('|', '/')} |"
            )
    lines.append("")

    st = r.get("stalls")
    if isinstance(st, dict):
        tn = st.get("turns") or {}
        lines.append(
            f"## Stalls ({st.get('max_strikes', 0)} strike{'s' if st.get('max_strikes', 0) != 1 else ''} at peak, "
            f"{st.get('strikes_now', 0)} at end)"
        )
        lines.append("")
        lines.append(
            "A turn is judged by effect: a file changed, a test status flipped, a commit, "
            "or delegated work. Turns with no tools or parked on a wait primitive are neutral."
        )
        lines.append("")
        lines.append(
            f"- turns: {tn.get('good', 0)} with effect · {tn.get('noeffect', 0)} without · {tn.get('neutral', 0)} neutral"
        )
        h = st.get("halted")
        if isinstance(h, dict):
            lines.append(
                f"- **HALTED** at turn {h.get('turn', '?')} (strike {h.get('strikes', '?')}, autonomy mode): "
                f"{h.get('denied', 0)} tool call(s) denied afterwards"
            )
        elif st.get("autonomy"):
            lines.append("- autonomy mode: halt armed at the strike cap, never reached")
        evs = st.get("events") or []
        if evs:
            lines.append("")
            lines.append("| Turn | Event | Strikes after | Reason |")
            lines.append("|---|---|---|---|")
            for ev in evs[-30:]:
                lines.append(
                    f"| {ev.get('turn', '?')} | {ev.get('kind', '?')} | {ev.get('strikes', '?')} | {ev.get('reason', '')} |"
                )
        lines.append("")

    cp = r.get("compliance")
    if isinstance(cp, dict):
        lines.append(
            f"## Rules compliance ({cp.get('with_detector', 0)} with a detector, "
            f"{cp.get('advisory', 0)} advisory, {cp.get('broken', 0)} broken)"
        )
        lines.append("")
        lines.append(
            "A rule with a detector has every matching tool call recorded. A rule without one "
            "is advisory: nothing here says whether it was followed. The verdict is what the hooks "
            "can see: `unattended` means no person approved the call (bypass / auto / dontAsk mode); "
            "`prompted` means Claude Code's permission prompt stood between the model and the call."
        )
        rules = cp.get("rules") or []
        if rules:
            lines.append("")
            lines.append("| Rule | Detector | Health | Matches |")
            lines.append("|---|---|---|---|")
            for ru in rules:
                det = ru.get("note") or ("yes" if ru.get("detector") else "advisory")
                if ru.get("detector"):
                    health = "ok" if ru.get("ok") else f"BROKEN: {ru.get('error', '')}"
                else:
                    health = "-"
                lines.append(
                    f"| [{ru.get('id', '')}] {str(ru.get('rule', '')).replace('|', '/')[:90]} | {det.replace('|', '/')} | {health.replace('|', '/')} | {ru.get('hits', 0)} |"
                )
        matches = cp.get("matches") or []
        lines.append("")
        lines.append(
            f"- matches: {len(matches)} · unattended {cp.get('unattended', 0)} · prompted {cp.get('prompted', 0)}"
        )
        if matches:
            lines.append("")
            lines.append("| Turn | Verdict | Rule | Tool | Input |")
            lines.append("|---|---|---|---|---|")
            for m in matches[-40:]:
                sub = " (subagent)" if m.get("subagent") else ""
                lines.append(
                    f"| {m.get('turn', '?')} | {m.get('verdict', '?')}{sub} | [{m.get('rule_id', '')}] {m.get('what', '')} | {m.get('tool', '')} | {str(m.get('input', '')).replace('|', '/')[:100]} |"
                )
        lines.append("")

    ar = r.get("autorun")
    if isinstance(ar, dict):
        lines.append(f"## Goal run ({ar.get('status', '?')})")
        lines.append("")
        lines.append("Engram's bracket around the session's /goal: the loop is Claude Code's, the record is the hooks'.")
        lines.append("")
        lines.append(f"- **Goal:** {str(ar.get('goal', '')).replace('|', '/')}")
        lines.append(
            f"- **Turns:** {ar.get('turns', 0)} of the {ar.get('max_turns', '?')} cap"
            + (f" · {ar['duration_s']} s" if ar.get("duration_s") is not None else "")
            + f" · evaluator verdicts {ar.get('verdicts', 0)}"
        )
        if ar.get("why"):
            lines.append(f"- **Ended:** {str(ar['why']).replace('|', '/')}")
        lines.append("")

    al = r.get("alerts") or []
    if al:
        lines.append(f"## Alerts ({len(al)})")
        lines.append("")
        lines.append("| At | Kind | Sent | Message |")
        lines.append("|---|---|---|---|")
        for a in al[-20:]:
            try:
                at_s = time.strftime("%H:%M", time.localtime(float(a.get("at") or 0)))
            except Exception:
                at_s = "?"
            sent = "yes" if a.get("sent") else f"no ({str(a.get('detail', ''))[:40].replace('|', '/')})"
            lines.append(f"| {at_s} | {a.get('kind', '')} | {sent} | {str(a.get('message', '')).replace('|', '/')[:120]} |")
        lines.append("")

    lines.append("## Not measured")
    lines.append("")
    for n in r.get("not_measured") or []:
        lines.append(f"- {n}")
    lines.append("")
    lines.append(f"_Generated {r['generated_at']} by claude-engram run_report schema {r['schema']}._")
    return "\n".join(lines) + "\n"


def _autorun_summary(state: dict) -> Optional[dict]:
    try:
        from claude_engram.hooks import autorun as _ar

        return _ar.summary(state)
    except Exception:
        return None


def runs_dir(project_dir: str) -> Path:
    return Path(project_dir) / RUNS_DIR


def write_report(session_id: str, project_dir: str, state: Optional[dict] = None) -> Optional[Path]:
    """Collect, render and write both files. Returns the .md path, or None
    when nothing could be written."""
    try:
        r = collect(session_id, project_dir, state)
        d = runs_dir(project_dir)
        d.mkdir(parents=True, exist_ok=True)
        md = d / f"{r['run_id']}.md"
        js = d / f"{r['run_id']}.json"
        _atomic(md, render_md(r))
        _atomic(js, json.dumps(r, indent=2) + "\n")
        return md
    except Exception:
        return None


def _atomic(path: Path, text: str) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(text.encode("utf-8"))
    tmp.replace(path)


def _transcript_bounds(path: Path) -> tuple[float, float]:
    """(first, last) record timestamps, from the head and a 64 KB tail read.
    Zero when unreadable."""
    first = last = 0.0
    try:
        with open(path, "rb") as fh:
            for i, line in enumerate(fh):
                m = _TS_RE.search(line)
                if m:
                    first = _parse_iso(m.group(1).decode("ascii", "ignore"))
                    if first:
                        break
                if i >= 400:
                    break
            size = fh.seek(0, 2)
            fh.seek(max(0, size - 65536))
            for line in fh.read().splitlines()[::-1]:
                m = _TS_RE.search(line)
                if m:
                    last = _parse_iso(m.group(1).decode("ascii", "ignore"))
                    if last:
                        break
    except Exception:
        return first, last
    return first, last


_TS_RE = re.compile(rb'"timestamp":\s*"([0-9T:.+\-]+Z?)"')


def goal_seen(transcript_path: str, max_lines: int = 400) -> bool:
    """Was a /goal set in this transcript? The sentinel goal_status attachment
    is written when the goal is set, near the top, so a bounded head scan is
    enough and cheap at SessionEnd."""
    if not transcript_path:
        return False
    try:
        with open(transcript_path, "rb") as fh:
            for i, line in enumerate(fh):
                if i >= max_lines:
                    break
                if b'"goal_status"' in line:
                    return True
    except Exception:
        return False
    return False


def substantial(state: dict) -> bool:
    """Worth a report: something was edited, or a compaction happened, or a
    goal was set (a /goal run that never touched Edit -- the model wrote its
    file through Bash -- must still leave its report), or the session ran
    three or more real turns (a /loop session appends through Bash and never
    touches Edit either; three Stop events is a session that did work, not a
    one-shot question), or a handful of prompts or a test run."""
    ps = _dict(state.get("pressure"))
    run = _dict(state.get("run"))
    return bool(
        state.get("files_edited_this_session")
        or int(ps.get("cycle") or 0) > 0
        or int(ps.get("stops_total") or 0) >= 3
        or int(state.get("prompts_this_session") or 0) >= 5
        or int(state.get("test_runs_this_session") or 0) > 0
        or goal_seen(str(run.get("transcript_path") or ""))
    )


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    project = os.getcwd()
    to_stdout = False
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--session" and i + 1 < len(args):
            sid = args[i + 1]
            i += 1
        elif a == "--project" and i + 1 < len(args):
            project = args[i + 1]
            i += 1
        elif a == "--stdout":
            to_stdout = True
        i += 1
    if not sid:
        print("usage: python -m claude_engram.run_report --session <id> [--project <dir>] [--stdout]")
        return 2
    if to_stdout:
        print(render_md(collect(sid, project)), end="")
        return 0
    p = write_report(sid, project)
    print(str(p) if p else "no report written")
    return 0 if p else 1


if __name__ == "__main__":
    sys.exit(main())
