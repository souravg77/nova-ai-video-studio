"""Headless UI logic tests for the Auto Video panel.

Uses the shared Qt stub (tests/ui_stub.py) so there is exactly one stub
implementation across UI test modules. Exercises the window's pure logic:
readiness formatting, Auto Video gating, and AUTO_VIDEO final-notice branching.
"""
from __future__ import annotations

import pytest

from ui_stub import install_qt_stub

@pytest.fixture
def ui_module():
    install_qt_stub()
    from nova_studio.ui import main_window
    return main_window


def test_readiness_text_formats_honestly(ui_module):
    MW = ui_module.MainWindow
    readiness = {
        "script": {"ready": False, "state": "unsupported_on_this_pc",
                   "blocker": "No script model (Qwen2.5 GGUF) is installed.",
                   "model": None},
        "tts": {"ready": False, "state": "unsupported_on_this_pc",
                "blocker": "No narration voice (Piper) is installed.",
                "voice": None},
        "render": {"ready": True, "state": "supported"},
    }
    text = MW._readiness_text(readiness)
    assert "✗ Qwen2.5 script: not installed" in text
    assert "✗ Piper narration: not installed" in text
    assert "✓ FFmpeg render: ready" in text
    assert "No script model" in text


def test_readiness_text_ready(ui_module):
    MW = ui_module.MainWindow
    readiness = {
        "script": {"ready": True, "state": "supported", "blocker": "",
                   "model": "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"},
        "tts": {"ready": True, "state": "supported", "blocker": "",
                "voice": "en_US-amy.onnx"},
        "render": {"ready": True, "state": "supported"},
    }
    text = MW._readiness_text(readiness)
    assert "✓ Qwen2.5 script: Qwen2.5-1.5B-Instruct-Q4_K_M.gguf" in text
    assert "✓ Piper narration: en_US-amy.onnx" in text
    # No blocker lines when ready.
    assert "→" not in text


# --- Window-level logic with a fake Studio ----------------------------------
class _FakeProject:
    def __init__(self):
        self.id = "pid"
        self.name = "Proj"
        self.target_width = 1280
        self.target_height = 720
        self.target_fps = 24
        self.scenes = []
        self.assets = []


class _FakeJob:
    def __init__(self, kind, state, **kw):
        self.id = "jid"
        self.kind = kind
        self.state = state
        self.progress = kw.get("progress", 0.0)
        self.logs = kw.get("logs", [])
        self.generation_state = kw.get("generation_state")
        self.blocker = kw.get("blocker", "")
        self.suggested_fallback = kw.get("suggested_fallback", "")
        self.outputs = kw.get("outputs", [])


class _FakeReport:
    warnings: list = []
    def human_summary(self): return "FakeCPU · 32 GB RAM · no GPU"


class _FakeStudio:
    def __init__(self, ready=True):
        self._ready = ready
        self.submitted = []
        self.cancelled = []
        self.project = _FakeProject()
        self.report = _FakeReport()

    def new_project(self, name): return self.project
    def save_project(self, p): pass
    def refresh_pipeline(self): pass

    def pipeline_readiness(self):
        r = self._ready
        return {
            "script": {"ready": r, "state": "supported" if r else "unsupported_on_this_pc",
                       "blocker": "" if r else "No script model installed.",
                       "model": "qwen.gguf" if r else None},
            "tts": {"ready": r, "state": "supported" if r else "unsupported_on_this_pc",
                    "blocker": "" if r else "No voice installed.",
                    "voice": "amy.onnx" if r else None},
            "render": {"ready": True, "state": "supported"},
        }

    def effective_profile(self, req):
        from nova_studio.core.capability import Profile
        return Profile.BALANCED, "balanced"

    def auto_video(self, project, brief, listener=None, preset=None, **kw):
        from nova_studio.models.job import JobKind, JobState
        self.submitted.append({"brief": brief, "preset": preset})
        return _FakeJob(JobKind.AUTO_VIDEO, JobState.QUEUED)

    def cancel_job(self, job_id):
        self.cancelled.append(job_id)
        return True

    def voice_gallery(self):
        # The window now embeds the Voice Studio panel, which queries this.
        from nova_studio.voice.registry import VoiceRegistry
        return VoiceRegistry("/nonexistent").gallery()

    def generation_registry(self, installed_ids=None):
        # The Phase 4 panel queries this; a CPU-only report -> unsupported.
        from nova_studio.phase4.generation_engine import GenerationEngineRegistry
        from nova_studio.models.hardware_report import HardwareReport
        return GenerationEngineRegistry(
            HardwareReport(physical_ram_mb=8000, backends_available=["ffmpeg"]),
            installed_ids=installed_ids or set())

    def intake_photos(self, paths):
        from nova_studio.phase4.intake import intake_photos as _i
        return _i(paths)

    def photo_video(self, project, scenes, config=None, voice=None,
                    listener=None):
        from nova_studio.models.job import JobKind, JobState
        self.submitted.append({"photo_scenes": scenes, "voice": voice})
        return _FakeJob(JobKind.PHOTO_VIDEO, JobState.QUEUED)

    def shutdown(self): pass


def test_auto_button_disabled_when_models_missing(ui_module):
    w = ui_module.MainWindow(_FakeStudio(ready=False))
    assert w.auto_btn.isEnabled() is False


def test_auto_button_enabled_when_ready(ui_module):
    w = ui_module.MainWindow(_FakeStudio(ready=True))
    assert w.auto_btn.isEnabled() is True


def test_auto_video_submits_brief(ui_module):
    studio = _FakeStudio(ready=True)
    w = ui_module.MainWindow(studio)
    w.brief_edit._plain = "A teaser about coffee"
    w._auto_video()
    assert studio.submitted and studio.submitted[0]["brief"] == "A teaser about coffee"
    assert w.active_job_id == "jid"
    # Running state: cancel enabled, render disabled.
    assert w.cancel_btn.isEnabled() is True
    assert w.render_btn.isEnabled() is False


def test_auto_video_requires_brief(ui_module):
    studio = _FakeStudio(ready=True)
    w = ui_module.MainWindow(studio)
    w.brief_edit._plain = "   "
    w._auto_video()
    assert studio.submitted == []  # nothing submitted on empty brief


def test_cancel_requests_stop(ui_module):
    studio = _FakeStudio(ready=True)
    w = ui_module.MainWindow(studio)
    w.active_job_id = "jid"
    w._cancel_job()
    assert studio.cancelled == ["jid"]


def test_auto_video_blocked_final_notice(ui_module):
    from nova_studio.models.job import JobKind, JobState, GenerationState
    studio = _FakeStudio(ready=True)
    w = ui_module.MainWindow(studio)
    job = _FakeJob(JobKind.AUTO_VIDEO, JobState.FAILED,
                   generation_state=GenerationState.UNSUPPORTED_ON_THIS_PC,
                   blocker="No narration voice installed.",
                   suggested_fallback="Import a recorded narration.")
    # Should not raise; sets a stage label explaining the stop.
    w._announce_final(job)
    assert "stopped" in w.stage_label.text().lower()
    assert "voice" in w.stage_label.text().lower()


def test_auto_video_success_final_notice(ui_module):
    from nova_studio.models.job import JobKind, JobState, GenerationState
    studio = _FakeStudio(ready=True)
    w = ui_module.MainWindow(studio)
    job = _FakeJob(JobKind.AUTO_VIDEO, JobState.COMPLETED,
                   generation_state=GenerationState.COMPLETED_AND_VALIDATED,
                   outputs=["/x/auto.mp4"])
    w._announce_final(job)
    assert "validated" in w.stage_label.text().lower()
