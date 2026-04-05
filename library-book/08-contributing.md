# Chapter 8 — Contributing

[← Back to Table of Contents](./README.md) · [Previous: The Gotchas](./07-the-gotchas.md) · [Next: The Roadmap →](./09-the-roadmap.md)

---

## Development Setup

```bash
# Clone
git clone https://github.com/20alexl/claude-engram.git
cd claude-engram

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install in development mode with all optional deps
pip install -e ".[semantic]"

# Install Ollama and pull model (for LLM-powered tools)
ollama pull gemma3:12b
```

## Running Tests

There's no formal test suite yet. Testing is done via inline verification:

```bash
# Basic import check
python -c "from claude_engram.server import server; print('OK')"

# Test memory system
python -c "
from claude_engram.tools.memory import MemoryStore, HotMemoryReader
m = MemoryStore()
m.remember_discovery('/tmp/test', 'Test', relevance=5)
assert m.recall(project_path='/tmp/test')['project'] is not None
m.forget_project('/tmp/test')
print('Memory OK')
"

# Test hooks compile
python -m py_compile claude_engram/hooks/remind.py && echo "OK"

# Test hook handlers match config
python -c "
import json, re, inspect
from claude_engram.hooks.remind import main
with open('hooks_config.json') as f:
    types = re.findall(r'remind\s+(\w+)', f.read())
source = inspect.getsource(main)
for t in types:
    assert f'\"{t}\"' in source, f'Missing: {t}'
print(f'All {len(types)} handlers present')
"
```

A proper pytest suite is a high-priority roadmap item.

## Code Style

No formal linter configured yet. Follow existing patterns:
- Type hints on function signatures
- Docstrings on public methods
- `snake_case` for everything
- Silent failure in hooks (`try/except: pass`) — hooks must never block Claude

## Before Submitting a PR

- [ ] All existing imports still work (`python -c "from claude_engram.server import server"`)
- [ ] `hooks_config.json` handler types match `main()` in `remind.py`
- [ ] `install.py`'s `get_hooks_config()` output matches `hooks_config.json`
- [ ] New hook handlers output proper JSON with `hookSpecificOutput.additionalContext`
- [ ] Memory changes preserve backward compatibility (existing `memory.json` files still load)
- [ ] No new dependencies in the base install (use `[optional]` extras)

## Project Structure for Contributors

| I want to... | Look in / Add to |
|--------------|-----------------|
| Add a new hook handler | `hooks/remind.py` `main()` function + `hooks_config.json` + `install.py` `get_hooks_config()` |
| Add a new MCP tool operation | `handlers.py` handler method + `tool_definitions_v2.py` schema + `server.py` route |
| Change memory behavior | `tools/memory.py` `MemoryStore` class |
| Change hook memory injection | `tools/memory.py` `HotMemoryReader` class |
| Add a new intent scorer | `hooks/intent.py` templates + `hooks/scorer_server.py` scoring logic |
| Fix a bug in session management | `tools/session.py` or `hooks/remind.py` session handlers |
| Update documentation | `library-book/` chapters or root `README.md` / `CLAUDE.md` |

## How Decisions Are Made

Feature requests and bug reports go to the [GitHub issues page](https://github.com/20alexl/claude-engram/issues). PRs are welcome for bug fixes and improvements that align with the design principles in [Chapter 2](./02-the-design.md).

---

[Next: The Roadmap →](./09-the-roadmap.md)
