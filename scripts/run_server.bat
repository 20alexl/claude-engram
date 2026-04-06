@echo off
set "SCRIPT_DIR=%~dp0"
"%SCRIPT_DIR%..\venv\Scripts\python.exe" -m claude_engram.server %*
