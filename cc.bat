@echo off
REM cc.bat - Unified Claude Code launcher
REM Usage:
REM   cc              # Interactive menu
REM   cc cc           # Claude Code subscription
REM   cc zen          # Zen API (free)
REM   cc or           # OpenRouter
REM   cc status       # Show status
REM   cc menu         # Interactive menu

python "%~dp0frood-cc-launcher.py" %*