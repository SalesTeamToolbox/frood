# Agent42 Windows Service Installation Script
# Installs Agent42 as a Windows service using NSSM (Non-Sucking Service Manager)
#
# Requirements:
#   - PowerShell (run as Administrator)
#   - NSSM (downloaded automatically if not present)
#
# Usage:
#   .\install-agent42-service.ps1
#
# After installation:
#   - Agent42 starts automatically on boot
#   - Dashboard: http://localhost:8000
#   - LLM Proxy: http://localhost:8000/llm/v1
#
# Management:
#   Start-Service agent42
#   Stop-Service agent42
#   Get-Service agent42
#   sc.exe delete agent42  (to uninstall)

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Agent42 Windows Service Installer" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if running as Administrator
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: This script must be run as Administrator." -ForegroundColor Red
    Write-Host "Right-click PowerShell -> 'Run as Administrator', then run this script." -ForegroundColor Yellow
    exit 1
}

# Get the Agent42 directory (parent of this script)
$Agent42Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $PythonExe) {
    Write-Host "ERROR: Python not found in PATH. Install Python 3.11+ first." -ForegroundColor Red
    exit 1
}

Write-Host "Agent42 Directory: $Agent42Dir" -ForegroundColor White
Write-Host "Python: $PythonExe" -ForegroundColor White
Write-Host ""

# Download NSSM if not present
$NssmDir = Join-Path $Agent42Dir "nssm"
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
$ExistingService = Get-Service -Name "agent42" -ErrorAction SilentlyContinue
if ($ExistingService) {
    Write-Host "Agent42 service already exists. Removing..." -ForegroundColor Yellow
    & $NssmExe stop agent42 2>$null
    Start-Sleep -Seconds 2
    & $NssmExe remove agent42 confirm 2>$null
    Start-Sleep -Seconds 1
}

# Install the service
Write-Host "Installing Agent42 service..." -ForegroundColor Yellow

$Agent42Py = Join-Path $Agent42Dir "agent42.py"
$LogDir = Join-Path $Agent42Dir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# Install service
& $NssmExe install agent42 $PythonExe $Agent42Py
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to install service." -ForegroundColor Red
    exit 1
}

# Configure service
& $NssmExe set agent42 AppDirectory $Agent42Dir
& $NssmExe set agent42 AppStdout (Join-Path $LogDir "agent42-service.log")
& $NssmExe set agent42 AppStderr (Join-Path $LogDir "agent42-service-error.log")
& $NssmExe set agent42 AppRotateFiles 1
& $NssmExe set agent42 AppRotateBytes 1048576
& $NssmExe set agent42 AppRotateOnline 1
& $NssmExe set agent42 Description "Agent42 AI Agent Platform - Dashboard, MCP Server, and LLM Proxy"
& $NssmExe set agent42 DisplayName "Agent42"
& $NssmExe set agent42 Start SERVICE_AUTO_START

Write-Host ""
Write-Host "Service installed successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Starting Agent42 service..." -ForegroundColor Yellow

Start-Service agent42
Start-Sleep -Seconds 3

$Status = Get-Service agent42
if ($Status.Status -eq "Running") {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host " Agent42 is now running as a Windows service!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Dashboard: http://localhost:8000" -ForegroundColor Cyan
    Write-Host "LLM Proxy: http://localhost:8000/llm/v1" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Commands:" -ForegroundColor Yellow
    Write-Host "  Start-Service agent42    # Start" -ForegroundColor White
    Write-Host "  Stop-Service agent42     # Stop" -ForegroundColor White
    Write-Host "  Get-Service agent42      # Status" -ForegroundColor White
    Write-Host "  Get-Content logs\agent42-service.log -Tail 20  # View logs" -ForegroundColor White
    Write-Host ""
    Write-Host "To uninstall: sc.exe delete agent42" -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "WARNING: Service may not have started correctly." -ForegroundColor Yellow
    Write-Host "Check logs: Get-Content logs\agent42-service-error.log" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Service status:" -ForegroundColor Yellow
    Get-Service agent42 | Format-List
}