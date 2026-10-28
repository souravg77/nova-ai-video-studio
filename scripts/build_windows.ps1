<#
    NOVA AI Video Studio - Windows environment build (roadmap section 6B)
    Creates the venv and installs the base + UI dependencies.
    AI model environments are installed separately and on demand.
    Run:  powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host 'Creating virtual environment (.venv)...'
if (-not (Test-Path '.venv')) {
    py -3.12 -m venv .venv
}
& .\.venv\Scripts\Activate.ps1

Write-Host 'Upgrading pip...'
python -m pip install --upgrade pip

Write-Host 'Installing base + UI dependencies...'
python -m pip install -r requirements\ui.txt

Write-Host 'Validating FFmpeg...'
if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    ffmpeg -f lavfi -i color=c=black:s=640x360:d=2 -c:v libx264 -pix_fmt yuv420p -y test.mp4
    ffprobe -v error -show_streams test.mp4 | Out-Null
    Remove-Item test.mp4 -ErrorAction SilentlyContinue
    Write-Host '  FFmpeg OK.'
} else {
    Write-Host '  WARNING: FFmpeg not found on PATH. Install a trusted build'
    Write-Host '  (review its license) before rendering.'
}

Write-Host "`nSetup complete. Launch with:  python -m nova_studio.app"
Write-Host "Hardware report only:         python -m nova_studio.core.hardware_cli"
