"""Headless tests for the Voice Studio UI panel logic."""
from __future__ import annotations

import pytest

from ui_stub import install_qt_stub

@pytest.fixture
def vp_module():
    install_qt_stub()
    from nova_studio.ui import voice_panel
    return voice_panel


class _FakeStudio:
    def __init__(self, voices_dir):
        from nova_studio.voice.registry import VoiceRegistry
        self._reg = VoiceRegistry(voices_dir)
        self.auditions = []

    def voice_gallery(self):
        return self._reg.gallery()

    def audition_voice(self, engine_id, voice_path, expression=None,
                       pronunciation=None, text="preview"):
        self.auditions.append((engine_id, voice_path))
        return {"ok": False, "path": "", "message": "No voice installed.",
                "unsupported": []}


def test_format_gallery_honest(vp_module, tmp_path):
    from nova_studio.voice.registry import VoiceRegistry
    g = VoiceRegistry(tmp_path).gallery()
    lines = vp_module.format_gallery(g)
    assert any("Piper" in ln and ln.startswith("✗") for ln in lines)


def test_unsupported_disables_controls(vp_module, tmp_path):
    from nova_studio.voice.registry import VoiceRegistry
    g = VoiceRegistry(tmp_path).gallery()
    # Piper: emphasis + emotion unsupported.
    assert set(vp_module.unsupported_for(g, "piper")) >= {"emphasis", "emotion"}


def test_panel_builds_and_disables_audition_without_voices(vp_module, tmp_path):
    studio = _FakeStudio(tmp_path)
    panel = vp_module.VoiceStudioPanel(studio)
    # No voices installed -> audition disabled.
    assert panel.audition_btn.isEnabled() is False


def test_pronunciation_editor_adds_entry(vp_module, tmp_path):
    studio = _FakeStudio(tmp_path)
    panel = vp_module.VoiceStudioPanel(studio)
    panel.word_edit.setText("NOVA")
    panel.sayas_edit.setText("noh-vah")
    panel._add_pron()
    assert panel.pron.entries.get("NOVA") == "noh-vah"
