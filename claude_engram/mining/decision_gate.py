"""The shape a captured decision has to have before it is stored.

Both capture paths (the miner over past transcripts, the prompt hook over
the live one) were storing anything their scorers let through: questions,
acknowledgements, test counts, pasted status lines, sentence fragments.
Eight days of one session put 636 such entries into a workspace store,
and they came back before edits as "Relevant memories for this file".

This gate is about FORM, never about any particular user's phrasing: a
decision is a declarative sentence of at least four words, not a question,
not a count or a table row or a commit report, not an acknowledgement, and
it carries a word that decides something. Shared by the miner, the prompt
hook and the pruning migration so all three agree.
"""

from __future__ import annotations

import re

_PREFIX = re.compile(r"^\s*(?:(?:DECISION:|USER PREFERENCE:|\(from user\)|\(confirmed\))\s*)+", re.IGNORECASE)
_ACK = re.compile(
    r"^(?:ok(?:ay)?|yes|yeah|yep|sure|fine|good|great|nice|approved?|confirmed?|go ahead|do it|"
    r"sounds good|looks good|proceed|thanks|thank you|perfect|correct|right|agreed|noted)\b[^a-z]*$",
    re.IGNORECASE,
)
# A word that decides: a choice, a rule, a direction, a permission.
_CUE = re.compile(
    r"\b(?:let'?s|we'?ll|i'?ll|we should|should(?:n'?t)?|always|never|from now on|going forward|"
    r"instead|switch(?:ed|ing)? to|adopt|keep|drop|go with|went with|decided?|decision|"
    r"approved?|prefer(?:red)?|stick with|rule|policy|default|use|do not|don'?t|stop|leave|"
    r"only|must|pause|no longer|rather than|rename|replace|move|split|merge|"
    r"revert|remove|allowed|forbidden|required|optional)\b",
    re.IGNORECASE,
)
# A word that redirects: what a correction or a preference carries.
_CORRECTION_CUE = re.compile(
    r"\b(?:no|not|don'?t|doesn'?t|isn'?t|wrong|instead|stop|actually|rather|never|should(?:n'?t)?|"
    r"meant|mean|wanted|want|prefer|keep|leave|undo|revert|different(?:ly)?|other)\b",
    re.IGNORECASE,
)
# Starts like code, a path, a URL, a quote, a list marker or a number.
_CODE_START = re.compile(r"^\s*(?:[`\"'|#>$-]|\w:[\\/]|/[a-z]|\.\.?/|https?://|\d)")
# A report: a table cell, a labelled count, "N passed", two commit hashes.
_REPORT_SHAPE = re.compile(
    r"\s\|\s|^\s*\||\b(?:count|total|passed|failed|errors?|outcomes?|exit(?:ed)?)\s*[:=]\s*\d|"
    r"\b\d+\s+(?:passed|failed|errors?)\b|\b[0-9a-f]{7,40}\b.*\b[0-9a-f]{7,40}\b",
    re.IGNORECASE,
)


def bare(text: str) -> str:
    """The text without engram's own prefixes. A "(confirmed)" entry is an
    assistant proposal the user said yes to; only its first sentence is the
    proposal, the rest is the report that followed it."""
    raw = (text or "").lstrip()
    confirmed = "(confirmed)" in raw[:40]
    t = _PREFIX.sub("", raw).strip()
    if confirmed:
        t = re.split(r"(?<=[.!?])\s+|\n", t, maxsplit=1)[0].strip()
    return t


def _alpha_ratio(s: str) -> float:
    letters = sum(ch.isalpha() or ch.isspace() for ch in s)
    return letters / max(1, len(s))


def why_not(text: str) -> str:
    """The first reason a text is not a decision, or '' when it may be one
    (the cue is checked by the callers, per kind)."""
    t = bare(text)
    if "?" in t:
        return "question"
    if len(t) < 20 or len(t.split()) < 4:
        return "too short"
    if _ACK.match(t):
        return "acknowledgement"
    if _CODE_START.match(t):
        return "starts like code or a path"
    if _REPORT_SHAPE.search(t):
        return "count, table or commit report"
    if _alpha_ratio(t) < 0.75:
        return "mostly symbols"
    return ""


def looks_like_decision(text: str) -> bool:
    """A decision: the shape above, plus a deciding word."""
    return not why_not(text) and bool(_CUE.search(bare(text)))


def looks_like_correction(text: str) -> bool:
    """A correction or preference: the shape above, plus a redirecting word."""
    return not why_not(text) and bool(_CORRECTION_CUE.search(bare(text)))
