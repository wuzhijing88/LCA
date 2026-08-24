@echo off
setlocal EnableExtensions

rem Keep the batch source ASCII-only. Chinese text is printed by PowerShell from UTF-8 Base64.
rem Do not switch the whole script to code page 65001: cmd then fails GOTO/CALL :label.
title Interception Driver Uninstaller

set "SCRIPT_FILE=%~f0"
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_VERSION=2026.08.17.2"
set "UNINSTALL_LOG=%TEMP%\Interception-uninstall.log"
set "ELEVATED="
if /I "%~1"=="/elevated" set "ELEVATED=1"

echo.
echo ==================================================
call :print "SW50ZXJjZXB0aW9uIOmpseWKqOWNuOi9veW3peWFtw=="
echo Version: %SCRIPT_VERSION%
call :print "5q2k5bel5YW35bCG5Y246L29IEludGVyY2VwdGlvbiDplK7nm5gv6byg5qCH6L+H5ruk6amx5Yqo44CC"
call :print "5Y246L295a6M5oiQ5ZCO5b+F6aG76YeN5ZCvIFdpbmRvd3PvvIzplK7nm5jpvKDmoIfmiY3kvJrlrozlhajmgaLlpI3mraPluLjjgII="
call :print "6L+Q6KGM5YmN6K+35YWI5YWz6ZetIExDQSDlj4rmiYDmnInkvb/nlKggSW50ZXJjZXB0aW9uIOeahOeoi+W6j+OAgg=="
echo.

:check_admin
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent()); if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { exit 0 } else { exit 1 }"
if not errorlevel 1 goto :admin_ready

if defined ELEVATED (
    call :print "W+mUmeivr10g5peg5rOV6I635b6X566h55CG5ZGY5p2D6ZmQ77yM5Y246L295bey5Y+W5raI44CC"
    call :print "6K+35Y+z6ZSu5q2k5paH5Lu277yM6YCJ5oup4oCc5Lul566h55CG5ZGY6Lqr5Lu96L+Q6KGM4oCd44CC"
    echo.
    pause
    exit /b 740
)

call :print "W+S/oeaBr10g5q2j5Zyo6K+35rGC566h55CG5ZGY5p2D6ZmQ77yM6K+35Zyo5by55Ye655qEIFVBQyDlr7nor53moYbkuK3pgInmi6nigJzmmK/igJ3jgII="
set "INTERCEPTION_UNINSTALL_SCRIPT=%SCRIPT_FILE%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "try { $script = $env:INTERCEPTION_UNINSTALL_SCRIPT; $work = Split-Path -LiteralPath $script -Parent; Start-Process -FilePath $script -ArgumentList @('/elevated') -WorkingDirectory $work -Verb RunAs -ErrorAction Stop } catch { exit 1 }"
if errorlevel 1 (
    call :print "W+mUmeivr10gVUFDIOaOiOadg+Wksei0peaIluiiq+WPlua2iO+8jOWNuOi9veayoeacieaJp+ihjOOAgg=="
    call :print "6K+35Y+z6ZSu5q2k5paH5Lu277yM6YCJ5oup4oCc5Lul566h55CG5ZGY6Lqr5Lu96L+Q6KGM4oCd44CC"
    echo.
    pause
    exit /b 1
)
exit /b 0

:admin_ready
call :print "W+S/oeaBr10g5bey6I635b6X566h55CG5ZGY5p2D6ZmQ44CC"
echo.

>"%UNINSTALL_LOG%" echo Interception uninstall started: %DATE% %TIME%

set "INSTALLER="
set "OFFICIAL_CODE="
set "FALLBACK_USED="
call :find_installer

if defined INSTALLER goto :run_official_uninstaller

call :print "W+aPkOekul0g5rKh5pyJ5om+5Yiw5a6Y5pa55a6J6KOF5ZmoIGluc3RhbGwtaW50ZXJjZXB0aW9uLmV4ZeOAgg=="
call :print "W+aPkOekul0g5bCG5bCd6K+V5L2/55So57O757uf5Lit55m76K6w55qEIEludGVyY2VwdGlvbiDnibnlvoHov5vooYzmuIXnkIbjgII="
echo.
goto :after_official_uninstaller

