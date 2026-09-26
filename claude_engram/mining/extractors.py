"""
Extractors — mine decisions, mistakes, approaches, and corrections from sessions.

Three-layer extraction:
  1. Structural — conversation flow patterns (most robust, typo-immune)
  2. Semantic  — embedding-model scoring against templates (typo-immune, 5-25ms/call)
  3. Regex     — fast pre-filter for obvious patterns (least robust)

All extractors output concise findings, not raw conversation text.
"""

import re
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

from claude_engram.mining.jsonl_reader import (
    extract_user_text,
    extract_assistant_text,
    extract_thinking,
    extract_tool_uses,
    extract_file_edits,
    extract_bash_commands,
    extract_tool_results,
    get_timestamp,
)


# Projects that received mined entries during the current pipeline run — read
# by background.run_mining to embed exactly those (see projects_fed_last_run).
_fed_projects: set[str] = set()


# ─── Data structures ─────────────────────────────────────────────────────


@dataclass
class Decision:
    content: str  # Concise: "Use numpy instead of ChromaDB for embeddings"
    reasoning: str = ""  # Why: "ChromaDB adds 200MB dependency"
    timestamp: str = ""
    source: str = ""  # "structural" | "semantic" | "regex"
    related_files: list[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class Mistake:
    description: str  # What went wrong
    fix: str = ""  # How it was fixed
    timestamp: str = ""
    related_files: list[str] = field(default_factory=list)
    error_type: str = ""  # "AttributeError", "test_failure", etc.


@dataclass
class Approach:
    tried: str  # What was attempted
    result: str  # "failed" | "worked"
    switched_to: str = ""  # What replaced it
    timestamp: str = ""
    related_files: list[str] = field(default_factory=list)


@dataclass
class Correction:
    user_said: str  # The correction text
    preference: str  # Extracted preference
    context: str = ""  # What assistant said before (to understand what was corrected)
    timestamp: str = ""


@dataclass
class SessionExtractions:
    session_id: str = ""
    decisions: list[Decision] = field(default_factory=list)
    mistakes: list[Mistake] = field(default_factory=list)
    approaches: list[Approach] = field(default_factory=list)
    corrections: list[Correction] = field(default_factory=list)
    # Every file the session edited, in order: the vote that names the
    # project an entry with no files of its own belongs to.
    session_files: list[str] = field(default_factory=list)
    summary: str = ""
    extracted_at: float = 0.0


# ─── Semantic scorer (embedding model) ──────────────────────────────────────────

# Templates for semantic classification. The encoder compares message embeddings
# against these templates. This is naturally typo-tolerant (100% in benchmarks).
_DECISION_TEMPLATES = [
    "let's use this approach instead",
    "I decided to go with this solution",
    "switch to a different method",
    "from now on always do it this way",
    "use X instead of Y",
    "the better approach is",
    "we should change to",
    "going with this implementation",
    "yes lets do that please",
    "go with that option",
    "ok change it to use this instead",
    "no do it differently, use the other way",
    "lets do it that way",
    "yes please do it to the best ability",
]

# What a user message usually is when it is NOT a decision, by category
# (a question, an instruction to act, an approval, a status report, a
# count, a pasted log). A decision has to beat the closest of these by
# MINED_DECISION_MARGIN; a bare cosine to the decision templates is where
# most short text sits under a modern encoder.
_NON_DECISION_TEMPLATES = [
    "a question asking what something does or how it works",
    "an instruction to run, check, fix or look at something",
    "an approval or acknowledgement of what was just proposed",
    "a status report on where the work stands right now",
    "a count of results: how many passed, failed or were skipped",
    "a pasted log, error trace or command output",
    "a request for a summary or an update",
    "a remark about timing, waiting or what happens next",
]
MINED_DECISION_MARGIN = 0.05

_CORRECTION_TEMPLATES = [
    "no that's wrong, do it differently",
    "stop doing that, I don't want that",
    "not what I asked for, I meant this instead",
    "don't do that, I want something else",
    "that's not right, please change it",
    "no I meant the other thing",
    "actually do it this way not that way",
]

_MISTAKE_TEMPLATES = [
    "sorry that was my mistake, let me fix it",
    "the bug was caused by this error",
    "the issue was in this function",
    "I was wrong about that, the real problem is",
    "that broke because of this",
]

_template_cache: dict[str, list[list[float]]] = {}


def _get_template_embeddings(
    templates: list[str], key: str
) -> Optional[list[list[float]]]:
    """Get cached template embeddings via the scorer server."""
    if key in _template_cache:
        return _template_cache[key]

    try:
        from claude_engram.hooks.scorer_server import embed_via_server

        embeddings = []
        for t in templates:
            emb = embed_via_server(t)
            if not emb:
                return None
            embeddings.append(emb)
        _template_cache[key] = embeddings
        return embeddings
    except Exception:
        return None


def _semantic_score_single(
    text_emb: list[float], template_embs: list[list[float]]
) -> float:
    """Score a pre-computed embedding against templates. Returns max cosine similarity."""
    max_sim = 0.0
    for templ_emb in template_embs:
        sim = sum(a * b for a, b in zip(text_emb, templ_emb))
        max_sim = max(max_sim, sim)
    return max_sim


def _batch_embed(texts: list[str]) -> list[list[float]]:
    """Batch embed texts via the scorer server. Single TCP call."""
    if not texts:
        return []
    try:
        from claude_engram.hooks.scorer_server import embed_batch_via_server

        return embed_batch_via_server(texts)
    except Exception:
        return [[] for _ in texts]


def _batch_score(
    texts: list[str],
    template_key: str,
    templates: list[str],
) -> list[float]:
    """
    Batch score texts against templates using the embedding model.

    Embeds all candidate texts in one pass, then scores against template embeddings.
    Much faster than individual calls for multiple candidates.
    """
    if not texts:
        return []

    template_embs = _get_template_embeddings(templates, template_key)
    if not template_embs:
        return [0.0] * len(texts)

    embeddings = _batch_embed(texts)

    scores = []
    for emb in embeddings:
        if emb:
            scores.append(_semantic_score_single(emb, template_embs))
        else:
            scores.append(0.0)

    return scores


# ─── Error type extraction (regex — precise, not fuzzy) ──────────────────

_ERROR_TYPE_PATTERN = re.compile(
    r"((?:Attribute|Type|Name|Import|Key|Index|Value|Runtime|Syntax|FileNotFound)Error):\s*(.{5,200})"
)

# A grep result line or a line of code after an error name is not the
# error's message ("ValueError: 141:def graphs_overrides(...)", 2026-09-25).
_SOURCE_LINE = re.compile(
    r"^\d+[:-]|^[\w./\\-]+\.\w{1,5}:\d+|"
    r"^(?:async def|def|class|import|from|return|raise|if|elif|else|for|while|try|except|with)\b"
)
# A single quoted token is a whole message for a KeyError ("'session_id'").
_QUOTED_TOKEN = re.compile(r"^(?:'[^']+'|\"[^\"]+\")$")

# A message another program relayed into the user's turn: a teammate's or
# an agent's report wrapped in tags, Claude Code's own notice of one, a
# system reminder. Its sentences are not the user's and the whole MESSAGE
# is dropped before any pattern sees it: the boilerplate around one matched
# "use ... instead" across sentence boundaries and the report's first
# sentence was stored as a decision (2026-09-25).
_RELAYED = re.compile(
    r"<(?:teammate|agent|peer)-message\b|Another (?:Claude )?session sent a message|<system-reminder\b",
    re.IGNORECASE,
)


def _typed_prompt(text: str, max_len: int = 500) -> bool:
    """A prompt the user typed, one paragraph, short enough to be a sentence
    or two: the only message a decision or a correction is mined from.
    Pasted markup or JSON, a relayed message, a wall of text are not."""
    t = (text or "").strip()
    if not t or len(t) >= max_len:
        return False
    if t.startswith("<") or t.startswith("{"):
        return False
    return not _RELAYED.search(t) and "\n\n" not in t


_TEST_FAILURE_PATTERN = re.compile(
    r"(\d+) (?:failed|errors?),?\s*(\d+)? ?(?:passed)?", re.I
)


# ─── Structural extractors ──────────────────────────────────────────────


def extract_all(messages: list[dict]) -> SessionExtractions:
    """
    Extract all intelligence from a message sequence using structural analysis.

    Analyzes conversation flow — not just individual messages:
    - User→Assistant direction changes = corrections/decisions
    - Error→Fix sequences = mistakes with fixes
    - Repeated file edits = struggle areas
    - Approach changes = tried-and-switched patterns
    """
    extractions = SessionExtractions(extracted_at=time.time())

    # Pre-classify messages into a conversation flow
    flow = _build_conversation_flow(messages)
    seen_files: set[str] = set()
    for fm in flow:
        for f in fm.file_edits:
            if f and f not in seen_files:
                seen_files.add(f)
                extractions.session_files.append(f)

    # 1. Extract mistakes from error→fix sequences
    extractions.mistakes = _extract_mistakes_structural(flow)

    # 2. Extract corrections from user redirect patterns
    extractions.corrections = _extract_corrections_structural(flow)

    # 3. Extract decisions (semantic + structural)
    extractions.decisions = _extract_decisions_structural(flow)

    # 4. Extract approach changes from file edit patterns
    extractions.approaches = _extract_approaches_structural(flow)

    return extractions


@dataclass
class FlowMessage:
    """A message in the conversation flow with pre-extracted data."""

    index: int
    msg_type: str  # "user" | "assistant"
    timestamp: str = ""
    user_text: str = ""
    assistant_texts: list[str] = field(default_factory=list)
    thinking: list[str] = field(default_factory=list)
    tool_names: list[str] = field(default_factory=list)
    file_edits: list[str] = field(default_factory=list)
    bash_commands: list[str] = field(default_factory=list)
    has_error: bool = False
    error_content: str = ""
    raw: dict = field(default_factory=dict)


def _build_conversation_flow(messages: list[dict]) -> list[FlowMessage]:
    """Pre-process messages into a structured flow for analysis."""
    flow = []

    for i, msg in enumerate(messages):
        msg_type = msg.get("type", "")
        if msg_type not in ("user", "assistant"):
            continue

        fm = FlowMessage(
            index=i,
            msg_type=msg_type,
            timestamp=get_timestamp(msg),
            raw=msg,
        )

        if msg_type == "user":
            fm.user_text = extract_user_text(msg) or ""

            # Check toolUseResult for errors
            tr = msg.get("toolUseResult", {})
            if isinstance(tr, dict) and tr.get("stderr"):
                stderr = tr["stderr"]
                if isinstance(stderr, str) and _ERROR_TYPE_PATTERN.search(stderr):
                    fm.has_error = True
                    fm.error_content = stderr[:500]

            # Check list content for tool_result blocks with errors
            raw_content = msg.get("message", {}).get("content", "")
            if isinstance(raw_content, list):
                for block in raw_content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("is_error"):
                        fm.has_error = True
                    block_content = block.get("content", "")
                    if isinstance(block_content, str) and _ERROR_TYPE_PATTERN.search(
                        block_content
                    ):
                        fm.has_error = True
                        if not fm.error_content:
                            fm.error_content = block_content[:500]

        elif msg_type == "assistant":
            fm.assistant_texts = extract_assistant_text(msg)
            fm.thinking = extract_thinking(msg)
            fm.tool_names = [t["name"] for t in extract_tool_uses(msg)]
            fm.file_edits = extract_file_edits(msg)
            fm.bash_commands = extract_bash_commands(msg)

        flow.append(fm)

    return flow


_CODE_SUFFIXES = frozenset(
    {".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".rs", ".go", ".java", ".kt", ".c", ".h",
     ".cc", ".cpp", ".hpp", ".cs", ".rb", ".php", ".swift", ".scala", ".lua", ".luau", ".sh", ".ps1", ".sql"}
)


def _code_like(path: str) -> bool:
    return ("." + str(path).rsplit(".", 1)[-1].lower()) in _CODE_SUFFIXES if "." in str(path) else False


def _extract_mistakes_structural(flow: list[FlowMessage]) -> list[Mistake]:
    """
    Extract mistakes from error→fix sequences.

    Pattern: tool_result with error → assistant explains/fixes
    This catches real errors, not false positives from word matching.
    """
    mistakes = []
    seen = set()

    for i, fm in enumerate(flow):
        if not fm.has_error or not fm.error_content:
            continue

        # Extract error type and message
        match = _ERROR_TYPE_PATTERN.search(fm.error_content)
        if not match:
            continue

        error_type = match.group(1)
        error_msg = match.group(2).strip()[:200]
        if _SOURCE_LINE.match(error_msg):
            continue
        if len(error_msg.split()) < 4 and not _QUOTED_TOKEN.match(error_msg):
            continue  # a fragment, not a message
        key = f"{error_type}:{error_msg[:60]}"

        if key in seen:
            continue
        seen.add(key)

        # Look ahead for the fix. Scan the next few assistant messages rather
        # than taking the first one's opening sentence: right after an error the
        # assistant is usually still narrating ("Let me check the correct
        # path:"), and the actual resolution lands a message or two later, after
        # the tool call. Narration stored as a fix is worse than no fix — it is
        # injected later as if it were guidance.
        fix = ""
        related_files = []
        # The files an error is tied to: the ones its own text names
        # (a traceback), else the CODE files edited right after it. A plan
        # markdown edited after a TypeError cannot have raised it, and
        # tying them together made every later edit of the plan warn
        # "Watch for: TypeError" (2026-09-22).
        traced = [
            t for t in re.findall(r"File [\"']([^\"']+\.\w{1,5})[\"']", fm.error_content or "")
            if not re.search(r"[\\/](?:site-packages|dist-packages|venv|\.venv)[\\/]", t)
        ]
        if traced:
            related_files = list(dict.fromkeys(traced))[:5]
        for j in range(i + 1, min(i + 4, len(flow))):
            if flow[j].msg_type != "assistant":
                continue
            if not related_files:
                related_files = [f for f in flow[j].file_edits if _code_like(f)]
            for text in flow[j].assistant_texts:
                if len(text) > 20:
                    candidate = _first_sentence(text, max_len=150)
                    if candidate and not _is_narration(candidate):
                        fix = candidate
                        break
            if fix:
                break

        mistakes.append(
            Mistake(
                description=f"{error_type}: {error_msg}",
                fix=fix,
                timestamp=fm.timestamp,
                related_files=related_files,
                error_type=error_type,
            )
        )

    return mistakes


def _extract_corrections_structural(flow: list[FlowMessage]) -> list[Correction]:
    """
    Extract user corrections from conversation flow.

    Structural pre-filter → batch semantic scoring → threshold.
    No regex for classification — structure + semantics only.
    """
    corrections = []
    seen = set()

    # Phase 1: Structural pre-filter — find candidate messages
    candidates = []  # (flow_index, text, prev_assistant)
    for i, fm in enumerate(flow):
        if fm.msg_type != "user" or not fm.user_text:
            continue

        text = fm.user_text.strip()
        if len(text) < 5 or not _typed_prompt(text):
            continue

        # Structural signals:
        # - Short user message (< 200 chars) = likely feedback/redirect
        # - Follows a long assistant response = response to work done
        is_short = len(text) < 200
        follows_work = False
        prev_assistant = ""
        for j in range(i - 1, max(i - 3, -1), -1):
            if flow[j].msg_type == "assistant":
                if flow[j].assistant_texts or flow[j].file_edits:
                    follows_work = True
                    if flow[j].assistant_texts:
                        prev_assistant = flow[j].assistant_texts[0][:200]
                break

        # Only consider short messages that follow assistant work
        if is_short and follows_work:
            candidates.append((i, text, prev_assistant))

    if not candidates:
        return []

    # Phase 2: Batch semantic scoring (one pass, typo-immune)
    candidate_texts = [c[1] for c in candidates]
    scores = _batch_score(candidate_texts, "corrections", _CORRECTION_TEMPLATES)

    # Phase 3: Threshold and extract
    for (idx, text, prev_asst), score in zip(candidates, scores):
        if score < 0.35:
            continue

        # Extract preference: strip leading negation noise
        preference = re.sub(r"^(?:no[,.\s]+)+", "", text, flags=re.I).strip()

        key = preference[:50].lower()
        if key in seen or len(preference) < 10:
            continue
        seen.add(key)

        corrections.append(
            Correction(
                user_said=text[:300],
                preference=preference[:300],
                context=prev_asst,
                timestamp=flow[idx].timestamp,
            )
        )

    return corrections


_CONFIRM_PATTERN = re.compile(
    r"^(yes|yeah|yep|ok|sure|do it|go ahead|lets? do|go with|proceed|approved?|confirmed?)\b",
    re.I,
)
# "use X instead" is bounded to one sentence: the greedy form matched from a
# "use" in one sentence to an "instead" three sentences later (2026-09-25).
_REDIRECT_PATTERN = re.compile(
    r"^(no|don'?t|stop|not that|instead|actually|switch to|use [^.!?\n]{1,80} instead|change [^.!?\n]{1,80} to)\b",
    re.I,
)
_EXPLICIT_DECISION_PATTERN = re.compile(
    r"(let'?s? (?:use|go with|switch to|do|try|change|make|keep)|from now on|always use|never use|we should|go with|"
    r"use [^.!?\n]{1,80} instead)",
    re.I,
)


def _extract_decisions_structural(flow: list[FlowMessage]) -> list[Decision]:
    """
    Extract decisions from conversation flow using structural patterns.

    Primary: conversation structure (no scorer needed)
      - User confirms assistant's proposal → decision is the proposal
      - User redirects with "no, do X" → decision is the redirect
      - User makes explicit choice → decision is the choice

    Secondary: semantic scoring as bonus (needs scorer)
    """
    decisions = []
    seen = set()

    from claude_engram.mining.decision_gate import looks_like_decision

    def _add(content, ts, files, confidence, source, reasoning=""):
        key = content[:50].lower()
        if key in seen or len(content) < 10:
            return
        if not looks_like_decision(content):
            return  # a count, a question, an acknowledgement, a status line
        seen.add(key)
        decisions.append(
            Decision(
                content=content,
                reasoning=reasoning,
                timestamp=ts,
                source=source,
                related_files=files,
                confidence=confidence,
            )
        )

    # Phase 1: Structural detection (works without scorer)
    for i, fm in enumerate(flow):
        if fm.msg_type != "user" or not fm.user_text:
            continue
        text = fm.user_text.strip()
        if not _typed_prompt(text):
            continue

        # Find preceding assistant message
        prev_proposal = ""
        prev_files = []
        for j in range(i - 1, max(i - 4, -1), -1):
            pf = flow[j]
            if pf.msg_type == "assistant":
                for t in pf.assistant_texts:
                    if len(t) > 30 and not t.startswith("<"):
                        prev_proposal = t[:200]
                        break
                prev_files = pf.file_edits
                break

        # Pattern A: User confirms assistant proposal (must be substantive)
        if _CONFIRM_PATTERN.match(text) and prev_proposal and len(prev_proposal) > 50:
            _add(
                f"(confirmed) {prev_proposal}",
                fm.timestamp,
                prev_files,
                0.7,
                "confirmation",
            )

        # Pattern B: User redirects
        elif _REDIRECT_PATTERN.match(text) and len(text) > 10:
            _add(
                _summarize_decision(text, _REDIRECT_PATTERN),
                fm.timestamp,
                prev_files,
                0.75,
                "redirect",
            )

        # Pattern C: Explicit decision language
        elif _EXPLICIT_DECISION_PATTERN.search(text):
            _add(
                _summarize_decision(text, _EXPLICIT_DECISION_PATTERN),
                fm.timestamp,
                prev_files,
                0.8,
                "explicit",
            )

    # Phase 2: Semantic scoring as bonus (catches decisions structural misses).
    # Scored as a MARGIN over the non-decision templates: a bare cosine of
    # 0.55 to the decision templates is where most short text sits under a
    # modern encoder, and the old question filter (`rstrip("?").endswith("?")`)
    # could never be true -- 636 mined "decisions" in eight days (2026-09-22).
    semantic_candidates = []
    for i, fm in enumerate(flow):
        if fm.msg_type == "user" and fm.user_text:
            text = fm.user_text.strip()
            if 15 < len(text) and _typed_prompt(text) and "?" not in text:
                semantic_candidates.append((text, fm.timestamp))

    if semantic_candidates:
        texts = [c[0] for c in semantic_candidates]
        scores = _batch_score(texts, "decisions", _DECISION_TEMPLATES)
        non_scores = _batch_score(texts, "non_decisions", _NON_DECISION_TEMPLATES)
        for (text, ts), score, non in zip(semantic_candidates, scores, non_scores):
            if score >= 0.55 and score - non >= MINED_DECISION_MARGIN:
                _add(
                    _summarize_decision(text),
                    ts,
                    [],
                    score,
                    "semantic",
                )

    return decisions


def _extract_approaches_structural(flow: list[FlowMessage]) -> list[Approach]:
    """
    Extract approach changes from file edit patterns.

    Patterns:
    1. Same file edited 3+ times = struggle → look for what changed
    2. Error → different file edited = approach switch
    3. Assistant uses different tool after error = technique switch
    """
    approaches = []

    # Track file edit sequences
    file_edit_runs: dict[str, list[int]] = {}  # file → [flow indices]
    for i, fm in enumerate(flow):
        for fp in fm.file_edits:
            file_edit_runs.setdefault(fp, []).append(i)

    # Find struggle files (3+ edits)
    for fp, indices in file_edit_runs.items():
        if len(indices) < 3:
            continue

        # Check if there were errors between edits
        error_between = False
        for idx in range(indices[0], indices[-1]):
            if idx < len(flow) and flow[idx].has_error:
                error_between = True
                break

        if error_between:
            # Look for what the assistant said after the last edit
            last_idx = indices[-1]
            context = ""
            for j in range(last_idx, min(last_idx + 3, len(flow))):
                if flow[j].msg_type == "assistant" and flow[j].assistant_texts:
                    context = _first_sentence(flow[j].assistant_texts[0], max_len=150)
                    break

            from pathlib import Path

            approaches.append(
                Approach(
                    tried=f"Multiple edits to {Path(fp).name} ({len(indices)} times)",
                    result="struggled" if error_between else "worked",
                    switched_to=context,
                    timestamp=flow[indices[0]].timestamp,
                    related_files=[fp],
                )
            )

    # Error → different file pattern
    for i, fm in enumerate(flow):
        if not fm.has_error:
            continue
        # Look ahead: does the assistant edit a DIFFERENT file next?
        prev_files = set()
        for j in range(max(0, i - 3), i):
            prev_files.update(flow[j].file_edits)
        for j in range(i + 1, min(i + 4, len(flow))):
            new_files = set(flow[j].file_edits) - prev_files
            if new_files:
                from pathlib import Path

                old = (
                    ", ".join(Path(f).name for f in prev_files)
                    if prev_files
                    else "previous approach"
                )
                new = ", ".join(Path(f).name for f in new_files)
                approaches.append(
                    Approach(
                        tried=f"Editing {old}",
                        result="error",
                        switched_to=f"Moved to {new}",
                        timestamp=fm.timestamp,
                        related_files=list(prev_files | new_files),
                    )
                )
                break

    return approaches


# ─── Helpers ─────────────────────────────────────────────────────────────


# Openers that announce an intention instead of stating a resolution. A "fix"
# mined from one of these gets replayed at the next matching error as if it were
# advice — the stored fix for a real recurring FileNotFoundError was literally
# "Let me check the correct path:".
_NARRATION_OPENERS = (
    "let me",
    "let's",
    "lets ",
    "i'll",
    "i will",
    "i need to",
    "i'm going to",
    "im going to",
    "now let",
    "first,",
    "next,",
    "looking at",
    "checking",
    "let me check",
    "ok,",
    "okay,",
    "right,",
    "hmm",
    "the issue is clear",
)


def _is_narration(text: str) -> bool:
    """True when a sentence announces what the assistant is about to do rather
    than what resolved the error. Trailing ':' is the strongest tell — it is a
    lead-in to a tool call, never a conclusion."""
    t = text.strip().lower()
    if not t:
        return True
    if t.endswith(":"):
        return True
    return any(t.startswith(p) for p in _NARRATION_OPENERS)


def _first_sentence(text: str, max_len: int = 150) -> str:
    """Extract the first meaningful sentence from text."""
    text = text.strip()
    # Find first sentence-ending punctuation
    for end in [". ", ".\n", "!\n", "! ", ":\n"]:
        idx = text.find(end)
        if 10 < idx < max_len:
            return text[: idx + 1].strip()
    return text[:max_len].strip()


def _summarize_decision(text: str, pattern: "re.Pattern | None" = None) -> str:
    """The sentence to store. With a pattern, the sentence the pattern
    matched: a two-sentence prompt was stored whole, or by its FIRST
    sentence, while the decision sat in the second (2026-09-25). Without
    one, the text when it is short, else its first sentence of a usable
    length."""
    text = text.strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
    if pattern is not None:
        for s in sentences:
            if 10 < len(s) < 200 and pattern.search(s):
                return s
    # If short enough, use as-is
    if len(text) <= 150:
        return text

    # Try to find the decision sentence
    for s in sentences:
        if len(s) > 15 and len(s) < 200:
            return s

    return text[:150]


def _extract_reasoning_from_text(text: str) -> str:
    """Extract reasoning from a text block."""
    patterns = [
        re.compile(r"(?:because|since|as)\s+(.{10,150})", re.I),
        re.compile(r"(?:to avoid|to prevent|to fix)\s+(.{10,100})", re.I),
        re.compile(r"(?:the reason|this is because)\s+(.{10,120})", re.I),
    ]
    for p in patterns:
        m = p.search(text)
        if m:
            return m.group(1).strip()[:150]
    return ""


# ─── Pipeline ────────────────────────────────────────────────────────────


def _live_messages(jsonl_file) -> list[dict]:
    """The user and assistant messages on the transcript's LIVE branch. A
    rewind leaves the abandoned turns in the file (append-only, the next
    prompt forks off an earlier record), and the miner had mined them as
    history: a decision the user rewound past was stored as decided
    (2026-09-26). A subagent's inline sidechain records are kept; a record
    with no uuid is kept."""
    from claude_engram.mining.jsonl_reader import iter_messages
    from claude_engram.transcript_chain import chain_of

    # The chain is built over EVERY record with a uuid: it runs through the
    # system and attachment records between turns.
    everything = [msg for _, msg in iter_messages(jsonl_file)]
    live = chain_of(m for m in everything if m.get("uuid"))
    messages = [m for m in everything if m.get("type") in ("user", "assistant")]
    if not live:
        return messages
    return [m for m in messages if m.get("isSidechain") or not m.get("uuid") or m["uuid"] in live]


def run_extraction_pipeline(
    project_path: str,
    index,  # SessionIndex
    engram_storage_dir: str = "~/.claude_engram",
) -> int:
    """
    Run all extractors on unprocessed sessions.

    Returns count of new extractions.
    """
    import json
    from pathlib import Path
    from claude_engram.mining.jsonl_reader import (
        resolve_jsonl_dir,
        iter_messages,
    )

    _fed_projects.clear()

    jsonl_dir = resolve_jsonl_dir(project_path)
    if not jsonl_dir:
        return 0

    storage = Path(engram_storage_dir).expanduser()
    manifest_path = storage / "manifest.json"
    if not manifest_path.exists():
        return 0

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    norm_path = str(Path(project_path).resolve()).replace("\\", "/")
    if len(norm_path) >= 2 and norm_path[1] == ":":
        norm_path = norm_path[0].lower() + norm_path[1:]

    proj_info = manifest.get("projects", {}).get(norm_path)
    if not proj_info:
        return 0

    hash_dir = storage / "projects" / proj_info["hash"]
    extractions_dir = hash_dir / "extractions"
    extractions_dir.mkdir(parents=True, exist_ok=True)

    # Check scorer availability once before the loop
    scorer_available = False
    try:
        from claude_engram.hooks.scorer_server import embed_via_server

        scorer_available = bool(embed_via_server("test"))
    except Exception:
        pass

    total_extractions = 0

    for session_id, session_meta in index.sessions.items():
        extraction_file = extractions_dir / f"{session_id}.json"
        previous = None

        if extraction_file.exists():
            try:
                existing = json.loads(extraction_file.read_text(encoding="utf-8"))
                previous = existing
                had_scorer = existing.get("scorer_available", False)
                has_content = any(
                    existing.get(k)
                    for k in ("decisions", "mistakes", "approaches", "corrections")
                )
                # A session that GREW since extraction (PreCompact then
                # SessionEnd, or resumed days later) is re-extracted whole —
                # the file is a full per-session overwrite, so this is
                # idempotent. Old extraction files lack the counter; they
                # keep the legacy skip behavior until a reindex.
                expected_main = int(session_meta.get("user_message_count", 0)) + int(
                    session_meta.get("assistant_message_count", 0)
                )
                stored_main = existing.get("main_message_count")
                grown = stored_main is not None and expected_main > int(stored_main)
                if not grown:
                    # Skip if: has content AND (scorer was available OR still isn't)
                    # Reprocess if: scorer is now available but wasn't during
                    # the original extraction
                    if has_content and (had_scorer or not scorer_available):
                        continue
                    # Skip empty files from genuinely empty sessions (< 10 messages)
                    if not has_content and existing.get("message_count", 999) < 10:
                        continue
            except Exception:
                pass

        jsonl_file = jsonl_dir / session_meta.get("jsonl_file", "")
        if not jsonl_file.exists():
            continue

        messages = _live_messages(jsonl_file)
        main_message_count = len(messages)

        session_dir = jsonl_dir / session_meta.get("jsonl_file", "").replace(
            ".jsonl", ""
        )
        subagents_dir = session_dir / "subagents"
        if subagents_dir.exists():
            for sub_jsonl in subagents_dir.glob("*.jsonl"):
                for _, msg in iter_messages(sub_jsonl, types={"user", "assistant"}):
                    messages.append(msg)

        if not messages:
            # Mark genuinely empty sessions so we don't re-parse their JSONL every run
            extraction_file.write_text(
                json.dumps(
                    {
                        "message_count": 0,
                        "main_message_count": 0,
                        "scorer_available": scorer_available,
                    }
                ),
                encoding="utf-8",
            )
            continue

        extractions = extract_all(messages)
        extractions.session_id = session_id

        count = (
            len(extractions.decisions)
            + len(extractions.mistakes)
            + len(extractions.approaches)
            + len(extractions.corrections)
        )

        extraction_data = asdict(extractions)
        extraction_data["scorer_available"] = scorer_available
        extraction_data["message_count"] = len(messages)
        extraction_data["main_message_count"] = main_message_count

        # Always write — even if count is 0. The scorer_available flag
        # lets us know whether to retry when scorer comes back.
        tmp = extraction_file.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(extraction_data, indent=2, default=str), encoding="utf-8"
        )
        tmp.replace(extraction_file)

        total_extractions += count

        # Feed only what this pass ADDED. A grown session is re-extracted
        # whole, and the store's dedupe is per project: when 0.8.52 moved
        # the destination of a no-file entry to the sub-project the
        # session's edits name, one live tick re-stored 347 entries there
        # that the root store already held (2026-09-24).
        fresh = _fresh_extractions(extractions, previous)
        if fresh.decisions or fresh.mistakes or fresh.approaches or fresh.corrections:
            _feed_to_memory_store(project_path, fresh, engram_storage_dir)

    return total_extractions


