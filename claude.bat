@echo off
REM claude.bat - Claude Code wrapper with provider switching
REM Place this in a directory that's in your PATH
REM Usage:
REM   claude                   # Interactive menu
REM   claude zen               # Run with Zen API
REM   claude cc                # Run with CC subscription
REM   claude status            # Show current status

set SCRIPT_DIR=%~dp0

if "%1"=="" (
    python "%SCRIPT_DIR%frood-cc-launcher.py"
    goto :eof
)

if "%1"=="zen" (
    python "%SCRIPT_DIR%frood-cc-launcher.py" zen %2 %3 %4 %5 %6 %7 %8 %9
    goto :eof
)

if "%1"=="cc" (
    python "%SCRIPT_DIR%frood-cc-launcher.py" cc %2 %3 %4 %5 %6 %7 %8 %9
    goto :eof
)

if "%1"=="status" (
    python "%SCRIPT_DIR%frood-cc-launcher.py" status
    goto :eof
)

python "%SCRIPT_DIR%frood-cc-launcher.py" %*