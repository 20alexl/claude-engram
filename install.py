#!/usr/bin/env python3
"""
Claude Engram Installer

Sets up Claude Engram for use with Claude Code:
1. Creates virtual environment (if needed)
2. Installs the mini_claude package
3. Shows how to enable in your projects

Usage:
  cd claude-engram
  python -m venv venv
  source venv/bin/activate  # or venv\\Scripts\\activate on Windows
  pip install -e mini_claude/
  python install.py

Requirements:
  - Python 3.10+
  - Ollama running with gemma3:12b (or another model)
  - Claude Code installed
"""

import json
import os
import platform
import subprocess
import sys
from pathlib import Path


def is_windows():
    """Check if running on Windows."""
    return platform.system() == "Windows"


def print_step(step: int, total: int, message: str):
    """Print a step message."""
    print(f"\n[{step}/{total}] {message}")


def print_success(message: str):
    """Print a success message."""
    print(f"  ✓ {message}")


def print_error(message: str):
    """Print an error message."""
    print(f"  ✗ {message}")


def print_warning(message: str):
    """Print a warning message."""
    print(f"  ⚠ {message}")


def check_venv():
    """Check if running in a virtual environment."""
    return sys.prefix != sys.base_prefix


def check_ollama():
    """Check if Ollama is running."""
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def check_package_installed():
    """Check if mini_claude package is installed."""
    try:
        import mini_claude
        return True
    except ImportError:
        return False


def install_package():
    """Install the mini_claude package."""
    script_dir = Path(__file__).parent.resolve()

    # pyproject.toml is at the repo root (same dir as install.py)
    if not (script_dir / "pyproject.toml").exists():
        return False, "pyproject.toml not found in repo root"

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", str(script_dir)],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            return False, result.stderr
        return True, None
    except Exception as e:
        return False, str(e)


def create_memory_dir():
    """Create the Claude Engram memory directory."""
    memory_dir = Path.home() / ".mini_claude"
    memory_dir.mkdir(parents=True, exist_ok=True)
    return str(memory_dir)


def create_launcher_script():
    """Create a launcher script that handles paths with spaces."""
    script_dir = Path(__file__).parent.resolve()
    scripts_dir = script_dir / "scripts"
    scripts_dir.mkdir(exist_ok=True)

    if is_windows():
        launcher = scripts_dir / "run_server.bat"
        launcher_content = '@echo off\nsetlocal\nset "SCRIPT_DIR=%%~dp0"\n"%%SCRIPT_DIR%%..\\venv\\Scripts\\python.exe" -m mini_claude.server %%*\n'
        try:
            launcher.write_text(launcher_content.replace('%%', '%'))
            return str(launcher)
        except Exception:
            return None
    else:
        launcher = scripts_dir / "run_server.sh"
        launcher_content = '#!/bin/bash\nSCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n"${SCRIPT_DIR}/../venv/bin/python" -m mini_claude.server "$@"\n'
        try:
            launcher.write_text(launcher_content)
            launcher.chmod(0o755)
            return str(launcher)
        except Exception:
            return None


def create_hook_launcher_script():
    """Create a hook launcher script that handles paths with spaces."""
    script_dir = Path(__file__).parent.resolve()
    scripts_dir = script_dir / "scripts"
    scripts_dir.mkdir(exist_ok=True)

    if is_windows():
        hook_launcher = scripts_dir / "run_hook.bat"
        hook_content = '@echo off\nsetlocal\nset "SCRIPT_DIR=%%~dp0"\n"%%SCRIPT_DIR%%..\\venv\\Scripts\\python.exe" -m mini_claude.hooks.remind %%*\n'
        try:
            hook_launcher.write_text(hook_content.replace('%%', '%'))
            return str(hook_launcher)
        except Exception:
            return None
    else:
        hook_launcher = scripts_dir / "run_hook.sh"
        hook_content = '#!/bin/bash\nSCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n"${SCRIPT_DIR}/../venv/bin/python" -m mini_claude.hooks.remind "$@"\n'
        try:
            hook_launcher.write_text(hook_content)
            hook_launcher.chmod(0o755)
            return str(hook_launcher)
        except Exception:
            return None


