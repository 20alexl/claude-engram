@echo off
REM Claude Engram MCP Server launcher for Windows
setlocal
set "SCRIPT_DIR=%~dp0"
"%SCRIPT_DIR%..\venv\Scripts\python.exe" -m claude_engram.server %*
