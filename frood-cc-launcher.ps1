# frood-cc-launcher.ps1 - Unified launcher for Claude Code with provider switching
# Usage:
#   .\frood-cc-launcher.ps1         # Interactive menu
#   .\frood-cc-launcher.ps1 zen     # Direct launch with Zen
#   .\frood-cc-launcher.ps1 cc      # Direct launch with CC subscription
#   .\frood-cc-launcher.ps1 status  # Show current status

param(
    [Parameter(Position=0)]
    [ValidateSet("zen", "z", "cc", "c", "status", "s", "help", "h")]
    [string]$Mode = ""
)

$ErrorActionPreference = "Continue"
$FROOD_URL = "http://localhost:8000"
$FROOD_HEALTH = "$FROOD_URL/health"
$FROOD_MODELS = "$FROOD_URL/llm/models"

# NOTE: Models are fetched dynamically from Frood at runtime, not hardcoded

function Test-FroodRunning {
    try {
        $response = Invoke-WebRequest -Uri $FROOD_HEALTH -Method Get -TimeoutSec 3 -ErrorAction SilentlyContinue
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Get-FroodModels {
    try {
        $response = Invoke-WebRequest -Uri $FROOD_MODELS -Method Get -TimeoutSec 5 -ErrorAction SilentlyContinue
        $data = $response.Content | ConvertFrom-Json
        return $data.data
    } catch {
        return @()
    }
}

function Get-ClaudeExe {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Claude\claude.exe",
        "$env:USERPROFILE\.local\bin\claude.exe",
        "$env:APPDATA\Claude\claude-code\2.1.92\claude.exe"
    )
    
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    
    # Try PATH
    $path = Get-Command claude -ErrorAction SilentlyContinue
    if ($path) {
        return $path.Source
    }
    
    return "claude"
}

function Get-DynamicModels {
    $models = Get-FroodModels
    $zenModels = @{}
    $ccModels = @{}
    
    foreach ($m in $models) {
        $provider = $m.provider
        $modelId = $m.id
        $category = $m.category
        
        if ($provider -eq "zen") {
            if ($modelId -match "qwen") { $zenModels["fast"] = $modelId }
            elseif ($modelId -match "minimax") { $zenModels["general"] = $modelId }
            elseif ($modelId -match "nemotron") { $zenModels["reasoning"] = $modelId }
            elseif ($modelId -match "pickle") { $zenModels["content"] = $modelId }
        }
        elseif ($provider -eq "anthropic") {
            if ($modelId -match "haiku") { $ccModels["fast"] = $modelId }
            elseif ($modelId -match "sonnet") { $ccModels["general"] = $modelId }
            elseif ($modelId -match "opus") { $ccModels["reasoning"] = $modelId }
        }
    }
    
    # Fallbacks if not all categories found
    $zenModels["fast"] = if ($zenModels["fast"]) { $zenModels["fast"] } else { "qwen3.6-plus-free" }
    $zenModels["general"] = if ($zenModels["general"]) { $zenModels["general"] } else { "minimax-m2.5-free" }
    $zenModels["reasoning"] = if ($zenModels["reasoning"]) { $zenModels["reasoning"] } else { "nemotron-3-super-free" }
    $zenModels["content"] = if ($zenModels["content"]) { $zenModels["content"] } else { "big-pickle" }
    
    $ccModels["fast"] = if ($ccModels["fast"]) { $ccModels["fast"] } else { "claude-haiku-4-5-20251001" }
    $ccModels["general"] = if ($ccModels["general"]) { $ccModels["general"] } else { "claude-sonnet-4-6-20260217" }
    $ccModels["reasoning"] = if ($ccModels["reasoning"]) { $ccModels["reasoning"] } else { "claude-opus-4-6-20260205" }
    
    return @{
        Zen = $zenModels
        CC = $ccModels
    }
}

function Set-ProviderEnv {
    param([string]$Provider)
    
    $models = Get-DynamicModels
    
    if ($Provider -eq "zen") {
        $env:ANTHROPIC_BASE_URL = "$FROOD_URL/llm/v1"
        $env:ANTHROPIC_API_KEY = $env:ZEN_API_KEY
        $env:ANTHROPIC_DEFAULT_SONNET_MODEL = $models.Zen["general"]
        $env:ANTHROPIC_DEFAULT_OPUS_MODEL = $models.Zen["reasoning"]
        $env:ANTHROPIC_DEFAULT_HAIKU_MODEL = $models.Zen["fast"]
        $env:CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC = "1"
        Write-Host "   [ZEN] Using models: sonnet=$($models.Zen.general), opus=$($models.Zen.reasoning), haiku=$($models.Zen.fast)" -ForegroundColor Gray
    } else {
        # CC mode - clear custom settings
        $env:ANTHROPIC_BASE_URL = $null
        $env:ANTHROPIC_API_KEY = $null
        $env:ANTHROPIC_DEFAULT_SONNET_MODEL = $null
        $env:ANTHROPIC_DEFAULT_OPUS_MODEL = $null
        $env:ANTHROPIC_DEFAULT_HAIKU_MODEL = $null
        $env:CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC = $null
        Write-Host "   [CC] Using models: sonnet=$($models.CC.general), opus=$($models.CC.reasoning), haiku=$($models.CC.fast)" -ForegroundColor Gray
    }
}

function Show-Status {
    $froodRunning = Test-FroodRunning
    
    Write-Host ""
    Write-Host "=" -NoNewline -ForegroundColor Cyan
    Write-Host (" " * 58) -NoNewline
    Write-Host "=" -ForegroundColor Cyan
    Write-Host "🤖 Claude Code Provider Status" -ForegroundColor Yellow
    Write-Host "=" -NoNewline -ForegroundColor Cyan
    Write-Host (" " * 58) -NoNewline
    Write-Host "=" -ForegroundColor Cyan
    
    Write-Host "`n📦 Frood (Frood Proxy):" -ForegroundColor White
    if ($froodRunning) {
        Write-Host "   ✅ Running at http://localhost:8000" -ForegroundColor Green
        $models = Get-FroodModels
        if ($models) {
            $zenCount = ($models | Where-Object { $_.provider -eq "zen" }).Count
            $ccCount = ($models | Where-Object { $_.provider -eq "anthropic" }).Count
            $orCount = ($models | Where-Object { $_.provider -eq "openrouter" }).Count
            Write-Host "   📊 Models: $($models.Count) total ($zenCount Zen, $ccCount CC, $orCount OpenRouter)" -ForegroundColor Gray
        }
    } else {
        Write-Host "   ❌ Not running" -ForegroundColor Red
        Write-Host "   💡 Start with: python frood.py" -ForegroundColor Gray
    }
    
    Write-Host "`n🔑 Environment:" -ForegroundColor White
    $baseUrl = if ($env:ANTHROPIC_BASE_URL) { $env:ANTHROPIC_BASE_URL } else { "(not set)" }
    Write-Host "   ANTHROPIC_BASE_URL: $baseUrl" -ForegroundColor Gray
    
    $defaultModel = if ($env:ANTHROPIC_DEFAULT_SONNET_MODEL) { $env:ANTHROPIC_DEFAULT_SONNET_MODEL } else { "(default)" }
    Write-Host "   Default Model: $defaultModel" -ForegroundColor Gray
    
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor Cyan
}

function Show-Menu {
    $froodRunning = Test-FroodRunning
    
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor Cyan
    Write-Host "🎯 Claude Code Launcher" -ForegroundColor Yellow
    Write-Host ("=" * 60) -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Select provider:" -ForegroundColor White
    Write-Host "  [1] Zen API     - Free models via Frood (Qwen, MiniMax, Nemotron)" -ForegroundColor Green
    Write-Host "  [2] CC Sub      - Anthropic Claude Code subscription (default)" -ForegroundColor Blue
    Write-Host "  [3] Status      - Show current configuration" -ForegroundColor Gray
    Write-Host "  [4] Exit        - Quit" -ForegroundColor Gray
    
    if ($froodRunning) {
        Write-Host ""
        Write-Host "✅ Frood is running and ready" -ForegroundColor Green
    } else {
        Write-Host ""
        Write-Host "⚠️  Frood not running - Zen mode will not work" -ForegroundColor Yellow
    }
    
    Write-Host ("=" * 60) -ForegroundColor Cyan
    
    $choice = Read-Host "`n> "
    
    switch ($choice) {
        "1" {
            if ($froodRunning) {
                Set-ProviderEnv -Provider "zen"
                Write-Host "`n🚀 Launching Claude Code with Zen API..." -ForegroundColor Green
                $claudeExe = Get-ClaudeExe
                & $claudeExe
            } else {
                Write-Host "❌ Frood is not running. Start it first with: python frood.py" -ForegroundColor Red
            }
        }
        "2" {
            Set-ProviderEnv -Provider "cc"
            Write-Host "`n🚀 Launching Claude Code with CC Subscription..." -ForegroundColor Blue
            $claudeExe = Get-ClaudeExe
            & $claudeExe
        }
        "3" {
            Show-Status
            Show-Menu
        }
        "4" {
            Write-Host "👋 Goodbye!" -ForegroundColor Gray
        }
        default {
            Write-Host "Invalid choice. Please enter 1-4." -ForegroundColor Red
            Show-Menu
        }
    }
}

function Launch-Claude {
    param(
        [string]$Provider,
        [string[]]$Args = @()
    )
    
    Set-ProviderEnv -Provider $Provider
    
    $providerLabel = if ($Provider -eq "zen") { "Zen API" } else { "CC Subscription" }
    Write-Host "`n🚀 Launching Claude Code with $providerLabel..." -ForegroundColor Yellow
    
    $claudeExe = Get-ClaudeExe
    & $claudeExe @Args
}

# Main execution
switch ($Mode) {
    { $_ -in @("zen", "z") } {
        if (Test-FroodRunning) {
            Launch-Claude -Provider "zen" -Args $args
        } else {
            Write-Host "❌ Frood is not running. Start it first with: python frood.py" -ForegroundColor Red
            exit 1
        }
    }
    { $_ -in @("cc", "c", "") } {
        if ($Mode -eq "") {
            Show-Menu
        } else {
            Launch-Claude -Provider "cc" -Args $args
        }
    }
    { $_ -in @("status", "s") } {
        Show-Status
    }
    { $_ -in @("help", "h") } {
        Write-Host @"
🤖 Claude Code Launcher

Usage:
  .\frood-cc-launcher.ps1          # Interactive menu
  .\frood-cc-launcher.ps1 zen      # Launch with Zen API
  .\frood-cc-launcher.ps1 cc        # Launch with CC subscription
  .\frood-cc-launcher.ps1 status    # Show status

Providers:
  zen  - Zen API via Frood proxy (free models: Qwen, MiniMax, Nemotron)
  cc   - Anthropic Claude Code subscription (default)

Notes:
  - Frood must be running for Zen mode to work
  - Start Frood with: python frood.py
  - Models are automatically configured for each provider
"@ -ForegroundColor White
    }
}