def get_hooks_config():
    """Generate the hooks configuration for ~/.claude/settings.json."""
    script_dir = Path(__file__).parent.resolve()

    if is_windows():
        hook_launcher = script_dir / "scripts" / "run_hook.bat"
        hook_cmd = str(hook_launcher)
        # Windows uses 2>NUL for stderr redirection
        stderr_redirect = "2>NUL"
    else:
        hook_launcher = script_dir / "scripts" / "run_hook.sh"
        hook_cmd = str(hook_launcher)
        # Unix uses 2>/dev/null for stderr redirection
        stderr_redirect = "2>/dev/null"

    return {
        "hooks": {
            "UserPromptSubmit": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f'"{hook_cmd}" prompt_json {stderr_redirect} || echo ""',
                            "timeout": 2000
                        }
                    ]
                }
            ],
            "PreToolUse": [
                {
                    "matcher": "Edit|Write",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f'"{hook_cmd}" pre_edit_json {stderr_redirect} || echo ""',
                            "timeout": 1000
                        }
                    ]
                }
            ],
            "PostToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f'"{hook_cmd}" bash_json {stderr_redirect} || echo ""',
                            "timeout": 1000
                        }
                    ]
                },
                {
                    "matcher": "Edit|Write",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f'"{hook_cmd}" post_edit_json {stderr_redirect} || echo ""',
                            "timeout": 1000
                        }
                    ]
                }
            ],
            "PostToolUseFailure": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f'"{hook_cmd}" tool_failure_json {stderr_redirect} || echo ""',
                            "timeout": 1000
                        }
                    ]
                }
            ],
            "PreCompact": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f'"{hook_cmd}" pre_compact_json {stderr_redirect} || echo ""',
                            "timeout": 2000
                        }
                    ]
                }
            ],
            "PostCompact": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f'"{hook_cmd}" post_compact_json {stderr_redirect} || echo ""',
                            "timeout": 2000
                        }
                    ]
                }
            ],
            "SessionStart": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f'"{hook_cmd}" session_start_json {stderr_redirect} || echo ""',
                            "timeout": 2000
                        }
                    ]
                }
            ],
            "Stop": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f'"{hook_cmd}" stop_json {stderr_redirect} || echo ""',
                            "timeout": 2000
                        }
                    ]
                }
            ],
            "SessionEnd": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f'"{hook_cmd}" session_end_json {stderr_redirect} || echo ""',
                            "timeout": 1500
                        }
                    ]
                }
            ]
        }
    }


def _is_mini_claude_hook(command: str) -> bool:
    """Check if a hook command belongs to mini_claude."""
    return "mini_claude" in command or "run_hook" in command


def _merge_hooks(existing_hooks: dict, new_hooks: dict) -> dict:
    """
    Merge mini_claude hooks into existing hooks without destroying user's other hooks.

    Strategy per hook event:
    - If event doesn't exist in existing: add our matchers
    - If event exists: for each of our matchers, check if our command is already there
      - If our command is there: update it (in case args changed)
      - If not: append our matcher
    - Never touch matchers that don't belong to mini_claude
    """
    merged = dict(existing_hooks)  # Shallow copy of event keys

    for event, new_matchers in new_hooks.items():
        if event not in merged:
            # Event doesn't exist yet — add our matchers wholesale
            merged[event] = new_matchers
            continue

        existing_matchers = merged[event]
        if not isinstance(existing_matchers, list):
            existing_matchers = []

        for new_matcher in new_matchers:
            new_pattern = new_matcher.get("matcher", "")
            new_hooks_list = new_matcher.get("hooks", [])

            # Find existing matcher with same pattern that has a mini_claude hook
            found = False
            for i, existing_matcher in enumerate(existing_matchers):
                if existing_matcher.get("matcher", "") != new_pattern:
                    continue

                existing_hook_list = existing_matcher.get("hooks", [])

                # Check if any existing hook in this matcher is ours
                our_idx = None
                for j, hook in enumerate(existing_hook_list):
                    if _is_mini_claude_hook(hook.get("command", "")):
                        our_idx = j
                        break

                if our_idx is not None:
                    # Update our existing hook in place
                    if new_hooks_list:
                        existing_hook_list[our_idx] = new_hooks_list[0]
                    found = True
                    break

            if not found:
                # No existing matcher with our hook — append as new matcher
                existing_matchers.append(new_matcher)

        merged[event] = existing_matchers

    return merged


