"""Setup & diagnostics checks report this PC honestly and point to a fix."""
import pytest

from nova_studio import config
from nova_studio.core import setup_check
from nova_studio.core.capability import CapabilityManager
from nova_studio.core.preflight import FFmpegDiagnostics
from nova_studio.core.setup_check import (CheckItem, Status, overall_status,
                                          run_setup_checks)
from nova_studio.models.hardware_report import HardwareReport
from nova_studio.models.registry import default_registry
from nova_studio.settings import AppSettings

_FF_OK = FFmpegDiagnostics(True, "C:/app/ffmpeg.exe", "C:/app/ffprobe.exe",
                           "bundled", "ffmpeg version 9.0.2", "FFmpeg OK")
_FF_MISSING = FFmpegDiagnostics(False, None, None, None, None,
                                "Missing or broken: ffmpeg, ffprobe.")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("NOVA_GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(setup_check, "check_ffmpeg", lambda refresh=False: _FF_OK)
    cfg = config.AppConfig(paths=config.Paths.create(tmp_path / "ws")).ensure()
    report = HardwareReport(physical_ram_mb=32000, backends_available=["ffmpeg"])
    cap = CapabilityManager(report, registry=default_registry())
    return cfg, report, cap


def _by_key(items):
    return {i.key: i for i in items}


def test_fresh_install_without_models(env):
    cfg, report, cap = env
    items = _by_key(run_setup_checks(cfg, report, cap, AppSettings()))
    assert items["ffmpeg"].status == Status.OK
    assert items["workspace"].status in (Status.OK, Status.WARN)
    assert items["script_model"].status == Status.INFO
    assert str(cfg.paths.models / "script") in items["script_model"].fix
    assert items["voice"].status == Status.INFO
    assert items["offline"].status == Status.OK
    assert items["gemini"].status == Status.INFO
    assert "Nothing is sent" in items["gemini"].detail


def test_missing_ffmpeg_is_a_failure_with_a_fix(env, monkeypatch):
    cfg, report, cap = env
    monkeypatch.setattr(setup_check, "check_ffmpeg", lambda refresh=False: _FF_MISSING)
    items = run_setup_checks(cfg, report, cap, AppSettings())
    ff = _by_key(items)["ffmpeg"]
    assert ff.status == Status.FAIL and "NOVA_FFMPEG_DIR" in ff.fix
    assert overall_status(items) == Status.FAIL


def test_script_model_without_runtime_warns(env, monkeypatch):
    cfg, report, cap = env
    script_dir = cfg.paths.models / "script"
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "qwen2.5-1.5b-instruct-q4_k_m.gguf").write_bytes(b"x")
    monkeypatch.setattr(setup_check, "module_available", lambda name: False)
    items = _by_key(run_setup_checks(cfg, report, cap, AppSettings()))
    assert items["script_model"].status == Status.OK
    assert items["script_runtime"].status == Status.WARN


def test_gemini_states_are_honest(env, monkeypatch):
    cfg, report, cap = env
    on = AppSettings()
    on.cloud.gemini_enabled = True

    monkeypatch.setattr(setup_check, "module_available", lambda name: False)
    g = _by_key(run_setup_checks(cfg, report, cap, on))["gemini"]
    assert g.status == Status.WARN and "does not include" in g.detail

    monkeypatch.setattr(setup_check, "module_available", lambda name: True)
    g = _by_key(run_setup_checks(cfg, report, cap, on))["gemini"]
    assert g.status == Status.WARN and "NOVA_GEMINI_API_KEY" in g.fix

    monkeypatch.setenv("NOVA_GEMINI_API_KEY", "k")
    g = _by_key(run_setup_checks(cfg, report, cap, on))["gemini"]
    assert g.status == Status.OK and "sent to Google" in g.detail


def test_overall_status_order():
    def mk(s):
        return CheckItem("k", "t", s, "d")
    assert overall_status([mk(Status.OK), mk(Status.INFO)]) == Status.OK
    assert overall_status([mk(Status.OK), mk(Status.WARN)]) == Status.WARN
    assert overall_status([mk(Status.WARN), mk(Status.FAIL)]) == Status.FAIL
