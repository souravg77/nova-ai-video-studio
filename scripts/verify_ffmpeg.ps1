<#
    Verify the FFmpeg that will be bundled into the installer.

    Fails (exit 1) unless BOTH ffmpeg.exe and ffprobe.exe in -Dir:
      * exist,
      * are real static builds, not package-manager shims (a Chocolatey shim
        is ~0.4 MB and only forwards to a path on the build machine), and
      * actually run and print a "<tool> version ..." banner.

    Usage:
      powershell -ExecutionPolicy Bypass -File scripts\verify_ffmpeg.ps1 -Dir packaging\ffmpeg
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Dir,
    # Static Windows builds are tens of MB; shims are well under 1 MB.
    [int]$MinSizeMB = 10
)
$ErrorActionPreference = 'Stop'
$failed = $false

foreach ($tool in @("ffmpeg", "ffprobe")) {
    $exe = Join-Path $Dir "$tool.exe"
    if (-not (Test-Path $exe)) {
        Write-Host "::error::$exe is missing."
        $failed = $true
        continue
    }
    $sizeMB = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    if ($sizeMB -lt $MinSizeMB) {
        Write-Host ("::error::$exe is only $sizeMB MB - this looks like a " +
                    "package-manager shim, not a real FFmpeg build.")
        $failed = $true
        continue
    }
    # Capture everything first: cutting the pipe early (Select -First) can
    # leave $LASTEXITCODE unreliable.
    $all = @(& $exe -hide_banner -version 2>&1)
    $code = $LASTEXITCODE
    $out = "$($all | Select-Object -First 1)"
    if ($code -ne 0 -or -not ($out -match "^$tool version")) {
        Write-Host "::error::$exe does not run correctly: $out"
        $failed = $true
        continue
    }
    Write-Host "OK  $tool ($sizeMB MB): $out"
}

if (-not (Get-ChildItem -Path $Dir -Filter "LICENSE*" -ErrorAction SilentlyContinue)) {
    Write-Host "::warning::No FFmpeg LICENSE file in $Dir; the installer must ship the build's licence."
}

if ($failed) { exit 1 }
exit 0
