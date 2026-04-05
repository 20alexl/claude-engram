@echo off
REM Claude Engram Hook launcher for Windows
setlocal
set "SCRIPT_DIR=%~dp0"
"%SCRIPT_DIR%..\venv\Scripts\python.exe" -m claude_engram.hooks.remind %*
