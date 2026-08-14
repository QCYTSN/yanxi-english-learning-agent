#ifndef MyAppVersion
  #define MyAppVersion "1.5.0"
#endif

#define MyAppName "言蹊 (Yanxi)"
#define MyAppPublisher "Yanxi contributors"
#define MyAppExeName "Yanxi.exe"

[Setup]
AppId={{C31F0558-5C74-4B8B-962F-F1C0B3A0A4B8}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Yanxi
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\release-artifacts
OutputBaseFilename=Yanxi-{#MyAppVersion}-Windows-x64-Setup
SetupIconFile=..\..\src\ielts_coach\resources\assets\app-icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
LicenseFile=..\..\LICENSE
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式"; Flags: checkedonce

[Files]
Source: "..\..\dist\Yanxi\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--stop"; RunOnceId: "StopIELTSStudyDesk"; Flags: runhidden waituntilterminated skipifdoesntexist

[UninstallDelete]
; The CLI `ui shortcut-install` shortcut is created with WScript.Shell, so
; Inno does not track it — remove it explicitly on uninstall.
Type: files; Name: "{userdesktop}\言蹊.lnk"
Type: filesandordirs; Name: "{app}"

; User questions, sessions, credentials and imported media are deliberately
; stored under LocalAppData\IELTS Study Desk\data and survive uninstall.
