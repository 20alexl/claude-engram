"""Context pressure: distance to the compaction point, and the nudges keyed on it.

Hooks receive no context-usage figures. The statusline does: on every update
it gets ``context_window.total_input_tokens`` and ``context_window_size``
(verified against the statusline docs, Claude Code 2.1.267). So the statusline
script mirrors those numbers to a per-session file -- the same pattern as the
``CLAUDE_ENGRAM_LAST_FILE_PATH`` mirror -- and the hooks read the mirror and
compute how far the session is from the point where auto-compaction fires.

Everything is a DISTANCE to the compaction point, never a raw percent. The
statusline's ``used_percentage`` is against the full window (200K or 1M), but
compaction does not fire at 100%: with nothing configured a 200K model compacts
at the 200K boundary and a native-1M model at about 967K (model-config docs).
``CLAUDE_CODE_AUTO_COMPACT_WINDOW`` (env, wins over everything) and the
``autoCompactWindow`` setting move that point. A window set only by the
``--autocompact`` launch flag is invisible from here; the assessment falls back
to the model default and names its source so the reader knows.

Two nudges, once each per compaction cycle:

  heads-up     ~10% of the window before the point: finish the step, start
               nothing long.
  checkpoint   ~3% before the point (5% on a 200K window, where 3% is 6K
               tokens): write a deliberate ``checkpoint_save`` NOW.
               PreCompact's automatic entry stays as the floor for the case
               where the model doesn't.

Plus a cadence nudge every ``CADENCE_STOPS`` turns without a deliberate
checkpoint, so a long run banks checkpoints on a schedule and the
pre-compaction one is never the only one.

No statusline, or a statusline that never calls ``record_statusline()``, means
no signal. That is announced at session start (no statusLine configured) or
after a few silent minutes (configured but not recording) -- never silently
absent -- and the cadence nudge still runs.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

from .paths import get_engram_storage_dir

MIRROR_SUFFIX = ".ctx.json"

# "compact before the window fills, at about 967K tokens by default"
# (model-config docs, native-1M models). Approximate by the docs' own wording.
DEFAULT_COMPACT_1M = 967_000
SMALL_WINDOW = 200_000

HEADSUP_FRACTION = 0.10  # of the window, before the point
# Auto-compaction does not fire AT the configured number: Claude Code keeps
# room for the model's output first. Measured 2026-09-10 on a 1M Fable
# session with `autoCompactWindow` 750K: the auto compaction's own record
# (`compactMetadata.preTokens`) read 717,578 -- ~32K under the setting, the
# size of the maximum output. A "3% out" band (30K on 1M, 10K on 200K) sat
# inside that reserve and never fired; so the last band is an absolute
# distance above the measured trigger, not a fraction of the window.
OUTPUT_RESERVE = 32_000
CHECKPOINT_MARGIN = 20_000  # above the trigger: room for one checkpoint call
CHECKPOINT_MARGIN_SMALL = 10_000  # windows <= 200K
# Fallback only. The real trigger is the model's own "step done" (see
# milestones.py); this fires when a run goes this long with NEITHER a
# deliberate checkpoint NOR a completion claim -- which is closer to a stall
# signal than a save schedule.
CADENCE_STOPS = 60

# Subscription usage windows. A run that hits the 5-hour or weekly limit ends
# on an API error (StopFailure: rate_limit), which no Stop hook sees and which
# Claude Code does not retry -- the goal loop cannot save it. Said once per
# window, with the reset time, at these fractions of the window.
BUDGET_FIVE_HOUR_PCT = 90
BUDGET_SEVEN_DAY_PCT = 95

# A statusLine is configured but no mirror has appeared this long after the
# session started: the script is not calling record_statusline(). Say so once.
NOT_RECORDING_AFTER_SECS = 300

_ENV_MIN_WINDOW = 100_000  # the documented lower bound for the env var


# ---------------------------------------------------------------------------
# Mirror: statusline -> per-session file -> hooks
# ---------------------------------------------------------------------------


def mirror_path(session_id: str) -> Path:
    """Per-session mirror file, next to the per-session hook state."""
    return get_engram_storage_dir() / "sessions" / f"{session_id}{MIRROR_SUFFIX}"


def record_statusline(data: dict) -> Optional[Path]:
    """Mirror the statusline payload's context numbers to the session file.

    Called from a statusline script with the JSON Claude Code fed it. Returns
    the mirror path, or None when the payload names no session (nothing to key
    on) or the write failed. Never raises: a statusline must keep rendering.
    """
    try:
        sid = str(data.get("session_id") or "").strip()
    except Exception:
        return None
    if not sid:
        return None
    ctx = data.get("context_window") or {}
    model = data.get("model") or {}
    rec = {
        "session_id": sid,
        "ts": time.time(),
        "total_input_tokens": ctx.get("total_input_tokens"),
        "context_window_size": ctx.get("context_window_size"),
        "used_percentage": ctx.get("used_percentage"),
        "model_id": model.get("id", "") or "",
        "model_name": model.get("display_name", "") or "",
        "total_cost_usd": (data.get("cost") or {}).get("total_cost_usd"),
    }
    # Subscription usage windows (Claude.ai plans; absent on API keys):
    # rate_limits.five_hour / seven_day {used_percentage, resets_at}.
    rl = data.get("rate_limits") or {}
    for key, prefix in (("five_hour", "five_hour"), ("seven_day", "seven_day")):
        w = rl.get(key) or {}
        if isinstance(w, dict) and w.get("used_percentage") is not None:
            rec[f"{prefix}_pct"] = w.get("used_percentage")
            rec[f"{prefix}_resets_at"] = w.get("resets_at")
    path = mirror_path(sid)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(rec), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        return None
    return path


def read_mirror(session_id: str) -> Optional[dict]:
    if not session_id:
        return None
    try:
        p = mirror_path(session_id)
        if not p.is_file():
            return None
        rec = json.loads(p.read_text(encoding="utf-8"))
        return rec if isinstance(rec, dict) else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Where compaction fires
# ---------------------------------------------------------------------------


def parse_window_value(value) -> Optional[int]:
    """Parse an ``autoCompactWindow`` value in the forms the docs list for the
    command and the setting: a plain token count (``200000``), a ``k``/``M``
    suffix (``500k``, ``1M``), or a bare 100..1000 meaning thousands."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = int(value)
    else:
        s = str(value).strip().lower().replace(",", "").replace("_", "")
        if not s:
            return None
        mult = 1
        if s.endswith("k"):
            mult, s = 1_000, s[:-1]
        elif s.endswith("m"):
            mult, s = 1_000_000, s[:-1]
        try:
            n = int(float(s) * mult)
        except ValueError:
            return None
    if 100 <= n <= 1000:
        n *= 1000
    return n if n > 0 else None


