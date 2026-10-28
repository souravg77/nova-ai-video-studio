<#
    NOVA AI Video Studio - Hardware check (roadmap section 6A)
    Verifies the REAL hardware. Distinguishes installed RAM from the page file
    and flags that WMI AdapterRAM is unreliable for integrated graphics.
    Run:  powershell -ExecutionPolicy Bypass -File scripts\hardware_check.ps1
#>
$ErrorActionPreference = 'Continue'

Write-Host '====================================================================='
Write-Host ' NOVA AI Video Studio - Hardware Check'
Write-Host '====================================================================='

Write-Host "`n[CPU]"
Get-CimInstance Win32_Processor |
    Select-Object Name, NumberOfCores, NumberOfLogicalProcessors |
    Format-List

Write-Host "[Installed physical RAM]"
Get-CimInstance Win32_ComputerSystem |
    Select-Object @{N='RAM_GB';E={[math]::Round($_.TotalPhysicalMemory/1GB,1)}} |
    Format-List
Write-Host "  NOTE: This is INSTALLED RAM. Confirm in Task Manager > Performance."
Write-Host "  The Windows page file / virtual memory is NOT a substitute for RAM"
Write-Host "  or GPU VRAM."

Write-Host "[GPU(s)]"
Get-CimInstance Win32_VideoController |
    Select-Object Name, DriverVersion, AdapterRAM |
    Format-List
Write-Host "  NOTE: AdapterRAM from WMI is unreliable for Intel integrated"
Write-Host "  graphics (often wrong or capped near 4 GB). Intel iGPU memory is"
Write-Host "  SHARED system RAM, not dedicated VRAM. Confirm dedicated VRAM with"
Write-Host "  vendor tooling (e.g. nvidia-smi for NVIDIA)."

Write-Host "[Storage - system drive]"
Get-Volume |
    Where-Object { $_.DriveLetter -eq ($env:SystemDrive.TrimEnd(':')) } |
    Select-Object DriveLetter, FileSystemLabel,
        @{N='Free_GB';E={[math]::Round($_.SizeRemaining/1GB,1)}},
        @{N='Total_GB';E={[math]::Round($_.Size/1GB,1)}} |
    Format-List

Write-Host "[NVIDIA (if present)]"
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
} else {
    Write-Host "  nvidia-smi not found - no confirmed NVIDIA CUDA GPU."
}

Write-Host "[Tooling]"
foreach ($t in @('python','git','ffmpeg','ffprobe')) {
    $cmd = Get-Command $t -ErrorAction SilentlyContinue
    if ($cmd) { Write-Host "  OK  $t -> $($cmd.Source)" }
    else      { Write-Host "  MISSING  $t" }
}

Write-Host "`nDone. Use this report to confirm the real machine before trusting"
Write-Host "any capability profile."
