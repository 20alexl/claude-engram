"""Milestones: the model's own "this step is done" as the checkpoint trigger.

A checkpoint is a deliberate call. Engram never writes one from a commit or
a timer on the model's behalf. What it does is read the moment the model
itself judges a unit of work closed -- "Phase 1 built", "step 3 done, next
is the run report", "all 60 checks pass" -- and, if no deliberate checkpoint
landed with that claim, ask for one at the next opportunity.

Where the judgment shows up (verified against the hooks reference):

  * The Stop hook receives ``last_assistant_message`` verbatim. That is the
    sentence where a step gets declared done. Read here.
  * ``ExitPlanMode``: a plan just got approved. Its steps ARE the milestone
    list, so bank the plan as a checkpoint with those steps pending.
  * ``TaskUpdate`` with ``status: completed``: the same judgment stated
    structurally. Claude Code leaves the task tools out on the newest models
    unless the user opts in, so this is a bonus path, not the design.

The classifier is two-tier like decision capture: a regex tier that wants a
completion word NEAR a unit noun (phase / step / part / ...), and, for weak
matches only, a semantic tier through the scorer daemon. Questions, negations
and future tense are rejected in the regex tier so "when phase 1 is done"
and "is step 3 finished?" never fire.

The nudge lands one turn late in an interactive session -- a Stop hook
cannot add context to the turn that just ended -- and at the next tool call
in a loop. The rule in the skill ("checkpoint before you declare a step
done") is the ideal path; this is the miss-catcher.
"""

from __future__ import annotations

import re
from typing import Optional

# Unit nouns: what a "done" has to be about before it counts as a milestone.
_UNIT = (
    r"(?:phase|step|part|stage|milestone|round|section|sprint|batch|item|"
    r"task|feature|refactor|migration|pull request|release|rollout|module|"
    r"component|epic|story|ticket|bench(?:mark)?|suite|plan|deliverable|"
    r"follow-?up|goal|objective|v?\d+\.\d+(?:\.\d+)?)"
)
_DONE = (
    r"(?:done|complete|completed|finished|shipped|landed|closed|closes|"
    r"wrapped up|wraps up|concluded|concludes|built|merged|verified|green|"
    r"passing|passes|passed|in place|wired|delivered|implemented|integrated|"
    r"met|achieved|reached|satisfied|resolved)"
)
# Words within a short window BEFORE the completion word that flip it to a
# non-claim: negation, future, conditional, partial.
_NEG = (
    r"(?:not|n't|never|isn't|aren't|wasn't|isnt|arent|still|almost|nearly|"
    r"half|partially|partly|until|once|when|before|after|if|unless|will be|"
    r"to be|should be|needs? to be|has to be|must be|could be|would be|"
    r"can't be|cannot be|yet|todo|pending|remaining)"
)