:run_official_uninstaller
for %%I in ("%INSTALLER%") do set "INSTALLER_DIR=%%~dpI"
call :print "W+S/oeaBr10g5om+5Yiw5a6Y5pa55a6J6KOF5Zmo77ya"
echo         "%INSTALLER%"
echo.

if not exist "%INSTALLER%" goto :installer_directory_error
call :print "W+atpemqpCAxLzJdIOato+WcqOaJp+ihjOWumOaWueWNuOi9veeoi+W6j++8jOivt+S4jeimgeaLlOaOiemUruebmOaIlum8oOaghy4uLg=="
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "try { $p = Start-Process -FilePath $env:INSTALLER -ArgumentList @('/uninstall') -WorkingDirectory $env:INSTALLER_DIR -Wait -PassThru -WindowStyle Hidden -ErrorAction Stop; if ($null -eq $p) { exit 1 }; exit $p.ExitCode } catch { exit 1 }"
set "OFFICIAL_CODE=%ERRORLEVEL%"

if "%OFFICIAL_CODE%"=="0" (
    call :print "W+WujOaIkF0g5a6Y5pa55Y246L2956iL5bqP5bey5omn6KGM5a6M5oiQ44CC"
) else (
    call :print "W+itpuWRil0g5a6Y5pa55Y246L2956iL5bqP6L+U5Zue5Luj56CB77ya"
    echo         %OFFICIAL_CODE%
    call :print "W+aPkOekul0g5bCG57un57ut5omn6KGM5YW85a655oCn5riF55CG5bm25aSN5qC46amx5Yqo54q25oCB44CC"
)
echo.
goto :after_official_uninstaller

:installer_directory_error
set "OFFICIAL_CODE=1"
call :print "W+itpuWRil0g5peg5rOV6K6/6Zeu5a6J6KOF5Zmo5omA5Zyo55uu5b2V77yM5bey6Lez6L+H5a6Y5pa55Y246L2956iL5bqP44CC"
call :print "W+aPkOekul0g5bCG57un57ut5omn6KGM5YW85a655oCn5riF55CG44CC"
echo.

:after_official_uninstaller
call :driver_present
if errorlevel 1 call :run_fallback

call :driver_present
if errorlevel 1 goto :uninstall_failed

call :leftover_driver_files
if errorlevel 1 (
    call :print "W+aPkOekul0gSW50ZXJjZXB0aW9uIOazqOWGjOS/oeaBr+W3sua4heeQhu+8jOS9humDqOWIhumpseWKqOaWh+S7tuS7jeiiqyBXaW5kb3dzIOWNoOeUqOOAgg=="
    call :print "6YeN5ZCv5ZCO6L+Z5Lqb5paH5Lu25Lya5aSx5pWI77yb6YeN5ZCv5ZCO5Y+v5YaN5qyh6L+Q6KGM5pys6ISa5pys56Gu6K6k44CC"
)

if defined OFFICIAL_CODE if not "%OFFICIAL_CODE%"=="0" call :print "W+aPkOekul0g5a6Y5pa55Y246L2956iL5bqP5pyq5q2j5bi46L+U5Zue77yM5L2G5YW85a655oCn5riF55CG5ZCO5bey5pyq5qOA5rWL5Yiw5rS75Yqo6amx5Yqo5rOo5YaM5L+h5oGv44CC"
if not defined INSTALLER if not defined FALLBACK_USED call :print "W+aPkOekul0g5b2T5YmN57O757uf5pyq5qOA5rWL5Yiw6ZyA6KaB5Y246L2955qEIEludGVyY2VwdGlvbiDpqbHliqjjgII="

echo.
call :print "W+aIkOWKn10g5b2T5YmN5bey5pyq5qOA5rWL5Yiw5q2j5Zyo5rOo5YaM55qEIEludGVyY2VwdGlvbiDplK7nm5gv6byg5qCH6L+H5ruk6amx5Yqo44CC"
call :print "W+mHjeimgV0g6K+35L+d5a2Y5b2T5YmN5bel5L2c5bm26YeN5ZCv6K6h566X5py677yM5L2/5Y246L295b275bqV55Sf5pWI44CC"
echo.
pause
exit /b 0

