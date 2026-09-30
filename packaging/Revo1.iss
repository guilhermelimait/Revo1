; Inno Setup script for Revo1-Setup-<version>.exe.
; Build with packaging\build.ps1, which passes AppVersion, Arch and SourceDir.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef Arch
  #define Arch "x64compatible"
#endif
#ifndef SourceDir
  #define SourceDir AddBackslash(GetEnv("TEMP")) + "Revo1-build\dist\Revo1"
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
AppId={{0E5A1A8D-7542-4525-8171-3899DB48E68B}
AppName=Revo1
AppVersion={#AppVersion}
AppVerName=Revo1 {#AppVersion}
AppPublisher=guilhermelimait
AppPublisherURL=https://github.com/guilhermelimait/Revo1
AppSupportURL=https://github.com/guilhermelimait/Revo1/issues
AppUpdatesURL=https://github.com/guilhermelimait/Revo1/releases
VersionInfoVersion={#AppVersion}
VersionInfoProductName=Revo1
VersionInfoDescription=Revo1 Setup
; A per-user install: no administrator prompt, and the app lands in
; %LOCALAPPDATA%\Programs\Revo1.
PrivilegesRequired=lowest
DefaultDirName={autopf}\Revo1
DisableProgramGroupPage=yes
DisableDirPage=auto
ArchitecturesAllowed={#Arch}
ArchitecturesInstallIn64BitMode={#Arch}
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=Revo1-Setup-{#AppVersion}{#Suffix}
SetupIconFile=..\revo1\assets\revo1.ico
UninstallDisplayIcon={app}\Revo1.exe
UninstallDisplayName=Revo1
LicenseFile=..\LICENSE
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=no

[Tasks]
Name: "startup"; Description: "Start Revo1 when I sign in to Windows"; GroupDescription: "Options:"
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Options:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Earlier installs replace their whole program folder, and the sign-in
; shortcut (also made by the old install.ps1) is recreated only if chosen.
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{userstartup}\Revo1.lnk"

[Icons]
Name: "{autoprograms}\Revo1"; Filename: "{app}\Revo1.exe"; AppUserModelID: "guilhermelimait.Revo1"
Name: "{userstartup}\Revo1"; Filename: "{app}\Revo1.exe"; Parameters: "--minimized"; Tasks: startup
Name: "{autodesktop}\Revo1"; Filename: "{app}\Revo1.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Revo1.exe"; Description: "Start Revo1 now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Code]
{ Revo1 keeps running in the background, so close it before files are
  replaced or removed. This also stops a copy started from source with
  pythonw -m revo1.app (the old install.ps1 shortcut). Settings in
  %LOCALAPPDATA%\Revo1 are kept. }
procedure StopRevo1();
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM Revo1.exe', '',
       SW_HIDE, ewWaitUntilTerminated, Code);
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
       '-NoProfile -NonInteractive -Command "Get-CimInstance Win32_Process -Filter ''Name like ''''python%'''''' | Where-Object CommandLine -like ''*revo1.app*'' | Invoke-CimMethod -MethodName Terminate | Out-Null"',
       '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(500);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRevo1();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  StopRevo1();
  Result := True;
end;
