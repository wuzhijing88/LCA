@echo off
setlocal

rem LCA release build entry: Nuitka standalone + local runtime files + optional Inno Setup installer.
rem Arguments are passed through, e.g.: build_release.bat --skip-nuitka --skip-installer
rem NOTE: keep this file ASCII-only. cmd.exe mis-parses multibyte text in batch files under legacy code pages.

set "PACKAGING_DIR=%~dp0"
for %%I in ("%PACKAGING_DIR%..\..") do set "PROJECT_ROOT=%%~fI"
set "PYTHON_EXE=%PROJECT_ROOT%\venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python in venv was not found:
    echo         "%PYTHON_EXE%"
    echo.
    echo Please create venv and install requirements.txt first.
    pause
    exit /b 1
)

chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

cd /d "%PROJECT_ROOT%"
"%PYTHON_EXE%" "%PACKAGING_DIR%build_release.py" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    pause
)

exit /b %EXIT_CODE%