def _managed_dir() -> Path:
    """Where managed (enterprise) settings live, per the docs: macOS
    ``/Library/Application Support/ClaudeCode``, Linux and WSL
    ``/etc/claude-code``, Windows ``C:\\Program Files\\ClaudeCode``."""
    if sys.platform == "darwin":
        return Path("/Library/Application Support/ClaudeCode")
    if sys.platform.startswith("win"):
        return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ClaudeCode"
    return Path("/etc/claude-code")


def _managed_files() -> list[Path]:
    """``managed-settings.json`` plus the ``managed-settings.d/`` drop-ins,
    which Claude Code merges in alphabetical order (later wins), so they
    are listed highest precedence first: drop-ins reversed, then the file."""
    d = _managed_dir()
    out: list[Path] = []
    try:
        dropins = sorted((d / "managed-settings.d").glob("*.json"))
    except Exception:
        dropins = []
    out += list(reversed(dropins))
    out.append(d / "managed-settings.json")
    return out


def _managed_registry() -> dict:
    """Windows only: ``HKLM`` then ``HKCU`` ``SOFTWARE\\Policies\\ClaudeCode``,
    value ``Settings`` holding the settings JSON as a string."""
    if not sys.platform.startswith("win"):
        return {}
    try:
        import winreg  # type: ignore[import-not-found]
    except Exception:
        return {}
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root, r"SOFTWARE\Policies\ClaudeCode") as k:
                raw, _kind = winreg.QueryValueEx(k, "Settings")
            d = json.loads(os.path.expandvars(str(raw)))
            if isinstance(d, dict):
                return d
        except Exception:
            continue
    return {}


def _settings_files(project_dir: str = "") -> list[Path]:
    """Settings files that can carry ``autoCompactWindow``, highest precedence
    first: managed, project-local, project, user. The ``--settings`` command
    line file sits between managed and project-local and is not visible to
    a hook."""
    out: list[Path] = list(_managed_files())
    if project_dir:
        p = Path(project_dir)
        out += [p / ".claude" / "settings.local.json", p / ".claude" / "settings.json"]
    # CLAUDE_CONFIG_DIR is Claude Code's own relocation of ~/.claude; honoring
    # it is correct for users who set it and is the test-isolation seam.
    cfg = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    out.append((Path(cfg) if cfg else Path.home() / ".claude") / "settings.json")
    return out


