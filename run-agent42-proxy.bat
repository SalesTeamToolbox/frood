@echo off
REM Frood LLM Proxy Launcher for Claude Code
REM This allows Claude Code to use Zen free models via Frood while
REM still having access to your Claude Code subscription as fallback.
REM
REM Usage: run-frood-proxy.bat [model]
REM
REM Examples:
REM   run-frood-proxy.bat              - Uses default (qwen3.6-plus-free)
REM   run-frood-proxy.bat claude-sonnet-4-6 - Uses Anthropic API if configured
REM   run-frood-proxy.bat subscription - Uses your Claude Code subscription
REM
REM To switch between models:
REM   1. Edit this script and change the MODEL variable
REM   2. Or open a new terminal and set: set ANTHROPIC_MODEL=qwen3.6-plus-free

set MODEL=%1
if "%MODEL%"=="" set MODEL=qwen3.6-plus-free

echo ================================================================================
echo Frood LLM Proxy - Claude Code Launcher
echo ================================================================================
echo.
echo Your Claude Code subscription is always available as the default.
echo This proxy adds access to Zen free models (qwen3.6-plus-free, etc.)
echo when you specify them.
echo.
echo Selected model: %MODEL%
echo.
echo To switch models, edit this script or set ANTHROPIC_MODEL before running claude.
echo.
echo Available models:
echo   - subscription    : Use Claude Code subscription (default)
echo   - qwen3.6-plus-free    : Zen free model (fast/coding)
echo   - minimax-m2.5-free   : Zen free model (general)
echo   - nemotron-3-super-free : Zen free model (reasoning)
echo   - big-pickle         : Zen free model (content)
echo   - claude-sonnet-4-6  : Anthropic API (if configured)
echo   - gpt-4o-mini        : OpenAI API (if configured)
echo.
echo Starting Frood dashboard (required for proxy)...
echo.

REM Start Frood in background
start /b python frood.py > nul 2>&1

REM Wait for Frood to start
timeout /t 3 /nobreak > nul

REM Set environment variables for Claude Code to use Frood proxy
set ANTHROPIC_BASE_URL=http://localhost:8000/llm/v1
set ANTHROPIC_API_KEY=dummy
set ANTHROPIC_MODEL=%MODEL%

echo Configuration applied:
echo   ANTHROPIC_BASE_URL=%ANTHROPIC_BASE_URL%
echo   ANTHROPIC_MODEL=%MODEL%
echo.
echo Starting Claude Code...
echo ================================================================================
echo.

REM Launch Claude Code
npx -y @anthropic-ai/claude-code .