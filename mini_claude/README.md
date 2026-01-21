# Mini Claude

Give Claude Code **persistent memory** across all your projects with smart habit tracking.

**The junior AI agent that remembers your mistakes, tracks your habits, and guides you toward better code.**

## What is This?

Mini Claude is an MCP server that gives Claude Code:
- 🧠 **Persistent memory** - Remembers discoveries and mistakes across sessions
- 📊 **Habit tracking** - Gamified feedback on your coding practices
- 🎯 **Smart suggestions** - Context-aware tool recommendations
- 🛡️ **Safety guards** - Loop detection, scope protection, output validation
- 🤖 **Local AI** - Uses Ollama (no cloud, no API costs)

## Quick Install

```bash
# 1. Install Ollama (if not already installed)
# Visit https://ollama.ai or:
curl -fsSL https://ollama.com/install.sh | sh

# 2. Pull the model
ollama pull qwen2.5-coder:7b

# 3. Clone and install Mini Claude
git clone https://github.com/20alexl/mini_claude.git
cd mini_claude

# 4. Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# 5. Install the package
pip install -e mini_claude/

# 6. Run the installer
python install.py
```

The installer will:
- Create launcher scripts
- Generate a global MCP configuration
- Set up hooks
- Show you how to use it

**Note:** The `venv` directory must stay! VSCode runs Mini Claude from `venv/bin/python`. Don't delete it or move the repo after installation.

## Setup for Your Projects

**Mini Claude works globally** - you install it once and it works in all projects!

### Option 1: Copy CLAUDE.md (Recommended)

Copy the `CLAUDE.md` file from this repo to your project root:

```bash
cp /path/to/mini_claude/CLAUDE.md /your/project/CLAUDE.md
```

**What is CLAUDE.md?**
- Instructions for Claude Code on how to use Mini Claude
- Checked into your repo (like a README for AI)
- Claude reads it automatically when working on your project
- Ensures Claude uses Mini Claude tools correctly

**Do you NEED it?** No, but highly recommended! Without it:
- Claude won't know to call `session_start`
- Won't know when to use which tools
- Won't follow best practices

With it:
- Claude automatically starts sessions
- Uses tools at the right time
- Logs mistakes and decisions
- Follows project conventions

### Option 2: Per-Project .mcp.json (Advanced)

If you want project-specific MCP configuration:

```bash
python install.py --setup /path/to/your/project
```

This creates a `.mcp.json` in your project that overrides the global config.

**Most users don't need this** - the global setup works great!

## How to Use

1. **Open your project in VSCode**
2. **Start Claude Code**
3. **Claude will automatically:**
   - Read `CLAUDE.md` (if present)
   - Start a session with `session_start`
   - Load project memories
   - Show you past mistakes to avoid

**That's it!** Mini Claude runs automatically via hooks.

## Getting Started: Your First Prompt

**IMPORTANT:** Give Claude a clear, complete prompt upfront. This helps Mini Claude guide the entire project effectively.

### Example Prompt Template

```
Build a [PROJECT TYPE] in Python with the following requirements:

CORE FEATURES:
1. [Feature 1]
2. [Feature 2]
3. [Feature 3]

TECHNICAL REQUIREMENTS:
- [Database/storage choice]
- [Authentication if needed]
- [Libraries to use]
- [Error handling requirements]
- [Testing requirements with coverage %]
- [Type hints/documentation requirements]

PROJECT STRUCTURE:
project_name/
├── src/
│   ├── __init__.py
│   ├── main.py
│   └── [other modules]
├── tests/
│   └── [test files]
├── README.md
└── requirements.txt

IMPLEMENTATION STEPS:
1. [Step 1]
2. [Step 2]
3. [Step 3]

CONSTRAINTS:
- [Edge cases to handle]
- [Validation requirements]
- [Performance requirements]

CONVENTIONS TO FOLLOW:
- Use snake_case for Python code
- Maximum function length: 50 lines
- Write docstrings for all public functions
- Use pathlib instead of os.path
```

### Real Example: Personal Finance CLI Tracker

<details>
<summary>Click to see a complete example prompt</summary>

