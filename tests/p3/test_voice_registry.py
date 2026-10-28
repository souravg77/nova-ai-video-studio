"""Voice engine registry reports real availability + capabilities."""
from nova_studio.voice.registry import VoiceRegistry


def test_piper_unavailable_without_runtime(tmp_path):
    # Voice files present but Piper runtime absent in CI -> not available.
    vdir = tmp_path / "tts"
    vdir.mkdir()
    (vdir / "en_US-amy-medium.onnx").write_text("x")
    (vdir / "en_US-amy-medium.onnx.json").write_text("{}")
    gallery = VoiceRegistry(vdir).gallery()
    piper = gallery.engine("piper")
    assert piper is not None
    # In CI the piper runtime is not installed -> available False, honest reason.
    assert piper.available is False
    assert "not installed" in piper.reason


def test_capabilities_are_honest():
    gallery = VoiceRegistry("/nonexistent").gallery()
    piper = gallery.engine("piper")
    # Piper supports speed+pause+pronunciation, not emphasis/emotion/cloning.
    assert piper.capabilities.speed is True
    assert piper.capabilities.pause is True
    assert piper.capabilities.pronunciation is True
    assert piper.capabilities.emphasis is False
    assert piper.capabilities.emotion is False
    assert piper.capabilities.cloning is False


def test_xtts_flags_noncommercial_license():
    gallery = VoiceRegistry("/nonexistent").gallery()
    xtts = gallery.engine("xtts_v2")
    assert xtts is not None
    assert xtts.capabilities.cloning is True
    assert "non-commercial" in xtts.reason.lower()
