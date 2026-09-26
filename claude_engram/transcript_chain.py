"""The live branch of a Claude Code transcript.

A rewind (Esc Esc, /rewind) fires no hook and writes no record. The
transcript is append-only: the abandoned turns stay in the file and the
next prompt is appended with the parentUuid of the record the user rewound
to, so a rewind shows only as a FORK. Everything engram derives from the
transcript (the checkpoint to restore, the decisions to mine) has to follow
the live chain: the walk from the last record up its parent links. Measured
on a real rewind, 2026-09-26: after "restore code and conversation" the file
on disk was back at the earlier version while the ring's newest checkpoint,
saved on the abandoned branch under the same session id, was still returned
by checkpoint_restore.

Stdlib only: the hooks import this under `python -S`.
"""

from __future__ import annotations

import glob
import json
import os
import re
from pathlib import Path
from typing import Iterable, Optional

_TASK_ID = re.compile(rb"task_id: (task_\d+)")
# The banner reads the tail only: a hook has 1-2 s, a transcript can be
# hundreds of MB, and a rewind concerns the recent turns by nature. Within
# the window the answer is exact: a record's parent is always earlier in
# the file, so every live record inside the window is reached before the
# walk leaves it.
TAIL_BYTES = 8_000_000


def _tail_lines(path: str | Path, tail_bytes: Optional[int]) -> list[bytes]:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if tail_bytes is not None and size > tail_bytes:
                fh.seek(size - tail_bytes)
                fh.readline()  # drop the partial line
            data = fh.read()
    except Exception:
        return []
    return data.splitlines()


def _records(path: str | Path, tail_bytes: Optional[int]) -> list[tuple[bytes, dict]]:
    """Every record with a uuid, in file order. The chain runs through the
    system and attachment records too (a prompt's parent is often the
    previous turn's turn_duration record), so no type is skipped here."""
    out = []
    for raw in _tail_lines(path, tail_bytes):
        if b'"uuid"' not in raw:
            continue
        try:
            d = json.loads(raw)
        except Exception:
            continue
        if isinstance(d, dict) and d.get("uuid"):
            out.append((raw, d))
    return out


def chain_of(records: Iterable[dict]) -> Optional[set]:
    """The uuids on the live branch of ``records`` (every main-chain record
    with a uuid, file order; system and attachment records included, since
    the chain runs through them): from the last user or assistant record up
    its parentUuid links. A record whose parent is not among the records
    ends the walk. None when there are no records to walk."""
    parent: dict = {}
    last = None
    for d in records:
        if d.get("isSidechain"):
            continue  # a subagent's chain, not this conversation's
        parent[d["uuid"]] = d.get("parentUuid")
        if d.get("type") in ("user", "assistant"):
            last = d["uuid"]
    if last is None:
        return None
    live = set()
    cur = last
    while cur and cur not in live:
        live.add(cur)
        cur = parent.get(cur)
    return live


def live_chain(path: str | Path, tail_bytes: Optional[int] = None) -> Optional[set]:
    """The uuids on the live branch of the transcript at ``path`` (the whole
    file by default; ``tail_bytes`` bounds the read for a hook). None when
    the file cannot be read or holds no chain."""
    recs = _records(path, tail_bytes)
    return chain_of(d for _raw, d in recs) if recs else None


_SAVE_OPS = ("checkpoint_save", "handoff_create")


def branch_checkpoints(path: str | Path, tail_bytes: Optional[int] = None) -> tuple[set, set]:
    """(task ids SAVED on the live branch, task ids saved anywhere in the
    file): the ``task_id: task_N`` a checkpoint_save result printed, matched
    to its tool call by id. A checkpoint_restore result quotes a task id too
    (the first live read counted a rewound checkpoint as live because the
    later restore, on the live branch, printed its id)."""
    recs = _records(path, tail_bytes)
    live = chain_of(d for _raw, d in recs) or set()
    saves: set = set()
    for _raw, d in recs:
        if d.get("type") != "assistant":
            continue
        content = (d.get("message") or {}).get("content")
        for block in content if isinstance(content, list) else []:
            if (isinstance(block, dict) and block.get("type") == "tool_use"
                    and str(block.get("name") or "").endswith("context")
                    and (block.get("input") or {}).get("operation") in _SAVE_OPS):
                saves.add(block.get("id"))
    on_branch: set = set()
    everywhere: set = set()
    for raw, d in recs:
        if d.get("type") != "user" or b"task_id: task_" not in raw:
            continue
        content = (d.get("message") or {}).get("content")
        for block in content if isinstance(content, list) else []:
            if not (isinstance(block, dict) and block.get("type") == "tool_result" and block.get("tool_use_id") in saves):
                continue
            for m in _TASK_ID.finditer(json.dumps(block).encode()):
                tid = m.group(1).decode()
                everywhere.add(tid)
                if d["uuid"] in live:
                    on_branch.add(tid)
    return on_branch, everywhere


def rewound_away(entry: dict, path: str | Path | None, tail_bytes: Optional[int] = TAIL_BYTES) -> bool:
    """True when the ring entry's save is in this transcript but NOT on its
    live branch: the user rewound past it. An entry the transcript never
    saved (an auto checkpoint from a hook, a save from another session, a
    transcript that cannot be read) is not judged."""
    tid = str((entry or {}).get("task_id") or "")
    if not tid or not path:
        return False
    try:
        on_branch, everywhere = branch_checkpoints(path, tail_bytes)
    except Exception:
        return False
    return tid in everywhere and tid not in on_branch


def transcript_for_session(session_id: str) -> Optional[Path]:
    """The transcript Claude Code writes for a session id, wherever its
    project dir is (~/.claude/projects/<slug>/<session_id>.jsonl)."""
    sid = str(session_id or "").strip()
    if not sid:
        return None
    root = Path.home() / ".claude" / "projects"
    hits = glob.glob(str(root / "*" / f"{sid}.jsonl"))
    return Path(hits[0]) if hits else None