```
Build a personal finance CLI tracker in Python with the following requirements:

CORE FEATURES:
1. Track expenses and income with categories
2. Set monthly budgets per category
3. Generate monthly spending reports
4. Support multiple currencies with conversion
5. Export data to CSV and JSON
6. Recurring transactions (monthly bills, salary)

TECHNICAL REQUIREMENTS:
- Use SQLite for data storage
- Support user authentication
- Use rich library for beautiful CLI output
- Comprehensive error handling
- pytest tests with >80% coverage
- Type hints throughout
- Security best practices (encrypted passwords)

PROJECT STRUCTURE:
finance_tracker/
├── finance_tracker/
│   ├── __init__.py
│   ├── cli.py          # Main CLI interface
│   ├── database.py     # Database operations
│   ├── models.py       # Data models
│   ├── auth.py         # User authentication
│   ├── currency.py     # Currency conversion
│   ├── reports.py      # Report generation
│   └── config.py       # Configuration
├── tests/
│   ├── test_database.py
│   ├── test_auth.py
│   └── test_reports.py
├── README.md
├── requirements.txt
└── setup.py

IMPLEMENTATION STEPS:
1. Set up project structure
2. Implement database schema
3. Build authentication system
4. Create transaction tracking
5. Add budget management
6. Implement currency conversion
7. Build reporting features
8. Write comprehensive tests
9. Add CLI interface with rich
10. Document everything

CONSTRAINTS:
- Handle negative amounts, invalid dates, duplicates
- Validate all user input
- Support data import/export
- Work offline (except currency conversion)
- Installable via pip

CONVENTIONS TO FOLLOW:
- Use snake_case for all Python code
- Maximum function length: 50 lines
- Write docstrings for all public functions
- Use pathlib instead of os.path
- Prefer composition over inheritance
- Never use bare except clauses
```

</details>

**Why this approach works:**
- ✅ Claude sees the full scope upfront
- ✅ Mini Claude can suggest relevant tools early
- ✅ Scope guard knows what files are in scope
- ✅ Decision logging captures architectural choices
- ✅ You get better, more focused results

**After the initial prompt:**
Just interact normally! Ask Claude questions, request changes, debug issues. Mini Claude works in the background.

## Your First Session

When you start working, Claude will see:

```
📊 Your Habits (last 7 days):

🌱 Just getting started!

Mini Claude will track your habits as you work:
  • Using Thinker tools before risky work
  • Avoiding death spiral loops
  • Building good coding practices

💡 Quick Start:
  1. On your next architectural task, try think_explore
  2. When editing auth/security files, use think_best_practice
  3. If you edit the same file 3+ times, check think_challenge

Check back in a few days to see your progress!
```

## Key Features

### 1. Smart Tool Suggestions

Instead of listing all tools, Mini Claude suggests THE RIGHT ONE:

```
⚠️ ARCHITECTURAL TASK DETECTED: 'authentication'

⚠️ RECOMMENDED: Start with think_best_practice
   WHY: Security is critical - learn the 2026 best practices first
```

### 2. Habit Tracking & Gamification

After a few days of use:

```
📊 Your Habits (last 7 days):
✅ Excellent! You used Thinker tools 85% of the time before risky work
   Keep building this habit!

🌟 Perfect! You avoided 3 potential loop(s)
```

### 3. Context-Aware Loop Detection

- 3+ edits + tests **passing** = iterative improvement ✅
- 3+ edits + tests **failing** = death spiral 🛑 (blocks!)

### 4. Session Exit Handoff

Before ending a session:

```
mcp__mini-claude__habit_session_summary(project_path="/your/project")
```

Creates a comprehensive summary for the next Claude instance:
- Files edited & why
- Decisions made & reasoning
- Mistakes logged
- Habit performance
- Tips for next session

## All 55 Tools

### 🔑 Essential (Start Here!)
| Tool | What It Does |
|------|--------------|
| `session_start` | Load memories + warnings (START EVERY SESSION) |
| `work_log_mistake` | Log mistakes so you don't repeat them |
| `work_log_decision` | Log WHY you made choices |
| `habit_session_summary` | Create handoff for next session |

