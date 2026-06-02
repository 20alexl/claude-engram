"""
Live-session commitment extraction.

Answers "what did I say I'd do this session, and is it done?" — the one
question session_mine's post-session index structurally cannot answer, because
indexing runs at SessionEnd while the question is almost always about the OPEN
session. This scans the live transcript directly (the newest ``*.jsonl`` for
the project).

Two channels, because a long session is full of "let me ..." narration that is
resolved seconds later and is NOT a real commitment:
  - DEFERRED: explicit future/open-loop markers (next session, remaining, TODO,
    still need to, follow-up, later, defer). Rare and durable, so scanned over
    the whole session.
  - IN-FLIGHT: immediate "I'll / let me / next" actions, but ONLY from the last
    handful of messages — older ones are long done, so position is the filter.
Each is marked done/open by looking for a later completion cue that shares a
content word.
"""

import re

from .jsonl_reader import get_live_transcript, iter_messages

# Durable, explicitly-deferred commitments — worth surfacing whenever they were
# said. These markers are deliberately rare.
_DEFER_RE = re.compile(
    r"\b(next session|next time|next up|remaining(?: step| work| item|:)|"
    r"still (?:need|have) to|to-?do\b|fixme\b|follow-?up|later (?:we|i'?ll|on)\b|"
    r"leave (?:it|that|this) for|defer(?:red)?\b|come back to|circle back|"
    r"revisit|future (?:work|session|step)|haven'?t (?:yet|gotten)|"
    r"in a (?:future|later|follow))",
    re.IGNORECASE,
)

# Immediate next-actions — only meaningful near the END of the session.
_ACTION_RE = re.compile(
    r"\b(i'?ll |i will |let me |going to |next,? i'?ll |then i'?ll )",
    re.IGNORECASE,
)

# Cues that a prior commitment was carried out.
_DONE_RE = re.compile(
    r"\b(done|fixed|shipped|committed|pushed|passing|passed|all green|"
    r"complete[d]?|verified|resolved|works now|✓|✅)\b",
    re.IGNORECASE,
)

# Conversational filler that matches but isn't a real task.
_SKIP_RE = re.compile(
    r"(let me know|i'?ll wait|i'?ll be here|i'?ll keep (?:you|it)|let me explain)",
    re.IGNORECASE,
)

_WORD_RE = re.compile(r"[a-zA-Z_][\w./-]{3,}")

# Strong completion cues: if one appears CLOSE to a commitment, treat it as done
# even without a shared content word (e.g. "I'll stage ..." soon followed by
# "committed / pushed").
_STRONG_DONE_RE = re.compile(
    r"\b(committed|pushed|shipped|landed|merged|all pass|all green|✓|✅)\b",
    re.IGNORECASE,
)

_TAIL_MESSAGES = 30  # recent assistant msgs that count as "in-flight"
_DEFER_MESSAGES = 450  # recent assistant msgs scanned for deferred open-loops
_DONE_WINDOW = 150  # how far ahead to look for a (weak) completion cue
_STRONG_DONE_WINDOW = 8  # proximity for a strong, overlap-free completion cue


def _assistant_text(msg: dict) -> str:
    """Pull plain text from a transcript message (string or content-block list)."""
    inner = msg.get("message", msg)
    content = inner.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _sentences(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n+", text) if p.strip()]


def extract_commitments(project_path: str) -> dict:
    """Scan the live transcript for open commitments (deferred + in-flight).

    Returns ``{"session", "scanned_messages", "deferred_open", "inflight_open"}``
    or ``{"error": ...}``.
    """
    live = get_live_transcript(project_path)
    if live is None:
        return {"error": "no live transcript found for this project"}

    per_msg: list[list[str]] = []  # sentences grouped by assistant message
    try:
        for _, msg in iter_messages(live, types={"assistant"}):
            text = _assistant_text(msg)
            if text:
                per_msg.append(_sentences(text))
    except Exception as e:  # pragma: no cover - defensive
        return {"error": f"could not read transcript: {e}"}

    flat = [s for msg in per_msg for s in msg]

    def _ok(s: str) -> bool:
        return 10 <= len(s) <= 240 and not _SKIP_RE.search(s)

    # Deferred markers: scan a RECENT window, not the whole session. On a
    # long-lived JSONL (months of work across compactions) a whole-session scan
    # dredges open-loops from unrelated past work; this keeps it to the current
    # work block while staying much wider than the in-flight tail.
    defer_tail = [s for msg in per_msg[-_DEFER_MESSAGES:] for s in msg]
    defer_start = len(flat) - len(defer_tail)
    deferred = [
        (defer_start + j, s)
        for j, s in enumerate(defer_tail)
        if _ok(s) and _DEFER_RE.search(s)
    ]

    # In-flight actions: only the tail (older "let me ..." are long resolved).
    tail = [s for msg in per_msg[-_TAIL_MESSAGES:] for s in msg]
    tail_start = len(flat) - len(tail)
    inflight = [
        (tail_start + j, s)
        for j, s in enumerate(tail)
        if _ok(s) and _ACTION_RE.search(s) and not _DEFER_RE.search(s)
    ]

    def _is_open(idx: int, s: str) -> bool:
        kw = set(_WORD_RE.findall(s.lower()))
        for offset, later in enumerate(flat[idx + 1 : idx + 1 + _DONE_WINDOW]):
            # A strong completion cue close by counts even without word overlap.
            if offset < _STRONG_DONE_WINDOW and _STRONG_DONE_RE.search(later):
                return False
            # A weaker cue must share a content word with the commitment.
            if _DONE_RE.search(later) and kw & set(_WORD_RE.findall(later.lower())):
                return False
        return True

    def _dedupe(items):
        by = {}
        for idx, s in items:
            by[re.sub(r"\W+", "", s.lower())[:60]] = (idx, s)
        return sorted(by.values())

    deferred_open = [s for idx, s in _dedupe(deferred) if _is_open(idx, s)]
    inflight_open = [s for idx, s in _dedupe(inflight) if _is_open(idx, s)]

    return {
        "session": live.stem,
        "scanned_messages": len(per_msg),
        "deferred_open": deferred_open[-15:],
        "inflight_open": inflight_open[-8:],
    }


def format_commitments(r: dict) -> str:
    """Human-readable digest — deferred open loops first, recent in-flight next."""
    if r.get("error"):
        return f"Commitments: {r['error']}."
    lines = [f"Open commitments from the live session ({r['scanned_messages']} msgs):"]
    if r["deferred_open"]:
        lines.append("DEFERRED / next-steps:")
        for c in r["deferred_open"]:
            lines.append(f"  [ ] {c}")
    if r["inflight_open"]:
        lines.append("IN-FLIGHT (recent, maybe unfinished):")
        for c in r["inflight_open"]:
            lines.append(f"  [~] {c}")
    if not r["deferred_open"] and not r["inflight_open"]:
        lines.append("  (no open commitments detected)")
    lines.append("Heuristic from transcript phrasing — verify against your real plan.")
    return "\n".join(lines)
