"""Planner engine catalog built from the real voice engines."""
from nova_studio.performance.catalog import build_registry, voice_choices, voice_engine_spec
from nova_studio.performance.characters import set_voice, create_character
from nova_studio.performance.engines import Role
from nova_studio.performance.planner import (
    DialogueLine, EngineSelection, PlanContext, Shot, plan_shot)
from nova_studio.voice.engine import PiperEngine, VoiceInfo


class FakePiper(PiperEngine):
    def __init__(self, present=True, voices=()):
        super().__init__(None)
        self._present, self._voices = present, list(voices)

    def is_runtime_present(self):
        return self._present

    def discover_voices(self):
        return self._voices


AMY = VoiceInfo(name="en_US-amy-medium.onnx", path="/v/amy.onnx", language="en_US",
                license_ok=True)
THORSTEN = VoiceInfo(name="de_DE-thorsten.onnx", path="/v/t.onnx", language="de_DE")


def test_voice_spec_declares_installed_languages_only():
    spec = voice_engine_spec(FakePiper(voices=[AMY, THORSTEN]))
    assert spec.id == "voice:piper" and Role.VOICE in spec.roles
    assert spec.capabilities.languages == ("de-DE", "en-US")
    assert spec.capabilities.supports_language("en")
    assert not spec.capabilities.supports_language("fr")
    assert spec.status().available and not spec.capabilities.emotion_control


def test_missing_runtime_or_voices_is_unavailable_with_reason():
    gone = voice_engine_spec(FakePiper(present=False))
    assert not gone.status().available and "not installed" in gone.status().reason
    empty = voice_engine_spec(FakePiper(voices=[]))
    assert not empty.status().available and "no voices" in empty.status().reason
    assert empty.capabilities.languages == ()
    assert voice_choices([FakePiper(voices=[])]) == []


def test_choices_flag_unreviewed_licences():
    ch = voice_choices([FakePiper(voices=[AMY, THORSTEN])])
    assert ch[0] == ("voice:piper", AMY.name, f"{AMY.name} (Piper)")
    assert "licence not reviewed" in ch[1][2]


def test_planner_uses_local_voice_and_flags_voice_from_other_engine():
    from nova_studio.performance.engines import EngineCapabilities, EngineSpec, EngineStatus
    up = lambda: EngineStatus(True)  # noqa: E731
    video = EngineSpec("vid", "Vid", frozenset({Role.VIDEO}), EngineCapabilities(
        video_generation=True, min_duration_s=1, max_duration_s=10,
        aspect_ratios=("16:9",), languages=("en",)), status_fn=up)
    lips = EngineSpec("lips", "Lips", frozenset({Role.LIPSYNC}),
                      EngineCapabilities(lip_sync=True), status_fn=up)
    reg = build_registry([FakePiper(voices=[AMY])], extra=[video, lips])
    from nova_studio.performance.characters import (
        Candidate, CandidateSource, add_candidates, approve_candidate)
    c = add_candidates(create_character("maya", "Maya"), [
        Candidate(id="a", image_path="/a.png", source=CandidateSource.UPLOADED)])
    c = approve_candidate(c, "a")
    shot = Shot(id="s", duration_s=5, character_ids=["maya"], dialogue_line_ids=["l1"])
    line = DialogueLine(id="l1", order=1, speaker_id="maya", text="Hi.")

    def plan(ch):
        ctx = PlanContext(characters=[ch], dialogue=[line],
                          selection=EngineSelection(video="vid", voice="voice:piper", lipsync="lips"))
        return {l.code for l in plan_shot(shot, ctx, reg).limitations}

    codes = plan(c)
    assert "voice_profile" in codes and "voice_engine_unavailable" not in codes
    assert "voice_profile" not in plan(set_voice(c, "voice:piper", AMY.name))
    assert "voice_engine_mismatch" in plan(set_voice(c, "voice:xtts_v2", "ref"))
    logged = set_voice(c, "voice:piper", AMY.name).history[-1]
    assert logged.action == "voice_changed" and AMY.name in logged.note
