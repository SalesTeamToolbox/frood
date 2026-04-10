# Frood LLM Proxy Configuration
# This file sets up Claude Code to use Frood's LLM proxy
# 
# Usage:
#   1. Run Frood: python frood.py
#   2. In any terminal: .\frood-env.bat
#   3. Start Claude Code: claude .
#   4. Use /model to switch between models
#
# Available models:
#   - qwen3.6-plus-free (Zen free)
#   - minimax-m2.5-free (Zen free)
#   - nemotron-3-super-free (Zen free)
#   - big-pickle (Zen free)
#   - claude-sonnet-4-6 (Anthropic API)
#   - gpt-4o-mini (OpenAI API)
#   - subscription (Claude Code subscription)

@echo off
echo Setting Frood LLM Proxy environment variables...
setx ANTHROPIC_BASE_URL "http://localhost:8000/llm/v1"
setx ANTHROPIC_API_KEY "dummy"
setx ANTHROPIC_MODEL "qwen3.6-plus-free"
echo.
echo Done! New terminals will use Frood proxy by default.
echo Restart your terminal or VS Code for changes to take effect.
echo.
echo To switch models, use /model in Claude Code.
echo To disable, run: frood-disable-proxy.bat