def _read_settings(path: Path) -> dict:
    try:
        if path.is_file():
            d = json.loads(path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
    except Exception:
        pass
    return {}


def settings_autocompact(project_dir: str = "") -> Optional[int]:
    return settings_autocompact_detail(project_dir)[0]


def settings_autocompact_detail(project_dir: str = "") -> tuple[Optional[int], str]:
    """(value, source): ``managed`` for the enterprise registry / files,
    ``settings`` for project-local, project and user files."""
    n = parse_window_value(_managed_registry().get("autoCompactWindow"))
    if n:
        return n, "managed"
    managed = set(_managed_files())
    for f in _settings_files(project_dir):
        n = parse_window_value(_read_settings(f).get("autoCompactWindow"))
        if n:
            return n, ("managed" if f in managed else "settings")
    return None, ""


def statusline_configured(project_dir: str = "") -> bool:
    """True when any settings file in scope declares a ``statusLine``."""
    return any(bool(_read_settings(f).get("statusLine")) for f in _settings_files(project_dir))


def compaction_point(window: int, project_dir: str = "") -> tuple[int, str]:
    """(token count where auto-compaction fires, where that number came from).

    Precedence per the docs: the env var beats the command, the flag and the
    setting; the setting is next; otherwise the model default. Claude Code caps
    the window at the model's context window, so we do too. The launch flag is
    not visible from a hook -- a session that set its window only that way
    reads as ``model-default`` here.
    """
    d = compaction_point_detail(window, project_dir)
    return d["point"], d["source"]


def compaction_point_detail(window: int, project_dir: str = "") -> dict:
    """compaction_point() plus what was CONFIGURED and whether the window
    capped it. A fixed autoCompactWindow is a token count, not a fraction:
    750K is 75% of a 1M model and, capped, the whole window of a 200K one --
    no headroom at all. ``recommended`` is 75% of this model's window, the
    number to give ``/autocompact`` on it."""
    window = int(window)
    configured = 0
    source = "model-default"
    env = os.environ.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "").strip()
    if env:
        try:
            n = int(env)
        except ValueError:
            n = 0
        if n >= _ENV_MIN_WINDOW:
            configured, source = n, "env"
    if not configured:
        n, label = settings_autocompact_detail(project_dir)
        if n:
            configured, source = int(n), label
    if configured:
        point = min(configured, window)
    elif window > SMALL_WINDOW:
        point = min(DEFAULT_COMPACT_1M, window)
    else:
        point = window
    return {
        "point": point,
        "source": source,
        "configured": configured,
        "capped": bool(configured and configured > window),
        "recommended": recommended_point(window),
    }