# A sentence ends at .!? followed by optional markdown closers ("claim.**")
# and whitespace; a bold header and the sentence after it are two sentences.
_SENT_SPLIT = re.compile(r"(?<=[.!?])[*_)\"'`]*\s+|\n+")
# A unit noun inside a hyphenated compound is not the unit ("follow-plan
# rules", "goal-test/out.txt"); ``follow-?up`` is itself a unit.
_U = rf"(?<![-\w/]){_UNIT}(?![-\w/])"
_STRONG_UNIT_THEN_DONE = re.compile(
    rf"{_U}[^.!?\n]{{0,60}}?\b(?P<done>{_DONE})\b", re.IGNORECASE
)
_STRONG_DONE_THEN_UNIT = re.compile(
    rf"\b(?P<done>{_DONE})\b[^.!?\n]{{0,40}}?{_U}", re.IGNORECASE
)
# Quoted spans are someone else's words or a past sentence being discussed
# ("X landed after it was saved" fired a nudge), never this turn's claim.
_QUOTED = re.compile(r"\"[^\"\n]{2,}\"|`[^`\n]{2,}`|“[^”\n]{2,}”")
# Restated history: a completion word that refers back to something that
# was already the case ("landed after it was saved", "already built",
# "done last session", "as of the previous commit"). Reporting the past is
# not closing a step now.
_HISTORY = re.compile(
    rf"\b(?:already|earlier|previously|beforehand|before this (?:session|turn|run)|"
    rf"last (?:session|turn|time|night|week|run)|in (?:the |a )?(?:previous|earlier|last|prior) "
    rf"(?:session|turn|commit|run|pass)|after (?:it|that|this|the \w+) (?:was|were|had|got)|"
    rf"as of|since (?:then|the last)|had (?:been )?{_DONE})\b",
    re.IGNORECASE,
)
_ALL_PASS = re.compile(
    r"\ball\s+(?:\d+\s+)?(?:checks|tests|benches|benchmarks|suites|cases)\s+"
    r"(?P<done>pass(?:ed|ing)?|green)\b"
    r"|\b(?P<n>\d+)\s*/\s*(?P=n)\b[^.!?\n]{0,20}\b(?P<done2>pass(?:ed|ing)?|green|ok)\b",
    re.IGNORECASE,
)
# A future / modal / conditional marker ANYWHERE before the completion word:
# "I'll mark the task complete", "the next verdict should say met", "after
# the third line lands the goal clears". Talk about completion, not a claim
# of it. Precision over recall: "After a long fight, phase 1 is done" is
# rejected too, and that is the right trade for a nudge.
_FUTURE_ANY = re.compile(
    r"\b(?:i'?ll|we'?ll|will|shall|would|should|could|might|may|going to|"
    r"about to|plan to|planning to|intend to|expect(?:s|ed)? to|then|once|"
    r"after|when|whenever|if|unless|until|before)\b",
    re.IGNORECASE,
)
# Imperatives and second-person instructions are addressed to someone, not
# reported: "Exit after it says the goal is met.", "Run the suite until it
# is green." A claim is first-person or declarative.
_IMPERATIVE_START = re.compile(
    r"^(?:exit|run|press|tell|let|open|send|wait|delete|keep|go|stop|start|"
    r"check|make|try|use|set|add|remove|restart|kill|ask|give|type|click|do|"
    r"please|then|now|first|next|finally|remember|note|see)\b(?=\s+[a-z])",
    re.IGNORECASE,
)  # the lookahead keeps "Run 3 of 3 done" (a count, not a command)
_SECOND_PERSON = re.compile(r"\b(?:you|your|yours|you'?re|you'?ll|you'?ve)\b", re.IGNORECASE)
# "Run 3 of 3 done", "step 2 of 5 complete": numeric progress that reaches
# the total is a claim even without a unit noun.
_N_OF_N_DONE = re.compile(
    r"\b(?P<n>\d+)\s+of\s+(?P=n)\b[^.!?\n]{0,30}\b(?P<done>done|complete|completed|finished)\b",
    re.IGNORECASE,
)
_UNIT_ANY = re.compile(rf"\b{_UNIT}\b", re.IGNORECASE)
_DONE_ANY = re.compile(rf"\b(?P<done>{_DONE})\b", re.IGNORECASE)
_NEG_BEFORE = re.compile(rf"\b{_NEG}\b[^.!?\n]{{0,14}}$", re.IGNORECASE)
_NEG_AFTER = re.compile(r"^[^.!?\n]{0,6}\b(?:yet|so far)\b", re.IGNORECASE)

STRONG = 1.0
WEAK = 0.5
THRESHOLD = 0.6
SEMANTIC_MARGIN = 0.03

_COMPLETION_TEMPLATES = [
    "This step is done.",
    "Phase complete; all tests pass.",
    "Finished this part of the plan, moving on to the next.",
    "The milestone is closed and verified.",
    "Built and verified, ready for the next step.",
    "That closes this section of the work.",
]
_NON_COMPLETION_TEMPLATES = [
    "Still working on this step.",
    "The next step is not done yet.",
    "I found a bug and am investigating it.",
    "Here is the plan for the next phase.",
    "Waiting on your answer before continuing.",
    "Is this step done?",
    "This will be done once the tests pass.",
]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text or "") if s and s.strip()]


def _done_span(m: "re.Match[str]") -> tuple[int, int]:
    for g in ("done", "done2"):
        try:
            if m.group(g) is not None:
                return m.start(g), m.end(g)
        except IndexError:
            continue
    return m.start(), m.end()


def _negated(sentence: str, m: "re.Match[str]") -> bool:
    """A negation / future / conditional / partial marker right before the
    completion word ("not done", "half done", "when ... is complete"), or a
    "yet" right after it."""
    start, end = _done_span(m)
    before = sentence[:start]
    return (
        bool(_NEG_BEFORE.search(before))
        or bool(_FUTURE_ANY.search(before))
        or bool(_NEG_AFTER.search(sentence[end:]))
    )


