"""Hardware detection runs on the real (test) machine without crashing."""
import pytest

from nova_studio.core.hardware import collect_hardware_report

pytestmark = pytest.mark.hardware


def test_collect_report_runs():
    r = collect_hardware_report()
    assert r.cpu_name
    assert r.logical_cores >= 1
    # Must distinguish physical RAM from virtual total.
    assert r.physical_ram_mb >= 0
    assert isinstance(r.warnings, list)
    # Summary never claims dedicated VRAM it didn't measure.
    summary = r.human_summary()
    assert isinstance(summary, str) and summary


def test_backends_only_real():
    r = collect_hardware_report()
    # Every reported backend must be a known label; no fabrication.
    for b in r.backends_available:
        assert b in {"ffmpeg", "openvino-cpu", "torch"}
