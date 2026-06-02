"""
Injection outcome log — Capability 6 (instrumentation).

Records what the pre-edit hook injected (memory / prediction / precheck /
blast) and the test outcomes that followed, so injection precision becomes
*measurable*
instead of assumed. ``reflect()`` correlates each test outcome with the
injection kinds that preceded it in the same session, surfacing which channels
earn their tokens — the thing that keeps proactive injection from decaying into
skimmed noise.

This is the measurement foundation; on its own it changes no live behaviour.
Tuning the scorer from this signal is the deliberate, conservative next step.

Single global log keyed by session_id (correlation is session-scoped, and
sessions are workspace-pooled), so it sidesteps the sub-project-vs-cwd project
mismatch between the edit hook and the bash hook. Bounded ring, atomic write,
degrades to silence. Under two concurrent sessions the last writer can drop a
few events — tolerable for a precision metric.

Storage: ~/.claude_engram/injection_outcomes.json
"""

import json
from pathlib import Path

MAX_EVENTS = 1000

# "context" was the single coarse injection kind before v0.6 split it into
# "memory" + "prediction". Live logging no longer emits it; only stale entries
# already in the global ring still carry it, so it's flagged as legacy in the
# human-readable summary (it self-heals as the bounded ring rolls over).
_LEGACY_KINDS = {"context"}


class OutcomeLog:
    VERSION = 1

    def __init__(self, path: Path):
        self._path = path
        self._data = {"version": self.VERSION, "events": []}
        self._dirty = False
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

    def save(self):
        if not self._dirty:
            return
        events = self._data.get("events", [])
        if len(events) > MAX_EVENTS:
            self._data["events"] = events[-MAX_EVENTS:]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._data), encoding="utf-8")
        tmp.replace(self._path)
        self._dirty = False

    def record_injection(
        self, file: str, kinds: list, session_id: str = "", ts: float = 0.0
    ):
        if not kinds:
            return
        self._data.setdefault("events", []).append(
            {
                "t": "inj",
                "file": file,
                "kinds": list(kinds),
                "sid": session_id,
                "ts": ts,
            }
        )
        self._dirty = True

    def record_outcome(
        self, passed: bool, session_id: str = "", file: str = "", ts: float = 0.0
    ):
        self._data.setdefault("events", []).append(
            {
                "t": "out",
                "passed": bool(passed),
                "sid": session_id,
                "file": file,
                "ts": ts,
            }
        )
        self._dirty = True

    def reflect(self) -> dict:
        """Correlate each outcome with the injection kinds that preceded it in
        the same session (since that session's previous outcome). Per kind:
        ``injected`` (times surfaced), ``before_pass`` / ``before_fail``
        (distinct outcomes it preceded)."""
        events = self._data.get("events", [])
        pending: dict = {}  # sid -> set(kinds) since last outcome
        per_kind: dict = {}
        total_inj = 0
        passes = fails = 0

        def slot(k):
            return per_kind.setdefault(
                k, {"injected": 0, "before_pass": 0, "before_fail": 0}
            )

        for e in events:
            sid = e.get("sid", "")
            if e.get("t") == "inj":
                for k in e.get("kinds", []):
                    slot(k)["injected"] += 1
                    total_inj += 1
                pending.setdefault(sid, set()).update(e.get("kinds", []))
            elif e.get("t") == "out":
                passed = e.get("passed", False)
                if passed:
                    passes += 1
                else:
                    fails += 1
                field = "before_pass" if passed else "before_fail"
                for k in pending.get(sid, set()):
                    slot(k)[field] += 1
                pending[sid] = set()

        return {
            "events": len(events),
            "total_injections": total_inj,
            "outcomes": {"pass": passes, "fail": fails},
            "per_kind": per_kind,
        }


def _log_path() -> Path:
    from claude_engram.hooks.paths import get_engram_storage_dir

    return get_engram_storage_dir() / "injection_outcomes.json"


def record_injection(file: str, kinds: list, session_id: str = "", ts: float = 0.0):
    try:
        log = OutcomeLog(_log_path())
        log.record_injection(file, kinds, session_id, ts)
        log.save()
    except Exception:
        pass


def record_outcome(passed: bool, session_id: str = "", file: str = "", ts: float = 0.0):
    try:
        log = OutcomeLog(_log_path())
        log.record_outcome(passed, session_id, file, ts)
        log.save()
    except Exception:
        pass


def reflect() -> dict:
    try:
        return OutcomeLog(_log_path()).reflect()
    except Exception:
        return {
            "events": 0,
            "total_injections": 0,
            "outcomes": {"pass": 0, "fail": 0},
            "per_kind": {},
        }


def format_reflection(r: dict) -> str:
    """Human-readable injection-precision summary."""
    if not r or not r.get("events"):
        return "No injection outcomes logged yet (edit + run tests to populate)."
    lines = [
        f"Injection precision over {r['events']} logged events "
        f"({r['total_injections']} injections; "
        f"{r['outcomes']['pass']} passing / {r['outcomes']['fail']} failing tests):"
    ]
    per_kind = r.get("per_kind", {})
    for kind in sorted(per_kind, key=lambda k: -per_kind[k]["injected"]):
        s = per_kind[kind]
        seen = s["before_pass"] + s["before_fail"]
        rate = (
            f"{(s['before_pass'] / seen * 100):.0f}% pre-pass"
            if seen
            else "no test yet"
        )
        label = f"{kind} (legacy, pre-split)" if kind in _LEGACY_KINDS else kind
        lines.append(
            f"  {label}: injected {s['injected']} | preceded {s['before_pass']} pass, "
            f"{s['before_fail']} fail ({rate})"
        )
    return "\n".join(lines)
