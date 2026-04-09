@echo off
REM cc-claude.bat - Run Claude Code with Anthropic CC Subscription (default)
REM Usage: cc-claude [args...]

REM Clear any custom LLM proxy settings
set ANTHROPIC_BASE_URL=
set ANTHROPIC_API_KEY=
set ANTHROPIC_DEFAULT_SONNET_MODEL=
set ANTHROPIC_DEFAULT_OPUS_MODEL=
set ANTHROPIC_DEFAULT_HAIKU_MODEL=
set CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=

echo [CC] Using Anthropic CC Subscription (default)

claude %*