"""Headless test for the Phase 4 UI panel's honest status text."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ui_stub import install_qt_stub  # noqa: E402


@pytest.fixture
def ui_module():
    install_qt_stub()
    from nova_studio.ui import main_window
    return main_window


def test_generation_status_blocks_on_igpu(ui_module):
    from nova_studio.phase4.generation_engine import GenerationEngineRegistry
    from nova_studio.models.hardware_report import (GpuInfo, GpuVendor,
                                                    HardwareReport)
    report = HardwareReport(
        physical_ram_mb=32000,
        gpus=[GpuInfo(name="Intel Iris Xe", vendor=GpuVendor.INTEL)],
        backends_available=["ffmpeg"])
    reg = GenerationEngineRegistry(report, installed_ids={"sadtalker"})
    d = reg.decide("sadtalker")
    text = ui_module.MainWindow._generation_status_text(d)
    assert text.startswith("✗")
    assert "unsupported_on_this_pc" in text
    assert "Fallback:" in text


def test_generation_status_supported_on_gpu(ui_module):
    from nova_studio.phase4.generation_engine import GenerationEngineRegistry
    from nova_studio.models.hardware_report import (GpuInfo, GpuVendor,
                                                    HardwareReport)
    report = HardwareReport(
        physical_ram_mb=64000,
        gpus=[GpuInfo(name="RTX 4090", vendor=GpuVendor.NVIDIA,
                      dedicated_vram_mb=24576, runtime_confirmed=True)],
        backends_available=["ffmpeg", "torch"])
    reg = GenerationEngineRegistry(report, installed_ids={"sadtalker"})
    d = reg.decide("sadtalker")
    text = ui_module.MainWindow._generation_status_text(d)
    assert text.startswith("✓")
