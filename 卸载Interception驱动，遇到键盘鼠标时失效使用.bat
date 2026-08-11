@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
set "INSTALLER="

call :set_installer "%SCRIPT_DIR%command line installer\install-interception.exe"
if defined INSTALLER goto check_admin

call :set_installer "%SCRIPT_DIR%install-interception.exe"
if defined INSTALLER goto check_admin

call :set_installer "%SCRIPT_DIR%Interception\command line installer\install-interception.exe"
if defined INSTALLER goto check_admin

for /f "delims=" %%I in ('dir /b /s /a:-d "%SCRIPT_DIR%install-interception.exe" 2^>nul') do (
    set "INSTALLER=%%~fI"
    goto check_admin
)

echo [ERROR] install-interception.exe was not found.
echo Place this script inside the Interception folder, then run it again.
pause
exit /b 1

:check_admin
fltmc >nul 2>&1
if errorlevel 1 (
    echo Requesting administrator privileges...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo Using installer:
echo   "%INSTALLER%"
echo.
echo Uninstalling Interception...
"%INSTALLER%" /uninstall
set "EXIT_CODE=%ERRORLEVEL%"
echo.

if "%EXIT_CODE%"=="0" (
    echo Interception uninstall command completed.
    echo Reboot Windows to finish removing the driver.
) else (
    echo [ERROR] Uninstall command failed with exit code %EXIT_CODE%.
)

echo.
pause
exit /b %EXIT_CODE%

:set_installer
if exist "%~1" set "INSTALLER=%~f1"
exit /b
