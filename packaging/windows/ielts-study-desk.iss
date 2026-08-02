#ifndef MyAppVersion
  #define MyAppVersion "1.4.0"
#endif

#define MyAppName "IELTS Study Desk"
#define MyAppPublisher "IELTS Study Desk contributors"
#define MyAppExeName "IELTS Study Desk.exe"

[Setup]
AppId={{C31F0558-5C74-4B8B-962F-F1C0B3A0A4B8}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\IELTS Study Desk
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\release-artifacts
OutputBaseFilename=IELTS-Study-Desk-{#MyAppVersion}-Windows-x64-Setup
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
Source: "..\..\dist\IELTS Study Desk\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--stop"; RunOnceId: "StopIELTSStudyDesk"; Flags: runhidden waituntilterminated skipifdoesntexist

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

; User questions, sessions, credentials and imported media are deliberately
; stored under LocalAppData\IELTS Study Desk\data and survive uninstall.