def install_hooks_config():
    """
    Install hooks configuration to ~/.claude/settings.json.

    Merges mini_claude hooks into existing hooks without destroying
    the user's other hooks (e.g., from other tools or custom scripts).
    """
    settings_file = Path.home() / ".claude" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)

    # Load existing settings or create new
    existing = {}
    if settings_file.exists():
        try:
            existing = json.loads(settings_file.read_text())
        except Exception:
            pass

    # Get new hooks config
    hooks_config = get_hooks_config()

    # Merge — preserves user's other hooks
    existing_hooks = existing.get("hooks", {})
    existing["hooks"] = _merge_hooks(existing_hooks, hooks_config["hooks"])

    try:
        settings_file.write_text(json.dumps(existing, indent=2))
        return True, str(settings_file)
    except Exception as e:
        return False, str(e)


def get_mcp_config():
    """Generate the .mcp.json configuration."""
    script_dir = Path(__file__).parent.resolve()

    # Use launcher script (handles paths with spaces better)
    if is_windows():
        launcher = script_dir / "scripts" / "run_server.bat"
    else:
        launcher = script_dir / "scripts" / "run_server.sh"

    if launcher.exists():
        return {
            "mcpServers": {
                "claude-engram": {
                    "command": str(launcher),
                    "args": []
                }
            }
        }

    # Fallback to direct python path
    if is_windows():
        venv_python = script_dir / "venv" / "Scripts" / "python.exe"
    else:
        venv_python = script_dir / "venv" / "bin" / "python"

    if venv_python.exists():
        python_path = str(venv_python)
    else:
        python_path = sys.executable

    return {
        "mcpServers": {
            "claude-engram": {
                "command": python_path,
                "args": ["-m", "mini_claude.server"]
            }
        }
    }


def create_project_mcp_config(target_dir: Path):
    """Create .mcp.json in a target project directory."""
    config = get_mcp_config()
    mcp_file = target_dir / ".mcp.json"

    try:
        mcp_file.write_text(json.dumps(config, indent=2))
        return True, str(mcp_file)
    except Exception as e:
        return False, str(e)


def copy_claude_md(target_dir: Path):
    """Copy CLAUDE.md template to target project."""
    script_dir = Path(__file__).parent.resolve()
    source = script_dir / "CLAUDE.md"
    target = target_dir / "CLAUDE.md"

    if not source.exists():
        return False, "CLAUDE.md not found in mini_claude repo"

    if target.exists():
        return False, "CLAUDE.md already exists in target (not overwriting)"

    try:
        content = source.read_text()
        target.write_text(content)
        return True, str(target)
    except Exception as e:
        return False, str(e)


def setup_project(target_dir: str):
    """Set up Claude Engram for a specific project."""
    target = Path(target_dir).resolve()

    if not target.exists():
        return False, f"Directory does not exist: {target}"

    print(f"\nSetting up Claude Engram for: {target}")

    # Create .mcp.json
    success, result = create_project_mcp_config(target)
    if success:
        print_success(f"Created {result}")
    else:
        print_error(f"Failed to create .mcp.json: {result}")
        return False, result

    # Copy CLAUDE.md
    success, result = copy_claude_md(target)
    if success:
        print_success(f"Created {result}")
    else:
        print_warning(result)

    return True, None