### 🧠 Session & Memory
| Tool | What It Does |
|------|--------------|
| `session_start` | Load project context |
| `memory_remember` | Store discoveries |
| `memory_recall` | Get memories |
| `memory_forget` | Clear memories |

### 📝 Work Tracking
| Tool | What It Does |
|------|--------------|
| `work_log_mistake` | Log when things break |
| `work_log_decision` | Log why you did something |
| `work_pre_edit_check` | Check context before editing |
| `work_session_summary` | See what happened |
| `work_save_session` | Persist to memory |

### 🛡️ Safety Guards
| Tool | What It Does |
|------|--------------|
| `code_quality_check` | Check code before writing |
| `loop_record_edit` | Record edit for loop detection |
| `loop_check_before_edit` | Check if editing might loop |
| `loop_record_test` | Record test results |
| `loop_status` | Get loop status |
| `scope_declare` | Declare files in scope |
| `scope_check` | Check if file in scope |
| `scope_expand` | Add files to scope |
| `scope_status` | Get scope status |
| `scope_clear` | Clear scope |

### 💾 Context Protection
| Tool | What It Does |
|------|--------------|
| `context_checkpoint_save` | Save task state |
| `context_checkpoint_restore` | Restore task state |
| `context_checkpoint_list` | List checkpoints |
| `context_instruction_add` | Add critical instruction |
| `context_instruction_reinforce` | Get reminders |
| `context_claim_completion` | Claim task complete |
| `context_self_check` | Verify claimed work |
| `context_handoff_create` | Create handoff |
| `context_handoff_get` | Get previous handoff |

### ✅ Output Validation
| Tool | What It Does |
|------|--------------|
| `output_validate_code` | Detect silent failures |
| `output_validate_result` | Check for fake outputs |

### 🔍 Search & Analysis
| Tool | What It Does |
|------|--------------|
| `scout_search` | Search codebase semantically |
| `scout_analyze` | Analyze code with LLM |
| `file_summarize` | Summarize a file |
| `deps_map` | Map dependencies |
| `impact_analyze` | Check what depends on file |

### 📋 Conventions
| Tool | What It Does |
|------|--------------|
| `convention_add` | Store coding rule |
| `convention_get` | Get project rules |
| `convention_check` | Check code against rules |

### 🧪 Testing & Git
| Tool | What It Does |
|------|--------------|
| `test_run` | Auto-detect and run tests |
| `test_can_claim_completion` | Check if tests allow completion |
| `git_generate_commit_message` | Generate from work logs |
| `git_auto_commit` | Auto-commit with context |

### 🚀 Momentum Tracking
| Tool | What It Does |
|------|--------------|
| `momentum_start_task` | Track multi-step task |
| `momentum_complete_step` | Mark step complete |
| `momentum_check` | Check momentum |
| `momentum_finish_task` | Mark task complete |
| `momentum_status` | Get status |

### 💭 Thinking Partner
| Tool | What It Does |
|------|--------------|
| `think_research` | Deep research (web + codebase + LLM) |
| `think_compare` | Compare options with pros/cons |
| `think_challenge` | Challenge assumptions |
| `think_explore` | Explore solution space |
| `think_best_practice` | Find 2026 best practices |

### 📊 Habit Tracking (NEW!)
| Tool | What It Does |
|------|--------------|
| `habit_get_stats` | View habit statistics |
| `habit_get_feedback` | Get gamified feedback |
| `habit_session_summary` | Comprehensive session summary |

### 🔧 Status
| Tool | What It Does |
|------|--------------|
| `mini_claude_status` | Health check |

## Architecture

