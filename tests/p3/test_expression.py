"""Pronunciation + expression settings apply or report unsupported honestly."""
from nova_studio.voice.engine import EngineCapabilities
from nova_studio.voice.expression import (ExpressionSettings, PronunciationDict,
                                         resolve_expression)


def test_pronunciation_rewrites_words():
    pron = PronunciationDict()
    pron.add("NOVA", "noh-vah")
    caps = EngineCapabilities(pronunciation=True)
    r = resolve_expression("Welcome to NOVA and nova.", ExpressionSettings(),
                           caps, pron)
    # Whole-word, case-insensitive.
    assert "noh-vah" in r.text
    assert "NOVA" not in r.text
    assert "pronunciation" in r.applied


def test_speed_and_pause_applied_when_supported():
    caps = EngineCapabilities(speed=True, pause=True)
    s = ExpressionSettings(speed=2.0, pause_sentence_ms=500)
    r = resolve_expression("Hello.", s, caps)
    assert r.engine_params["length_scale"] == 0.5
    assert r.engine_params["sentence_silence_s"] == 0.5
    assert set(r.applied) >= {"speed", "pause"}
    assert r.unsupported == []


def test_unsupported_settings_reported_not_applied():
    # Engine supports neither emphasis nor emotion.
    caps = EngineCapabilities(speed=True, emphasis=False, emotion=False)
    s = ExpressionSettings(emphasis_words=["now"], emotion="cheerful")
    r = resolve_expression("Act now.", s, caps)
    assert "emphasis" in r.unsupported
    assert "emotion" in r.unsupported
    assert "emphasis_words" not in r.engine_params
    assert "emotion" not in r.engine_params


def test_pronunciation_unsupported_when_engine_cant():
    pron = PronunciationDict()
    pron.add("Qwen", "kwen")
    caps = EngineCapabilities(pronunciation=False)
    r = resolve_expression("Qwen rocks.", ExpressionSettings(), caps, pron)
    # Text unchanged, reported unsupported.
    assert r.text == "Qwen rocks."
    assert "pronunciation" in r.unsupported
