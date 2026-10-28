# Building the Windows installer (NOVA-Setup.exe)

This folder turns the NOVA source into a Windows 11 installer. The build must
run **on Windows** — PyInstaller freezes the Python interpreter of the OS it
runs on, so a `.exe` can only be produced on Windows, not cross-built from
Linux/macOS.

## One command

From the repo root, in PowerShell on Windows 11 (x64):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
```

This creates a build venv, installs the UI deps + PyInstaller, downloads and
bundles a static FFmpeg, runs PyInstaller, then runs Inno Setup — producing:

```
packaging\Output\NOVA-Setup.exe
```

Double-click that to install NOVA (Start-Menu + optional desktop shortcut,
installs to Program Files, data kept in `%LOCALAPPDATA%\NovaStudio`).

## Prerequisites

| Tool | Why | Get it |
|------|-----|--------|
| Python 3.10–3.12 (`py` launcher) | build venv + PyInstaller | https://www.python.org/downloads/ |
| Inno Setup 6 (`ISCC.exe`) | builds the installer | https://jrsoftware.org/isinfo.php |

PyInstaller and PySide6 are installed automatically into `.build-venv` by the
script. Inno Setup must be installed first (the script looks for `ISCC.exe` on
PATH and at the default install path).

## What the pieces are

- `nova_studio.spec` — PyInstaller spec. Onedir, windowed (no console), bundles
  PySide6 + pydantic + platformdirs and the `licenses/`, `scripts/`, `docs/`
  reference files. Entry point is `src/nova_studio/win_launcher.py`, which puts
  a bundled FFmpeg on PATH before launching the GUI.
- `installer.iss` — Inno Setup script. x64-only, Windows 10 1809+/11, admin
  install to Program Files, Start-Menu + desktop shortcuts (including a
  "Hardware report" shortcut that runs `NOVA-Studio.exe --hardware`), and an
  uninstaller that leaves user data in place.
- `version_info.txt` — version/metadata shown in the exe's file properties.
- `scripts\build_exe.ps1` — orchestrates the whole build.

## FFmpeg bundling and licensing

The build downloads a static FFmpeg (Gyan.dev essentials build) into
`packaging\ffmpeg\` and ships `ffmpeg.exe` + `ffprobe.exe` beside the app. **You
must review that build's license before redistributing NOVA** — FFmpeg builds
mix GPL/LGPL components and codecs with their own terms. See
https://ffmpeg.org/legal.html and keep the bundled license files
(`packaging\ffmpeg\*.txt`, copied into the installer as `ffmpeg-licenses\`).

To build without bundling FFmpeg (users then install FFmpeg themselves and put
it on PATH):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1 -NoFfmpeg
```

## Optional: app icon

Drop a `packaging\nova.ico` (256×256 multi-size `.ico`) and both the exe and
the installer will use it automatically. Without it they use the default icon.

## Models are NOT bundled

The installer ships only the app + FFmpeg. Qwen2.5 (script) and Piper (voice)
models are added by the user into `%LOCALAPPDATA%\NovaStudio\models\` after
install — nothing is downloaded automatically, and the app reports an honest
blocker until they're present (see `docs/p2_pipeline.md`).

## Signing (recommended for distribution)

The produced exe is unsigned, so SmartScreen will warn on first run. For public
distribution, sign both `dist\NOVA-Studio\NOVA-Studio.exe` and
`packaging\Output\NOVA-Setup.exe` with a code-signing certificate
(`signtool sign /fd sha256 /tr <timestamp-url> /td sha256 ...`).
