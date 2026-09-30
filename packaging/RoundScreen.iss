; Inno Setup script for RoundScreen-Setup-<version>.exe.
; Build with packaging\build.ps1, which passes AppVersion, Arch and SourceDir.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef Arch
  #define Arch "x64compatible"
#endif
#ifndef SourceDir
  #define SourceDir AddBackslash(GetEnv("TEMP")) + "RoundScreen-build\dist\RoundScreen"
#endif
; Only the x64 build (which also runs on Windows on ARM) has no suffix.
#if Arch == "arm64"
  #define Suffix "-arm64"
#else
  #define Suffix ""
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{6F1B2C4E-8D3A-4B7F-9C1E-2A5D7E9F0B34}
AppName=RoundScreen
AppVersion={#AppVersion}
AppVerName=RoundScreen {#AppVersion}
AppPublisher=guilhermelimait
AppPublisherURL=https://github.com/guilhermelimait/RoundScreen
AppSupportURL=https://github.com/guilhermelimait/RoundScreen/issues
AppUpdatesURL=https://github.com/guilhermelimait/RoundScreen/releases
VersionInfoVersion={#AppVersion}
VersionInfoProductName=RoundScreen
VersionInfoDescription=RoundScreen Setup
; A per-user install: no administrator prompt, and the app lands in
; %LOCALAPPDATA%\Programs\RoundScreen.
PrivilegesRequired=lowest
DefaultDirName={autopf}\RoundScreen
DisableProgramGroupPage=yes
DisableDirPage=auto
ArchitecturesAllowed={#Arch}
ArchitecturesInstallIn64BitMode={#Arch}
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=RoundScreen-Setup-{#AppVersion}{#Suffix}
SetupIconFile=..\roundscreen\assets\roundscreen.ico
UninstallDisplayIcon={app}\RoundScreen.exe
UninstallDisplayName=RoundScreen
LicenseFile=..\LICENSE
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=no

[Tasks]
Name: "startup"; Description: "Start RoundScreen when I sign in to Windows"; GroupDescription: "Options:"
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Options:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Earlier installs replace their whole program folder, and the sign-in
; shortcut (also made by the old install.ps1) is recreated only if chosen.
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{userstartup}\RoundScreen.lnk"

[Icons]
Name: "{autoprograms}\RoundScreen"; Filename: "{app}\RoundScreen.exe"; AppUserModelID: "guilhermelimait.RoundScreen"
Name: "{userstartup}\RoundScreen"; Filename: "{app}\RoundScreen.exe"; Tasks: startup
Name: "{autodesktop}\RoundScreen"; Filename: "{app}\RoundScreen.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\RoundScreen.exe"; Description: "Start RoundScreen now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Code]
{ RoundScreen keeps running in the background, so close it before files are
  replaced or removed. This also stops a copy started from source with
  pythonw -m roundscreen.app (the old install.ps1 shortcut). Settings in
  %LOCALAPPDATA%\RoundScreen are kept. }
procedure StopRoundScreen();
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM RoundScreen.exe', '',
       SW_HIDE, ewWaitUntilTerminated, Code);
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
       '-NoProfile -NonInteractive -Command "Get-CimInstance Win32_Process -Filter ''Name like ''''python%'''''' | Where-Object CommandLine -like ''*roundscreen.app*'' | Invoke-CimMethod -MethodName Terminate | Out-Null"',
       '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(500);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRoundScreen();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  StopRoundScreen();
  Result := True;
end;
