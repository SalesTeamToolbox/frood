@echo off
REM zen-claude.bat - Run Claude Code with Zen API (via Frood proxy)
REM Usage: zen-claude [args...]

set ANTHROPIC_BASE_URL=http://localhost:8000/llm/v1
set ANTHROPIC_API_KEY=%ZEN_API_KEY%
set ANTHROPIC_DEFAULT_SONNET_MODEL=qwen3.6-plus-free
set ANTHROPIC_DEFAULT_OPUS_MODEL=minimax-m2.5-free
set ANTHROPIC_DEFAULT_HAIKU_MODEL=nemotron-3-super-free
set CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

echo [Zen] Using Frood proxy at %ANTHROPIC_BASE_URL%
echo [Zen] Models: qwen3.6-plus-free, minimax-m2.5-free, nemotron-3-super-free

claude %*