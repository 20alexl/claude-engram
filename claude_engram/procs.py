"""Census of the engram processes on this machine: role, pid, memory, age.

Shown by ``claude_engram_status`` so a pile of daemons or miners is visible
from inside a session instead of from Task Manager after the fact
(2026-09-25: the machine ran out of commit charge under a chain of
orphaned scorer daemons and stacked miners).
"""

import time

ROLES = (
    ("claude_engram.hooks.scorer_server", "scorer"),
    ("claude_engram.mining.background", "miner"),
    ("claude_engram.embed_worker", "embed worker"),
    ("claude_engram.migrations", "migration"),
    ("claude_engram.server", "mcp server"),
    ("hook_client", "hook"),
    ("claude_engram.hooks.remind", "hook"),
)


def _role(cmdline: str) -> str:
    for needle, role in ROLES:
        if needle in cmdline:
            return role
    return "other" if "claude_engram" in cmdline else ""


def census() -> list[dict]:
    """One row per engram process (a venv launcher stub is folded into the
    interpreter it started). Empty when psutil is unavailable."""
    try:
        import psutil
    except ImportError:
        return []
    now = time.time()
    procs: dict[int, psutil.Process] = {}
    cmdlines: dict[int, str] = {}
    for p in psutil.process_iter(["pid", "cmdline", "memory_info", "create_time"]):
        try:
            cmdline = " ".join(p.info["cmdline"] or [])
        except Exception:
            continue
        if _role(cmdline):
            procs[p.info["pid"]] = p
            cmdlines[p.info["pid"]] = cmdline
    rows: list[dict] = []
    for pid, p in procs.items():
        cmdline = cmdlines[pid]
        try:
            # A venv launcher runs the real interpreter as a child with the
            # same command line; report the child, not the stub.
            if any(cmdlines.get(c.pid) == cmdline for c in p.children()):
                continue
        except psutil.Error:
            continue
        mem = p.info["memory_info"]
        rss = (mem.rss if mem else 0) / 1e6
        rows.append(
            {
                "pid": pid,
                "role": _role(cmdline),
                "rss_mb": int(rss),
                "commit_mb": int((mem.vms if mem else 0) / 1e6),
                "age_min": round((now - (p.info["create_time"] or now)) / 60, 1),
            }
        )
    rows.sort(key=lambda r: (-r["rss_mb"], r["pid"]))
    return rows


def census_lines(rows: list[dict]) -> list[str]:
    """Human lines for the status report, with the totals that matter."""
    if not rows:
        return ["Processes: none found (or psutil unavailable)"]
    by_role: dict[str, list[dict]] = {}
    for r in rows:
        by_role.setdefault(r["role"], []).append(r)
    lines = [
        f"Processes: {len(rows)} engram, {sum(r['rss_mb'] for r in rows)} MB resident, "
        f"{sum(r['commit_mb'] for r in rows)} MB committed"
    ]
    for role, group in sorted(by_role.items()):
        lines.append(
            f"  {role}: {len(group)} "
            + ", ".join(f"pid {r['pid']} {r['rss_mb']} MB {r['age_min']} min" for r in group[:6])
        )
    scorers = by_role.get("scorer", [])
    if len(scorers) > 1:
        lines.append(f"  WARNING: {len(scorers)} scorer daemons; one is the design")
    miners = by_role.get("miner", [])
    if len(miners) > 1:
        lines.append(f"  WARNING: {len(miners)} miners; the lock allows one")
    return lines