def _extraction_key(kind: str, item) -> tuple:
    get = item.get if isinstance(item, dict) else (lambda k, d="": getattr(item, k, d))
    text = {"decisions": "content", "mistakes": "description", "approaches": "tried", "corrections": "preference"}[kind]
    return (kind, str(get(text, "") or ""), str(get("timestamp", "") or ""))


def _fresh_extractions(extractions: SessionExtractions, previous: Optional[dict]) -> SessionExtractions:
    """The extractions not present in the session's previous extraction
    file (matched by kind, text and message timestamp). With no previous
    file everything is fresh: the first mine of a session feeds it all."""
    if not previous:
        return extractions
    seen: set[tuple] = set()
    for kind in ("decisions", "mistakes", "approaches", "corrections"):
        for item in previous.get(kind) or []:
            if isinstance(item, dict):
                seen.add(_extraction_key(kind, item))
    fresh = SessionExtractions(
        session_id=extractions.session_id,
        session_files=list(extractions.session_files),
        summary=extractions.summary,
        extracted_at=extractions.extracted_at,
    )
    fresh.decisions = [d for d in extractions.decisions if _extraction_key("decisions", d) not in seen]
    fresh.mistakes = [m for m in extractions.mistakes if _extraction_key("mistakes", m) not in seen]
    fresh.approaches = [a for a in extractions.approaches if _extraction_key("approaches", a) not in seen]
    fresh.corrections = [c for c in extractions.corrections if _extraction_key("corrections", c) not in seen]
    return fresh


