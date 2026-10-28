"""Hardware report honesty: RAM vs page file, shared vs dedicated VRAM."""
from nova_studio.models.hardware_report import GpuInfo, GpuVendor, HardwareReport


def test_intel_igpu_is_not_dedicated_vram():
    gpu = GpuInfo(name="Intel UHD Graphics 770", vendor=GpuVendor.INTEL,
                  dedicated_vram_mb=None, shared_memory_mb=16000)
    assert gpu.is_integrated is True
    assert gpu.dedicated_vram_gb == 0.0


def test_nvidia_with_vram_is_best_gpu_only_if_confirmed():
    confirmed = GpuInfo(name="RTX 4090", vendor=GpuVendor.NVIDIA,
                        dedicated_vram_mb=24576, runtime_confirmed=True)
    unconfirmed = GpuInfo(name="RTX 4090", vendor=GpuVendor.NVIDIA,
                          dedicated_vram_mb=24576, runtime_confirmed=False)
    r1 = HardwareReport(gpus=[confirmed])
    r2 = HardwareReport(gpus=[unconfirmed])
    assert r1.best_gpu is confirmed
    assert r1.has_nvidia_cuda is True
    # Unconfirmed device must not count as CUDA-capable.
    assert r2.has_nvidia_cuda is False


def test_virtual_memory_not_counted_as_ram():
    r = HardwareReport(physical_ram_mb=8000, virtual_memory_total_mb=32000)
    # Our summary/gating uses physical_ram only.
    assert r.physical_ram_gb == 7.8
    assert r.max_dedicated_vram_mb == 0


def test_human_summary_flags_shared_memory():
    r = HardwareReport(
        cpu_name="Core i5-1235U", physical_cores=10, logical_cores=12,
        physical_ram_mb=8000, available_ram_mb=4000,
        gpus=[GpuInfo(name="Intel Iris Xe", vendor=GpuVendor.INTEL)],
        disk_free_mb=15000, disk_total_mb=1_000_000)
    s = r.human_summary()
    assert "shared memory, not dedicated VRAM" in s
