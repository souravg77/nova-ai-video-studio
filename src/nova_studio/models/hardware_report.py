"""Typed hardware report.

Crucially distinguishes installed physical RAM, page-file/virtual memory,
shared GPU memory, and dedicated VRAM — the core honesty requirement from
roadmap sections 1, 2 and 7. A GPU name is never treated as proof of
capability.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class GpuVendor(str, Enum):
    INTEL = "intel"
    NVIDIA = "nvidia"
    AMD = "amd"
    UNKNOWN = "unknown"


class GpuInfo(BaseModel):
    name: str = "Unknown GPU"
    vendor: GpuVendor = GpuVendor.UNKNOWN
    driver_version: Optional[str] = None
    # Dedicated VRAM in MB. None means "could not be determined reliably".
    # For Intel integrated graphics this is typically None/0 — memory is
    # SHARED system RAM, reported separately below.
    dedicated_vram_mb: Optional[int] = None
    shared_memory_mb: Optional[int] = None
    # Whether a working accelerated runtime (CUDA / OpenVINO GPU plugin) was
    # actually confirmed exposing this device — not merely that it appears in
    # a system inventory.
    runtime_confirmed: bool = False

    @property
    def is_integrated(self) -> bool:
        return self.vendor == GpuVendor.INTEL and not self.dedicated_vram_mb

    @property
    def dedicated_vram_gb(self) -> float:
        return round((self.dedicated_vram_mb or 0) / 1024, 2)


class HardwareReport(BaseModel):
    """A measured snapshot. Every field is observed, never advertised."""

    cpu_name: str = "Unknown CPU"
    physical_cores: int = 0
    logical_cores: int = 0

    # INSTALLED physical RAM — the real number, read separately from any
    # page-file figure. This is the value profiles are gated on.
    physical_ram_mb: int = 0
    available_ram_mb: int = 0
    # Page file / commit limit minus physical. Reported for transparency and
    # NEVER substituted for VRAM or physical RAM.
    virtual_memory_total_mb: int = 0

    gpus: list[GpuInfo] = Field(default_factory=list)

    disk_free_mb: int = 0
    disk_total_mb: int = 0

    platform: str = "unknown"
    os_version: str = ""

    # Runtimes/backends the app could actually import and initialise.
    backends_available: list[str] = Field(default_factory=list)

    # Non-fatal problems detected while collecting (e.g. WMI AdapterRAM was
    # unreliable, RAM figure may be virtual, disk space ambiguous).
    warnings: list[str] = Field(default_factory=list)

    collected_at: str = ""

    # ------------------------------------------------------------------
    # Derived, honest accessors
    # ------------------------------------------------------------------
    @property
    def physical_ram_gb(self) -> float:
        return round(self.physical_ram_mb / 1024, 1)

    @property
    def available_ram_gb(self) -> float:
        return round(self.available_ram_mb / 1024, 1)

    @property
    def disk_free_gb(self) -> float:
        return round(self.disk_free_mb / 1024, 1)

    @property
    def best_gpu(self) -> Optional[GpuInfo]:
        """The GPU with the most *confirmed dedicated* VRAM, or None."""
        usable = [g for g in self.gpus if g.runtime_confirmed and g.dedicated_vram_mb]
        if usable:
            return max(usable, key=lambda g: g.dedicated_vram_mb or 0)
        return self.gpus[0] if self.gpus else None

    @property
    def max_dedicated_vram_mb(self) -> int:
        return max((g.dedicated_vram_mb or 0 for g in self.gpus), default=0)

    @property
    def has_nvidia_cuda(self) -> bool:
        return any(
            g.vendor == GpuVendor.NVIDIA and g.runtime_confirmed
            for g in self.gpus
        )

    def human_summary(self) -> str:
        gpu_desc = "; ".join(
            f"{g.name}"
            + (f" [{g.dedicated_vram_gb} GB dedicated VRAM]" if g.dedicated_vram_mb
               else " [shared memory, not dedicated VRAM]")
            for g in self.gpus
        ) or "No GPU detected"
        return (
            f"{self.cpu_name} ({self.physical_cores}C/{self.logical_cores}T) · "
            f"{self.physical_ram_gb} GB installed RAM "
            f"({self.available_ram_gb} GB available) · "
            f"GPU: {gpu_desc} · "
            f"{self.disk_free_gb} GB free of "
            f"{round(self.disk_total_mb / 1024, 1)} GB"
        )
