; Inno Setup script for the PIP Companion installer (ADR-034). Built by tools\build_exe.ps1:
;   ISCC.exe /DAppVersion=1.0.0 tools\installer\pip.iss  ->  build\app\PIP-Setup-<version>.exe
; Installs PIP.exe (PyInstaller one-folder build in build\app\dist\PIP) per user, no admin prompt by default.
; The user's data (%LOCALAPPDATA%\PIP) is never removed by the uninstaller.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define Root AddBackslash(SourcePath) + "..\.."

[Setup]
AppId={{6B1C2E7A-4F0D-4C8E-9C1B-7E2A5D3F9A41}
AppName=PIP Companion
AppVersion={#AppVersion}
AppVerName=PIP Companion {#AppVersion}
AppPublisher=PIP
DefaultDirName={autopf}\PIP Companion
DefaultGroupName=PIP Companion
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#Root}\build\app
OutputBaseFilename=PIP-Setup-{#AppVersion}
SetupIconFile={#Root}\tools\pip.ico
UninstallDisplayIcon={app}\PIP.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a &Desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "autostart"; Description: "Start PIP with &Windows (in the tray)"; GroupDescription: "Shortcuts:"
Name: "gpu"; Description: "Download &GPU speech for the NVIDIA graphics card (~1.3 GB, much faster speech-to-text)"; GroupDescription: "Speech:"; Check: HasNvidiaGpu

[Files]
Source: "{#Root}\build\app\dist\PIP\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\PIP Companion"; Filename: "{app}\PIP.exe"; Comment: "PIP - your focus companion"
Name: "{autodesktop}\PIP Companion"; Filename: "{app}\PIP.exe"; Tasks: desktopicon; Comment: "PIP - your focus companion"
; Same name as the tray menu's "Start with Windows" (service/desktop.py), so the menu shows it ticked.
Name: "{userstartup}\PIP Companion"; Filename: "{app}\PIP.exe"; Parameters: "--background"; Tasks: autostart

[Run]
Filename: "{app}\PIP.exe"; Parameters: "--install-gpu"; Description: "Open PIP and download GPU speech"; Tasks: gpu; Flags: nowait postinstall skipifsilent
Filename: "{app}\PIP.exe"; Description: "Open PIP"; Tasks: not gpu; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/im PIP.exe /f"; Flags: runhidden; RunOnceId: "StopPIP"

[UninstallDelete]
Type: files; Name: "{userstartup}\PIP Companion.lnk"

[Code]
function HasNvidiaGpu(): Boolean;
begin
  { nvidia-smi ships with every NVIDIA driver }
  Result := FileExists(ExpandConstant('{sys}\nvidia-smi.exe'));
end;
