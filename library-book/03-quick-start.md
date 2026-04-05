# Chapter 3 — Quick Start

[← Back to Table of Contents](./README.md) · [Previous: The Design](./02-the-design.md) · [Next: The Internals →](./04-the-internals.md)

---

## Install

```bash
# 1. Install Ollama and pull the default model
ollama pull gemma3:12b

# 2. Clone and install
git clone https://github.com/20alexl/claude-engram.git
cd claude-engram
python -m venv venv

# Linux/Mac
source venv/bin/activate
# Windows
venv\Scripts\activate

# Base install
pip install -e .

# With semantic decision capture (recommended)
pip install -e ".[semantic]"

# 3. Run installer
python install.py
```

### Requirements

- Python 3.10+
- Ollama (for semantic search and code analysis)
- Claude Code (CLI, desktop app, or IDE extension)

## First Use

After running `install.py`, open any project in Claude Code. Claude Engram starts working immediately — no commands needed.

You'll see hook output like:

```
Claude Engram session started (startup)
Rules (2):
  [a1b2c3] Always use strict TypeScript
  [d4e5f6] Never commit .env files
Past mistakes (1):
  [g7h8i9] Broke the auth middleware by removing the session check
```

## Verify It Works

```bash
# Check that the MCP server responds
python -c "from mini_claude.server import server; print('OK')"

# Check hooks are installed
python -m mini_claude.hooks.remind prompt_json < /dev/null
```

## Set Up a Project

```bash
# Option 1: Installer
python install.py --setup /path/to/your/project

# Option 2: Manual
# Copy .mcp.json and CLAUDE.md to your project root
```

## Common Setup Issues

| Issue | Fix |
|-------|-----|
| `ModuleNotFoundError: mini_claude` | Activate the venv: `source mini_claude/venv/bin/activate` |
| MCP server not showing in Claude Code | Restart Claude Code. Check `.mcp.json` exists in project root. |
| Ollama connection refused | Start Ollama: `ollama serve` |
| Hooks not firing | Run `python install.py` to reinstall hooks to `~/.claude/settings.json` |
| `sentence-transformers` not found | Install with: `pip install -e ".[semantic]"` (optional, regex fallback works) |

## What's Next

- **[Usage Guide (Chapter 5)](./05-usage-guide.md)** — learn the main features
- **[The Internals (Chapter 4)](./04-the-internals.md)** — understand how it works under the hood

---

[Next: The Internals →](./04-the-internals.md)
