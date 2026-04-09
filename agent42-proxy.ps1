# Agent42 LLM Proxy PowerShell Functions
# Add this to your PowerShell profile: $PROFILE
# Then run: Set-Agent42Model qwen3.6-plus-free
# Or: Set-Agent42Model subscription

function Set-Agent42Model {
    param(
        [string]$Model = "qwen3.6-plus-free"
    )
    
    $env:ANTHROPIC_BASE_URL = "http://localhost:8000/llm/v1"
    $env:ANTHROPIC_API_KEY = "dummy"
    $env:ANTHROPIC_MODEL = $Model
    
    Write-Host "Agent42 LLM Proxy: Using model '$Model'" -ForegroundColor Cyan
    Write-Host "  Base URL: $env:ANTHROPIC_BASE_URL" -ForegroundColor Gray
    Write-Host "  Model: $env:ANTHROPIC_MODEL" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Start Claude Code with: claude ." -ForegroundColor Yellow
}

function Set-Agent42Subscription {
    Set-Agent42Model "subscription"
}

function Get-Agent42Models {
    Write-Host "Available Agent42 LLM Proxy Models:" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Zen Free Models:" -ForegroundColor Green
    Write-Host "  - qwen3.6-plus-free       (fast/coding)" -ForegroundColor White
    Write-Host "  - minimax-m2.5-free      (general)" -ForegroundColor White
    Write-Host "  - nemotron-3-super-free  (reasoning)" -ForegroundColor White
    Write-Host "  - big-pickle             (content)" -ForegroundColor White
    Write-Host ""
    Write-Host "Other Models (if API keys configured):" -ForegroundColor Yellow
    Write-Host "  - claude-sonnet-4-6      (Anthropic API)" -ForegroundColor White
    Write-Host "  - gpt-4o-mini            (OpenAI API)" -ForegroundColor White
    Write-Host "  - subscription           (Claude Code subscription)" -ForegroundColor White
}

function Start-Agent42Proxy {
    Write-Host "Starting Agent42 dashboard..." -ForegroundColor Cyan
    Start-Process -FilePath "python" -ArgumentList "agent42.py" -WindowStyle Hidden
    Start-Sleep -Seconds 3
    Write-Host "Agent42 dashboard started. Use Set-Agent42Model to configure." -ForegroundColor Green
}