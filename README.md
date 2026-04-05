# Claude Engram

Persistent memory and self-awareness for Claude Code. Tracks mistakes, decisions, and context across sessions automatically via hooks. Includes loop detection, scope guards, tiered memory with archiving, semantic intent scoring, and a local LLM for code analysis.

## Features

- **Auto-tracks mistakes** from any failed tool. Warns before editing the same file again.
- **Auto-captures decisions** from user prompts ("let's use X instead of Y") via semantic + regex scoring.
- **Detects edit loops** when the same file is edited 3+ times without progress.
- **Survives compaction** by auto-saving checkpoints and re-injecting rules/mistakes after.
- **Saves session handoffs** so the next session picks up where you left off.
- **Archives old memories** to cold storage instead of deleting. Searchable, restorable.
- **Scores and injects context** before every edit, surfacing the 3 most relevant memories.
- **Scopes memory per project** in multi-project workspaces. Workspace-level rules cascade down.

Most of this works automatically via Claude Code hooks. No tool invocations needed.

## Install

```bash
# 1. Ollama (for semantic search / code analysis)
ollama pull gemma3:12b

# 2. Clone and install
git clone https://github.com/20alexl/claude-engram.git
cd claude-engram
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

pip install -e .                # Base
pip install -e ".[semantic]"    # + AllMiniLM decision capture (recommended)

# 3. Configure hooks + MCP server
python install.py
```

### Per-Project Setup

```bash
python install.py --setup /path/to/your/project
```

Or copy `.mcp.json` and `CLAUDE.md` to your project root manually.

## Quick Usage

After install, Claude Engram works automatically. You'll see hook output like:

```
Claude Engram session started (startup)
Rules (2):
  [a1b2c3] Always use strict TypeScript
Past mistakes (1):
  [d4e5f6] Broke the auth middleware by removing the session check
Edit tracked: server.py (edit #2)
FAIL Test tracked
Auto-logged: Import error: Module 'flask' not found
```

For manual operations:

```python
memory(operation="remember", content="...", project_path="/path")
memory(operation="add_rule", content="Always do X", project_path="/path")
work(operation="log_decision", decision="...", reason="...")
scout_search(query="how does auth work", directory="/path")
```

## Configuration

```bash
export MINI_CLAUDE_MODEL="gemma3:27b"           # Ollama model (default: gemma3:12b)
export MINI_CLAUDE_OLLAMA_URL="http://host:11434" # Remote Ollama
export MINI_CLAUDE_KEEP_ALIVE="5m"               # Keep model loaded
export MINI_CLAUDE_ARCHIVE_DAYS=30               # Archive threshold (default: 14)
export MINI_CLAUDE_SCORER_TIMEOUT=3600           # Scorer idle timeout (default: 1800)
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| MCP server not connecting | Check `ollama list`, restart Claude Code |
| Hooks not firing | Run `python install.py` to reinstall |
| Memories not showing | `memory(operation="archive_status", project_path="/path")` to check counts |
| `ModuleNotFoundError` | Activate the venv first |

## Documentation

**[Read the Library Book](./library-book/)** for the complete guide: design principles, internals, full usage guide, advanced features, gotchas, and complete tool reference.

## License

MIT
