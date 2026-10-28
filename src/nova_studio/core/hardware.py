"""Hardware detection (roadmap sections 4, 6, 7-milestone-2).

Collects a measured HardwareReport. On Windows it uses PowerShell/CIM (WMI);
on other platforms it falls back to /proc + shutil so the logic is testable
in CI and in this sandbox.

Honesty rules enforced here:
  * Installed physical RAM is read independently of any page-file figure.
  * Intel integrated graphics memory is reported as SHARED, never as
    dedicated VRAM.
  * WMI Win32_VideoController.AdapterRAM is known-unreliable for iGPUs; when
    used it is flagged with a warning rather than trusted as VRAM.
  * A device appearing in inventory is NOT marked runtime_confirmed. That
    flag is only set once a runtime (OpenVINO/CUDA) actually initialises it.
"""
from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ..models.hardware_report import GpuInfo, GpuVendor, HardwareReport


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _vendor_from_name(name: str) -> GpuVendor:
    n = name.lower()
    if "nvidia" in n or "geforce" in n or "rtx" in n or "quadro" in n or "tesla" in n:
        return GpuVendor.NVIDIA
    if "intel" in n or "uhd" in n or "iris" in n or "arc" in n:
        return GpuVendor.INTEL
    if "amd" in n or "radeon" in n:
        return GpuVendor.AMD
    return GpuVendor.UNKNOWN


# ----------------------------------------------------------------------------
# Windows collection via PowerShell / CIM
# ----------------------------------------------------------------------------
_PS_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$cs  = Get-CimInstance Win32_ComputerSystem
$os  = Get-CimInstance Win32_OperatingSystem
$vcs = Get-CimInstance Win32_VideoController
$sys = Get-Volume | Where-Object { $_.DriveLetter -eq ($env:SystemDrive.TrimEnd(':')) } | Select-Object -First 1

$gpus = @()
foreach ($v in $vcs) {
  $gpus += [PSCustomObject]@{
    name = $v.Name
    driver = $v.DriverVersion
    adapterRAM = $v.AdapterRAM
  }
}

# PageFile / commit info for transparency (NOT used as RAM or VRAM).
$commitMB = [math]::Round($os.TotalVirtualMemorySize / 1024, 0)

