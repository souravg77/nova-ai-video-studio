"""Talking-head generation gates block iGPU / unlicensed / uninstalled."""
from nova_studio.models.hardware_report import (GpuInfo, GpuVendor,
                                                HardwareReport)
from nova_studio.phase4.generation_engine import (GenerationEngineRegistry,
                                                  GenVerdict)


def _igpu():
    return HardwareReport(
        cpu_name="i5-12th", physical_ram_mb=32000,
        gpus=[GpuInfo(name="Intel Iris Xe", vendor=GpuVendor.INTEL)],
        backends_available=["ffmpeg"])


def _rtx(vram_mb=24576):
    return HardwareReport(
        physical_ram_mb=64000,
        gpus=[GpuInfo(name="RTX 4090", vendor=GpuVendor.NVIDIA,
                      dedicated_vram_mb=vram_mb, runtime_confirmed=True)],
        backends_available=["ffmpeg", "torch"])


def test_not_installed_blocks():
    reg = GenerationEngineRegistry(_igpu(), installed_ids=set())
    d = reg.decide("sadtalker")
    assert d.verdict == GenVerdict.NOT_INSTALLED
    assert not d.can_attempt
    assert d.suggested_fallback


def test_igpu_unsupported_even_when_installed():
    reg = GenerationEngineRegistry(_igpu(), installed_ids={"sadtalker"})
    d = reg.decide("sadtalker")
    assert d.verdict == GenVerdict.UNSUPPORTED_ON_THIS_PC
    assert "NVIDIA" in d.blocker
    assert not d.can_attempt


def test_insufficient_vram_blocks():
    reg = GenerationEngineRegistry(_rtx(vram_mb=4096), installed_ids={"sadtalker"})
    d = reg.decide("sadtalker")  # needs 6144
    assert d.verdict == GenVerdict.UNSUPPORTED_ON_THIS_PC
    assert "VRAM" in d.blocker


def test_supported_on_capable_gpu():
    reg = GenerationEngineRegistry(_rtx(), installed_ids={"sadtalker"})
    assert reg.decide("sadtalker").verdict == GenVerdict.SUPPORTED


def test_commercial_use_blocked_by_license():
    reg = GenerationEngineRegistry(_rtx(), installed_ids={"sadtalker"})
    d = reg.decide("sadtalker", commercial_use=True)
    assert d.verdict == GenVerdict.BLOCKED_BY_LICENSE


def test_unknown_engine_not_installed():
    reg = GenerationEngineRegistry(_igpu())
    d = reg.decide("does_not_exist")
    assert d.verdict == GenVerdict.NOT_INSTALLED
