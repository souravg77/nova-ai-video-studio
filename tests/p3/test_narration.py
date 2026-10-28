"""Scene narration manager: validated per-scene audio + single-scene regen."""
import pytest

from nova_studio.adapters.tts import TTSAdapter
from nova_studio.voice.engine import EngineCapabilities
from nova_studio.voice.expression import ExpressionSettings
from nova_studio.voice.narration import NarrationManager, VoiceProfile

pytestmark = pytest.mark.export  # fake piper needs ffmpeg


def _manager(voice_path, tmp_path):
    profile = VoiceProfile(
        engine_id="piper", voice_path=str(voice_path),
        capabilities=EngineCapabilities(speed=True, pause=True,
                                        pronunciation=True),
        expression=ExpressionSettings(speed=1.0))
    return NarrationManager(profile, tts_adapter=TTSAdapter(voice_path=str(voice_path)))


def test_generate_all_validates_each(tmp_path, fake_piper_voice, fake_piper_cli):
    mgr = _manager(fake_piper_voice, tmp_path)
    scenes = mgr.generate_all(["First.", "Second.", "Third."],
                              tmp_path / "narr")
    assert len(scenes) == 3
    assert all(s.ok for s in scenes)
    assert all(s.duration_s > 0 for s in scenes)
    from pathlib import Path
    assert all(Path(s.audio_path).exists() for s in scenes)


def test_regenerate_one_scene_only(tmp_path, fake_piper_voice, fake_piper_cli):
    mgr = _manager(fake_piper_voice, tmp_path)
    scenes = mgr.generate_all(["Alpha.", "Beta.", "Gamma."], tmp_path / "narr")
    # Capture other scenes' audio mtimes.
    from pathlib import Path
    before = {i: Path(scenes[i].audio_path).stat().st_mtime_ns
              for i in (0, 2)}
    # Regenerate scene 1 with new text.
    scenes = mgr.regenerate_scene(scenes, 1, tmp_path / "narr",
                                  new_text="Beta rewritten.")
    assert scenes[1].text == "Beta rewritten."
    assert scenes[1].ok
    # Scenes 0 and 2 untouched (same files, unchanged).
    after = {i: Path(scenes[i].audio_path).stat().st_mtime_ns for i in (0, 2)}
    assert after == before


def test_unavailable_voice_reports_blocker(tmp_path):
    # No fake piper on PATH, no voice -> honest failure, not fake audio.
    profile = VoiceProfile(engine_id="piper", voice_path="",
                           capabilities=EngineCapabilities())
    mgr = NarrationManager(profile, tts_adapter=TTSAdapter(voice_path=None))
    scenes = mgr.generate_all(["Hello."], tmp_path / "narr")
    assert scenes[0].ok is False
