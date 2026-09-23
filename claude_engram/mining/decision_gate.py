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
# Acknowledgement words, alone or strung together ("ok looks good, thanks").
_ACK = re.compile(
    r"^(?:(?:ok(?:ay)?|yes|yeah|yep|sure|fine|good|great|nice|approved?|confirmed?|go ahead|do it|"
    r"sounds good|looks good|proceed|thanks|thank you|perfect|correct|right|agreed|noted|please|cool|done)"
    r"\b[\s,.!;:-]*)+$",
    re.IGNORECASE,
)
# A word that decides: a choice, a rule, a direction, a permission. Tuned
# on the neutral corpus in tests/bench_decision_capture_v2.py (120
# decisions, 100 not): scored by tests/bench_correction_gate.py.
_CUE = re.compile(
    r"\b(?:let'?s|we'?ll|i'?ll|we should|should(?:n'?t)?|always|never|from now on|going forward|"
    r"instead|switch(?:ed|ing)? to|adopt|keep|drop|go(?:ing)? with|went with|decided?|decision|"
    r"approved?|prefer(?:red)?|stick with|rule|policy|default|use|do not|don'?t|stop|leave|"
    r"only|must|pause|no longer|rather than|allowed|forbidden|required|optional|implement|"
    r"lock in|pick|choose|chose|commit to|settle on|standardi[sz]e on|needs? to|needs? at least|"
    r"require[sd]?|go native|move to|not .{1,30}\b(?:but|instead)\b|,\s*not\b)\b",
    re.IGNORECASE,
)
# An edit verb is an instruction on its own ("rename this variable", "revert
# the last commit") and a decision when it names a transition ("replace X
# with Y", "migrate from A to B") or a scope ("rename every handler") and
# its object is not deictic ("this file", "that variable").
_ACTION_CUE = re.compile(
    r"\b(?:rename|replace|move|split|merge|revert|remove|undo|delete|rewrite|migrate|swap|convert|upgrade|switch)\b",
    re.IGNORECASE,
)
_ACTION_DEICTIC = re.compile(
    r"\b(?:rename|replace|move|split|merge|revert|remove|undo|delete|rewrite|migrate|swap|convert|upgrade|switch)\b"
    r"(?:\s+\S+){0,2}\s+(?:this|that|these|those|the last|the latest)\b",
    re.IGNORECASE,
)
_SCOPE = re.compile(r"\b(?:all|every|always|never|any|new|from now on|going forward|whole|everywhere|across|each|no longer)\b", re.IGNORECASE)
_TRANSITION = re.compile(r"\bfrom\b.*\bto\b|\bwith\b|\bover\b|\busing\b|\bto\b", re.IGNORECASE)
# Hedges, history, opinion and third parties: talk about a choice, not a
# choice of ours.
_HEDGE = re.compile(
    r"\b(?:not sure|unsure|not certain|no idea|wondering|whether|maybe|perhaps|might|could potentially|"
    r"potentially|thinking about|think about|consider(?:ing)?|used to|were going to|was going to|personally|"
    r"(?:most|many|some|other|several) (?:people|teams|projects|folks|companies|devs|developers)|"
    r"our competitors|the previous team|the old team|use case)\b",
    re.IGNORECASE,
)
# A word that redirects: what a correction or a preference carries. Tuned
# on the neutral 220-prompt corpus in tests/bench_decision_capture_v2.py
# (positives: its negation and convention decisions; negatives: every
# not-decision), never on any one session: the broad first list (with
# "other", "should", "want", "actually", "mean") scored precision 0.74,
# recall 0.57; this one 0.86 / 0.80. Position did not matter (the same
# list within the first six words: 0.86 / 0.78). "undo" and "revert" are
# commands more often than corrections and are left to the decision cue.
_CORRECTION_CUE = re.compile(
    r"\b(?:no|not|don'?t|doesn'?t|isn'?t|wasn'?t|never|wrong|instead|stop|rather than|shouldn'?t|"
    r"meant|prefer|differently|always|avoid|only)\b",
    re.IGNORECASE,
)
# Starts like code, markup, a path, a URL, a quote, a list marker or a number.
_CODE_START = re.compile(r"^\s*(?:[`\"'|#>$<-]|\w:[\\/]|/[a-z]|\.\.?/|https?://|\d)")
# A request opener: asks for something rather than deciding it.
_REQUEST = re.compile(
    r"^\s*(?:(?:can|could|would|will|may) (?:you|we|i)\b|please\b|give me|tell me|show me|let me know|"
    r"what (?:is|are|do|does|should|would)|how (?:do|does|should|would|about)|remind me|help me)",
    re.IGNORECASE,
)
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
    if len(t) < 12 or len(t.split()) < 3:
        return "too short"
    if _ACK.match(t):
        return "acknowledgement"
    if _CODE_START.match(t):
        return "starts like code or a path"
    if _REQUEST.match(t):
        return "a request"
    if _REPORT_SHAPE.search(t):
        return "count, table or commit report"
    if _alpha_ratio(t) < 0.75:
        return "mostly symbols"
    return ""


def looks_like_decision(text: str) -> bool:
    """A decision: the shape above, not a hedge, plus a deciding word (an
    edit verb counts only with a scope word)."""
    t = bare(text)
    if why_not(text) or _HEDGE.search(t):
        return False
    if _CUE.search(t):
        return True
    if _ACTION_CUE.search(t) and not _ACTION_DEICTIC.search(t):
        return bool(_SCOPE.search(t) or _TRANSITION.search(t))
    return False


def looks_like_correction(text: str) -> bool:
    """A correction or preference: the shape above, plus a redirecting word,
    and not a hedge ("not sure if we need it yet" redirects nothing)."""
    t = bare(text)
    return not why_not(text) and bool(_CORRECTION_CUE.search(t)) and not _HEDGE.search(t)