:run_fallback
set "FALLBACK_USED=1"
call :print "W+atpemqpCAyLzJdIOS7jeajgOa1i+WIsCBJbnRlcmNlcHRpb24g5rOo5YaM5L+h5oGv77yM5q2j5Zyo5omn6KGM5YW85a655oCn5riF55CGLi4u"
call :fallback_cleanup
set "FALLBACK_CODE=%ERRORLEVEL%"
if not "%FALLBACK_CODE%"=="0" call :print "W+itpuWRil0g5YW85a655oCn5riF55CG6YGH5Yiw6ZSZ6K+v77yM5bCG5Zyo5pyA5ZCO5aSN5qC457uT5p6c44CC"
if "%FALLBACK_CODE%"=="0" call :print "W+aPkOekul0g5bey56e76Zmk6L+H5ruk5Zmo5bm256aB55So6amx5Yqo5pyN5Yqh77yb6KKr5Y2g55So55qE6aG555uu5bCG5Zyo6YeN5ZCv5ZCO5Yig6Zmk44CC"
echo.
exit /b 0

:uninstall_failed
if not defined UNINSTALL_LOG set "UNINSTALL_LOG=%TEMP%\Interception-uninstall.log"
echo.
call :print "W+Wksei0pV0g5Y246L295ZCO5LuN5qOA5rWL5YiwIEludGVyY2VwdGlvbiDpqbHliqjms6jlhozkv6Hmga/jgII="
echo.
call :print "5Y+v6IO95Y6f5Zug77ya"
call :print "MS4g6amx5Yqo5q2j5Zyo5L2/55So77yM6ZyA5YWI6YeN5ZCv5ZCO5YaN5qyh6L+Q6KGM5pys6ISa5pys77yb"
call :print "Mi4g5a6J5YWo6L2v5Lu25oiW57O757uf562W55Wl6Zi75q2i5LqG6amx5Yqo5L+u5pS577yb"
call :print "My4g5b2T5YmN54mI5pys5LiN5piv5a6Y5pa5IEludGVyY2VwdGlvbiAxLjAwIOmpseWKqOOAgg=="
echo.
call :print "5bu66K6u77ya5L2/55So5Y6f5aeLIEludGVyY2VwdGlvbiDlronoo4XljIXlho3mrKHmiafooYwgL3VuaW5zdGFsbO+8jA=="
call :print "5oiW6L+b5YWlIFdpbmRvd3Mg5a6J5YWo5qih5byP5ZCO6L+Q6KGM5pys6ISa5pys44CC"
call :print "W+aXpeW/l10g6K+m57uG5L+h5oGv5bey5L+d5a2Y5Yiw77ya"
echo         "%UNINSTALL_LOG%"
pause
exit /b 1

:find_installer
rem Check the script directory and common relative paths first.
if exist "%SCRIPT_DIR%command line installer\install-interception.exe" set "INSTALLER=%SCRIPT_DIR%command line installer\install-interception.exe"
if not defined INSTALLER if exist "%SCRIPT_DIR%install-interception.exe" set "INSTALLER=%SCRIPT_DIR%install-interception.exe"
if not defined INSTALLER if exist "%SCRIPT_DIR%Interception\command line installer\install-interception.exe" set "INSTALLER=%SCRIPT_DIR%Interception\command line installer\install-interception.exe"
if defined INSTALLER exit /b 0

rem Search the script directory and common installation roots recursively.
set "SEARCH_ROOT=%SCRIPT_DIR%"
call :search_root
set "SEARCH_ROOT=%ProgramFiles%\LCA"
call :search_root
set "SEARCH_ROOT=%ProgramFiles(x86)%\LCA"
call :search_root
set "SEARCH_ROOT=%ProgramData%\LCA"
call :search_root
set "SEARCH_ROOT=%SystemDrive%\Interception"
call :search_root
set "SEARCH_ROOT=%SystemDrive%\LCA"
call :search_root
exit /b 0

:search_root
if defined INSTALLER exit /b 0
if not defined SEARCH_ROOT exit /b 0
if not exist "%SEARCH_ROOT%*" exit /b 0
for /f "delims=" %%I in ('dir /b /s /a:-d "%SEARCH_ROOT%\install-interception.exe" 2^>nul') do if not defined INSTALLER set "INSTALLER=%%~fI"
exit /b 0

