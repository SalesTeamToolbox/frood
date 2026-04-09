# zen-claude.ps1 - Run Claude Code with Zen API (via Frood proxy)
# Usage: .\zen-claude.ps1 [args...]

$env:ANTHROPIC_BASE_URL = "http://localhost:8000/llm/v1"
$env:ANTHROPIC_API_KEY = $env:ZEN_API_KEY
$env:ANTHROPIC_DEFAULT_SONNET_MODEL = "qwen3.6-plus-free"
$env:ANTHROPIC_DEFAULT_OPUS_MODEL = "minimax-m2.5-free"
$env:ANTHROPIC_DEFAULT_HAIKU_MODEL = "nemotron-3-super-free"
$env:CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC = "1"

Write-Host "[Zen] Using Frood proxy at $env:ANTHROPIC_BASE_URL" -ForegroundColor Cyan
Write-Host "[Zen] Sonnet: qwen3.6-plus-free, Opus: minimax-m2.5-free, Haiku: nemotron-3-super-free" -ForegroundColor Gray

claude $args