def _regex_tier(sentence: str) -> float:
    if "?" in sentence:
        return 0.0
    # Quoted spans are discussed, not claimed; restated history is reported,
    # not closed. Both leave nothing for a claim to stand on.
    sentence = _QUOTED.sub(" ", sentence)
    if _HISTORY.search(sentence):
        return 0.0
    if _IMPERATIVE_START.match(sentence.lstrip("*-# ")) or _SECOND_PERSON.search(sentence):
        return 0.0
    m = _ALL_PASS.search(sentence)
    if m and not _negated(sentence, m):
        return STRONG
    m = _N_OF_N_DONE.search(sentence)
    if m and not _negated(sentence, m):
        return STRONG
    for rx in (_STRONG_UNIT_THEN_DONE, _STRONG_DONE_THEN_UNIT):
        m = rx.search(sentence)
        if m and not _negated(sentence, m):
            return STRONG
    md = _DONE_ANY.search(sentence)
    if md and _UNIT_ANY.search(sentence) and not _negated(sentence, md):
        return WEAK
    return 0.0


def _embed_batch(texts: list[str]) -> list[list[float]]:
    """Seam for the semantic tier (patched in the bench)."""
    try:
        from claude_engram.hooks.scorer_server import embed_batch_via_server

        return embed_batch_via_server(texts)
    except Exception:
        return []


def _cos(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _semantic_tier(sentence: str) -> Optional[float]:
    """Completion-vs-not margin for a WEAK regex match. None when the scorer
    is unavailable (the weak match then stays weak: not a claim)."""
    vecs = _embed_batch([sentence] + _COMPLETION_TEMPLATES + _NON_COMPLETION_TEMPLATES)
    if not vecs or not vecs[0]:
        return None
    s = vecs[0]
    n_c = len(_COMPLETION_TEMPLATES)
    comp = vecs[1 : 1 + n_c]
    non = vecs[1 + n_c :]
    if not comp or not non or not all(comp) or not all(non):
        return None
    best_c = max(_cos(s, v) for v in comp)
    best_n = max(_cos(s, v) for v in non)
    return best_c - best_n


def classify_completion(text: str, use_semantic: bool = True) -> tuple[float, str]:
    """(score, the claiming sentence). Score >= THRESHOLD = a completion claim.

    Strong regex matches score 1.0 outright. A weak match (completion word and
    a unit noun in the same sentence, not adjacent) consults the semantic tier
    when available and passes only with a positive margin.
    """
    best = (0.0, "")
    for sent in _sentences(text)[:40]:
        if len(sent) < 8 or len(sent) > 600:
            continue
        score = _regex_tier(sent)
        if score >= STRONG:
            return (STRONG, sent[:160])
        if score >= WEAK and score > best[0]:
            if use_semantic:
                margin = _semantic_tier(sent)
                if margin is not None and margin > SEMANTIC_MARGIN:
                    return (STRONG, sent[:160])
            best = (score, sent[:160])
    return best if best[0] >= THRESHOLD else (0.0, "")


def is_completion_claim(text: str, use_semantic: bool = True) -> tuple[bool, str]:
    score, quote = classify_completion(text, use_semantic=use_semantic)
    return (score >= THRESHOLD, quote)


# ---------------------------------------------------------------------------
# Nudge texts
# ---------------------------------------------------------------------------


def milestone_text(quote: str, kind: str = "claim") -> str:
    if kind == "claim_remember":
        closed = f' ("{quote}")' if quote else ""
        return (
            f"<engram-context>Last turn banked state with memory(remember){closed}. "
            "A remember stores a fact; the restore after a compaction or a new session "
            "reads checkpoints only, so that state is not what comes back. Keep the fact, "
            'and bank the state too: context(checkpoint_save, task_description="<what closed, '
            'what is next>"). Engram never writes this for you.</engram-context>'
        )
    lead = (
        f'You marked a task done: "{quote}".'
        if kind == "task"
        else f'Last turn you closed a step: "{quote}".'
    )
    return (
        f"<engram-context>{lead} No deliberate checkpoint followed. Bank it: "
        'context(checkpoint_save, task_description="<one line: what closed, what is next>") '
        "is enough; the structured fields (pending_steps, files_involved, "
        "handoff_warnings) are optional. Engram never writes this for you."
        "</engram-context>"
    )


def plan_text() -> str:
    return (
        "<engram-context>Plan mode exited. If the plan was approved, bank it as "
        "a checkpoint now: context(checkpoint_save) with task_description = the "
        "goal and pending_steps = the plan's steps. Every later 'step done' then "
        "maps onto that list, and a restore shows exactly where in the plan the "
        "session is.</engram-context>"
    )
