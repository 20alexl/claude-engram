"""
Extractors — mine decisions, mistakes, approaches, and corrections from sessions.

Three-layer extraction:
  1. Structural — conversation flow patterns (most robust, typo-immune)
  2. Semantic  — AllMiniLM scoring against templates (typo-immune, 5-25ms/call)
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
    summary: str = ""
    extracted_at: float = 0.0


# ─── Semantic scorer (AllMiniLM) ──────────────────────────────────────────

# Templates for semantic classification. AllMiniLM compares message embeddings
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
]

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
    """Get cached template embeddings via AllMiniLM scorer server."""
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
    """Batch embed texts via AllMiniLM scorer server. Single TCP call."""
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
    Batch score texts against templates using AllMiniLM.

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
        key = f"{error_type}:{error_msg[:60]}"

        if key in seen:
            continue
        seen.add(key)

        # Look ahead for the fix (next assistant message)
        fix = ""
        related_files = []
        for j in range(i + 1, min(i + 4, len(flow))):
            if flow[j].msg_type == "assistant":
                # Check if assistant acknowledges and fixes
                for text in flow[j].assistant_texts:
                    if len(text) > 20:
                        # Concise fix description from first sentence
                        fix = _first_sentence(text, max_len=150)
                        break
                related_files = flow[j].file_edits
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
        if len(text) < 5 or len(text) > 500:
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


def _extract_decisions_structural(flow: list[FlowMessage]) -> list[Decision]:
    """
    Extract decisions from conversation flow.

    Patterns:
    1. User explicitly states a choice ("let's use X", "go with Y")
    2. Assistant switches approach after discussion
    3. Semantic scoring against decision templates
    """
    decisions = []
    seen = set()

    # Phase 1: Structural pre-filter — find candidate texts
    candidates = []  # (text, source, timestamp, files, reasoning)

    for i, fm in enumerate(flow):
        # User messages: directive messages (not questions, not tool results)
        if fm.msg_type == "user" and fm.user_text:
            text = fm.user_text.strip()
            if 15 < len(text) < 500 and not text.rstrip("?").endswith("?"):
                candidates.append((text, "user", fm.timestamp, [], ""))

        # Assistant thinking blocks only (much rarer, high signal)
        # Skip assistant text — too many messages, low decision density
        elif fm.msg_type == "assistant":
            for thought in fm.thinking:
                if len(thought) > 50:
                    candidates.append(
                        (
                            thought[:300],
                            "thinking",
                            fm.timestamp,
                            fm.file_edits,
                            _extract_reasoning_from_text(thought),
                        )
                    )

    if not candidates:
        return []

    # Phase 2: Batch semantic scoring (one pass)
    candidate_texts = [c[0] for c in candidates]
    scores = _batch_score(candidate_texts, "decisions", _DECISION_TEMPLATES)

    # Phase 3: Threshold and extract
    for (text, source, ts, files, reasoning), score in zip(candidates, scores):
        threshold = 0.5 if source == "user" else 0.6
        confidence_factor = (
            1.0 if source == "user" else (0.9 if source == "thinking" else 0.8)
        )

        if score < threshold:
            continue

        content = _summarize_decision(text)
        key = content[:50].lower()
        if key in seen:
            continue
        seen.add(key)

        decisions.append(
            Decision(
                content=content,
                reasoning=reasoning,
                timestamp=ts,
                source=source,
                related_files=files,
                confidence=min(score * confidence_factor, 1.0),
            )
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


def _first_sentence(text: str, max_len: int = 150) -> str:
    """Extract the first meaningful sentence from text."""
    text = text.strip()
    # Find first sentence-ending punctuation
    for end in [". ", ".\n", "!\n", "! ", ":\n"]:
        idx = text.find(end)
        if 10 < idx < max_len:
            return text[: idx + 1].strip()
    return text[:max_len].strip()


def _summarize_decision(text: str) -> str:
    """Extract a concise decision statement from text."""
    text = text.strip()
    # If short enough, use as-is
    if len(text) <= 150:
        return text

    # Try to find the decision sentence
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for s in sentences:
        s = s.strip()
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

        if extraction_file.exists():
            try:
                existing = json.loads(extraction_file.read_text(encoding="utf-8"))
                had_scorer = existing.get("scorer_available", False)
                has_content = any(
                    existing.get(k)
                    for k in ("decisions", "mistakes", "approaches", "corrections")
                )
                # Skip if: has content AND (scorer was available OR still isn't)
                # Reprocess if: scorer is now available but wasn't during original extraction
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

        messages = []
        for _, msg in iter_messages(jsonl_file, types={"user", "assistant"}):
            messages.append(msg)

        session_dir = jsonl_dir / session_meta.get("jsonl_file", "").replace(".jsonl", "")
        subagents_dir = session_dir / "subagents"
        if subagents_dir.exists():
            for sub_jsonl in subagents_dir.glob("*.jsonl"):
                for _, msg in iter_messages(sub_jsonl, types={"user", "assistant"}):
                    messages.append(msg)

        if not messages:
            # Mark genuinely empty sessions so we don't re-parse their JSONL every run
            extraction_file.write_text(
                json.dumps({"message_count": 0, "scorer_available": scorer_available}),
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

        # Always write — even if count is 0. The scorer_available flag
        # lets us know whether to retry when scorer comes back.
        tmp = extraction_file.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(extraction_data, indent=2, default=str), encoding="utf-8"
        )
        tmp.replace(extraction_file)

        total_extractions += count

        if count > 0:
            _feed_to_memory_store(project_path, extractions, engram_storage_dir)

    return total_extractions


def _feed_to_memory_store(
    project_path: str,
    extractions: SessionExtractions,
    engram_storage_dir: str,
):
    """Feed high-confidence extractions into MemoryStore."""
    try:
        from claude_engram.tools.memory import MemoryStore

        store = MemoryStore(storage_dir=engram_storage_dir)

        # High-confidence decisions
        for d in extractions.decisions:
            if d.confidence >= 0.6:
                content = f"DECISION: {d.content}"
                if d.reasoning:
                    content += f" (reason: {d.reasoning})"
                store.remember_discovery(
                    project_path,
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
                    project_path,
                    content,
                    category="mistake",
                    source="session_mining",
                    relevance=8,
                    related_files=m.related_files,
                    auto_embed=False,
                )

        # User corrections with clear directives
        for c in extractions.corrections:
            pref = c.preference.lower()
            has_directive = any(
                w in pref
                for w in [
                    "don't",
                    "dont",
                    "stop",
                    "never",
                    "always",
                    "should",
                    "want",
                    "need",
                    "prefer",
                    "use",
                    "not",
                    "instead",
                ]
            )
            if has_directive and len(c.preference) > 15:
                store.remember_discovery(
                    project_path,
                    f"USER PREFERENCE: {c.preference[:200]}",
                    category="decision",
                    source="session_mining",
                    relevance=7,
                    auto_embed=False,
                )

    except Exception:
        pass
