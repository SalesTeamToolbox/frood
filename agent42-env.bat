# Agent42 LLM Proxy Configuration
# This file sets up Claude Code to use Agent42's LLM proxy
# 
# Usage:
#   1. Run Agent42: python agent42.py
#   2. In any terminal: .\agent42-env.bat
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
echo Setting Agent42 LLM Proxy environment variables...
setx ANTHROPIC_BASE_URL "http://localhost:8000/llm/v1"
setx ANTHROPIC_API_KEY "dummy"
setx ANTHROPIC_MODEL "qwen3.6-plus-free"
echo.
echo Done! New terminals will use Agent42 proxy by default.
echo Restart your terminal or VS Code for changes to take effect.
echo.
echo To switch models, use /model in Claude Code.
echo To disable, run: agent42-disable-proxy.bat