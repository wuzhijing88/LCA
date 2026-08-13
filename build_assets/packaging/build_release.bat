@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

set "STEP=INIT"
set "ERRMSG="

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR_NOSLASH=%SCRIPT_DIR:~0,-1%"
for %%I in ("%SCRIPT_DIR%..\..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"

echo ========================================
echo   LCA - Auto Build Script
echo ========================================
echo.

set "STEP=CHECK_VENV"
if not exist "venv\Scripts\python.exe" (
    set "ERRMSG=Missing venv\Scripts\python.exe"
    goto fail
)
venv\Scripts\python.exe --version >nul 2>&1
if errorlevel 1 (
    set "ERRMSG=Broken venv\\Scripts\\python.exe, please repair the base Python referenced by venv\\pyvenv.cfg"
    goto fail
)

set "STEP=CLEAN_PREVIOUS_BUILD_ARTIFACTS"
echo [0.2/6] Clean previous build traces...
if exist "%PROJECT_ROOT%\build_assets\packaging\build_output" rd /s /q "%PROJECT_ROOT%\build_assets\packaging\build_output"
if exist "%PROJECT_ROOT%\build_assets\packaging\release_output" rd /s /q "%PROJECT_ROOT%\build_assets\packaging\release_output"
if exist "%PROJECT_ROOT%\build_assets\packaging\_tmp_probe_comtypes.py" del /f /q "%PROJECT_ROOT%\build_assets\packaging\_tmp_probe_comtypes.py" >nul 2>&1
if exist "%PROJECT_ROOT%\nuitka-crash-report.xml" del /f /q "%PROJECT_ROOT%\nuitka-crash-report.xml" >nul 2>&1

set "BUILD_OUTPUT_DIR=%PROJECT_ROOT%\build_assets\packaging\build_output"
set "RELEASE_OUTPUT_DIR=%PROJECT_ROOT%\build_assets\packaging\release_output"
set "DIST=%BUILD_OUTPUT_DIR%\main.dist"
set "BUILD_DIR=%BUILD_OUTPUT_DIR%\main.build"

set "STEP=PREPARE_OUTPUT"
echo [1/6] Prepare build outputs...

set "STEP=BUILD_MAIN_NUITKA"
echo.
echo [2/6] Build main.exe with Nuitka...
echo.

venv\Scripts\python.exe build_assets\packaging\run_nuitka_main_build.py --project-root "%PROJECT_ROOT%" --output-dir "%BUILD_OUTPUT_DIR%"

if errorlevel 1 (
    set "ERRMSG=Nuitka main build failed"
    goto fail
)

if not exist "%DIST%\main.exe" (
    set "ERRMSG=Missing %DIST%\main.exe"
    goto fail
)

set "STEP=VERIFY_TASK_MODULES"
echo [2.05/6] Verify packaged task modules...
venv\Scripts\python.exe build_assets\packaging\verify_packaged_task_modules.py --build-dir "%BUILD_DIR%"
if errorlevel 1 (
    set "ERRMSG=Packaged task module verification failed"
    goto fail
)

set "STEP=INJECT_WINDOWS_MANIFEST"
echo [2.1/6] Inject Windows DPI manifest...
venv\Scripts\python.exe build_assets\packaging\inject_windows_manifest.py --exe "%DIST%\main.exe" --manifest "%SCRIPT_DIR_NOSLASH%\lca_main.manifest"
if errorlevel 1 (
    set "ERRMSG=Inject Windows DPI manifest failed"
    goto fail
)

set "STEP=CHECK_CORE_RESOURCES"
echo [2.5/6] Check required resources...

if not exist "venv\Lib\site-packages\uiautomation\bin\UIAutomationClient_VC140_X64.dll" (
    set "ERRMSG=Missing source UIAutomationClient_VC140_X64.dll"
    goto fail
)
if not exist "venv\Lib\site-packages\uiautomation\bin\UIAutomationClient_VC140_X86.dll" (
    set "ERRMSG=Missing source UIAutomationClient_VC140_X86.dll"
    goto fail
)
if not exist "%DIST%\uiautomation\bin" mkdir "%DIST%\uiautomation\bin"
for %%f in (UIAutomationClient_VC140_X64.dll UIAutomationClient_VC140_X86.dll) do (
    copy /y "venv\Lib\site-packages\uiautomation\bin\%%f" "%DIST%\uiautomation\bin\%%f" >nul 2>&1
    if not exist "%DIST%\uiautomation\bin\%%f" (
        set "ERRMSG=Missing UIAutomation runtime DLL: %%f"
        goto fail
    )
)

if not exist "%DIST%\Interception\library\x64\interception.dll" (
    if not exist "Interception\library\x64\interception.dll" (
        set "ERRMSG=Missing source Interception x64 DLL"
        goto fail
    )
    if not exist "%DIST%\Interception\library\x64" mkdir "%DIST%\Interception\library\x64"
copy "Interception\library\x64\interception.dll" "%DIST%\Interception\library\x64\interception.dll" >nul 2>&1
)
if not exist "%DIST%\Interception\library\x64\interception.dll" (
    set "ERRMSG=Missing Interception x64 DLL"
    goto fail
)

if not exist "%DIST%\Interception\library\x86\interception.dll" (
    if not exist "Interception\library\x86\interception.dll" (
        set "ERRMSG=Missing source Interception x86 DLL"
        goto fail
    )
    if not exist "%DIST%\Interception\library\x86" mkdir "%DIST%\Interception\library\x86"
copy "Interception\library\x86\interception.dll" "%DIST%\Interception\library\x86\interception.dll" >nul 2>&1
)
if not exist "%DIST%\Interception\library\x86\interception.dll" (
    set "ERRMSG=Missing Interception x86 DLL"
    goto fail
)
if not exist "tools\ibinputsimulator\ib_worker_core.ahk" (
    set "ERRMSG=Missing source ib_worker_core.ahk"
    goto fail
)
if not exist "%DIST%\tools\ibinputsimulator" mkdir "%DIST%\tools\ibinputsimulator"
copy /y "tools\ibinputsimulator\ib_worker_core.ahk" "%DIST%\tools\ibinputsimulator\ib_worker_core.ahk" >nul 2>&1
if not exist "%DIST%\tools\ibinputsimulator\ib_worker_core.ahk" (
    set "ERRMSG=Missing ib_worker_core.ahk"
    goto fail
)
findstr /l /c:"UIntP" "%DIST%\tools\ibinputsimulator\ib_worker_core.ahk" >nul
if errorlevel 1 (
    set "ERRMSG=ib_worker_core.ahk version check failed (UIntP missing)"
    goto fail
)
findstr /l /c:"UInt*" "%DIST%\tools\ibinputsimulator\ib_worker_core.ahk" >nul
if not errorlevel 1 (
    set "ERRMSG=ib_worker_core.ahk version check failed (legacy UInt* found)"
    goto fail
)

if not exist "tools\ibinputsimulator\Binding.AHK2\IbInputSimulator.ahk" (
    set "ERRMSG=Missing source IbInputSimulator.ahk"
    goto fail
)
if not exist "%DIST%\tools\ibinputsimulator\Binding.AHK2" mkdir "%DIST%\tools\ibinputsimulator\Binding.AHK2"
copy /y "tools\ibinputsimulator\Binding.AHK2\IbInputSimulator.ahk" "%DIST%\tools\ibinputsimulator\Binding.AHK2\IbInputSimulator.ahk" >nul 2>&1
if not exist "%DIST%\tools\ibinputsimulator\Binding.AHK2\IbInputSimulator.ahk" (
    set "ERRMSG=Missing IbInputSimulator.ahk"
    goto fail
)
if not exist "tools\ibinputsimulator\Binding.AHK2\IbInputSimulator.dll" (
    set "ERRMSG=Missing source IbInputSimulator.dll"
    goto fail
)
if not exist "%DIST%\tools\ibinputsimulator\Binding.AHK2" mkdir "%DIST%\tools\ibinputsimulator\Binding.AHK2"
copy /y "tools\ibinputsimulator\Binding.AHK2\IbInputSimulator.dll" "%DIST%\tools\ibinputsimulator\Binding.AHK2\IbInputSimulator.dll" >nul 2>&1
if not exist "%DIST%\tools\ibinputsimulator\Binding.AHK2\IbInputSimulator.dll" (
    set "ERRMSG=Missing IbInputSimulator.dll"
    goto fail
)
if not exist "AutoHotkey\AutoHotkey64.exe" (
    set "ERRMSG=Missing source AutoHotkey64.exe"
    goto fail
)
if not exist "%DIST%\AutoHotkey" mkdir "%DIST%\AutoHotkey"
copy /y "AutoHotkey\AutoHotkey64.exe" "%DIST%\AutoHotkey\AutoHotkey64.exe" >nul 2>&1
if not exist "%DIST%\AutoHotkey\AutoHotkey64.exe" (
    set "ERRMSG=Missing AutoHotkey64.exe"
    goto fail
)
set "STEP=COPY_VC_RUNTIME"
echo [3/6] Copy VC runtime...
set "VCRUNTIME=C:\Windows\System32"
if not exist "%DIST%\AutoHotkey" mkdir "%DIST%\AutoHotkey"
if not exist "%DIST%\tools\ibinputsimulator\Binding.AHK2" mkdir "%DIST%\tools\ibinputsimulator\Binding.AHK2"
for %%f in (concrt140.dll msvcp140.dll vcomp140.dll vcruntime140.dll vcruntime140_1.dll) do (
    if exist "%VCRUNTIME%\%%f" (
        copy "%VCRUNTIME%\%%f" "%DIST%\%%f" >nul 2>&1
        copy "%VCRUNTIME%\%%f" "%DIST%\AutoHotkey\%%f" >nul 2>&1
        copy "%VCRUNTIME%\%%f" "%DIST%\tools\ibinputsimulator\Binding.AHK2\%%f" >nul 2>&1
    )
)

set "STEP=STAGE_PACKAGED_RUNTIME_ASSETS"
venv\Scripts\python.exe build_assets\packaging\stage_packaged_runtime_assets.py --project-root "%PROJECT_ROOT%" --dist "%DIST%"
if errorlevel 1 (
    set "ERRMSG=Stage packaged runtime assets failed"
    goto fail
)

set "STEP=VERIFY_PACKAGED_OCR_RUNTIME"
echo [5.7/6] Verify offline PP-OCRv4 runtime...
venv\Scripts\python.exe build_assets\packaging\verify_packaged_ocr_runtime.py --dist "%DIST%"
if errorlevel 1 (
    set "ERRMSG=Packaged OCR runtime verification failed"
    goto fail
)

set "STEP=VERIFY_NO_SOURCE_FILES"
venv\Scripts\python.exe build_assets\packaging\verify_no_source_files.py --dist "%DIST%"
if errorlevel 1 (
    set "ERRMSG=Packaged dist still contains Python source files"
    goto fail
)

set "STEP=CHECK_SUBPROCESS_RUNTIME"
echo [5.8/6] Smoke test final packaged subprocess workers...
venv\Scripts\python.exe build_assets\packaging\verify_packaged_subprocess_workers.py --exe "%DIST%\main.exe" --build-dir "%BUILD_DIR%"
if errorlevel 1 (
    set "ERRMSG=Packaged subprocess workers smoke test failed"
    goto fail
)

echo.
echo ========================================
echo   Build stage completed
echo   Output dir: %DIST%
echo ========================================
echo.

for /f "tokens=1" %%a in ('powershell -command "(Get-ChildItem '%DIST%' -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB" 2^>nul') do set SIZE=%%a
if defined SIZE (
    echo Total size: ~ %SIZE% MB
) else (
    dir /s "%DIST%"
)

set "STEP=CHECK_INNO_SETUP"
echo.
echo ========================================
echo   Build installers
echo ========================================
echo.

set "ISCC="
for %%p in (
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    "C:\Program Files\Inno Setup 6\ISCC.exe"
    "D:\Inno Setup 6\ISCC.exe"
) do if exist %%p set "ISCC=%%~p"

if "%ISCC%"=="" (
    echo Inno Setup not found, skip installer build.
    echo Please install Inno Setup locally and retry.
    echo.
    pause
    exit /b 0
)

set "STEP=BUILD_MAIN_INSTALLER"
echo Build main installer...
"%ISCC%" "%SCRIPT_DIR_NOSLASH%\setup.iss"
if errorlevel 1 (
    set "ERRMSG=Main installer build failed"
    goto fail
)

echo.
echo ========================================
echo   Build complete
echo   Installer: build_assets\packaging\release_output\LCA_Setup_v1.2.6.3.exe
echo ========================================
echo.
pause
exit /b 0

:fail
echo.
echo ========================================
echo   BUILD FAILED
echo ========================================
echo Step: %STEP%
if defined ERRMSG echo Error: %ERRMSG%
echo ErrorLevel: %errorlevel%
echo.
pause
exit /b 1


