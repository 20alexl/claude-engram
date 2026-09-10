"""
The toggle: ``python -m claude_engram.run`` -- launch an unattended run.

Engram does not invent the loop. ``/goal`` is the loop; this brackets it:

1. Writes the run manifest: goal, prompt, model, permission mode, the
   compaction point it sets, the rules in scope with their detectors, the
   start commit.
2. Launches ``claude -p`` with a caller-chosen session id, autonomy mode on
   (``CLAUDE_ENGRAM_AUTONOMY=1``: the strike-3 halt arms, alerts fire),
   ``CLAUDE_CODE_AUTO_COMPACT_WINDOW`` at 75% of the model's context window
   (a token count that fits the model, not a fixed number), a hard
   ``--max-turns`` (the evaluator's own "or stop after N turns" is not
   honored, verified), and a prompt that tells the model to park on a wait
   primitive rather than poll.
3. On exit, reads the session state. A ``rate_limit`` failure with a known
   reset sleeps until the window resets and resumes the same session
   (``claude -p --resume <id>``; a resume restores an active /goal,
   verified). Anything else ends the run.
4. Writes the run report and sends the closing alert.

Every number it sets is printed and lands in the manifest.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

DEFAULT_FRACTION = 0.75
DEFAULT_MAX_TURNS = 150
DEFAULT_MAX_RESUMES = 3
RESUME_SLACK_SECS = 90
MAX_RESUME_WAIT_SECS = 6 * 3600  # a weekly window is not worth sleeping on

PARK_HINT = (
    "This run is unattended (engram autonomy mode). Work in units that finish "
    "before a checkpoint call, and call context(checkpoint_save) before declaring "
    "a step done. If you must wait for something -- a scheduled task, a build, a "
    "file another process writes -- park on Monitor or ScheduleWakeup instead of "
    "polling: tool use without effect strikes, and three strikes halt the run. "
    "If a rule with a detector matches a command you are about to run and the rule "
    "says ask first, stop and say what you need instead of running it."
)


def model_window(model: str, explicit: Optional[str] = None) -> int:
    """The model's context window in tokens. Explicit wins; otherwise a
    small table by alias, defaulting to 1M (the current Claude 5 family)."""
    from claude_engram.hooks.context_pressure import parse_window_value

    if explicit:
        n = parse_window_value(explicit)
        if n:
            return int(n)
        raise SystemExit(f"cannot parse --context-window {explicit!r}")
    m = (model or "").lower()
    if "haiku" in m:
        return 200_000
    return 1_000_000


def compaction_env(window: int, fraction: float) -> int:
    return max(100_000, int(window * fraction) // 1000 * 1000)


def build_prompt(goal: str, prompt: str, park_hint: bool = True) -> str:
    parts = []
    if goal.strip():
        parts.append("/goal " + goal.strip())
    if prompt.strip():
        parts.append(prompt.strip())
    if park_hint:
        parts.append(PARK_HINT)
    return "\n\n".join(parts)


def build_env(base, point: int, alert_command: str = "") -> dict:
    env = {str(k): str(v) for k, v in dict(base).items()}
    env["CLAUDE_ENGRAM_AUTONOMY"] = "1"
    env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = str(int(point))
    env["MSYS_NO_PATHCONV"] = "1"  # Git Bash would rewrite /goal into a path
    if alert_command:
        env["CLAUDE_ENGRAM_ALERT_COMMAND"] = alert_command
    # A run launched from inside a Claude session must not inherit its identity.
    for k in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT"):
        env.pop(k, None)
    return env


def build_cmd(
    prompt: Optional[str],
    session_id: str,
    permission_mode: str,
    model: str = "",
    max_turns: int = 0,
    resume: bool = False,
    claude_bin: str = "claude",
) -> list[str]:
    # A .py stand-in (the bench's fake claude) runs under this interpreter;
    # a .cmd wrapper cannot carry a multi-line prompt through cmd.exe.
    cmd = ([sys.executable, claude_bin] if claude_bin.lower().endswith(".py") else [claude_bin]) + ["-p"]
    if resume:
        cmd += ["--resume", session_id]
        if prompt:
            cmd.append(prompt)
    else:
        if prompt:
            cmd.append(prompt)
        cmd += ["--session-id", session_id]
    cmd += ["--output-format", "json", "--permission-mode", permission_mode]
    if model:
        cmd += ["--model", model]
    if max_turns and max_turns > 0:
        cmd += ["--max-turns", str(int(max_turns))]
    return cmd


def _rules_snapshot(project_dir: str) -> list[dict]:
    try:
        from claude_engram.hooks.compliance import rules_with_detectors
        from claude_engram.hooks.storage import load_project_memory

        return [
            {"id": r["id"], "rule": r["content"][:160], "detector": bool(r.get("detector")), "note": (r.get("detector") or {}).get("note", "")}
            for r in rules_with_detectors(load_project_memory(project_dir))
        ]
    except Exception:
        return []


def _git_head(project_dir: str) -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=project_dir, capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def write_manifest(project_dir: str, session_id: str, data: dict) -> Optional[Path]:
    try:
        d = Path(project_dir) / ".engram" / "runs"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{time.strftime('%Y-%m-%d')}-{session_id[:8]}.manifest.json"
        p.write_bytes((json.dumps(data, indent=2, default=str) + "\n").encode("utf-8"))
        return p
    except Exception:
        return None


def prime_state(session_id: str, goal: str, manifest_path: str = "") -> None:
    """Before launch: record the goal and the manifest in the session's
    state so every checkpoint the run saves carries the goal, and the run
    report can name the manifest. SessionStart keeps the run block."""
    try:
        from claude_engram.hooks import remind

        remind._session_id = session_id
        state = remind.load_state()
        _run = state.get("run")
        run: dict = _run if isinstance(_run, dict) else {}
        if goal.strip():
            run["goal"] = goal.strip()[:500]
        if manifest_path:
            run["manifest"] = manifest_path
        run["launcher"] = True
        state["run"] = run
        remind.save_state(state)
    except Exception:
        pass


def session_state(session_id: str) -> dict:
    try:
        from claude_engram.hooks import remind

        remind._session_id = session_id
        return remind.load_state()
    except Exception:
        return {}


def resume_decision(state: dict, resumes_done: int, max_resumes: int, now: Optional[float] = None) -> tuple[bool, float, str]:
    """(resume?, wait_seconds, why). Only a rate_limit failure with a known
    reset inside MAX_RESUME_WAIT_SECS earns a resume."""
    now = time.time() if now is None else now
    run = state.get("run") or {}
    last = run.get("last_failure") or {}
    if not last:
        return False, 0.0, "no API failure recorded"
    if last.get("error_type") != "rate_limit":
        return False, 0.0, f"last failure is {last.get('error_type')}, not a usage limit"
    if resumes_done >= max_resumes:
        return False, 0.0, f"resume budget spent ({max_resumes})"
    reset = last.get("five_hour_resets_at") or last.get("seven_day_resets_at")
    try:
        reset_t = float(reset or 0)
    except (TypeError, ValueError):
        reset_t = 0.0
    if not reset_t:
        return False, 0.0, "usage limit hit but no reset time known (no statusline mirror?)"
    try:
        slack = float(os.environ.get("CLAUDE_ENGRAM_RESUME_SLACK", RESUME_SLACK_SECS))
    except ValueError:
        slack = float(RESUME_SLACK_SECS)
    wait = max(0.0, reset_t - now) + slack
    if wait > MAX_RESUME_WAIT_SECS:
        return False, wait, f"window resets in {wait / 3600:.1f} h; too long to hold a launcher"
    return True, wait, f"usage limit; window resets in {max(0.0, reset_t - now) / 60:.0f} min"


def _parse_result(stdout: str) -> dict:
    for line in reversed((stdout or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                d = json.loads(line)
                return d if isinstance(d, dict) else {}
            except Exception:
                continue
    return {}


def _alert(message: str, project_dir: str, kind: str, session_id: str, command: str = "") -> None:
    try:
        from claude_engram import alerts
        from claude_engram.hooks import remind

        remind._session_id = session_id
        state = remind.load_state()
        alerts.send(message, project_dir, kind=kind, state=state, command=command)
        remind.save_state(state)
    except Exception:
        pass


def launch(args: argparse.Namespace) -> int:
    project_dir = str(Path(args.project or os.getcwd()).resolve())
    session_id = args.session_id or str(uuid.uuid4())
    window = model_window(args.model or "", args.context_window)
    point = compaction_env(window, args.window_fraction)
    prompt_text = args.prompt or ""
    if args.prompt_file:
        prompt_text = Path(args.prompt_file).read_text(encoding="utf-8")
    if not (args.goal or "").strip() and not prompt_text.strip():
        print("nothing to run: give --goal and/or --prompt", file=sys.stderr)
        return 2
    prompt = build_prompt(args.goal or "", prompt_text, park_hint=not args.no_park_hint)
    alert_cmd = (args.alert_command or os.environ.get("CLAUDE_ENGRAM_ALERT_COMMAND", "")).strip()
    env = build_env(os.environ, point, alert_cmd)
    cmd = build_cmd(prompt, session_id, args.permission_mode, args.model or "", args.max_turns, claude_bin=args.claude_bin)
    manifest = {
        "session_id": session_id,
        "project": project_dir,
        "goal": args.goal or "",
        "prompt": prompt,
        "model": args.model or "(default)",
        "permission_mode": args.permission_mode,
        "context_window": window,
        "compaction_point": point,
        "max_turns": args.max_turns,
        "max_resumes": args.max_resumes,
        "alert_command": bool(args.alert_command or os.environ.get("CLAUDE_ENGRAM_ALERT_COMMAND")),
        "start_commit": _git_head(project_dir),
        "started_at": time.time(),
        "rules": _rules_snapshot(project_dir),
        "cmd": cmd,
    }
    print(f"engram run {session_id[:8]}")
    print(f"  project      {project_dir}")
    print(f"  model        {manifest['model']}  window {window:,}  compaction point {point:,} ({args.window_fraction:.0%})")
    print(f"  permissions  {args.permission_mode}   max turns {args.max_turns}   max resumes {args.max_resumes}")
    print(f"  rules        {len(manifest['rules'])} in scope, {sum(1 for r in manifest['rules'] if r['detector'])} with a detector")
    if args.dry_run:
        print("  dry run: not launching")
        print("  cmd: " + " ".join(_short(c) for c in cmd))
        print(json.dumps({k: v for k, v in manifest.items() if k not in ("prompt", "cmd")}, indent=2, default=str))
        return 0
    mp = write_manifest(project_dir, session_id, manifest)
    if mp:
        print(f"  manifest     {mp}")
    prime_state(session_id, args.goal or "", str(mp) if mp else "")

    resumes = 0
    exit_code = 1
    result: dict = {}
    while True:
        started = time.time()
        # stdin closed: with a prompt on the command line claude -p still
        # waits 3 s for piped input before proceeding (seen on the first run).
        r = subprocess.run(cmd, cwd=project_dir, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        exit_code = r.returncode
        result = _parse_result(r.stdout)
        print(
            f"  claude exited {exit_code} after {time.time() - started:.0f}s"
            + (f"; turns {result.get('num_turns')}" if result.get("num_turns") is not None else "")
            + (f"; cost ${float(result.get('total_cost_usd', 0)):.2f}" if result.get("total_cost_usd") is not None else "")
        )
        if r.stderr.strip():
            print("  stderr: " + r.stderr.strip()[-300:])
        state = session_state(session_id)
        halted = ((state.get("stall") or {}).get("halted")) if isinstance(state.get("stall"), dict) else None
        if halted:
            print(f"  HALTED at turn {halted.get('turn')} (strikes {halted.get('strikes')}); release with: python -m claude_engram.hooks.stall release {session_id}")
            break
        ok, wait, why = resume_decision(state, resumes, args.max_resumes)
        if exit_code == 0 or not ok:
            if exit_code != 0:
                print(f"  not resuming: {why}")
            break
        resumes += 1
        print(f"  {why}; sleeping {wait / 60:.0f} min then resuming ({resumes}/{args.max_resumes})")
        _alert(f"run {session_id[:8]} paused: usage limit, resuming in {wait / 60:.0f} min", project_dir, "paused", session_id, alert_cmd)
        time.sleep(wait)
        cmd = build_cmd("Continue.", session_id, args.permission_mode, args.model or "", args.max_turns, resume=True, claude_bin=args.claude_bin)

    report = None
    try:
        from claude_engram import run_report

        report = run_report.write_report(session_id, project_dir)
    except Exception:
        report = None
    if report:
        print(f"  report       {report}")
    summary = str(result.get("result") or "")[:160].replace("\n", " ")
    kind = "done" if exit_code == 0 else "failed"
    _alert(f"run {session_id[:8]} {kind} (exit {exit_code})" + (f": {summary}" if summary else ""), project_dir, kind, session_id, alert_cmd)
    return exit_code


def _short(s: str) -> str:
    s = str(s)
    return (s[:60] + "…") if len(s) > 60 else s


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m claude_engram.run", description="Launch an unattended, supervised claude -p run.")
    ap.add_argument("--goal", default="", help="the /goal condition (the loop)")
    ap.add_argument("--prompt", default="", help="task text after the goal")
    ap.add_argument("--prompt-file", default="", help="read the task text from a file")
    ap.add_argument("--project", default="", help="project directory (default: cwd)")
    ap.add_argument("--model", default="", help="model alias or id (sonnet, opus, fable, ...)")
    ap.add_argument("--permission-mode", default="bypassPermissions", help="default bypassPermissions: nobody is there to answer a prompt")
    ap.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS, help=f"hard turn cap (default {DEFAULT_MAX_TURNS}); the goal evaluator's own cap is not honored")
    ap.add_argument("--context-window", default="", help="the model's window (e.g. 1M, 200k); default by alias: haiku 200K, else 1M")
    ap.add_argument("--window-fraction", type=float, default=DEFAULT_FRACTION, help="compaction point as a fraction of the window (default 0.75)")
    ap.add_argument("--max-resumes", type=int, default=DEFAULT_MAX_RESUMES, help="resumes after a usage-limit exit")
    ap.add_argument("--alert-command", default="", help="shell command for out-of-session alerts; {message} is replaced")
    ap.add_argument("--session-id", default="", help="use this UUID (default: new)")
    ap.add_argument("--claude-bin", default="claude", help="the claude executable")
    ap.add_argument("--no-park-hint", action="store_true", help="do not append the unattended-run instructions")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    args = ap.parse_args(argv)
    return launch(args)


if __name__ == "__main__":
    raise SystemExit(main())
