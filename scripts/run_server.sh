#!/bin/bash
# Claude Engram MCP Server launcher
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"${SCRIPT_DIR}/../venv/bin/python" -m claude_engram.server "$@"