:driver_present
rem Read-only detection of the Interception class filters and service names.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$found = $false; $sets = @('CurrentControlSet') + @(Get-ChildItem -LiteralPath 'HKLM:\SYSTEM' -ErrorAction SilentlyContinue | Where-Object { $_.PSChildName -match '^ControlSet\d{3}$' } | ForEach-Object { $_.PSChildName }); $sets = @($sets | Select-Object -Unique); $targets = @(@('{4d36e96b-e325-11ce-bfc1-08002be10318}','keyboard'), @('{4d36e96f-e325-11ce-bfc1-08002be10318}','mouse')); foreach ($set in $sets) { foreach ($target in $targets) { $path = 'HKLM:\SYSTEM\' + $set + '\Control\Class\' + $target[0]; $value = (Get-ItemProperty -LiteralPath $path -Name UpperFilters -ErrorAction SilentlyContinue).UpperFilters; foreach ($item in @($value)) { if ([string]$item -ieq $target[1]) { $found = $true } } } }; $services = @(@('keyboard','Keyboard Upper Filter Driver'), @('mouse','Mouse Upper Filter Driver')); foreach ($serviceInfo in $services) { $service = Get-ItemProperty -LiteralPath ('HKLM:\SYSTEM\CurrentControlSet\Services\' + $serviceInfo[0]) -ErrorAction SilentlyContinue; if ($null -ne $service -and [string]$service.DisplayName -ieq $serviceInfo[1] -and [int]$service.Start -ne 4) { $found = $true } }; if ($found) { exit 1 } else { exit 0 }"
exit /b %ERRORLEVEL%

:fallback_cleanup
rem Remove only verified Interception entries, disable the services, and schedule locked files for reboot deletion.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$failed = $false; $log = Join-Path $env:TEMP 'Interception-uninstall.log'; function Log([string]$message) { try { Add-Content -LiteralPath $log -Value ((Get-Date -Format s) + ' ' + $message) -Encoding UTF8 } catch {} }; Log 'fallback-start'; $hklm = [Microsoft.Win32.Registry]::LocalMachine; $system = $hklm.OpenSubKey('SYSTEM'); $sets = @('CurrentControlSet'); if ($null -ne $system) { $sets += @($system.GetSubKeyNames() | Where-Object { $_ -match '^ControlSet\d{3}$' }); $system.Close() }; $sets = @($sets | Select-Object -Unique); $targets = @(@('{4d36e96b-e325-11ce-bfc1-08002be10318}','keyboard','kbdclass'), @('{4d36e96f-e325-11ce-bfc1-08002be10318}','mouse','mouclass')); $verified = @{ keyboard = $false; mouse = $false }; foreach ($set in $sets) { foreach ($target in $targets) { $key = $null; $path = 'SYSTEM\' + $set + '\Control\Class\' + $target[0]; try { $key = $hklm.OpenSubKey($path, $true); if ($null -eq $key) { continue }; $old = [string[]]$key.GetValue('UpperFilters', $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames); if ($null -eq $old) { continue }; $hasFilter = $false; foreach ($value in $old) { if ([string]$value -ieq $target[1]) { $hasFilter = $true } }; if (-not $hasFilter) { continue }; $verified[$target[1]] = $true; $new = New-Object 'System.Collections.Generic.List[string]'; foreach ($value in $old) { if ($value -and [string]$value -ine $target[1]) { [void]$new.Add([string]$value) } }; $hasBase = $false; foreach ($value in $new) { if ([string]$value -ieq $target[2]) { $hasBase = $true } }; if (-not $hasBase) { [void]$new.Add($target[2]) }; $key.SetValue('UpperFilters', [string[]]$new.ToArray(), [Microsoft.Win32.RegistryValueKind]::MultiString); $check = [string[]]$key.GetValue('UpperFilters'); if (@($check | Where-Object { $_ -ieq $target[1] }).Count -gt 0) { $failed = $true; Log ('filter-verify-failed ' + $path) } else { Log ('filter-removed ' + $path) } } catch { $failed = $true; Log ('filter-error ' + $path + ' ' + $_.Exception.Message) } finally { if ($null -ne $key) { $key.Close() } } } }; $services = @(@('keyboard','keyboard.sys','Keyboard Upper Filter Driver'), @('mouse','mouse.sys','Mouse Upper Filter Driver')); foreach ($entry in $services) { $name = $entry[0]; $driverPath = Join-Path $env:windir ('System32\drivers\' + $entry[1]); $isInterception = $verified[$name]; foreach ($set in $sets) { $serviceKey = $null; try { $serviceKey = $hklm.OpenSubKey(('SYSTEM\' + $set + '\Services\' + $name)); if ($null -ne $serviceKey -and [string]$serviceKey.GetValue('DisplayName') -ieq $entry[2]) { $isInterception = $true } } finally { if ($null -ne $serviceKey) { $serviceKey.Close() } } }; if (Test-Path -LiteralPath $driverPath) { $file = Get-Item -LiteralPath $driverPath -ErrorAction SilentlyContinue; if ($null -ne $file -and (([string]$file.VersionInfo.ProductName -ieq 'Interception') -or ([string]$file.VersionInfo.CompanyName -ieq 'Oblita'))) { $isInterception = $true } }; if (-not $isInterception) { Log ('service-skipped ' + $name); continue }; foreach ($set in $sets) { $serviceKey = $null; try { $serviceKey = $hklm.OpenSubKey(('SYSTEM\' + $set + '\Services\' + $name), $true); if ($null -ne $serviceKey) { $serviceKey.SetValue('Start', 4, [Microsoft.Win32.RegistryValueKind]::DWord) } } catch { $failed = $true; Log ('service-disable-error ' + $set + ' ' + $name + ' ' + $_.Exception.Message) } finally { if ($null -ne $serviceKey) { $serviceKey.Close() } } }; $null = sc.exe config $name start= disabled 2>&1; Log ('service-config ' + $name + ' code=' + $LASTEXITCODE); $null = sc.exe delete $name 2>&1; $deleteCode = $LASTEXITCODE; Log ('service-delete ' + $name + ' code=' + $deleteCode); if ($deleteCode -ne 0 -and $deleteCode -ne 1072 -and $deleteCode -ne 1060) { $failed = $true }; if (Test-Path -LiteralPath $driverPath) { try { Remove-Item -LiteralPath $driverPath -Force -ErrorAction Stop; Log ('file-removed ' + $driverPath) } catch { try { $session = $hklm.OpenSubKey('SYSTEM\CurrentControlSet\Control\Session Manager', $true); $pending = [string[]]$session.GetValue('PendingFileRenameOperations', [string[]]@(), [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames); $source = '\??\' + $driverPath; if (-not (@($pending) -icontains $source)) { $list = New-Object 'System.Collections.Generic.List[string]'; foreach ($item in @($pending)) { if ($null -ne $item) { [void]$list.Add([string]$item) } }; [void]$list.Add($source); [void]$list.Add(''); $session.SetValue('PendingFileRenameOperations', [string[]]$list.ToArray(), [Microsoft.Win32.RegistryValueKind]::MultiString) }; $session.Close(); Log ('file-scheduled ' + $driverPath) } catch { $failed = $true; Log ('file-schedule-error ' + $driverPath + ' ' + $_.Exception.Message) } } } }; foreach ($set in $sets) { foreach ($target in $targets) { $path = 'HKLM:\SYSTEM\' + $set + '\Control\Class\' + $target[0]; $value = (Get-ItemProperty -LiteralPath $path -Name UpperFilters -ErrorAction SilentlyContinue).UpperFilters; if (@($value) -icontains $target[1]) { $failed = $true; Log ('final-filter-present ' + $set + ' ' + $target[1]) } } }; Log ('fallback-end failed=' + $failed); if ($failed) { exit 2 } else { exit 0 }"
exit /b %ERRORLEVEL%

:leftover_driver_files
rem Driver files can remain locked until the reboot; this is a separate check.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$leftover = $false; foreach ($name in @('keyboard.sys','mouse.sys')) { $path = Join-Path $env:windir ('System32\drivers\' + $name); if (Test-Path -LiteralPath $path) { $file = Get-Item -LiteralPath $path -ErrorAction SilentlyContinue; if ($null -ne $file -and (([string]$file.VersionInfo.ProductName -ieq 'Interception') -or ([string]$file.VersionInfo.CompanyName -ieq 'Oblita'))) { $leftover = $true } } }; if ($leftover) { exit 1 } else { exit 0 }"
exit /b %ERRORLEVEL%

:print
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$text = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('%~1')); Write-Host $text"
exit /b 0
