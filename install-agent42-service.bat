@echo off
REM Install Agent42 as a Windows Service
REM Must be run as Administrator

echo ========================================
echo  Agent42 Windows Service Installer
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
sc query agent42 >nul 2>&1
if %errorLevel% equ 0 (
    echo Agent42 service already exists. Removing...
    winsw.exe uninstall agent42-service.xml
    timeout /t 2 /nobreak >nul
)

REM Install the service
echo Installing Agent42 service...
winsw.exe install agent42-service.xml
if %errorLevel% neq 0 (
    echo ERROR: Failed to install service.
    pause
    exit /b 1
)

echo.
echo Service installed! Starting Agent42...
net start agent42

echo.
echo ========================================
echo  Agent42 is now running as a service!
echo ========================================
echo.
echo Dashboard: http://localhost:8000
echo LLM Proxy: http://localhost:8000/llm/v1
echo.
echo Commands:
echo   net start agent42     - Start
echo   net stop agent42      - Stop
echo   sc query agent42      - Status
echo.
echo Logs: logs\agent42.out.log and agent42.err.log
echo.
echo To uninstall: winsw.exe uninstall agent42-service.xml
echo.
pause