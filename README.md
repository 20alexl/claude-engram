# Mini Claude

Persistent memory for Claude Code. Stores mistakes, decisions, and task state across sessions.

## What It Does

Claude Code forgets everything between sessions and after context compaction. Mini Claude stores:

- **Checkpoints** - Save task state, restore after compaction
- **Mistakes** - Log errors so you don't repeat them
- **Decisions** - Log why you chose something
- **Memories** - General notes and discoveries

Runs locally with Ollama. No cloud, no API costs.

## Install

### Requirements

- Python 3.10+
- [Ollama](https://ollama.ai) with `qwen2.5-coder:7b`
- Claude Code (VSCode extension)

### Steps

```bash
# 1. Install Ollama and pull model
ollama pull qwen2.5-coder:7b

# 2. Clone and install
git clone https://github.com/20alexl/mini_claude.git
cd mini_claude
python -m venv venv

# Linux/Mac
source venv/bin/activate

# Windows
venv\Scripts\activate

pip install -e mini_claude/

# 3. Run installer
python install.py
```

The installer creates launcher scripts and MCP configuration.

**Don't delete the venv folder** - VSCode runs Mini Claude from it.

## Setup Per Project

Copy `CLAUDE.md` to your project root. This tells Claude how to use Mini Claude.

The `.mcp.json` is usually global (installed once, works everywhere).

## Tools

### Essential

| Tool | Purpose |
|------|---------|
| `session_start` | Load memories + checkpoint |
| `session_end` | Save work summary |
| `pre_edit_check` | Check before editing files |

### Memory

```
memory(operation="remember", content="...", project_path="...")
memory(operation="search", project_path="...", query="...")
```

### Work Tracking

```
work(operation="log_mistake", description="...", file_path="...")
work(operation="log_decision", decision="...", reason="...")
```

### Context (Checkpoints)

```
context(operation="checkpoint_save", task_description="...", current_step="...", ...)
context(operation="checkpoint_restore")
```

### Analysis

| Tool | Purpose |
|------|---------|
| `impact_analyze` | See what depends on a file |
| `deps_map` | Map file dependencies |
| `scout_search` | Search codebase |

### Think

```
think(operation="audit", file_path="...")
think(operation="challenge", assumption="...")
think(operation="research", question="...", project_path="...")
```

## Configuration

```bash
# Different model
export MINI_CLAUDE_MODEL="qwen2.5-coder:14b"

# Remote Ollama
export MINI_CLAUDE_OLLAMA_URL="http://192.168.1.100:11434"
```

## Troubleshooting

### MCP Server Not Connecting

1. Check Ollama is running: `ollama list`
2. Restart VSCode
3. Check Claude Code → MCP Servers status

### Ollama Not Running

```bash
ollama serve
ollama pull qwen2.5-coder:7b
```

## Architecture

```
Claude Code
    │
    ├── MCP Server (Mini Claude)
    │       │
    │       └── ~/.mini_claude/ (state files)
    │
    └── Ollama (local LLM)
```

State is stored in `~/.mini_claude/` per project.

## License

MIT