def main():
    print("=" * 60)
    print("Claude Engram Installer")
    print("=" * 60)
    print("\nClaude Engram gives Claude Code persistent memory and")
    print("self-awareness tools to help avoid repeating mistakes.")

    total_steps = 7
    script_dir = Path(__file__).parent.resolve()

    # Step 1: Check virtual environment
    print_step(1, total_steps, "Checking virtual environment...")
    if check_venv():
        print_success("Running in virtual environment")
    else:
        print_error("Not running in a virtual environment!")
        print("\n  Please create and activate a venv first:")
        print(f"    cd \"{script_dir}\"")
        print("    python -m venv venv")
        print("    source venv/bin/activate  # Linux/Mac")
        print("    # or: venv\\Scripts\\activate  # Windows")
        print("\n  Then run this script again.")
        return 1

    # Step 2: Check Ollama
    print_step(2, total_steps, "Checking Ollama...")
    if check_ollama():
        print_success("Ollama is running")
    else:
        print_error("Ollama is not running")
        print("  Please start Ollama and pull the model:")
        print("    ollama serve")
        print("    ollama pull gemma3:12b")
        response = input("\n  Continue anyway? (y/n): ")
        if response.lower() != 'y':
            return 1

    # Step 3: Install package
    print_step(3, total_steps, "Installing mini_claude package...")
    if check_package_installed():
        print_success("Package already installed")
    else:
        success, error = install_package()
        if success:
            print_success("Package installed")
        else:
            print_error(f"Failed to install package: {error}")
            print("\n  Try manually:")
            print(f"    pip install -e \"{script_dir / 'mini_claude'}\"")
            return 1

    # Step 4: Create memory directory
    print_step(4, total_steps, "Creating memory directory...")
    memory_dir = create_memory_dir()
    print_success(f"Memory directory: {memory_dir}")

    # Step 4b: Create launcher scripts
    print("  Creating launcher scripts...")
    launcher = create_launcher_script()
    if launcher:
        print_success(f"Server launcher: {launcher}")
    else:
        print_warning("Could not create server launcher script")

    hook_launcher = create_hook_launcher_script()
    if hook_launcher:
        print_success(f"Hook launcher: {hook_launcher}")
    else:
        print_warning("Could not create hook launcher script")

    # Step 5: Install hooks to ~/.claude/settings.json
    print_step(5, total_steps, "Installing enforcement hooks...")
    success, result = install_hooks_config()
    if success:
        print_success(f"Hooks installed: {result}")
    else:
        print_error(f"Failed to install hooks: {result}")

    # Step 6: Create .mcp.json in this directory
    print_step(6, total_steps, "Creating MCP configuration...")
    success, result = create_project_mcp_config(script_dir)
    if success:
        print_success(f"Created {result}")
    else:
        print_error(f"Failed: {result}")

    # Step 7: Pre-build semantic intent cache (optional)
    print_step(7, total_steps, "Building semantic intent cache...")
    try:
        from mini_claude.hooks.intent import build_template_cache
        if build_template_cache():
            print_success("AllMiniLM decision templates cached (semantic intent scoring enabled)")
        else:
            print_warning("sentence-transformers not installed - using regex-based intent scoring")
            print("  To enable semantic scoring: pip install sentence-transformers numpy")
    except Exception as e:
        print_warning(f"Could not build intent cache: {e}")
        print("  Regex-based intent scoring will be used as fallback")

    # Summary
    print("\n" + "=" * 60)
    print("Installation complete!")
    print("=" * 60)

    config = get_mcp_config()
    mcp_json = json.dumps(config, indent=2)

    print("\n" + "-" * 60)
    print("HOW TO USE IN YOUR PROJECTS")
    print("-" * 60)

    print("\nOption 1: Copy .mcp.json to your project (recommended)")
    print("  Copy the .mcp.json file from this directory to your project root.")
    print(f"  Location: {script_dir / '.mcp.json'}")

    print("\nOption 2: Run setup command")
    print("  python install.py --setup /path/to/your/project")
    print("  This creates .mcp.json and copies CLAUDE.md template.")

    print("\nOption 3: Create .mcp.json manually")
    print("  Create a file named .mcp.json in your project root with:")
    print(mcp_json)

    print("\n" + "-" * 60)
    print("AFTER SETUP")
    print("-" * 60)
    print("\n1. Open your project in VSCode")
    print("2. Start Claude Code")
    print("3. Approve the claude-engram MCP server when prompted")
    print("4. Claude should use: session_start(project_path=\"/your/project\")")

    print("\n" + "-" * 60)
    print("TOOLS AVAILABLE (v2 - combined)")
    print("-" * 60)
    print("""
  Essential:
    mini_claude_status, session_start, session_end, pre_edit_check

  Combined (use 'operation' parameter):
    memory (remember/recall/forget/search/cleanup/add_rule/...)
    work (log_mistake/log_decision)
    scope (declare/check/expand/status/clear)
    loop (record_edit/record_test/check/status/reset)
    context (checkpoint_save/checkpoint_restore/handoff_create/...)
    convention (add/get/check/remove)
    output (validate_code/validate_result)

  Standalone:
    scout_search, scout_analyze, file_summarize, deps_map
    impact_analyze, code_quality_check, code_pattern_check
    audit_batch, find_similar_issues
""")

    return 0


def main_with_args():
    """Main entry point with argument handling."""
    if len(sys.argv) >= 3 and sys.argv[1] == "--setup":
        # Setup a specific project
        target_dir = sys.argv[2]

        # Quick check that mini_claude is importable
        if not check_package_installed():
            print("Error: mini_claude package not installed.")
            print("Run 'python install.py' first to install.")
            return 1

        success, error = setup_project(target_dir)
        if success:
            print("\nSetup complete!")
            print("1. Open the project in VSCode")
            print("2. Start Claude Code")
            print("3. Approve the claude-engram MCP server when prompted")
            return 0
        else:
            return 1
    else:
        return main()


if __name__ == "__main__":
    sys.exit(main_with_args())