[PSCustomObject]@{
  cpuName = $cpu.Name
  cores = $cpu.NumberOfCores
  logical = $cpu.NumberOfLogicalProcessors
  physicalRamMB = [math]::Round($cs.TotalPhysicalMemory / 1MB, 0)
  availRamMB = [math]::Round($os.FreePhysicalMemory / 1024, 0)
  commitMB = $commitMB
  gpus = $gpus
  diskFreeMB = if ($sys) { [math]::Round($sys.SizeRemaining / 1MB, 0) } else { 0 }
  diskTotalMB = if ($sys) { [math]::Round($sys.Size / 1MB, 0) } else { 0 }
  osVersion = $os.Caption + ' ' + $os.Version
} | ConvertTo-Json -Depth 4 -Compress
"""


def _collect_windows() -> HardwareReport:
    report = HardwareReport(platform="windows", collected_at=_now())
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_SCRIPT],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(proc.stdout.strip())
    except Exception as exc:  # pragma: no cover - windows-only path
        report.warnings.append(f"PowerShell hardware query failed: {exc}")
        return _collect_posix(base=report)

    report.cpu_name = str(data.get("cpuName") or "Unknown CPU").strip()
    report.physical_cores = int(data.get("cores") or 0)
    report.logical_cores = int(data.get("logical") or 0)
    report.physical_ram_mb = int(data.get("physicalRamMB") or 0)
    report.available_ram_mb = int(data.get("availRamMB") or 0)
    report.virtual_memory_total_mb = int(data.get("commitMB") or 0)
    report.disk_free_mb = int(data.get("diskFreeMB") or 0)
    report.disk_total_mb = int(data.get("diskTotalMB") or 0)
    report.os_version = str(data.get("osVersion") or "")

    gpus = data.get("gpus") or []
    if isinstance(gpus, dict):
        gpus = [gpus]
    for g in gpus:
        name = str(g.get("name") or "Unknown GPU").strip()
        vendor = _vendor_from_name(name)
        gpu = GpuInfo(name=name, vendor=vendor,
                      driver_version=str(g.get("driver") or "") or None)
        adapter_ram = g.get("adapterRAM")
        if vendor == GpuVendor.INTEL:
            # Integrated: AdapterRAM is unreliable AND it is shared memory.
            report.warnings.append(
                f"'{name}': Intel integrated graphics — memory is shared "
                f"system RAM, not dedicated VRAM. AdapterRAM ignored."
            )
            gpu.dedicated_vram_mb = None
        elif adapter_ram and int(adapter_ram) > 0:
            # 32-bit AdapterRAM caps near 4 GB and is often wrong; flag it.
            vram_mb = int(int(adapter_ram) / (1024 * 1024))
            gpu.dedicated_vram_mb = vram_mb
            report.warnings.append(
                f"'{name}': VRAM from WMI AdapterRAM ({vram_mb} MB) is "
                f"unverified; confirm with vendor tooling before trusting."
            )
        report.gpus.append(gpu)

    _annotate_ram_warning(report)
    report.backends_available = _detect_backends()
    return report


# ----------------------------------------------------------------------------
# POSIX / fallback collection (used in CI + this Linux sandbox)
# ----------------------------------------------------------------------------
def _read_meminfo() -> dict[str, int]:
    info: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            m = re.match(r"(\w+):\s+(\d+)\s*kB", line)
            if m:
                info[m.group(1)] = int(m.group(2))  # kB
    except Exception:
        pass
    return info


def _cpu_name_posix() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or platform.machine() or "Unknown CPU"


def _nvidia_smi_gpus() -> list[GpuInfo]:
    gpus: list[GpuInfo] = []
    if shutil.which("nvidia-smi") is None:
        return gpus
    try:
        out = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2:
                gpus.append(GpuInfo(
                    name=parts[0], vendor=GpuVendor.NVIDIA,
                    dedicated_vram_mb=int(float(parts[1])),
                    driver_version=parts[2] if len(parts) > 2 else None,
                    runtime_confirmed=False,  # confirmed later by CUDA probe
                ))
    except Exception:
        pass
    return gpus


def _collect_posix(base: HardwareReport | None = None) -> HardwareReport:
    report = base or HardwareReport(platform=platform.system().lower(),
                                    collected_at=_now())
    report.cpu_name = _cpu_name_posix()
    try:
        import os
        report.logical_cores = os.cpu_count() or 0
        report.physical_cores = report.logical_cores  # best-effort
    except Exception:
        pass

    mem = _read_meminfo()
    if mem:
        report.physical_ram_mb = int(mem.get("MemTotal", 0) / 1024)
        report.available_ram_mb = int(
            mem.get("MemAvailable", mem.get("MemFree", 0)) / 1024)
        swap = int(mem.get("SwapTotal", 0) / 1024)
        report.virtual_memory_total_mb = report.physical_ram_mb + swap

    try:
        du = shutil.disk_usage(Path.home())
        report.disk_free_mb = int(du.free / (1024 * 1024))
        report.disk_total_mb = int(du.total / (1024 * 1024))
    except Exception:
        pass

    report.os_version = f"{platform.system()} {platform.release()}"
    report.gpus.extend(_nvidia_smi_gpus())
    if not report.gpus:
        report.warnings.append(
            "No dedicated GPU detected via nvidia-smi; assuming CPU-only / "
            "integrated graphics. Treat any GPU memory as shared, not VRAM."
        )
    _annotate_ram_warning(report)
    report.backends_available = _detect_backends()
    return report


# ----------------------------------------------------------------------------
# Shared helpers
# ----------------------------------------------------------------------------
def _annotate_ram_warning(report: HardwareReport) -> None:
    """Flag the ambiguous '32 GB' case from the roadmap."""
    if report.virtual_memory_total_mb > report.physical_ram_mb * 1.3:
        report.warnings.append(
            f"Virtual/commit memory ({round(report.virtual_memory_total_mb/1024,1)} "
            f"GB) significantly exceeds installed RAM "
            f"({report.physical_ram_gb} GB). Page file is NOT a substitute for "
            f"RAM or VRAM; profiles are gated on installed RAM only."
        )
    if report.physical_ram_mb == 0:
        report.warnings.append(
            "Could not read installed physical RAM. Confirm in Task Manager "
            "(Performance tab) before trusting any profile selection."
        )


def _detect_backends() -> list[str]:
    """Report only runtimes that actually import. Never assume from GPU name."""
    backends = ["ffmpeg"] if shutil.which("ffmpeg") else []
    for mod, label in (("openvino", "openvino-cpu"),
                       ("torch", "torch")):
        try:
            __import__(mod)
            backends.append(label)
        except Exception:
            pass
    return backends


def collect_hardware_report() -> HardwareReport:
    """Collect a measured hardware report for the current machine."""
    if platform.system().lower().startswith("win"):
        return _collect_windows()
    return _collect_posix()