def recommended_point(window: int) -> int:
    """75% of the window, rounded down to a whole thousand."""
    return (int(window) * 3 // 4) // 1000 * 1000


def _env_float(name: str, default: float) -> float:
    try:
        v = float(os.environ.get(name, "").strip() or default)
        return v if 0 < v < 1 else default
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        v = int(os.environ.get(name, "").strip() or default)
        return v if v > 0 else default
    except ValueError:
        return default


def thresholds(window: int, point: int) -> dict:
    """Token counts at which each nudge fires.

    ``trigger_at`` is where auto-compaction actually fires: the configured
    point minus the output reserve (see OUTPUT_RESERVE). The checkpoint band
    sits a fixed margin above that trigger; the heads-up sits a fraction of
    the window below the point and is pulled under the checkpoint band when
    a small window would otherwise put it above."""
    reserve = _env_int("CLAUDE_ENGRAM_OUTPUT_RESERVE", OUTPUT_RESERVE)
    margin_default = CHECKPOINT_MARGIN_SMALL if window <= SMALL_WINDOW else CHECKPOINT_MARGIN
    margin = _env_int("CLAUDE_ENGRAM_CHECKPOINT_MARGIN", margin_default)
    hu = _env_float("CLAUDE_ENGRAM_HEADSUP_FRACTION", HEADSUP_FRACTION)
    trigger_at = int(point - reserve)
    checkpoint_at = int(trigger_at - margin)
    headsup_at = int(point - hu * window)
    if headsup_at >= checkpoint_at:
        headsup_at = int(checkpoint_at - hu * window / 2)
    return {
        "headsup_at": headsup_at,
        "checkpoint_at": checkpoint_at,
        "trigger_at": trigger_at,
    }


def assess(mirror: Optional[dict], project_dir: str = "") -> dict:
    """Distance to the compaction point from a mirror record.

    ``band`` is one of ``nodata`` (no mirror, or no tokens counted yet),
    ``clear``, ``headsup``, ``checkpoint``.
    """
    out: dict = {"band": "nodata", "reason": ""}
    if not mirror:
        out["reason"] = "no mirror"
        return out
    used = mirror.get("total_input_tokens") or 0
    window = mirror.get("context_window_size") or 0
    if not used or not window:
        out["reason"] = "no tokens counted yet"
        return out
    used, window = int(used), int(window)
    d = compaction_point_detail(window, project_dir)
    point, source = d["point"], d["source"]
    th = thresholds(window, point)
    band = "clear"
    if used >= th["checkpoint_at"]:
        band = "checkpoint"
    elif used >= th["headsup_at"]:
        band = "headsup"
    out.update(
        band=band,
        used=used,
        window=window,
        point=point,
        source=source,
        configured=d["configured"],
        capped=d["capped"],
        recommended=d["recommended"],
        distance=point - used,
        ts=mirror.get("ts"),
        model=mirror.get("model_name") or mirror.get("model_id") or "",
        **th,
    )
    return out


# ---------------------------------------------------------------------------
# Nudges (state-latched, once per band per compaction cycle)
# ---------------------------------------------------------------------------


def _k(n: int) -> str:
    return f"{n / 1000:.0f}K"


def _pct(n: int, window: int) -> str:
    return f"{100.0 * n / window:.0f}%" if window else "?"


def pressure_state(state: dict) -> dict:
    ps = state.get("pressure")
    if not isinstance(ps, dict):
        ps = {}
        state["pressure"] = ps
    ps.setdefault("cycle", 0)  # compactions seen this session
    ps.setdefault("headsup_done", False)
    ps.setdefault("checkpoint_done", False)
    ps.setdefault("compacted_at", 0.0)
    ps.setdefault("stops_since_checkpoint", 0)
    ps.setdefault("last_manual_checkpoint_at", 0.0)
    ps.setdefault("not_recording_announced", False)
    ps.setdefault("last_stop_at", 0.0)
    ps.setdefault("milestone_pending", None)
    ps.setdefault("setpoint_notice_done", False)
    ps.setdefault("budget_5h_noticed_reset", 0)  # resets_at the 5-hour notice was for
    ps.setdefault("budget_7d_noticed_reset", 0)
    return ps


def note_manual_checkpoint(state: dict) -> None:
    """A deliberate checkpoint_save happened: reset the cadence counter and
    drop any staged milestone nudge -- it was answered."""
    ps = pressure_state(state)
    ps["stops_since_checkpoint"] = 0
    ps["last_manual_checkpoint_at"] = time.time()
    ps["milestone_pending"] = None


def _ring_manual_after(project_dir: str, t: float) -> bool:
    """Is there a deliberate (manual) checkpoint in the project's ring newer
    than ``t``? The ring is what any process writes; the state flag is not."""
    if not project_dir or not t:
        return False
    try:
        from claude_engram.hooks.remind import get_handoff_data

        entry = get_handoff_data(project_dir) or {}
        if str(entry.get("kind", "")) != "manual":
            return False
        created = float(entry.get("created") or entry.get("timestamp") or 0.0)
        return created > t
    except Exception:
        return False


MILESTONE_NUDGE_GAP_SECS = 3600  # at most one prose-triggered nudge an hour


def _turn_corroborates_a_close(state: dict, quote: str) -> bool:
    """A sentence alone is not a close. The trade-lab trial (2026-09-11) got
    four nudges quoting status-report lines to the person ("Track B is built
    and merged", a bullet relaying another agent's work); the model tuned
    them out. A claim counts only when the turn that made it did something:
    a commit, an edit, a delegated agent (hooks/stall.py accounts these to
    the open turn, judged after this runs). A list bullet is a relay, never
    a close of the model's own."""
    q = (quote or "").lstrip()
    if q.startswith(("- ", "* ", "• ", "-**", "*  ")):
        return False
    _stall = state.get("stall")
    turn = (_stall if isinstance(_stall, dict) else {}).get("turn")
    if not isinstance(turn, dict):
        return False
    effects = turn.get("effects") or []
    return bool(effects) or bool(turn.get("delegated"))


def stage_milestone(state: dict, quote: str, kind: str = "claim", since: float = 0.0) -> None:
    """Remember that a unit closed without a deliberate checkpoint; the next
    injection point asks for one. The newest claim wins. ``since`` is the
    start of the turn that made the claim: a checkpoint saved anywhere in
    that turn -- before the closing sentence, the usual order -- answers it."""
    ps = pressure_state(state)
    ps["milestone_pending"] = {"quote": quote[:160], "kind": kind, "at": time.time(), "since": float(since or 0.0)}


def note_stop(state: dict, last_message: str = "") -> None:
    """One assistant turn ended (the Stop hook). If the model's final message
    declares a step done and no deliberate checkpoint landed this turn, stage
    the milestone nudge. A checkpoint that DID land this turn is the ideal
    path and nothing is staged."""
    ps = pressure_state(state)
    ps["stops_since_checkpoint"] = int(ps.get("stops_since_checkpoint", 0)) + 1
    ps["stops_total"] = int(ps.get("stops_total", 0)) + 1
    prev_stop = float(ps.get("last_stop_at") or 0.0)
    ps["last_stop_at"] = time.time()
    if not last_message:
        return
    if float(ps.get("last_manual_checkpoint_at") or 0.0) > prev_stop:
        return  # banked this turn already
    try:
        from claude_engram.hooks.milestones import is_completion_claim

        claimed, quote = is_completion_claim(last_message)
    except Exception:
        return
    if claimed and _turn_corroborates_a_close(state, quote):
        stage_milestone(state, quote, "claim", since=prev_stop)
        # A completion claim is a unit boundary; the fallback cadence counts
        # turns with neither a checkpoint nor a claim.
        ps["stops_since_checkpoint"] = 0


def note_compaction(state: dict) -> None:
    """PostCompact: open a new cycle. Latches clear; a mirror written before
    this moment still shows the pre-compaction count and is ignored until the
    statusline writes a fresh one. Also appends a compaction record for the
    run report (sizes come from the transcript's compact_boundary metadata;
    this record adds the moment and, via note_restored, what was restored)."""
    ps = pressure_state(state)
    ps["cycle"] = int(ps.get("cycle", 0)) + 1
    ps["headsup_done"] = False
    ps["checkpoint_done"] = False
    ps["compacted_at"] = time.time()
    comps = ps.get("compactions")
    if not isinstance(comps, list):
        comps = []
    comps.append({"at": ps["compacted_at"], "cycle": ps["cycle"], "restored": None})
    ps["compactions"] = comps[-50:]


def note_restored(state: dict, entry: Optional[dict]) -> None:
    """PostCompact re-injected this ring entry; pin it to the latest
    compaction record so the report can say what each compaction restored."""
    ps = pressure_state(state)
    comps = ps.get("compactions")
    if not isinstance(comps, list) or not comps or not isinstance(entry, dict):
        return
    comps[-1]["restored"] = {
        "kind": entry.get("kind", "auto"),
        "task_id": entry.get("task_id", ""),
        "summary": str(entry.get("summary") or entry.get("task_description") or "")[:120],
    }


def current_assessment(state: dict, session_id: str, project_dir: str = "") -> dict:
    """assess() over the session's mirror, ignoring a pre-compaction reading."""
    ps = pressure_state(state)
    mirror = read_mirror(session_id)
    if mirror and ps.get("compacted_at") and (mirror.get("ts") or 0) <= ps["compacted_at"]:
        a = assess(None, project_dir)
        a["reason"] = "mirror predates the last compaction"
        return a
    return assess(mirror, project_dir)


def headsup_text(a: dict, cycle: int) -> str:
    return (
        "<engram-context>Context pressure: "
        f"{_k(a['used'])} used of a {_k(a['point'])} compaction point "
        f"({_k(a['distance'])} left, {_pct(a['distance'], a['window'])} of the window; "
        f"point source: {a['source']}). Compaction #{cycle + 1} is coming. "
        "Finish the current step and start nothing long. "
        f"The checkpoint call comes at ~{_k(a['checkpoint_at'])}."
        "</engram-context>"
    )


def checkpoint_text(a: dict) -> str:
    left = max(0, int(a["trigger_at"]) - int(a["used"]))
    return (
        "<engram-context>CHECKPOINT NOW: "
        f"{_k(left)} tokens to the auto-compaction trigger (~{_k(a['trigger_at'])}; "
        f"the {_k(a['point'])} setting minus the output reserve). "
        "Call context(checkpoint_save) with task_description, current_step, "
        "completed_steps, pending_steps, files_involved, handoff_warnings and a "
        "handoff_summary, then continue. PreCompact's automatic entry is only a floor."
        "</engram-context>"
    )


def cadence_text(stops: int) -> str:
    return (
        "<engram-context>Checkpoint fallback: "
        f"{stops} turns with neither a deliberate checkpoint nor a completed step. "
        "Either a unit is closing without being declared, or the run is not "
        "progressing. Bank a context(checkpoint_save) with where things stand; "
        "a compaction or a crash keeps only what is written.</engram-context>"
    )


def setpoint_text(a: dict) -> str:
    """The configured compaction point does not fit this model. Once per
    session, with the number to use on it."""
    rec = a.get("recommended") or 0
    rec_arg = f"{rec // 1000}k"
    if a.get("capped"):
        return (
            "<engram-context>Compaction point: autoCompactWindow "
            f"{_k(a['configured'])} ({a['source']}) is above this model's "
            f"{_k(a['window'])} window, so Claude Code caps it at the boundary: "
            "compaction fires with no headroom for a checkpoint. The setting is a "
            "token count, not a fraction; the right number here is "
            f"`/autocompact {rec_arg}` (75%). Only the person at the terminal can "
            "change it for this session.</engram-context>"
        )
    return (
        "<engram-context>Compaction point: no autoCompactWindow is set and this "
        f"model's window is {_k(a['window'])}, so compaction fires at the boundary "
        "with no headroom for a checkpoint. `/autocompact "
        f"{rec_arg}` (75%) gives the checkpoint call room on this model."
        "</engram-context>"
    )


def setpoint_mismatch(a: dict) -> bool:
    if a.get("band") == "nodata" or not a.get("window"):
        return False
    if a.get("capped"):
        return True
    return a.get("source") == "model-default" and int(a["window"]) <= SMALL_WINDOW


def _fmt_reset(ts) -> str:
    """'14:05 (in 41 min)' or '' when unknown."""
    try:
        t = float(ts or 0)
    except (TypeError, ValueError):
        return ""
    if t <= 0:
        return ""
    left = t - time.time()
    when = time.strftime("%a %H:%M", time.localtime(t))
    if left <= 0:
        return f"{when} (passed)"
    if left < 3600:
        return f"{when} (in {left / 60:.0f} min)"
    if left < 48 * 3600:
        return f"{when} (in {left / 3600:.1f} h)"
    return f"{when} (in {left / 86400:.1f} d)"


def budget_text(window: str, pct, resets_at) -> str:
    reset = _fmt_reset(resets_at)
    reset_s = f", resets {reset}" if reset else ""
    if window == "five_hour":
        return (
            f"<engram-context>Usage budget: the 5-hour window is at {float(pct):.0f}%{reset_s}. "
            "A limit hit ends the turn on an API error that no Stop hook sees and Claude Code "
            "does not retry; a goal loop dies there. Finish the current step, bank a "
            "context(checkpoint_save), and park on a ScheduleWakeup or Monitor until the reset "
            "instead of running into it mid-step.</engram-context>"
        )
    return (
        f"<engram-context>Usage budget: the 7-day window is at {float(pct):.0f}%{reset_s}. "
        "Nothing unattended should start before it resets; checkpoint what is open."
        "</engram-context>"
    )


def budget_nudges(state: dict, mirror: Optional[dict]) -> list[str]:
    """Once per window (keyed by resets_at): the 5-hour window at
    BUDGET_FIVE_HOUR_PCT, the weekly at BUDGET_SEVEN_DAY_PCT. Absent fields
    (API-key sessions) mean nothing fires."""
    if not mirror:
        return []
    ps = pressure_state(state)
    out: list[str] = []
    five = _env_int("CLAUDE_ENGRAM_BUDGET_FIVE_HOUR_PCT", BUDGET_FIVE_HOUR_PCT)
    seven = _env_int("CLAUDE_ENGRAM_BUDGET_SEVEN_DAY_PCT", BUDGET_SEVEN_DAY_PCT)
    for key, threshold, latch in (
        ("five_hour", five, "budget_5h_noticed_reset"),
        ("seven_day", seven, "budget_7d_noticed_reset"),
    ):
        pct = mirror.get(f"{key}_pct")
        if pct is None:
            continue
        try:
            pct_f = float(pct)
        except (TypeError, ValueError):
            continue
        resets = mirror.get(f"{key}_resets_at") or 0
        try:
            resets_i = int(float(resets))
        except (TypeError, ValueError):
            resets_i = 0
        if pct_f < threshold:
            continue
        # Same window already announced (same reset stamp) -> quiet.
        if resets_i and int(ps.get(latch) or 0) == resets_i:
            continue
        if not resets_i and int(ps.get(latch) or 0) == -1:
            continue
        ps[latch] = resets_i or -1
        out.append(budget_text(key, pct_f, resets_i))
    return out


def not_recording_text() -> str:
    return (
        "<engram-context>Context pressure: a statusLine is configured but no "
        "context reading has arrived from it. Engram cannot see how close "
        "compaction is; pre-compaction checkpoint nudges are off and only the "
        "turn cadence runs. Add record_statusline() to the statusline script "
        "or point statusLine at `python -m claude_engram.hooks.context_pressure "
        "statusline` (README: Context pressure).</engram-context>"
    )


def nudge(state: dict, session_id: str, project_dir: str = "") -> tuple[str, bool]:
    """Return (text, state_changed). Text is "" when nothing is due.

    Called wherever a hook can inject context (UserPromptSubmit, PreToolUse,
    PostToolUse). Each band fires once per compaction cycle; the cadence nudge
    fires every CADENCE_STOPS turns until a deliberate checkpoint resets it.
    The caller saves state when the flag is set.
    """
    ps = pressure_state(state)
    a = current_assessment(state, session_id, project_dir)
    changed = False
    texts: list[str] = []

    if a["band"] == "checkpoint" and not ps["checkpoint_done"]:
        ps["checkpoint_done"] = True
        ps["headsup_done"] = True
        changed = True
        texts.append(checkpoint_text(a))
    elif a["band"] == "headsup" and not ps["headsup_done"]:
        ps["headsup_done"] = True
        changed = True
        texts.append(headsup_text(a, int(ps["cycle"])))
    elif a["band"] == "nodata" and a.get("reason") == "no mirror":
        started = state.get("last_session_start") or 0
        if (
            not ps["not_recording_announced"]
            and started
            and time.time() - started > NOT_RECORDING_AFTER_SECS
            and statusline_configured(project_dir)
        ):
            ps["not_recording_announced"] = True
            changed = True
            texts.append(not_recording_text())

    # The setpoint is a token count and the model's window decides whether
    # it fits. Said once per session, with the number for this model.
    if not ps["setpoint_notice_done"] and setpoint_mismatch(a):
        ps["setpoint_notice_done"] = True
        changed = True
        texts.append(setpoint_text(a))

    # Subscription usage windows, once per window, from the same mirror.
    _budget = budget_nudges(state, read_mirror(session_id))
    if _budget:
        changed = True
        texts.extend(_budget)

    # A closed step with no deliberate checkpoint behind it. Delivered once;
    # a checkpoint that landed since the claim answers it silently.
    mp = ps.get("milestone_pending")
    if isinstance(mp, dict) and not texts:
        ps["milestone_pending"] = None
        changed = True
        claim_at = float(mp.get("at") or 0.0)
        # The turn that made the claim started at ``since``; the usual order
        # is save first, closing sentence last, so a save anywhere in that
        # turn answers the claim.
        window_start = float(mp.get("since") or 0.0) or claim_at
        answered = float(ps.get("last_manual_checkpoint_at") or 0.0) > window_start
        if not answered:
            # The state flag is set by checkpoint_save in THIS session's
            # process; a save made from another process (a script, the MCP
            # server under a different session id) reaches the ring but not
            # the flag. The ring is the record, so read it: a manual entry
            # newer than the turn's start answers the nudge. (Three false
            # nudges on 2026-09-10 came from exactly that.)
            answered = _ring_manual_after(project_dir, window_start)
        # One prose nudge an hour: past that it is wallpaper (the trial's
        # verdict). Task-tool closes are structural and not rate-limited.
        recent = time.time() - float(ps.get("milestone_nudged_at") or 0.0) < MILESTONE_NUDGE_GAP_SECS
        if not answered and not (recent and mp.get("kind") == "claim"):
            from claude_engram.hooks.milestones import milestone_text

            ps["milestone_nudged_at"] = time.time()
            texts.append(milestone_text(str(mp.get("quote", "")), str(mp.get("kind", "claim"))))

    cadence = _env_int("CLAUDE_ENGRAM_CHECKPOINT_CADENCE", CADENCE_STOPS)
    stops = int(ps.get("stops_since_checkpoint", 0))
    if stops >= cadence and not texts:
        # Re-arm rather than latch: fires again after another full cadence
        # until a deliberate save resets the count.
        ps["stops_since_checkpoint"] = 0
        changed = True
        texts.append(cadence_text(stops))

    return ("\n".join(texts), changed)


def rhythm_text(state: dict, session_id: str, project_dir: str = "") -> str:
    """One line for the PostCompact banner: which compaction this was and where
    the nudges sit, so the model plans work in units that finish before the
    checkpoint call. Uses whatever mirror exists for the window size only --
    that number does not change across a compaction."""
    ps = pressure_state(state)
    cycle = int(ps.get("cycle", 0))
    mirror = read_mirror(session_id)
    window = int((mirror or {}).get("context_window_size") or 0)
    cadence = _env_int("CLAUDE_ENGRAM_CHECKPOINT_CADENCE", CADENCE_STOPS)
    if not window:
        return (
            f"Compaction #{cycle}. No context reading (statusline mirror missing); "
            f"checkpoint on cadence, every {cadence} turns."
        )
    d = compaction_point_detail(window, project_dir)
    point, source = d["point"], d["source"]
    th = thresholds(window, point)
    capped = ""
    if d["capped"]:
        capped = (
            f"; the configured {_k(d['configured'])} is capped at the "
            f"{_k(window)} window -- `/autocompact {d['recommended'] // 1000}k` fits this model"
        )
    return (
        f"Compaction #{cycle}. Rhythm: heads-up at ~{_k(th['headsup_at'])} "
        f"({_pct(th['headsup_at'], window)}), checkpoint at ~{_k(th['checkpoint_at'])}, "
        f"auto-compaction at ~{_k(th['trigger_at'])} (the {_k(point)} {source} setting "
        f"minus the output reserve{capped}). Plan work in units that finish "
        "before the checkpoint call."
    )


def session_start_text(project_dir: str = "") -> str:
    """Line for the SessionStart banner when there is no statusLine at all."""
    if statusline_configured(project_dir):
        return ""
    return (
        "Context pressure: no statusLine configured, so engram cannot see context "
        "usage. Pre-compaction checkpoint nudges are off; cadence nudges only. "
        "See README: Context pressure."
    )


# ---------------------------------------------------------------------------
# CLI: a ready-made statusline, and a debugging view
# ---------------------------------------------------------------------------


def _fmt_statusline(data: dict) -> str:
    model = (data.get("model") or {}).get("display_name", "") or ""
    model = model.replace("Claude ", "")
    ctx = data.get("context_window") or {}
    used = ctx.get("total_input_tokens") or 0
    window = ctx.get("context_window_size") or 0
    parts = [p for p in [model] if p]
    if used and window:
        point, _ = compaction_point(int(window))
        parts.append(f"ctx {_k(int(used))}/{_k(int(window))}")
        parts.append(f"compact at {_k(point)} ({_k(point - int(used))} left)")
    cost = (data.get("cost") or {}).get("total_cost_usd")
    if cost is not None:
        parts.append(f"${cost:.2f}")
    five = ((data.get("rate_limits") or {}).get("five_hour") or {}).get("used_percentage")
    if five is not None:
        try:
            parts.append(f"5h {float(five):.0f}%")
        except (TypeError, ValueError):
            pass
    cwd = data.get("cwd") or ""
    if cwd:
        parts.append(os.path.basename(cwd))
    return " | ".join(parts)


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "statusline"
    if cmd == "statusline":
        try:
            data = json.load(sys.stdin)
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        record_statusline(data)
        print(_fmt_statusline(data), end="")
        return 0
    if cmd == "assess":
        sid = args[1] if len(args) > 1 else os.environ.get("CLAUDE_CODE_SESSION_ID", "")
        project_dir = args[2] if len(args) > 2 else ""
        print(json.dumps(assess(read_mirror(sid), project_dir), indent=2))
        return 0
    print("usage: python -m claude_engram.hooks.context_pressure statusline | assess [session_id] [project_dir]")
    return 2


if __name__ == "__main__":
    sys.exit(main())
