"""Headless tests for the Voice Studio UI panel logic."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Reuse the shared Qt stub.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ui_stub import install_qt_stub  # noqa: E402


@pytest.fixture
def ui_module():
    install_qt_stub()
    from nova_studio.ui import main_window
    return main_window


def test_voice_status_text_marks_availability(ui_module):
    from nova_studio.voice.registry import VoiceRegistry
    gallery = VoiceRegistry("/nonexistent").gallery()
    text = ui_module.MainWindow._voice_status_text(gallery)
    # Both engines unavailable in CI -> ✗ with reasons.
    assert "✗ Piper" in text
    assert "✗ XTTS-v2" in text
    assert "non-commercial" in text.lower()


class _FakeConfig:
    class paths:
        pass


class _FakeStudio:
    """Just enough for MainWindow to build and drive the voice panel."""
    def __init__(self, caps=None):
        from nova_studio.voice.engine import EngineCapabilities
        self._caps = caps or EngineCapabilities(
            speed=True, pause=True, pronunciation=True,
            emphasis=False, emotion=False)
        self.auditioned = []

        class _Report:
            warnings = []
            def human_summary(self): return "x"
        self.report = _Report()

        class _Paths:
            projects = Path("/tmp")
        class _Cfg:
            paths = _Paths()
        self.config = _Cfg()
        self.project = type("P", (), {"id": "p", "name": "P", "scenes": [],
                                      "assets": [], "target_width": 1280,
                                      "target_height": 720, "target_fps": 24})()

    def new_project(self, name): return self.project
    def save_project(self, p): pass
    def refresh_pipeline(self): pass
    def effective_profile(self, req):
        from nova_studio.core.capability import Profile
        return Profile.BALANCED, "b"

    def pipeline_readiness(self):
        return {"script": {"ready": False, "blocker": "", "model": None,
                           "state": "x"},
                "tts": {"ready": False, "blocker": "", "voice": None,
                        "state": "x"},
                "render": {"ready": True, "state": "supported"}}

    def voice_gallery(self):
        from nova_studio.voice.engine import (EngineStatus, VoiceInfo)
        caps = self._caps
        status = EngineStatus(
            engine_id="piper", display_name="Piper", runtime="piper",
            available=True, capabilities=caps,
            voices=[VoiceInfo(name="amy.onnx", path="/models/tts/amy.onnx",
                              language="en_US", quality="medium")])

        class _Gallery:
            engines = [status]
            def engine(self, eid):
                return status if eid == "piper" else None
        return _Gallery()

    def audition_voice(self, engine_id, voice_path, expression=None,
                       pronunciation=None):
        self.auditioned.append((engine_id, voice_path))
        return {"ok": True, "path": "/tmp/preview.wav", "message": "ok",
                "unsupported": []}

    def generation_registry(self, installed_ids=None):
        from nova_studio.phase4.generation_engine import GenerationEngineRegistry
        from nova_studio.models.hardware_report import HardwareReport
        return GenerationEngineRegistry(
            HardwareReport(physical_ram_mb=8000, backends_available=["ffmpeg"]),
            installed_ids=installed_ids or set())

    def shutdown(self): pass


def test_voice_panel_lists_available_voice(ui_module):
    w = ui_module.MainWindow(_FakeStudio())
    assert w._voice_entries  # one voice present
    assert w.audition_btn.isEnabled() is True


def test_controls_disabled_for_unsupported_caps(ui_module):
    from nova_studio.voice.engine import EngineCapabilities
    # Engine without pause/pronunciation -> those controls disabled.
    caps = EngineCapabilities(speed=True, pause=False, pronunciation=False)
    w = ui_module.MainWindow(_FakeStudio(caps=caps))
    w._voice_selected(0)
    assert w.speed_spin.isEnabled() is True
    assert w.pause_spin.isEnabled() is False
    assert w.pron_btn.isEnabled() is False
    assert "pause" in w.unsupported_label.text().lower()


def test_audition_calls_backend(ui_module):
    studio = _FakeStudio()
    w = ui_module.MainWindow(studio)
    w._audition()
    assert studio.auditioned == [("piper", "/models/tts/amy.onnx")]
