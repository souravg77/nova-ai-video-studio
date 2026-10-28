"""Headless test for the P4.6 'Make photo video' button logic."""
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


class _Job:
    def __init__(self):
        self.id = "j"


class _Report:
    warnings = []
    def human_summary(self): return "x"


class _Studio:
    def __init__(self):
        self.report = _Report()
        self.submitted = []
        class _Paths:
            projects = Path("/tmp")
        class _Cfg:
            paths = _Paths()
        self.config = _Cfg()
        self.project = type("P", (), {"id": "p", "name": "P", "scenes": [],
                                      "assets": [], "target_width": 640,
                                      "target_height": 360, "target_fps": 24})()

    def new_project(self, n): return self.project
    def save_project(self, p): pass
    def refresh_pipeline(self): pass
    def effective_profile(self, r):
        from nova_studio.core.capability import Profile
        return Profile.BALANCED, "b"
    def pipeline_readiness(self):
        return {"script": {"ready": False, "blocker": "", "model": None,
                           "state": "x"},
                "tts": {"ready": False, "blocker": "", "voice": None,
                        "state": "x"},
                "render": {"ready": True, "state": "supported"}}
    def voice_gallery(self):
        from nova_studio.voice.registry import VoiceRegistry
        return VoiceRegistry("/nonexistent").gallery()
    def generation_registry(self, installed_ids=None):
        from nova_studio.phase4.generation_engine import GenerationEngineRegistry
        from nova_studio.models.hardware_report import HardwareReport
        return GenerationEngineRegistry(
            HardwareReport(physical_ram_mb=8000, backends_available=["ffmpeg"]),
            installed_ids=installed_ids or set())
    def photo_video(self, project, scenes, config=None, voice=None,
                    listener=None):
        self.submitted.append({"scenes": scenes, "config": config,
                               "voice": voice})
        return _Job()
    def shutdown(self): pass


def test_photo_video_button_disabled_until_photos(ui_module):
    w = ui_module.MainWindow(_Studio())
    assert w.photo_video_btn.isEnabled() is False


def test_make_photo_video_requires_three(ui_module):
    studio = _Studio()
    w = ui_module.MainWindow(studio)
    w._approved_photos = ["a.png"]  # not three
    w._make_photo_video()
    assert studio.submitted == []


def test_make_photo_video_submits_captions_only(ui_module):
    studio = _Studio()
    w = ui_module.MainWindow(studio)
    w._approved_photos = ["a.png", "b.png", "c.png"]
    # No voice selected -> captions-only (want_narration False).
    w._make_photo_video()
    assert len(studio.submitted) == 1
    sub = studio.submitted[0]
    assert sub["voice"] is None
    assert sub["config"]["want_narration"] is False
    assert len(sub["scenes"]) == 3
