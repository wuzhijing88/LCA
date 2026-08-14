; LCA Inno Setup 6 安装包脚本
; 通常由 build_release.py 调用并传入 /DAppVersion=... /DReleaseDir=...
; 也可以直接用 Inno Setup 打开编译（使用下方默认值）

#ifndef AppName
  #define AppName "LCA"
#endif
#ifndef AppVersion
  #define AppVersion "0.0.0.0"
#endif
#ifndef ReleaseDir
  #define ReleaseDir AddBackslash(SourcePath) + "release_output\LCA"
#endif

#define DisclaimerFile AddBackslash(ReleaseDir) + "resources\disclaimer.txt"
#define LicenseTxtFile AddBackslash(ReleaseDir) + "LICENSE"

[Setup]
AppId={{B7E6D2F4-3C61-4E2A-9F1B-5A8C0D9E7712}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
; 程序运行时会写入自身目录（配置/日志/工作流），且启动时自动提权，安装需管理员权限
PrivilegesRequired=admin
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
SetupIconFile={#ReleaseDir}\resources\icon.ico
UninstallDisplayIcon={app}\LCA.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
DisableProgramGroupPage=yes
#if FileExists(DisclaimerFile)
InfoBeforeFile={#DisclaimerFile}
#endif

[Languages]
#if FileExists(AddBackslash(CompilerPath) + "Languages\ChineseSimplified.isl")
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#endif
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#ReleaseDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
; 工作目录必须是程序目录：主题 QSS 与运行数据均按程序根目录相对路径解析
Name: "{group}\{#AppName}"; Filename: "{app}\LCA.exe"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\LCA.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
; LCA.exe 带 requireAdministrator 清单。postinstall 默认 runasoriginaluser + CreateProcess，
; 会因无法提权而失败（错误 740）。runascurrentuser 沿用安装程序已提升的管理员令牌启动。
Filename: "{app}\LCA.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent runascurrentuser

; 卸载时保留用户数据（config.json、workflows/、images/、logs/ 等），如需彻底删除请手动清理安装目录