def projects_fed_last_run() -> list[str]:
    """Projects that received mined entries since the last pipeline start.

    Mined entries go in with ``auto_embed=False`` (bulk insert), so somebody has
    to embed them afterwards or the vector half of hybrid_search stays empty
    forever. The miner is the only process allowed to do that work, and it only
    knows WHICH projects to embed because attribution routes entries to
    sub-projects. background.run_mining reads this right after extraction.
    """
    return sorted(_fed_projects)


def _feed_to_memory_store(
    project_path: str,
    extractions: SessionExtractions,
    engram_storage_dir: str,
):
    """Feed high-confidence extractions into MemoryStore."""
    try:
        from claude_engram.tools.memory import MemoryStore

        store = MemoryStore(storage_dir=engram_storage_dir)
        # Each entry is filed under the sub-project its files name, not the
        # session's cwd: a workspace-root session pooled every sibling's
        # mistakes in the root store (hooks/paths.target_project_for_files).
        from claude_engram.hooks.paths import target_project_for_files

        # Only a REGISTERED project can receive an entry. Marker-walking alone
        # sent files under a git worktree (E:/ws/trade-lab/.scratch/stack/... —
        # a `.git` FILE is a marker) to the worktree directory, which is not a
        # project anybody asks about, so the entries surfaced under whichever
        # store the walk happened to land in.
        known = list((store._manifest.get("projects", {}) or {}).keys())

        # An entry that names no file (a decision, a preference) is filed
        # where the SESSION's edits point, the same answer the prompt hook
        # gives through session_project: a workspace-root session had the
        # hook file a sentence under trade-lab and the miner file the same
        # sentence under the root (2026-09-24).
        session_files = list(extractions.session_files or [])

        def _target(files: list, content: str) -> str:
            dst = target_project_for_files(
                project_path, files or session_files, content, known_projects=known
            )
            if files and dst == project_path and session_files:
                # The entry's own files cast no vote (relative traceback
                # paths, files outside the root): the session's edits
                # decide, as for an entry with no files. Every mistake of
                # a sub-project worked from the workspace root had pooled
                # in the root store this way (2026-09-24).
                dst = target_project_for_files(
                    project_path, session_files, content, known_projects=known
                )
            _fed_projects.add(dst)
            return dst

        home = _target([], "")

        # One sentence, one entry. The prompt hook stores a typed sentence
        # live as "(from user) ...", sometimes under the cwd's project while
        # the miner routes by the session's edits; the miner then stored it
        # again as a decision and a third time as a preference (2026-09-25).
        # The store's own dedupe compares whole contents, and the prefixes
        # differ, so the comparison here is on the bare sentence, against
        # the destination store and its ancestors, and against what this
        # pass has already stored.
        from claude_engram.mining.decision_gate import bare

        def _bare_key(content: str) -> str:
            return " ".join(bare(content).lower().split())

        held_cache: dict[str, set[str]] = {}

        def _held(dst: str) -> set[str]:
            if dst not in held_cache:
                keys: set[str] = set()
                norm_dst = store._normalize_path(dst)
                for norm in known:
                    if norm == norm_dst or norm_dst.startswith(norm.rstrip("/") + "/"):
                        proj = store.get_project(norm)
                        for e in (proj.entries if proj else []):
                            if e.category == "decision":
                                keys.add(_bare_key(e.content))
                held_cache[dst] = keys
            return held_cache[dst]

        def _first_time(dst: str, content: str) -> bool:
            key = _bare_key(content)
            if not key:
                return False
            held = _held(dst)
            if key in held:
                return False
            # the hook cuts a long sentence at a word; a prefix of 30+ chars is the same sentence
            if len(key) >= 30 and any(k.startswith(key) or key.startswith(k) for k in held if len(k) >= 30):
                return False
            held.add(key)
            return True

        # High-confidence decisions
        for d in extractions.decisions:
            if d.confidence >= 0.6:
                content = f"DECISION: {d.content}"
                if d.reasoning:
                    content += f" (reason: {d.reasoning})"
                dst = _target(d.related_files, content)
                if not _first_time(dst, content):
                    continue
                store.remember_discovery(
                    dst,
                    content,
                    category="decision",
                    source="session_mining",
                    relevance=7,
                    related_files=d.related_files,
                    auto_embed=False,
                )

        # Mistakes with clear error types
        for m in extractions.mistakes:
            if m.error_type:
                content = f"MISTAKE: {m.description}"
                if m.fix:
                    content += f" — Fix: {m.fix}"
                store.remember_discovery(
                    _target(m.related_files, content),
                    content,
                    category="mistake",
                    source="session_mining",
                    relevance=8,
                    related_files=m.related_files,
                    auto_embed=False,
                )

        # User corrections, judged by the function the prompt hook uses on a
        # typed prompt (hooks/intent.capture_decision): one rule for a
        # sentence wherever it was seen. Server-only for the scorer: this
        # runs inside the MCP server, which must not load a second model.
        # The substring list this replaced matched "not" inside "note" and
        # "use" inside "because", so every short reply qualified (2026-09-22).
        from claude_engram.hooks.intent import capture_decision

        for c in extractions.corrections:
            kept = capture_decision(c.preference, server_only=True)
            if kept and _first_time(home, f"USER PREFERENCE: {kept}"):
                store.remember_discovery(
                    home,
                    f"USER PREFERENCE: {kept}",
                    category="decision",
                    source="session_mining",
                    relevance=7,
                    auto_embed=False,
                )

    except Exception:
        pass
