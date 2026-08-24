; Inno Setup Script - Chinese Version
; Encoding: UTF-8 with BOM

#define MyAppName "LCA"
#define MyAppEdition "离线版"
#define MyAppDisplayName "LCA 离线版"
#define MyAppPublisher "LCA"
#define MyAppExeName "main.exe"
#define MyAppIcon "..\..\resources\icon.ico"
#define MyAppMutex "LCA_Application_Mutex_B8C3D4E5"
#define MyAppId "B8C3D4E5-F6A7-8901-BCDE-FA2345678901"

#ifndef MySourceDist
  #define MySourceDist "build_output\main.dist"
#endif

#ifndef MyOutputDir
  #define MyOutputDir "release_output"
#endif

[Setup]
AppId={#emit '{{' + MyAppId + '}'}
AppName={#MyAppDisplayName}
AppVersion={#MyAppEdition}
AppVerName={#MyAppDisplayName}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppDisplayName}
DisableDirPage=no
AllowNoIcons=yes
OutputDir={#MyOutputDir}
OutputBaseFilename=LCA_离线版_Setup

; 压缩优化
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4

; 图标设置
SetupIconFile={#MyAppIcon}
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardStyle=modern

; 权限和架构
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; 最低系统版本 (Windows 10)
MinVersion=10.0

; 防止多实例运行
AppMutex={#MyAppMutex}
SetupMutex=LCA_Setup_Mutex

; 应用程序管理
CloseApplications=force
CloseApplicationsFilter={#MyAppExeName}
RestartApplications=yes
RestartIfNeededByRun=yes

; 卸载设置
Uninstallable=yes
UninstallDisplayName={#MyAppDisplayName}
CreateUninstallRegKey=yes
UpdateUninstallLogAppName=yes

; 目录和磁盘
DirExistsWarning=auto
ExtraDiskSpaceRequired=524288000
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
UsePreviousGroup=yes
UsePreviousTasks=yes

; Inno 的 PE 字段要求数字，仅作为内部固定值，不对外表示版本号
VersionInfoVersion=1.0.0.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppDisplayName}安装程序
VersionInfoProductName={#MyAppDisplayName}
VersionInfoProductVersion=1.0.0.0
VersionInfoCopyright=Copyright (C) {#MyAppPublisher}

; 安装界面
ShowComponentSizes=yes
ShowLanguageDialog=auto
WizardImageStretch=yes
WizardSizePercent=100

; 许可协议
LicenseFile=..\..\resources\disclaimer.txt

; 安装日志 (便于排查问题)
SetupLogging=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项:"
Name: "startmenuicon"; Description: "创建开始菜单快捷方式"; GroupDescription: "附加选项:"; Flags: unchecked

[Files]
Source: "{#MySourceDist}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "export_runtime\*;runtime_templates\*;workflow_lite_runner_template*.exe;_tufup_data\*;qtmonaco\*;QtWebEngineProcess.exe;*Qt6WebEngine*;*qtwebengine*;*PP-OCRv6*.onnx;*PP-OCRv5*.onnx;config\credentials.json;config\build_auth_secret.b64x2"

[InstallDelete]
; 安装前清理旧版残留：源码缓存、已废弃更新/精简运行时、变量编辑器，以及 RapidOCR 误带的 v5/v6 模型
Type: filesandordirs; Name: "{app}\win32com"
Type: files; Name: "{app}\comtypes\gen\*.py"
Type: filesandordirs; Name: "{app}\comtypes\gen\__pycache__"
Type: filesandordirs; Name: "{app}\_tufup_data"
Type: filesandordirs; Name: "{app}\export_runtime"
Type: filesandordirs; Name: "{app}\runtime_templates"
Type: filesandordirs; Name: "{app}\qtmonaco"
Type: files; Name: "{app}\QtWebEngineProcess.exe"
Type: files; Name: "{app}\Qt6WebEngine*.dll"
Type: files; Name: "{app}\PySide6\Qt6WebEngine*.dll"
Type: filesandordirs; Name: "{app}\PySide6\resources\qtwebengine_locales"
Type: files; Name: "{app}\PySide6\resources\qtwebengine*"
Type: files; Name: "{app}\PySide6\translations\qtwebengine*"
Type: files; Name: "{app}\workflow_lite_runner_template*.exe"
Type: filesandordirs; Name: "{app}\map_navigation_worker.build"
Type: filesandordirs; Name: "{app}\map_navigation_worker.dist"
Type: files; Name: "{app}\models\rapidocr\*PP-OCRv6*"
Type: files; Name: "{app}\models\rapidocr\*PP-OCRv5*"
Type: files; Name: "{app}\rapidocr\*.onnx"
Type: files; Name: "{app}\rapidocr\*\*.onnx"

[Icons]
; 桌面图标
Name: "{autodesktop}\{#MyAppDisplayName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\resources\icon.ico"
; 开始菜单图标
Name: "{autoprograms}\{#MyAppDisplayName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startmenuicon; IconFilename: "{app}\resources\icon.ico"
Name: "{autoprograms}\卸载 {#MyAppDisplayName}"; Filename: "{uninstallexe}"; Tasks: startmenuicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppDisplayName}"; Flags: nowait postinstall skipifsilent runascurrentuser shellexec

[UninstallDelete]
; 运行时缓存始终删除；日志、配置、工作流、图片、备份由 Code 段按用户选择处理
Type: filesandordirs; Name: "{app}\win32com"

[Code]
const
  APP_MUTEX_NAME = '{#MyAppMutex}';
  APP_ID = '{#MyAppId}';
  UNINSTALL_ROOT = 'Software\Microsoft\Windows\CurrentVersion\Uninstall';

function GetPrimaryUninstallKey(): String;
begin
  Result := UNINSTALL_ROOT + '\{' + APP_ID + '}_is1';
end;

function GetLegacyUninstallKey(): String;
begin
  Result := UNINSTALL_ROOT + '\' + APP_ID + '_is1';
end;

function GetUserDataRoot(): String;
begin
  { 现行用户数据位于 %LOCALAPPDATA%\LCA；便携模式数据仍可能位于程序目录 }
  Result := Trim(GetEnv('LOCALAPPDATA'));
  if Result = '' then
    Result := Trim(GetEnv('APPDATA'));
  if Result <> '' then
    Result := AddBackslash(Result) + '{#MyAppName}'
  else
    Result := '';
end;

procedure DeleteUserDataTree();
var
  UserDataRoot: String;
begin
  UserDataRoot := GetUserDataRoot();
  if UserDataRoot = '' then
    Exit;
  if DirExists(UserDataRoot) then
    DelTree(UserDataRoot, True, True, True);
end;

function EnsureDirectoryExists(const DirPath: String): Boolean;
begin
  if DirPath = '' then
  begin
    Result := False;
    Exit;
  end;

  if DirExists(DirPath) then
  begin
    Result := True;
    Exit;
  end;

  Result := ForceDirectories(DirPath);
end;

function BackupDirectoryTree(const SourceDir: String; const BackupRoot: String): Boolean;
var
  FindRec: TFindRec;
  SourcePath: String;
  BackupPath: String;
begin
  Result := True;

  if not DirExists(SourceDir) then
    Exit;

  if not EnsureDirectoryExists(BackupRoot) then
  begin
    Result := False;
    Exit;
  end;

  if FindFirst(AddBackslash(SourceDir) + '*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name = '.') or (FindRec.Name = '..') then
          Continue;

        SourcePath := AddBackslash(SourceDir) + FindRec.Name;
        BackupPath := AddBackslash(BackupRoot) + FindRec.Name;

        if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
        begin
          if not BackupDirectoryTree(SourcePath, BackupPath) then
          begin
            Result := False;
            Exit;
          end;
        end
        else
        begin
          if not EnsureDirectoryExists(ExtractFileDir(BackupPath)) then
          begin
            Result := False;
            Exit;
          end;

          if not CopyFile(SourcePath, BackupPath, False) then
          begin
            Result := False;
            Exit;
          end;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

function BackupFileIfExists(const InstallPath: String; const RelativePath: String; const BackupRoot: String): Boolean;
var
  SourcePath: String;
  BackupPath: String;
begin
  Result := True;
  SourcePath := AddBackslash(InstallPath) + RelativePath;
  if not FileExists(SourcePath) then
    Exit;

  BackupPath := AddBackslash(BackupRoot) + RelativePath;
  if not EnsureDirectoryExists(ExtractFileDir(BackupPath)) then
  begin
    Result := False;
    Exit;
  end;

  Result := CopyFile(SourcePath, BackupPath, False);
end;

function BackupRootJsonFiles(const InstallPath: String; const BackupRoot: String): Boolean;
var
  FindRec: TFindRec;
  SourcePath: String;
  BackupPath: String;
begin
  Result := True;

  if not DirExists(InstallPath) then
    Exit;

  if not EnsureDirectoryExists(BackupRoot) then
  begin
    Result := False;
    Exit;
  end;

  if FindFirst(AddBackslash(InstallPath) + '*.json', FindRec) then
  begin
    try
      repeat
        if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
          Continue;

        SourcePath := AddBackslash(InstallPath) + FindRec.Name;
        BackupPath := AddBackslash(BackupRoot) + FindRec.Name;
        if not CopyFile(SourcePath, BackupPath, False) then
        begin
          Result := False;
          Exit;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

function RestoreDirectoryTree(const BackupRoot: String; const TargetDir: String): Boolean;
var
  FindRec: TFindRec;
  BackupPath: String;
  TargetPath: String;
begin
  Result := True;

  if not DirExists(BackupRoot) then
    Exit;

  if not EnsureDirectoryExists(TargetDir) then
  begin
    Result := False;
    Exit;
  end;

  if FindFirst(AddBackslash(BackupRoot) + '*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name = '.') or (FindRec.Name = '..') then
          Continue;

        BackupPath := AddBackslash(BackupRoot) + FindRec.Name;
        TargetPath := AddBackslash(TargetDir) + FindRec.Name;

        if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
        begin
          if not RestoreDirectoryTree(BackupPath, TargetPath) then
          begin
            Result := False;
            Exit;
          end;
        end
        else
        begin
          if not EnsureDirectoryExists(ExtractFileDir(TargetPath)) then
          begin
            Result := False;
            Exit;
          end;

          if not CopyFile(BackupPath, TargetPath, False) then
          begin
            Result := False;
            Exit;
          end;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

procedure DeleteRootRuntimeFiles(const InstallPath: String);
var
  FindRec: TFindRec;
  FileName: String;
  FilePath: String;
  LowerName: String;
begin
  if not DirExists(InstallPath) then
    Exit;

  if FindFirst(AddBackslash(InstallPath) + '*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name = '.') or (FindRec.Name = '..') then
          Continue;

        if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
          Continue;

        FileName := FindRec.Name;
        LowerName := LowerCase(FileName);
        FilePath := AddBackslash(InstallPath) + FileName;

        if
          (LowerName = LowerCase('{#MyAppExeName}')) or
          (LowerName = 'automationlog.txt') or
          (Pos('unins', LowerName) = 1) or
          (ExtractFileExt(LowerName) = '.dll') or
          (ExtractFileExt(LowerName) = '.pyd') or
          (ExtractFileExt(LowerName) = '.manifest')
        then
          DeleteFile(FilePath);
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

procedure DeleteRuntimeDirectoryIfExists(const InstallPath: String; const RelativePath: String);
var
  TargetPath: String;
begin
  TargetPath := AddBackslash(InstallPath) + RelativePath;
  if DirExists(TargetPath) then
    DelTree(TargetPath, True, True, True);
end;

function GetPreservedUserDataDirNames(): TArrayOfString;
begin
  SetArrayLength(Result, 11);
  Result[0] := 'backups';
  Result[1] := 'logs';
  Result[2] := 'config';
  Result[3] := 'workflows';
  Result[4] := 'images';
  Result[5] := 'runtime_data';
  Result[6] := 'runtime';
  Result[7] := 'models';
  Result[8] := 'sounds';
  Result[9] := 'pic_cache';
  Result[10] := 'templates';
end;

function GetProgramRuntimeDirNames(): TArrayOfString;
begin
  SetArrayLength(Result, 29);
  Result[0] := 'AutoHotkey';
  Result[1] := 'certs';
  Result[2] := 'charset_normalizer';
  Result[3] := 'comtypes';
  Result[4] := 'config';
  Result[5] := 'cryptography';
  Result[6] := 'cv2';
  Result[7] := 'Interception';
  Result[8] := 'numpy';
  Result[9] := 'numpy.libs';
  Result[10] := 'PIL';
  Result[11] := 'psutil';
  Result[12] := 'PySide6';
  Result[13] := 'resources';
  Result[14] := 'shiboken6';
  Result[15] := 'themes';
  Result[16] := 'uiautomation';
  Result[17] := 'winrt';
  Result[18] := 'tools';
  Result[19] := 'rapidocr';
  Result[20] := 'yaml';
  Result[21] := 'keyboard';
  Result[22] := 'mouse';
  Result[23] := 'qtmonaco';
  Result[24] := 'onnxruntime';
  Result[25] := 'win32com';
  Result[26] := '_tufup_data';
  Result[27] := 'export_runtime';
  Result[28] := 'runtime_templates';
end;

procedure DeleteFilesByMask(const DirPath, Mask: String);
var
  FindRec: TFindRec;
begin
  if not DirExists(DirPath) then
    Exit;

  if FindFirst(AddBackslash(DirPath) + Mask, FindRec) then
  begin
    try
      repeat
        if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) = 0 then
          DeleteFile(AddBackslash(DirPath) + FindRec.Name);
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

procedure DeleteAppUserData();
var
  AppPath: String;
  Names: TArrayOfString;
  i: Integer;
begin
  AppPath := ExpandConstant('{app}');
  DeleteFile(AddBackslash(AppPath) + 'config.json');
  DeleteFile(AddBackslash(AppPath) + 'workflow_favorites.json');
  DeleteFile(AddBackslash(AppPath) + 'universal_system_config.json');
  DeleteFilesByMask(AppPath, 'config.instance-*.json');
  DeleteFilesByMask(AppPath, '*.log');
  Names := GetPreservedUserDataDirNames();
  for i := 0 to GetArrayLength(Names) - 1 do
    DelTree(AddBackslash(AppPath) + Names[i], True, True, True);
  DeleteUserDataTree();
end;

function CleanupPortableInstallResiduals(const InstallPath: String): Boolean;
var
  Path: String;
  BackupRoot: String;
  Names: TArrayOfString;
  i: Integer;
begin
  Result := False;
  Path := RemoveBackslashUnlessRoot(Trim(InstallPath));
  if Path = '' then
    Exit;

  if not DirExists(Path) then
  begin
    Result := True;
    Exit;
  end;

  BackupRoot := ExpandConstant('{tmp}\lca_install_preserve');
  if DirExists(BackupRoot) then
    DelTree(BackupRoot, True, True, True);

  if not EnsureDirectoryExists(BackupRoot) then
    Exit;

  Names := GetPreservedUserDataDirNames();
  for i := 0 to GetArrayLength(Names) - 1 do
  begin
    if not BackupDirectoryTree(AddBackslash(Path) + Names[i], AddBackslash(BackupRoot) + Names[i]) then
      Exit;
  end;

  if not BackupRootJsonFiles(Path, BackupRoot) then
    Exit;

  DeleteRootRuntimeFiles(Path);
  Names := GetProgramRuntimeDirNames();
  for i := 0 to GetArrayLength(Names) - 1 do
    DeleteRuntimeDirectoryIfExists(Path, Names[i]);

  Names := GetPreservedUserDataDirNames();
  for i := 0 to GetArrayLength(Names) - 1 do
  begin
    if not RestoreDirectoryTree(AddBackslash(BackupRoot) + Names[i], AddBackslash(Path) + Names[i]) then
      Exit;
  end;
  if not RestoreDirectoryTree(BackupRoot, Path) then
    Exit;

  if DirExists(BackupRoot) then
    DelTree(BackupRoot, True, True, True);

  Result := not FileExists(AddBackslash(Path) + '{#MyAppExeName}');
end;

// 强制终止进程 (带重试机制)
procedure KillProcess(const ExeName: String);
var
  ResultCode: Integer;
  Retries: Integer;
begin
  for Retries := 0 to 2 do
  begin
    if Exec('taskkill', '/F /IM ' + ExeName + ' /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      Break;
    Sleep(500);
  end;
end;

// 检查应用程序是否正在运行 (通过 Mutex)
function IsAppRunning(): Boolean;
begin
  Result := CheckForMutexes(APP_MUTEX_NAME);
end;

// 等待应用程序关闭
function WaitForAppClose(MaxWaitSeconds: Integer): Boolean;
var
  WaitCount: Integer;
begin
  Result := True;
  WaitCount := 0;

  while IsAppRunning() and (WaitCount < MaxWaitSeconds) do
  begin
    Sleep(1000);
    Inc(WaitCount);
  end;

  if IsAppRunning() then
    Result := False;
end;

function GetUninstallString(): String;
var
  UninstallString: String;
begin
  Result := '';
  if RegQueryStringValue(HKLM64, GetPrimaryUninstallKey(), 'UninstallString', UninstallString) then
    Result := UninstallString
  else if RegQueryStringValue(HKLM, GetPrimaryUninstallKey(), 'UninstallString', UninstallString) then
    Result := UninstallString
  else if RegQueryStringValue(HKCU, GetPrimaryUninstallKey(), 'UninstallString', UninstallString) then
    Result := UninstallString
  else if RegQueryStringValue(HKLM64, GetLegacyUninstallKey(), 'UninstallString', UninstallString) then
    Result := UninstallString
  else if RegQueryStringValue(HKLM, GetLegacyUninstallKey(), 'UninstallString', UninstallString) then
    Result := UninstallString
  else if RegQueryStringValue(HKCU, GetLegacyUninstallKey(), 'UninstallString', UninstallString) then
    Result := UninstallString;
end;

function GetInstalledVersion(): String;
var
  Version: String;
begin
  Result := '';
  if RegQueryStringValue(HKLM64, GetPrimaryUninstallKey(), 'DisplayVersion', Version) then
    Result := Version
  else if RegQueryStringValue(HKLM, GetPrimaryUninstallKey(), 'DisplayVersion', Version) then
    Result := Version
  else if RegQueryStringValue(HKCU, GetPrimaryUninstallKey(), 'DisplayVersion', Version) then
    Result := Version
  else if RegQueryStringValue(HKLM64, GetLegacyUninstallKey(), 'DisplayVersion', Version) then
    Result := Version
  else if RegQueryStringValue(HKLM, GetLegacyUninstallKey(), 'DisplayVersion', Version) then
    Result := Version
  else if RegQueryStringValue(HKCU, GetLegacyUninstallKey(), 'DisplayVersion', Version) then
    Result := Version;
end;

function GetInstalledAppPath(): String;
var
  AppPath: String;
begin
  Result := '';
  if RegQueryStringValue(HKLM64, GetPrimaryUninstallKey(), 'InstallLocation', AppPath) then
    Result := AppPath
  else if RegQueryStringValue(HKLM, GetPrimaryUninstallKey(), 'InstallLocation', AppPath) then
    Result := AppPath
  else if RegQueryStringValue(HKCU, GetPrimaryUninstallKey(), 'InstallLocation', AppPath) then
    Result := AppPath
  else if RegQueryStringValue(HKLM64, GetPrimaryUninstallKey(), 'Inno Setup: App Path', AppPath) then
    Result := AppPath
  else if RegQueryStringValue(HKLM, GetPrimaryUninstallKey(), 'Inno Setup: App Path', AppPath) then
    Result := AppPath
  else if RegQueryStringValue(HKCU, GetPrimaryUninstallKey(), 'Inno Setup: App Path', AppPath) then
    Result := AppPath
  else if RegQueryStringValue(HKLM64, GetLegacyUninstallKey(), 'InstallLocation', AppPath) then
    Result := AppPath
  else if RegQueryStringValue(HKLM, GetLegacyUninstallKey(), 'InstallLocation', AppPath) then
    Result := AppPath
  else if RegQueryStringValue(HKCU, GetLegacyUninstallKey(), 'InstallLocation', AppPath) then
    Result := AppPath
  else if RegQueryStringValue(HKLM64, GetLegacyUninstallKey(), 'Inno Setup: App Path', AppPath) then
    Result := AppPath
  else if RegQueryStringValue(HKLM, GetLegacyUninstallKey(), 'Inno Setup: App Path', AppPath) then
    Result := AppPath
  else if RegQueryStringValue(HKCU, GetLegacyUninstallKey(), 'Inno Setup: App Path', AppPath) then
    Result := AppPath;

  Result := RemoveBackslashUnlessRoot(Trim(Result));
end;

function HasAnyUninstallEntry(): Boolean;
begin
  Result :=
    RegKeyExists(HKLM64, GetPrimaryUninstallKey()) or
    RegKeyExists(HKLM, GetPrimaryUninstallKey()) or
    RegKeyExists(HKCU, GetPrimaryUninstallKey()) or
    RegKeyExists(HKLM64, GetLegacyUninstallKey()) or
    RegKeyExists(HKLM, GetLegacyUninstallKey()) or
    RegKeyExists(HKCU, GetLegacyUninstallKey());
end;

function DeleteUninstallKey(const RootKey: Integer; const Key: String): Boolean;
begin
  Result := True;
  if RegKeyExists(RootKey, Key) then
    Result := RegDeleteKeyIncludingSubkeys(RootKey, Key);
end;

function CleanupUninstallRegistryResiduals(): Boolean;
begin
  Result :=
    DeleteUninstallKey(HKLM64, GetPrimaryUninstallKey()) and
    DeleteUninstallKey(HKLM, GetPrimaryUninstallKey()) and
    DeleteUninstallKey(HKCU, GetPrimaryUninstallKey()) and
    DeleteUninstallKey(HKLM64, GetLegacyUninstallKey()) and
    DeleteUninstallKey(HKLM, GetLegacyUninstallKey()) and
    DeleteUninstallKey(HKCU, GetLegacyUninstallKey());
end;

// 解析卸载命令，兼容 "xxx\unins000.exe" 及其附带参数
function ParseUninstallCommand(const RawCommand: String; var UninstallerPath: String; var UninstallerParams: String): Boolean;
var
  Command: String;
  LowerCommand: String;
  i: Integer;
begin
  Result := False;
  UninstallerPath := '';
  UninstallerParams := '';
  Command := Trim(RawCommand);
  if Command = '' then
    Exit;

  if (Length(Command) >= 2) and (Command[1] = '"') then
  begin
    for i := 2 to Length(Command) do
    begin
      if Command[i] = '"' then
      begin
        UninstallerPath := Copy(Command, 2, i - 2);
        UninstallerParams := Trim(Copy(Command, i + 1, MaxInt));
        Break;
      end;
    end;
  end
  else
  begin
    LowerCommand := LowerCase(Command);
    i := Pos('.exe', LowerCommand);
    if i > 0 then
    begin
      UninstallerPath := Trim(Copy(Command, 1, i + 3));
      UninstallerParams := Trim(Copy(Command, i + 4, MaxInt));
    end
    else
    begin
      i := Pos(' ', Command);
      if i > 0 then
      begin
        UninstallerPath := Copy(Command, 1, i - 1);
        UninstallerParams := Trim(Copy(Command, i + 1, MaxInt));
      end
      else
        UninstallerPath := Command;
    end;
  end;

  Result := UninstallerPath <> '';
end;

function IsMsiexec(const ExePath: String): Boolean;
var
  ExeFile: String;
begin
  ExeFile := LowerCase(ExtractFileName(RemoveQuotes(Trim(ExePath))));
  Result := (ExeFile = 'msiexec') or (ExeFile = 'msiexec.exe');
end;

function EnsureUninstallSilentParams(const ExePath: String; const Params: String): String;
var
  FinalParams: String;
  LowerParams: String;
begin
  FinalParams := Trim(Params);
  LowerParams := LowerCase(' ' + FinalParams + ' ');

  if IsMsiexec(ExePath) then
  begin
    if (Pos(' /x', LowerParams) = 0) and (Pos(' /i', LowerParams) > 0) then
    begin
      StringChangeEx(FinalParams, '/I{', '/X{', False);
      StringChangeEx(FinalParams, '/i{', '/X{', False);
      StringChangeEx(FinalParams, '/I ', '/X ', False);
      StringChangeEx(FinalParams, '/i ', '/X ', False);
      LowerParams := LowerCase(' ' + FinalParams + ' ');
    end;

    if (Pos(' /qn ', LowerParams) = 0) and (Pos(' /quiet ', LowerParams) = 0) then
    begin
      if FinalParams <> '' then
        FinalParams := FinalParams + ' ';
      FinalParams := FinalParams + '/qn';
    end;

    if Pos(' /norestart ', LowerParams) = 0 then
    begin
      if FinalParams <> '' then
        FinalParams := FinalParams + ' ';
      FinalParams := FinalParams + '/norestart';
    end;
  end
  else
  begin
    if (Pos(' /silent ', LowerParams) = 0) and (Pos(' /verysilent ', LowerParams) = 0) then
    begin
      if FinalParams <> '' then
        FinalParams := FinalParams + ' ';
      FinalParams := FinalParams + '/VERYSILENT /SUPPRESSMSGBOXES';
    end;

    if Pos(' /norestart ', LowerParams) = 0 then
    begin
      if FinalParams <> '' then
        FinalParams := FinalParams + ' ';
      FinalParams := FinalParams + '/NORESTART';
    end;
  end;

  Result := FinalParams;
end;

function IsUninstallExitCodeSuccess(const Code: Integer): Boolean;
begin
  Result := (Code = 0) or (Code = 1641) or (Code = 3010);
end;

function ExecuteUninstallCommand(const RawCommand: String): Boolean;
var
  UninstallExe: String;
  UninstallParams: String;
  ResultCode: Integer;
begin
  Result := False;
  if not ParseUninstallCommand(RawCommand, UninstallExe, UninstallParams) then
    Exit;

  UninstallParams := EnsureUninstallSilentParams(UninstallExe, UninstallParams);
  if not Exec(UninstallExe, UninstallParams, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Exit;

  Result := IsUninstallExitCodeSuccess(ResultCode);
end;

function HasProgramResidualFiles(const InstallPath: String): Boolean;
var
  Path: String;
begin
  Path := RemoveBackslashUnlessRoot(Trim(InstallPath));
  if Path = '' then
  begin
    Result := False;
    Exit;
  end;

  Result :=
    FileExists(AddBackslash(Path) + '{#MyAppExeName}') or
    FileExists(AddBackslash(Path) + 'unins000.exe');
end;

function TryUninstallByPath(const InstallPath: String): Boolean;
var
  Path: String;
  Uninstaller: String;
begin
  Result := True;
  Path := RemoveBackslashUnlessRoot(Trim(InstallPath));
  if Path = '' then
    Exit;

  Uninstaller := AddBackslash(Path) + 'unins000.exe';
  if not FileExists(Uninstaller) then
  begin
    Result := False;
    Exit;
  end;

  if not ExecuteUninstallCommand('"' + Uninstaller + '"') then
  begin
    Result := False;
    Exit;
  end;

  Sleep(1000);
  Result := not HasProgramResidualFiles(Path);
end;

function IsPortableInstallResidual(const InstallPath: String): Boolean;
var
  Path: String;
begin
  Path := RemoveBackslashUnlessRoot(Trim(InstallPath));
  if Path = '' then
  begin
    Result := False;
    Exit;
  end;

  Result :=
    FileExists(AddBackslash(Path) + '{#MyAppExeName}') and
    (not FileExists(AddBackslash(Path) + 'unins000.exe'));
end;

function EnsureNoResidualAtPath(const InstallPath: String): Boolean;
begin
  if not HasProgramResidualFiles(InstallPath) then
  begin
    Result := True;
    Exit;
  end;

  if not TryUninstallByPath(InstallPath) then
  begin
    if IsPortableInstallResidual(InstallPath) then
    begin
#ifdef NonInteractive
      KillProcess('{#MyAppExeName}');
      Result := CleanupPortableInstallResiduals(InstallPath);
      Exit;
#else
      if MsgBox(
        '检测到目标安装目录是旧版绿色文件残留，没有可用卸载器。' + #13#10#13#10 +
        '安装程序将保留工作流、图片、配置和备份，先清理旧程序文件后再继续安装。' + #13#10#13#10 +
        '是否继续？',
        mbConfirmation,
        MB_YESNO
      ) = IDYES then
      begin
        KillProcess('{#MyAppExeName}');
        Result := CleanupPortableInstallResiduals(InstallPath);
        Exit;
      end;
#endif
    end;

    Result := False;
    Exit;
  end;

  Result := not HasProgramResidualFiles(InstallPath);
end;

function UninstallOldVersion(): Boolean;
var
  UninstallString: String;
  InstallPath: String;
begin
  Result := True;

  InstallPath := GetInstalledAppPath();

  if HasAnyUninstallEntry() then
  begin
    UninstallString := GetUninstallString();
    if (UninstallString <> '') and ExecuteUninstallCommand(UninstallString) then
      Sleep(1000)
    else if not TryUninstallByPath(InstallPath) then
    begin
      Result := False;
      Exit;
    end;

    if HasAnyUninstallEntry() then
    begin
      if not CleanupUninstallRegistryResiduals() then
      begin
        Result := False;
        Exit;
      end;

      Sleep(300);
      if HasAnyUninstallEntry() then
      begin
        Result := False;
        Exit;
      end;
    end;
  end;

  if (InstallPath <> '') and (not EnsureNoResidualAtPath(InstallPath)) then
  begin
    Result := False;
    Exit;
  end;
end;

function InitializeSetup(): Boolean;
begin
  Result := True;

  // 检查是否有运行中的应用程序
  if IsAppRunning() then
  begin
#ifdef NonInteractive
    KillProcess('{#MyAppExeName}');
    if not WaitForAppClose(5) then
    begin
      Result := False;
      Exit;
    end;
#else
    if MsgBox('检测到 {#MyAppDisplayName} 正在运行。' + #13#10 +
              '是否强制关闭并继续安装？', mbConfirmation, MB_YESNO) = IDYES then
    begin
      KillProcess('{#MyAppExeName}');
      if not WaitForAppClose(5) then
      begin
        MsgBox('无法关闭应用程序，请手动关闭后重试。', mbError, MB_OK);
        Result := False;
        Exit;
      end;
    end
    else
    begin
      Result := False;
      Exit;
    end;
#endif
  end;

  if HasAnyUninstallEntry() then
  begin
#ifndef NonInteractive
    if MsgBox('检测到已安装版本。' + #13#10 +
              '安装前将先卸载旧版本，卸载完成后才会继续安装。' + #13#10#13#10 +
              '是否继续？', mbConfirmation, MB_YESNO) = IDNO then
    begin
      Result := False;
      Exit;
    end;
#endif
  end;

  if not UninstallOldVersion() then
  begin
#ifndef NonInteractive
    MsgBox('旧版本未完全卸载，已停止安装，避免覆盖安装。请先手动卸载后重试。', mbError, MB_OK);
#endif
    Result := False;
    Exit;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  TargetPath: String;
begin
  Result := '';
  TargetPath := RemoveBackslashUnlessRoot(Trim(ExpandConstant('{app}')));
  if TargetPath = '' then
    Exit;

  if not EnsureNoResidualAtPath(TargetPath) then
    Result := '目标安装目录存在旧版本文件，已停止安装以避免覆盖。请先手动卸载或清理后重试。';
end;

// 卸载前处理
function InitializeUninstall(): Boolean;
begin
  Result := True;

  // 检查应用是否运行中
  if CheckForMutexes(APP_MUTEX_NAME) then
  begin
#ifdef NonInteractive
    KillProcess('{#MyAppExeName}');
    Sleep(2000);
#else
    if MsgBox('检测到 {#MyAppDisplayName} 正在运行。' + #13#10 +
              '是否强制关闭并继续卸载？', mbConfirmation, MB_YESNO) = IDYES then
    begin
      KillProcess('{#MyAppExeName}');
      Sleep(2000);
    end
    else
    begin
      Result := False;
      Exit;
    end;
#endif
  end;

#ifndef NonInteractive
  if MsgBox('是否保留用户数据？' + #13#10#13#10 +
            '选择"是"将保留配置、工作流、图片和备份' + #13#10 +
            '选择"否"将完全删除所有数据', mbConfirmation, MB_YESNO) = IDNO then
    DeleteAppUserData();
#endif
end;

// 卸载完成后清理
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    // 清理可能残留的空目录
    RemoveDir(ExpandConstant('{app}'));
  end;
end;
