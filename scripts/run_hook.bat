@echo off
REM Mini Claude Hook launcher for Windows
setlocal
set "SCRIPT_DIR=%~dp0"
"%SCRIPT_DIR%..\venv\Scripts\python.exe" -m mini_claude.hooks.remind %*
