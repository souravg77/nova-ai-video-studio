<#
    NOVA AI Video Studio - Windows installer build (one command).

    Produces packaging\Output\NOVA-Setup.exe.

    Steps:
      1. Create/activate a build venv and install deps + PyInstaller.
      2. Fetch a static FFmpeg build (ffmpeg.exe + ffprobe.exe) and bundle it,
         unless -NoFfmpeg is given or they already exist.
      3. Run PyInstaller (onedir, windowed) -> dist\NOVA-Studio\.
      4. Run Inno Setup (ISCC) -> packaging\Output\NOVA-Setup.exe.

    Prerequisites on the build machine (Windows 11 x64):
      - Python 3.10-3.12 on PATH (py launcher).
      - Inno Setup 6 (ISCC.exe) -- https://jrsoftware.org/isinfo.php
        Either on PATH or at the default install location.

    Usage:
      powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
      powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1 -NoFfmpeg
#>
[CmdletBinding()]
param(
    [switch]$NoFfmpeg,
    [string]$PythonVersion = "3.12"
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Section($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

# --- 1. Build environment -------------------------------------------------
Section "Build environment"
$venv = Join-Path $root ".build-venv"
if (-not (Test-Path $venv)) {
    py -$PythonVersion -m venv $venv
}
$py = Join-Path $venv "Scripts\python.exe"
& $py -m pip install --upgrade pip | Out-Null
& $py -m pip install -r requirements\ui.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed." }

# --- 2. FFmpeg -------------------------------------------------------------
$ffdir = Join-Path $root "packaging\ffmpeg"
if (-not $NoFfmpeg) {
    Section "FFmpeg"
    $ffexe = Join-Path $ffdir "ffmpeg.exe"
    if (Test-Path $ffexe) {
        Write-Host "  FFmpeg already present at $ffdir"
    } else {
        New-Item -ItemType Directory -Force -Path $ffdir | Out-Null
        $zip = Join-Path $env:TEMP "ffmpeg-release-essentials.zip"
        # Gyan.dev static builds are a common, widely used Windows FFmpeg source.
        # REVIEW THE BUILD'S LICENSE (GPL/LGPL + codecs) before redistributing;
        # see https://ffmpeg.org/legal.html and packaging\README.md.
        $url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        Write-Host "  Downloading FFmpeg from $url"
        Invoke-WebRequest -Uri $url -OutFile $zip
        $tmp = Join-Path $env:TEMP "ffmpeg-extract"
        if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
        Expand-Archive -Path $zip -DestinationPath $tmp
        $bin = Get-ChildItem -Path $tmp -Recurse -Filter "ffmpeg.exe" |
            Select-Object -First 1
        if (-not $bin) { throw "ffmpeg.exe not found in the downloaded archive." }
        Copy-Item $bin.FullName (Join-Path $ffdir "ffmpeg.exe")
        Copy-Item (Join-Path $bin.DirectoryName "ffprobe.exe") `
            (Join-Path $ffdir "ffprobe.exe")
        # Keep the build's license/readme next to the binaries.
        Get-ChildItem -Path (Split-Path $bin.DirectoryName -Parent) -Filter "*.txt" |
            ForEach-Object { Copy-Item $_.FullName $ffdir }
        $lic = Join-Path (Split-Path $bin.DirectoryName -Parent) "LICENSE"
        if (Test-Path $lic) { Copy-Item $lic (Join-Path $ffdir "LICENSE.txt") }
        Write-Host "  FFmpeg bundled at $ffdir"
    }
} else {
    Write-Host "  Skipping FFmpeg bundle (-NoFfmpeg). The app will require a" `
        "system FFmpeg on PATH."
}

# --- 3. PyInstaller --------------------------------------------------------
Section "PyInstaller"
if (Test-Path (Join-Path $root "dist\NOVA-Studio")) {
    Remove-Item -Recurse -Force (Join-Path $root "dist\NOVA-Studio")
}
& $py -m PyInstaller packaging\nova_studio.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
$exe = Join-Path $root "dist\NOVA-Studio\NOVA-Studio.exe"
if (-not (Test-Path $exe)) { throw "Expected $exe was not produced." }
Write-Host "  Built $exe"

# --- 4. Inno Setup ---------------------------------------------------------
Section "Inno Setup installer"
$iscc = $null
foreach ($cand in @(
    "ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe")) {
    $c = Get-Command $cand -ErrorAction SilentlyContinue
    if ($c) { $iscc = $c.Source; break }
    if (Test-Path $cand) { $iscc = $cand; break }
}
if (-not $iscc) {
    throw "Inno Setup (ISCC.exe) not found. Install Inno Setup 6 from " +
          "https://jrsoftware.org/isinfo.php and re-run."
}
& $iscc packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed." }

$setup = Join-Path $root "packaging\Output\NOVA-Setup.exe"
if (Test-Path $setup) {
    Section "Done"
    Write-Host "Installer created: $setup" -ForegroundColor Green
} else {
    throw "Inno Setup ran but NOVA-Setup.exe was not found."
}
