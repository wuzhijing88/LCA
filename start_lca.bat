@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"
set "APP_ENTRY=%~dp0main.py"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python in venv was not found:
    echo         "%PYTHON_EXE%"
    echo.
    echo Please create venv or install dependencies before starting LCA.
    pause
    exit /b 1
)

if not exist "%APP_ENTRY%" (
    echo [ERROR] App entry was not found:
    echo         "%APP_ENTRY%"
    pause
    exit /b 1
)

echo [LCA] Starting...
echo [LCA] Working directory: %CD%
echo.

"%PYTHON_EXE%" "%APP_ENTRY%" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] LCA exited with code: %EXIT_CODE%
    pause
)

exit /b %EXIT_CODE%
