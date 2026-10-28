; Kiwi Windows 桌面版安装脚本（Inno Setup 6）。
;
; 由 desktop\build.ps1 调用：
;   ISCC.exe /DAppVersion=1.0.0 /DStageDir=...\build\app /DPrereqsDir=...\build\prereqs
;            /DOutputDir=...\dist /DFixedWebView2=0 kiwi.iss
;
; 安装到当前用户目录，不请求管理员权限；用户数据在 %LOCALAPPDATA%\Kiwi，
; 卸载时保留。

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef StageDir
  #define StageDir "..\build\app"
#endif
#ifndef PrereqsDir
  #define PrereqsDir "..\build\prereqs"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
; 命令行 /D 定义在 ISPP 中始终是字符串；build.ps1 传入 "0"（Evergreen）或
; "1"（随包 Fixed Version）。
#ifndef FixedWebView2
  #define FixedWebView2 "0"
#endif

#define AppName "Kiwi"
#define AppPublisher "Kiwi"
#define AppExeName "Kiwi.Desktop.exe"
#define AppMutexName "Kiwi.Desktop.SingleInstance"
#define WebView2Installer "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"

[Setup]
; AppId 固定：升级沿用同一安装项；请勿修改。
AppId={{6A1F9C24-7E3D-4B58-9C0A-2F5D8E1B7A43}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\Kiwi
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
; x64compatible 覆盖 x64 系统；显式排除 ARM64（桌面版未验证 ARM64）。
ArchitecturesAllowed=x64compatible and not arm64
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19045
OutputDir={#OutputDir}
OutputBaseFilename=Kiwi-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
AppMutex={#AppMutexName}
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes
UsePreviousTasks=yes
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName} {#AppVersion}
SetupLogging=yes

[Files]
; 缺少 WebView2 时运行；dontcopy 表示只在安装过程中临时展开，不进入程序目录。
Source: "{#PrereqsDir}\{#WebView2Installer}"; Flags: dontcopy skipifsourcedoesntexist
; 全部程序文件（宿主、runtime、前端、Qdrant、便携 Python、可选 Fixed WebView2）。
Source: "{#StageDir}\*"; DestDir: "{app}"; Excludes: "*.pdb"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; 卸载时 Inno 只删除安装清单中的程序文件；%LOCALAPPDATA%\Kiwi 数据目录不在清单内，自动保留。

[Code]
const
  WebView2ClientKey =
    'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebView2ClientKeyWow =
    'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function ReadWebView2Version(RootKey: Integer; const SubKey: String): String;
var
  Version: String;
begin
  Version := '';
  RegQueryStringValue(RootKey, SubKey, 'pv', Version);
  Result := Version;
end;

function WebView2Installed: Boolean;
var
  Version: String;
begin
  Version := ReadWebView2Version(HKCU, WebView2ClientKey);
  if Version = '' then
    Version := ReadWebView2Version(HKLM, WebView2ClientKey);
  if Version = '' then
    Version := ReadWebView2Version(HKLM, WebView2ClientKeyWow);
  Result := (Version <> '') and (Version <> '0.0.0.0');
end;

procedure InstallWebView2IfNeeded;
var
  Installer: String;
  ResultCode: Integer;
begin
  if WebView2Installed then
    Exit;

  Installer := ExpandConstant('{tmp}\{#WebView2Installer}');
  if not FileExists(Installer) then
  begin
    if not WizardSilent then
      MsgBox('未找到随包的 WebView2 运行时安装程序。' + #13#10 + #13#10 +
             '请安装 Microsoft Edge WebView2 Runtime 后重新启动 Kiwi，' + #13#10 +
             '或改用携带 Fixed Version 运行时的安装包。',
             mbError, MB_OK);
    Exit;
  end;

  if not Exec(Installer, '/silent /install', '', SW_SHOW, ewWaitUntilTerminated, ResultCode) then
  begin
    if not WizardSilent then
      MsgBox('启动 WebView2 运行时安装程序失败。', mbError, MB_OK);
    Exit;
  end;

  if (ResultCode <> 0) and (not WizardSilent) then
    MsgBox('WebView2 运行时安装未成功（退出码 ' + IntToStr(ResultCode) + '）。' + #13#10 +
           '可稍后手动安装 Microsoft Edge WebView2 Runtime。', mbError, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    #if FixedWebView2 != "1"
    if not WebView2Installed then
    begin
      try
        ExtractTemporaryFile('{#WebView2Installer}');
        InstallWebView2IfNeeded;
      except
        if not WizardSilent then
          MsgBox('无法展开随包的 WebView2 安装程序：' + GetExceptionMessage,
                 mbError, MB_OK);
      end;
    end;
    #endif
  end;
end;
