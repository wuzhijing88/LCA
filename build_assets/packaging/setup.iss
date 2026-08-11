; Inno Setup Script - Chinese Version
; Encoding: UTF-8 with BOM

#define MyAppName "LCA"
#define MyAppVersion "1.2.6.3"
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
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableDirPage=no
AllowNoIcons=yes
OutputDir={#MyOutputDir}
OutputBaseFilename=LCA_Setup_v{#MyAppVersion}

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
CloseApplicationsFilter=*.exe
RestartApplications=yes
RestartIfNeededByRun=yes

; 卸载设置
Uninstallable=yes
UninstallDisplayName={#MyAppName}
CreateUninstallRegKey=yes
UpdateUninstallLogAppName=yes

; 目录和磁盘
DirExistsWarning=auto
ExtraDiskSpaceRequired=524288000
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
UsePreviousGroup=yes
UsePreviousTasks=yes

; 版本信息
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} 安装程序
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
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
Source: "{#MySourceDist}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "export_runtime\*;runtime_templates\*;workflow_lite_runner_template*.exe"
; 注意: _tufup_data目录包含更新元数据和当前版本归档文件,必须包含在安装包中

[InstallDelete]
; 安装前清理旧版残留源码与运行时缓存，避免升级后保留旧 .py 文件
Type: filesandordirs; Name: "{app}\win32com"
Type: files; Name: "{app}\comtypes\gen\*.py"
Type: filesandordirs; Name: "{app}\comtypes\gen\__pycache__"

[Icons]
; 桌面图标
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\resources\icon.ico"
; 开始菜单图标
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startmenuicon; IconFilename: "{app}\resources\icon.ico"
Name: "{autoprograms}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"; Tasks: startmenuicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent runascurrentuser shellexec

[UninstallDelete]
; 卸载时删除日志文件和临时文件
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\*.log"
Type: files; Name: "{app}\app_*.log"
Type: filesandordirs; Name: "{app}\win32com"
; 用户目录数据和字库相关数据（用户选择完全删除时由Code段处理）
; 注意: 不删除 config.json 和 _tufup_data,保留用户配置和更新数据

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

function CleanupPortableInstallResiduals(const InstallPath: String): Boolean;
var
  Path: String;
  BackupRoot: String;
  PreserveDir: String;
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

  PreserveDir := AddBackslash(BackupRoot) + 'backups';
  if not BackupDirectoryTree(AddBackslash(Path) + 'backups', PreserveDir) then
    Exit;

  PreserveDir := AddBackslash(BackupRoot) + 'logs';
  if not BackupDirectoryTree(AddBackslash(Path) + 'logs', PreserveDir) then
    Exit;

  PreserveDir := AddBackslash(BackupRoot) + 'config';
  if not BackupDirectoryTree(AddBackslash(Path) + 'config', PreserveDir) then
    Exit;

  PreserveDir := AddBackslash(BackupRoot) + 'workflows';
  if not BackupDirectoryTree(AddBackslash(Path) + 'workflows', PreserveDir) then
    Exit;

  PreserveDir := AddBackslash(BackupRoot) + 'images';
  if not BackupDirectoryTree(AddBackslash(Path) + 'images', PreserveDir) then
    Exit;

  PreserveDir := AddBackslash(BackupRoot) + 'templates';
  if not BackupDirectoryTree(AddBackslash(Path) + 'templates', PreserveDir) then
    Exit;

  PreserveDir := AddBackslash(BackupRoot) + 'pic_cache';
  if not BackupDirectoryTree(AddBackslash(Path) + 'pic_cache', PreserveDir) then
    Exit;

  if not BackupRootJsonFiles(Path, BackupRoot) then
    Exit;

  DeleteRootRuntimeFiles(Path);
  DeleteRuntimeDirectoryIfExists(Path, 'AutoHotkey');
  DeleteRuntimeDirectoryIfExists(Path, 'certs');
  DeleteRuntimeDirectoryIfExists(Path, 'charset_normalizer');
  DeleteRuntimeDirectoryIfExists(Path, 'comtypes');
  DeleteRuntimeDirectoryIfExists(Path, 'config');
  DeleteRuntimeDirectoryIfExists(Path, 'cryptography');
  DeleteRuntimeDirectoryIfExists(Path, 'cv2');
  DeleteRuntimeDirectoryIfExists(Path, 'Interception');
  DeleteRuntimeDirectoryIfExists(Path, 'numpy');
  DeleteRuntimeDirectoryIfExists(Path, 'numpy.libs');
  DeleteRuntimeDirectoryIfExists(Path, 'PIL');
  DeleteRuntimeDirectoryIfExists(Path, 'psutil');
  DeleteRuntimeDirectoryIfExists(Path, 'PySide6');
  DeleteRuntimeDirectoryIfExists(Path, 'resources');
  DeleteRuntimeDirectoryIfExists(Path, 'shiboken6');
  DeleteRuntimeDirectoryIfExists(Path, 'themes');
  DeleteRuntimeDirectoryIfExists(Path, 'uiautomation');
  DeleteRuntimeDirectoryIfExists(Path, 'winrt');

  if not RestoreDirectoryTree(AddBackslash(BackupRoot) + 'backups', AddBackslash(Path) + 'backups') then
    Exit;
  if not RestoreDirectoryTree(AddBackslash(BackupRoot) + 'logs', AddBackslash(Path) + 'logs') then
    Exit;
  if not RestoreDirectoryTree(AddBackslash(BackupRoot) + 'config', AddBackslash(Path) + 'config') then
    Exit;
  if not RestoreDirectoryTree(AddBackslash(BackupRoot) + 'workflows', AddBackslash(Path) + 'workflows') then
    Exit;
  if not RestoreDirectoryTree(AddBackslash(BackupRoot) + 'images', AddBackslash(Path) + 'images') then
    Exit;
  if not RestoreDirectoryTree(AddBackslash(BackupRoot) + 'templates', AddBackslash(Path) + 'templates') then
    Exit;
  if not RestoreDirectoryTree(AddBackslash(BackupRoot) + 'pic_cache', AddBackslash(Path) + 'pic_cache') then
    Exit;
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
      if MsgBox(
        '检测到目标安装目录是旧版绿色文件残留，没有可用卸载器。' + #13#10#13#10 +
        '安装程序将保留工作流、图片、备份和字库数据，先清理旧程序文件后再继续安装。' + #13#10#13#10 +
        '是否继续？',
        mbConfirmation,
        MB_YESNO
      ) = IDYES then
      begin
        KillProcess('{#MyAppExeName}');
        Result := CleanupPortableInstallResiduals(InstallPath);
        Exit;
      end;
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
    if MsgBox('检测到 {#MyAppName} 正在运行。' + #13#10 +
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
  end;

  if HasAnyUninstallEntry() then
  begin
    if MsgBox('检测到已安装版本。' + #13#10 +
              '安装前将先卸载旧版本，卸载完成后才会继续安装。' + #13#10#13#10 +
              '是否继续？', mbConfirmation, MB_YESNO) = IDNO then
    begin
      Result := False;
      Exit;
    end;
  end;

  if not UninstallOldVersion() then
  begin
    MsgBox('旧版本未完全卸载，已停止安装，避免覆盖安装。请先手动卸载后重试。', mbError, MB_OK);
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
    if MsgBox('检测到 {#MyAppName} 正在运行。' + #13#10 +
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
  end;

  if MsgBox('是否保留用户数据？' + #13#10#13#10 +
            '选择"是"将保留配置文件、工作流文件、模板图片和备份' + #13#10 +
            '选择"否"将完全删除所有数据', mbConfirmation, MB_YESNO) = IDNO then
  begin
    // 完全删除模式：删除所有用户数据
    DelTree(ExpandConstant('{app}\config.json'), False, True, False);
    // 删除备份目录
    DelTree(ExpandConstant('{app}\backups'), True, True, True);
    // 删除模板图片目录
    DelTree(ExpandConstant('{app}\pic_cache'), True, True, True);
    DelTree(ExpandConstant('{app}\templates'), True, True, True);
    // 删除当前用户目录下的运行时与配置数据
    DeleteUserDataTree();
  end;
  // 保留模式：不删除任何用户数据（config.json、工作流、模板、备份全部保留）
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
