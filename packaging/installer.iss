; Inno Setup script for NOVA AI Video Studio (Windows 11 x64).
; Build with: ISCC.exe packaging\installer.iss
; Expects the PyInstaller onedir output at dist\NOVA-Studio\ (the PySide6 app
; from packaging\nova_studio.spec) and a verified FFmpeg at packaging\ffmpeg\
; (ffmpeg.exe, ffprobe.exe, LICENSE.txt).
;
; Produces: packaging\Output\NOVA-Setup.exe

#define AppName "NOVA AI Video Studio"
#define AppShortName "NOVA Studio"
#define AppVersion "0.1.0"
#define AppPublisher "NOVA Studio"
#define AppExeName "NOVA-Studio.exe"
; Path to the PyInstaller onedir output (relative to this script).
#define DistDir "..\dist\NOVA-Studio"

[Setup]
AppId={{B7A9F3C2-2E6A-4C1F-9E2D-7C1A8E2D0001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppShortName}
DefaultGroupName={#AppShortName}
; Per-machine install into Program Files (x64 only).
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=Output
OutputBaseFilename=NOVA-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExeName}
LicenseFile=..\licenses\THIRD_PARTY_NOTICES.md
DisableProgramGroupPage=yes
; Require Windows 10 1809+ / Windows 11.
MinVersion=10.0.17763

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; The entire PyInstaller onedir bundle.
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs
; Bundled FFmpeg, shipped next to the app exe where NOVA looks first.
; REQUIRED: compilation fails if it is missing, so an installer can never ship
; without a working renderer again (scripts\verify_ffmpeg.ps1 runs first and
; rejects package-manager shims). Build with /DNoFfmpeg only for a deliberately
; FFmpeg-less package that relies on a system FFmpeg.
#ifndef NoFfmpeg
Source: "ffmpeg\ffmpeg.exe"; DestDir: "{app}"
Source: "ffmpeg\ffprobe.exe"; DestDir: "{app}"
Source: "ffmpeg\LICENSE.txt"; DestDir: "{app}\ffmpeg-licenses"
#endif

[Icons]
Name: "{group}\{#AppShortName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Hardware report"; Filename: "{app}\{#AppExeName}"; Parameters: "--hardware"; Comment: "Show the detected hardware and capability profile"
Name: "{group}\Uninstall {#AppShortName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppShortName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppShortName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove the app folder on uninstall. User data in %LOCALAPPDATA%\NovaStudio is
; intentionally LEFT in place (projects, models) unless the user removes it.
Type: filesandordirs; Name: "{app}"

[Messages]
; Shown on the welcome page.
WelcomeLabel2=This will install {#AppName} on your computer.%n%nNOVA runs fully offline. Your projects and any models you add are kept in %LOCALAPPDATA%\NovaStudio and are not touched by uninstall.%n%nTalking-head video generation requires a compatible NVIDIA GPU; on other hardware NOVA produces narrated photo videos instead.