```
┌─────────────────────────────────────────────┐
│           Claude Code (Main AI)             │
└──────────────────┬──────────────────────────┘
                   │
    ┌──────────────┴──────────────┐
    │                             │
    ▼                             ▼
┌─────────────┐          ┌─────────────────┐
│ MCP Server  │          │ Hooks (Auto)    │
│(Mini Claude)│          │   + CLAUDE.md   │
└──────┬──────┘          └────────┬────────┘
       │                          │
       ▼                          ▼
┌───────────────────────────────────────────┐
│        ~/.mini_claude/ (State)            │
│  • memory.json - Project memories         │
│  • habits.json - Habit tracking           │
│  • conventions.json - Project rules       │
│  • loop_detector.json - Edit tracking     │
│  • scope_guard.json - Scope tracking      │
└───────────────────────────────────────────┘
       │
       ▼
┌───────────────────────────────────────────┐
│     Ollama (Local LLM - qwen2.5-coder)    │
└───────────────────────────────────────────┘
```

## Requirements

- **Python 3.10+**
- **[Ollama](https://ollama.ai)** with `qwen2.5-coder:7b`
- **Claude Code** (VSCode extension)

## Configuration

### Use a Different Model

```bash
# Use a different model
export MINI_CLAUDE_MODEL="qwen2.5-coder:14b"

# Custom Ollama URL
export MINI_CLAUDE_OLLAMA_URL="http://192.168.1.100:11434"
```

Add to `~/.bashrc` or `~/.zshrc` to make permanent.

**Recommended models:**
- `qwen2.5-coder:7b` (default) - Fast, good quality
- `qwen2.5-coder:14b` - Better quality, slower
- `codellama:7b` - Alternative
- `deepseek-coder:6.7b` - Another option

## Troubleshooting

### MCP Server Not Connecting

1. Check Ollama is running: `ollama list`
2. Restart VSCode completely
3. Check Claude Code → "MCP Servers" status
4. Approve the mini-claude server when prompted

### "No such tool available"

The MCP server isn't loaded. Steps:
1. Check `~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json` exists
2. Restart VSCode
3. Wait for Claude Code to load MCP servers
4. Try again

### Ollama Not Running

```bash
ollama serve  # Start Ollama in background
ollama pull qwen2.5-coder:7b  # Pull the model
```

### Package Not Found

```bash
cd /path/to/mini_claude
source venv/bin/activate
pip install -e mini_claude/
```

## Why Local LLM?

- ✅ **Privacy** - Code never leaves your machine
- ✅ **Speed** - No network latency
- ✅ **Cost** - No API fees
- ✅ **Reliability** - Works offline

The 7B model is sufficient for search, summaries, and pattern recognition.

## FAQs

### Do I need CLAUDE.md in every project?

**Recommended but not required.** Without it:
- Claude won't know to start sessions
- Won't use tools effectively
- Might forget to log mistakes

With it:
- Claude follows best practices automatically
- Uses Mini Claude properly
- Logs work correctly

**Think of it as a README for AI** - you'd include a README in your project, right?

### What's the difference between .mcp.json and CLAUDE.md?

- **`.mcp.json`**: MCP server configuration (global or per-project)
  - Tells VSCode how to connect to Mini Claude
  - Usually global (install once, works everywhere)

- **`CLAUDE.md`**: Instructions for Claude Code (per-project)
  - Tells Claude how to use Mini Claude tools
  - Checked into your repo
  - Ensures consistent behavior

### Can I use Mini Claude with multiple projects?

**Yes!** That's the default setup. Install once, use everywhere. Each project gets its own:
- Memories
- Habit tracking
- Conventions
- Work logs

### Does it slow down Claude Code?

**No!**
- Tools run asynchronously
- Hooks are fast (< 100ms)
- LLM calls are cached
- Most tools don't use the LLM at all

### Do I need to keep the venv folder?

**Yes!** The venv must stay where you installed it. Here's why:

- VSCode runs Mini Claude from `venv/bin/python`
- The MCP configuration points to this path
- If you move/delete the venv, Mini Claude stops working

**What you CAN do:**
- Use Mini Claude from multiple projects (it's global)
- Copy CLAUDE.md to different repos
- Have different memories per project

**What you CAN'T do:**
- Move the mini_claude repo after installation
- Delete the venv folder
- Rename the venv folder

If you need to reinstall, just run `python install.py` again.

## Contributing

PRs welcome! The goal: make Claude Code more reliable through memory and habit formation.

## License

MIT

---

**Built with ❤️ to make AI coding assistants actually remember things.**
