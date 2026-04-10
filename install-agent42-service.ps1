# Frood Windows Service Installation Script
# Installs Frood as a Windows service using NSSM (Non-Sucking Service Manager)
#
# Requirements:
#   - PowerShell (run as Administrator)
#   - NSSM (downloaded automatically if not present)
#
# Usage:
#   .\install-frood-service.ps1
#
# After installation:
#   - Frood starts automatically on boot
#   - Dashboard: http://localhost:8000
#   - LLM Proxy: http://localhost:8000/llm/v1
#
# Management:
#   Start-Service frood
#   Stop-Service frood
#   Get-Service frood
#   sc.exe delete frood  (to uninstall)

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Frood Windows Service Installer" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if running as Administrator
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: This script must be run as Administrator." -ForegroundColor Red
    Write-Host "Right-click PowerShell -> 'Run as Administrator', then run this script." -ForegroundColor Yellow
    exit 1
}

# Get the Frood directory (parent of this script)
$FroodDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $PythonExe) {
    Write-Host "ERROR: Python not found in PATH. Install Python 3.11+ first." -ForegroundColor Red
    exit 1
}

Write-Host "Frood Directory: $FroodDir" -ForegroundColor White
Write-Host "Python: $PythonExe" -ForegroundColor White
Write-Host ""

# Download NSSM if not present
$NssmDir = Join-Path $FroodDir "nssm"
$NssmExe = Join-Path $NssmDir "nssm.exe"

if (-not (Test-Path $NssmExe)) {
    Write-Host "Downloading NSSM..." -ForegroundColor Yellow
    
    # Create directory
    New-Item -ItemType Directory -Force -Path $NssmDir | Out-Null
    
    # Download NSSM (64-bit)
    $NssmZip = Join-Path $env:TEMP "nssm-2.24.zip"
    $NssmUrl = "https://nssm.cc/release/nssm-2.24.zip"
    
    try {
        Invoke-WebRequest -Uri $NssmUrl -OutFile $NssmZip -UseBasicParsing
        Expand-Archive -Path $NssmZip -DestinationPath (Join-Path $env:TEMP "nssm-extract") -Force
        
        # Copy the 64-bit executable
        $ExtractedNssm = Join-Path $env:TEMP "nssm-extract\nssm-2.24\win64\nssm.exe"
        if (Test-Path $ExtractedNssm) {
            Copy-Item $ExtractedNssm $NssmExe -Force
            Write-Host "NSSM installed to: $NssmExe" -ForegroundColor Green
        } else {
            Write-Host "ERROR: Could not find nssm.exe in downloaded archive." -ForegroundColor Red
            exit 1
        }
        
        # Cleanup
        Remove-Item $NssmZip -Force -ErrorAction SilentlyContinue
        Remove-Item (Join-Path $env:TEMP "nssm-extract") -Recurse -Force -ErrorAction SilentlyContinue
    } catch {
        Write-Host "ERROR: Failed to download NSSM: $_" -ForegroundColor Red
        Write-Host "Download manually from https://nssm.cc/download and place nssm.exe in: $NssmDir" -ForegroundColor Yellow
        exit 1
    }
} else {
    Write-Host "NSSM found: $NssmExe" -ForegroundColor Green
}

# Check if service already exists
$ExistingService = Get-Service -Name "frood" -ErrorAction SilentlyContinue
if ($ExistingService) {
    Write-Host "Frood service already exists. Removing..." -ForegroundColor Yellow
    & $NssmExe stop frood 2>$null
    Start-Sleep -Seconds 2
    & $NssmExe remove frood confirm 2>$null
    Start-Sleep -Seconds 1
}

# Install the service
Write-Host "Installing Frood service..." -ForegroundColor Yellow

$FroodPy = Join-Path $FroodDir "frood.py"
$LogDir = Join-Path $FroodDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# Install service
& $NssmExe install frood $PythonExe $FroodPy
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to install service." -ForegroundColor Red
    exit 1
}

# Configure service
& $NssmExe set frood AppDirectory $FroodDir
& $NssmExe set frood AppStdout (Join-Path $LogDir "frood-service.log")
& $NssmExe set frood AppStderr (Join-Path $LogDir "frood-service-error.log")
& $NssmExe set frood AppRotateFiles 1
& $NssmExe set frood AppRotateBytes 1048576
& $NssmExe set frood AppRotateOnline 1
& $NssmExe set frood Description "Frood AI Agent Platform - Dashboard, MCP Server, and LLM Proxy"
& $NssmExe set frood DisplayName "Frood"
& $NssmExe set frood Start SERVICE_AUTO_START

Write-Host ""
Write-Host "Service installed successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Starting Frood service..." -ForegroundColor Yellow

Start-Service frood
Start-Sleep -Seconds 3

$Status = Get-Service frood
if ($Status.Status -eq "Running") {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host " Frood is now running as a Windows service!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Dashboard: http://localhost:8000" -ForegroundColor Cyan
    Write-Host "LLM Proxy: http://localhost:8000/llm/v1" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Commands:" -ForegroundColor Yellow
    Write-Host "  Start-Service frood    # Start" -ForegroundColor White
    Write-Host "  Stop-Service frood     # Stop" -ForegroundColor White
    Write-Host "  Get-Service frood      # Status" -ForegroundColor White
    Write-Host "  Get-Content logs\frood-service.log -Tail 20  # View logs" -ForegroundColor White
    Write-Host ""
    Write-Host "To uninstall: sc.exe delete frood" -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "WARNING: Service may not have started correctly." -ForegroundColor Yellow
    Write-Host "Check logs: Get-Content logs\frood-service-error.log" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Service status:" -ForegroundColor Yellow
    Get-Service frood | Format-List
}