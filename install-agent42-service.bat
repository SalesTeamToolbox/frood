@echo off
REM Install Frood as a Windows Service
REM Must be run as Administrator

echo ========================================
echo  Frood Windows Service Installer
echo ========================================
echo.

REM Check for admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ERROR: This script must be run as Administrator.
    echo Right-click this file -> "Run as Administrator"
    pause
    exit /b 1
)

cd /d "%~dp0"

REM Check if service already exists
sc query frood >nul 2>&1
if %errorLevel% equ 0 (
    echo Frood service already exists. Removing...
    winsw.exe uninstall frood-service.xml
    timeout /t 2 /nobreak >nul
)

REM Install the service
echo Installing Frood service...
winsw.exe install frood-service.xml
if %errorLevel% neq 0 (
    echo ERROR: Failed to install service.
    pause
    exit /b 1
)

echo.
echo Service installed! Starting Frood...
net start frood

echo.
echo ========================================
echo  Frood is now running as a service!
echo ========================================
echo.
echo Dashboard: http://localhost:8000
echo LLM Proxy: http://localhost:8000/llm/v1
echo.
echo Commands:
echo   net start frood     - Start
echo   net stop frood      - Stop
echo   sc query frood      - Status
echo.
echo Logs: logs\frood.out.log and frood.err.log
echo.
echo To uninstall: winsw.exe uninstall frood-service.xml
echo.
pause