# Mini Claude

Persistent memory for Claude Code. Also: loop detection, scope guards, code analysis, and a local LLM for second opinions.

## What It Does

Claude Code forgets everything between sessions and after context compaction. Mini Claude provides:

- **Checkpoints** - Save task state, auto-restore after compaction
- **Mistake memory** - Log errors, get warned next time you touch that file
- **Decision memory** - Log WHY you chose something
- **Loop detection** - Warns when editing same file 3+ times (death spiral)
- **Scope guards** - Declare allowed files, prevent over-refactoring
- **Impact analysis** - See what depends on a file before changing it
- **Convention storage** - Store project rules, check code against them
- **Think tools** - Get second opinion from local 7B model

Runs locally with Ollama. No cloud, no API costs.

## Install

### Requirements

- Python 3.10+
- [Ollama](https://ollama.ai) with `qwen2.5-coder:7b`
- Claude Code (VSCode extension or CLI)

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

# Windows (PowerShell)
.\venv\Scripts\Activate.ps1
# Windows (cmd)
venv\Scripts\activate.bat

pip install -e mini_claude/

# 3. Run installer
python install.py
```

The installer creates launcher scripts and MCP configuration.

**Don't delete the venv folder** - VSCode runs Mini Claude from it.

## Setup Per Project

Copy [`CLAUDE.md`](CLAUDE.md) to your project root. This tells Claude how to use Mini Claude.

## Tools

### Session Management

| Tool | Purpose |
|------|---------|
| `session_start` | Load memories, mistakes, checkpoint |
| `session_end` | Save work summary (no args needed) |
| `pre_edit_check` | Check mistakes, loops, scope before editing |

### Memory & Work Tracking

| Tool | Purpose |
|------|---------|
| `memory(remember/search/clusters)` | Store and find discoveries |
| `work(log_mistake)` | Record error + how to avoid |
| `work(log_decision)` | Record choice + reasoning |

### Context Protection

| Tool | Purpose |
|------|---------|
| `context(checkpoint_save)` | Save task state for compaction survival |
| `context(checkpoint_restore)` | Restore after compaction |
| `context(verify_completion)` | Verify task is actually done |

### Scope & Loop Detection

| Tool | Purpose |
|------|---------|
| `scope(declare)` | Set allowed files for task |
| `scope(check)` | Verify file is in scope |
| `loop(check)` | Check if editing too much |

### Code Analysis

| Tool | Purpose |
|------|---------|
| `impact_analyze` | What depends on this file |
| `deps_map` | Map imports/dependencies |
| `scout_search` | Semantic codebase search (reads actual code) |
| `scout_analyze` | Analyze code snippet with LLM |
| `file_summarize` | Quick file purpose summary |
| `code_quality_check` | Detect AI slop |
| `audit_batch` | Audit multiple files |
| `find_similar_issues` | Find bug patterns |

### Think (Local LLM)

| Tool | Purpose |
|------|---------|
| `think(research)` | Research with codebase context |
| `think(compare)` | Evaluate options |
| `think(challenge)` | Devil's advocate |
| `think(audit)` | Find issues in file |

### Conventions

| Tool | Purpose |
|------|---------|
| `convention(add)` | Store project rule |
| `convention(check)` | Check code against rules |
| `code_pattern_check` | Check against conventions with LLM |

### Validation

| Tool | Purpose |
|------|---------|
| `output(validate_code)` | Check for silent failures |
| `git(commit_message)` | Generate commit from work logs |

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

```text
Claude Code
    │
    ├── MCP Server (Mini Claude)
    │       │
    │       └── ~/.mini_claude/ (state files)
    │
    └── Ollama (local LLM)
```

State is stored in `~/.mini_claude/` per project.

## Issues

Report bugs or request features: https://github.com/20alexl/mini_claude/issues

## License

MIT
