"""
Benchmark: session identity + checkpoint-derived session title.

Guards two Claude Code integration seams:

  1. Session identity (CC 2.1.154+). Working state lives in
     sessions/<session_id>.json. Hooks learn the id from stdin; the MCP server
     has no stdin, so before it adopted CLAUDE_CODE_SESSION_ID it fell through
     to the shared hook_state.json -- a file the per-session hooks never write --
     and session_end reported a stale session's stats. Also pins the invariant
     that a stdin id always beats the environment (the scorer daemon serves many
     sessions from one process and re-reads the id per request).

  2. Session title (CC 2.1.152+). A restored DELIBERATE checkpoint names the
     session; a per-turn auto never does, so engram cannot stomp a title the
     user chose with "Session stopped. 2 files edited."

Run: python tests/bench_session_identity.py
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_fails = []


def check(name, cond):
    print(("  [PASS] " if cond else "  [FAIL] ") + name)
    if not cond:
        _fails.append(name)


def test_session_identity():
    print("Session identity (stdin id > env id > shared fallback):")
    from claude_engram.hooks import remind

    saved_env = os.environ.get("CLAUDE_CODE_SESSION_ID")
    saved_sid = remind._session_id
    try:
        # No id anywhere -> shared fallback (older Claude Code).
        os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
        remind._session_id = ""
        check(
            "no id at all -> shared hook_state.json",
            remind.adopt_env_session_id() == ""
            and remind.get_state_file().name == "hook_state.json",
        )

        # Env id only -> adopted (the MCP server's case).
        os.environ["CLAUDE_CODE_SESSION_ID"] = "env-session"
        remind._session_id = ""
        adopted = remind.adopt_env_session_id()
        p = remind.get_state_file()
        check(
            "env id adopted -> sessions/<id>.json",
            adopted == "env-session"
            and p.name == "env-session.json"
            and p.parent.name == "sessions",
        )

        # A stdin-derived id must win: it is per-call truth, the environment is
        # process-level and outlives any single payload.
        remind._session_id = "stdin-session"
        check(
            "stdin id beats env id",
            remind.adopt_env_session_id() == "stdin-session"
            and remind.get_state_file().name == "stdin-session.json",
        )
        check(
            "adopt is idempotent",
            remind.adopt_env_session_id() == "stdin-session",
        )
    finally:
        remind._session_id = saved_sid
        if saved_env is None:
            os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
        else:
            os.environ["CLAUDE_CODE_SESSION_ID"] = saved_env


def test_mcp_reads_live_session_state():
    print("MCP-side state read (the session_end regression):")
    from claude_engram.hooks import remind

    saved_dir = os.environ.get("CLAUDE_ENGRAM_DIR")
    saved_env = os.environ.get("CLAUDE_CODE_SESSION_ID")
    saved_sid = remind._session_id
    with tempfile.TemporaryDirectory() as td:
        store = Path(td) / "store"
        (store / "sessions").mkdir(parents=True)
        # Stale shared file (what the bug surfaced) vs the live per-session file.
        (store / "hook_state.json").write_text(
            json.dumps(
                {
                    "last_session_start": time.time() - 15 * 86400,
                    "files_edited_this_session": [],
                }
            )
        )
        (store / "sessions" / "live-sess.json").write_text(
            json.dumps(
                {
                    "last_session_start": time.time() - 1800,
                    "files_edited_this_session": ["a.py", "b.py", "c.py"],
                }
            )
        )
        try:
            os.environ["CLAUDE_ENGRAM_DIR"] = str(store)
            os.environ["CLAUDE_CODE_SESSION_ID"] = "live-sess"

            remind._session_id = ""  # MCP server before adopting
            stale = remind.load_state()
            check(
                "without adopt: reads the stale shared file",
                len(stale.get("files_edited_this_session", [])) == 0,
            )

            remind.adopt_env_session_id()  # what server.py does at import
            live = remind.load_state()
            check(
                "after adopt: reads THIS session's state",
                len(live.get("files_edited_this_session", [])) == 3,
            )
        finally:
            remind._session_id = saved_sid
            if saved_dir is None:
                os.environ.pop("CLAUDE_ENGRAM_DIR", None)
            else:
                os.environ["CLAUDE_ENGRAM_DIR"] = saved_dir
            if saved_env is None:
                os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
            else:
                os.environ["CLAUDE_CODE_SESSION_ID"] = saved_env


def test_session_title_unit():
    print("Session title selection (deliberate only):")
    from claude_engram.hooks.remind import _session_title_from_checkpoint as title

    check("no entry -> no title", title({}) == "")
    check(
        "auto checkpoint -> no title (never stomps a chosen name)",
        title({"kind": "auto", "summary": "Session stopped. 2 files edited."}) == "",
    )
    check(
        "manual with no text -> no title",
        title({"kind": "manual", "summary": "   "}) == "",
    )
    t = title(
        {
            "kind": "manual",
            "task_description": "Migrating auth to OAuth2",
            "project_path": "/w/myproj",
        }
    )
    check("manual -> '<project>: <task>'", t == "myproj: Migrating auth to OAuth2")
    t2 = title(
        {
            "kind": "manual",
            "summary": "First line only\nsecond line dropped",
            "project_path": "/w/chappie",
        }
    )
    check("multi-line summary -> first line only", t2 == "chappie: First line only")
    t3 = title({"kind": "manual", "task_description": "x" * 200, "project_path": "/w/p"})
    check("long task truncated", len(t3) < 80 and t3.endswith("..."))
    check(
        "no project -> bare headline",
        title({"kind": "manual", "task_description": "Standalone"}) == "Standalone",
    )


SEED_SRC = '''
import time, sys
from pathlib import Path
from claude_engram.hooks import remind
from claude_engram import handoff_store as hs

kind, desc, project = sys.argv[1], sys.argv[2], sys.argv[3]
dirs = [d for d in (remind._project_hash_dir(project), remind._global_handoff_dir()) if d]
hs.write_handoff(
    {"kind": kind, "task_description": desc, "summary": desc,
     "project_path": project, "files_involved": [], "created": time.time(),
     "task_id": "task_test_1"},
    dirs,
)
'''


def test_session_title_through_hook():
    print("Session title through the real SessionStart hook:")
    py = sys.executable
    repo = Path(__file__).resolve().parent.parent

    for kind, desc, expect_title in [
        ("manual", "Migrating auth to OAuth2", True),
        ("auto", "Session stopped. 2 files edited.", False),
    ]:
        with tempfile.TemporaryDirectory() as td:
            store, project = Path(td) / "store", Path(td) / "proj"
            store.mkdir(parents=True)
            project.mkdir(parents=True)
            (project / "pyproject.toml").write_text("[project]\nname='proj'\n")

            env = dict(os.environ)
            env["CLAUDE_ENGRAM_DIR"] = str(store)
            env.pop("CLAUDE_CODE_SESSION_ID", None)

            seed_file = store / "_seed.py"
            seed_file.write_text(SEED_SRC)
            s = subprocess.run(
                [py, str(seed_file), kind, desc, str(project)],
                capture_output=True, text=True, env=env, cwd=str(repo),
            )
            if s.returncode != 0:
                check(f"{kind}: seed wrote a checkpoint", False)
                continue

            r = subprocess.run(
                [py, "-m", "claude_engram.hooks.remind", "session_start_json"],
                input=json.dumps(
                    {"session_id": "hook-title", "source": "startup", "cwd": str(project)}
                ),
                capture_output=True, text=True, env=env, cwd=str(project),
            )
            try:
                hso = json.loads(r.stdout)["hookSpecificOutput"]
            except Exception:
                check(f"{kind}: hook emitted parseable JSON", False)
                continue

            check(
                f"{kind}: hook output keeps a valid SessionStart schema",
                hso.get("hookEventName") == "SessionStart"
                and "additionalContext" in hso,
            )
            got = hso.get("sessionTitle")
            check(
                f"{kind}: sessionTitle {'set' if expect_title else 'absent'}"
                + (f" ({got!r})" if got else ""),
                (got is not None) == expect_title,
            )


if __name__ == "__main__":
    test_session_identity()
    test_mcp_reads_live_session_state()
    test_session_title_unit()
    test_session_title_through_hook()
    print("-" * 60)
    print(
        f"RESULTS: {'ALL PASS' if not _fails else str(len(_fails)) + ' FAILED: ' + str(_fails)}"
    )
    sys.exit(1 if _fails else 0)
