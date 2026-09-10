"""
Alerts: one line, out of the session, when something needs a person.

Two channels, both recorded in the session state either way:

* In the session, the model calls ``PushNotification`` (desktop, and the
  phone when Remote Control is connected). Hooks cannot call it; the halt
  text and the launcher's prompt tell the model when to.
* Out of the session -- the run died on an API error, the launcher gave
  up, a permission prompt is waiting with nobody there -- a shell command
  the owner configured runs with the message. Nothing is built in: there
  is no service engram would be right to pick. ``{message}`` in the command
  is replaced (shell-quoted); with no placeholder the message arrives on
  stdin.

    .engram/config.json:  {"alert_command": "curl -s -d {message} https://ntfy.sh/<topic>"}
    or CLAUDE_ENGRAM_ALERT_COMMAND

The rule from the plan: under 200 characters, leads with what to act on,
never for routine progress.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from typing import Optional

ALERT_TIMEOUT = 15.0
KEEP = 50


def alert_command(project_dir: str = "") -> str:
    env = os.environ.get("CLAUDE_ENGRAM_ALERT_COMMAND", "").strip()
    if env:
        return env
    try:
        from claude_engram import project_config as _pc

        cmd = _pc.load(project_dir).get("alert_command") if project_dir else ""
        return str(cmd or "").strip()
    except Exception:
        return ""


def _quote(s: str) -> str:
    if os.name == "nt":
        # cmd.exe quoting: double quotes, inner quotes escaped.
        return '"' + s.replace('"', '\\"') + '"'
    return shlex.quote(s)


def send(
    message: str,
    project_dir: str = "",
    kind: str = "info",
    state: Optional[dict] = None,
    command: str = "",
) -> dict:
    """Run the owner's alert command with the message. Returns the record
    ({at, kind, message, sent, detail}); appends it to state["alerts"] when a
    state dict is given. ``command`` overrides the configured one (the
    launcher passes its --alert-command). Never raises."""
    message = " ".join(str(message or "").split())[:200]
    rec = {"at": time.time(), "kind": kind, "message": message, "sent": False, "detail": ""}
    cmd = (command or "").strip() or alert_command(project_dir)
    if not cmd:
        rec["detail"] = "no alert_command configured"
    else:
        try:
            if "{message}" in cmd:
                full = cmd.replace("{message}", _quote(message))
                r = subprocess.run(full, shell=True, capture_output=True, text=True, timeout=ALERT_TIMEOUT)
            else:
                r = subprocess.run(cmd, shell=True, input=message, capture_output=True, text=True, timeout=ALERT_TIMEOUT)
            rec["sent"] = r.returncode == 0
            rec["detail"] = (r.stdout or r.stderr or "").strip()[:200] if r.returncode != 0 else "ok"
        except subprocess.TimeoutExpired:
            rec["detail"] = f"alert command timed out after {ALERT_TIMEOUT:.0f}s"
        except Exception as e:
            rec["detail"] = str(e)[:200]
    if isinstance(state, dict):
        state["alerts"] = (list(state.get("alerts") or []) + [rec])[-KEEP:]
    return rec


def summary(state: dict) -> list[dict]:
    return [a for a in (state.get("alerts") or []) if isinstance(a, dict)]
