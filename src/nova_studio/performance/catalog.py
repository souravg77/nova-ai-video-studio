"""The engines the shot planner can choose from, built from what is really
installed on this PC plus any cloud engine the user switched on.

Voice engines come from the existing ``voice`` package (Piper, XTTS-v2), so
the planner and Voice Studio agree on what is available. A voice engine's
languages are the languages of its installed voices; with no voices it is
unavailable and declares none.
"""
from __future__ import annotations

from typing import Optional

from ..voice.engine import VoiceEngine, VoiceInfo
from .engines import EngineCapabilities, EngineRegistry, EngineSpec, EngineStatus, Role


def voice_language(voice: VoiceInfo) -> Optional[str]:
    """'en_US' (Piper naming) -> 'en-US'. Unknown stays unknown."""
    lang = (voice.language or "").strip()
    if not lang or lang == "unknown":
        return None
    return lang.replace("_", "-")


def voice_engine_spec(engine: VoiceEngine) -> EngineSpec:
    st = engine.status()
    langs = tuple(sorted({l for v in st.voices if (l := voice_language(v))}))
    caps = EngineCapabilities(
        speech_synthesis=True,
        emotion_control=engine.capabilities.emotion,
        languages=langs)

    def status() -> EngineStatus:
        now = engine.status()
        return EngineStatus(now.available, now.reason.strip())

    return EngineSpec(
        id=f"voice:{engine.engine_id}", name=f"{engine.display_name} (local voice)",
        roles=frozenset({Role.VOICE}), capabilities=caps,
        description=f"Local text-to-speech ({engine.runtime}).",
        status_fn=status)


def build_registry(voice_engines: list[VoiceEngine],
                   extra: Optional[list[EngineSpec]] = None) -> EngineRegistry:
    """Rebuild whenever voices are installed or settings change, so declared
    languages and availability are current."""
    specs = [voice_engine_spec(e) for e in voice_engines]
    return EngineRegistry(specs + list(extra or []))


def voice_choices(voice_engines: list[VoiceEngine]) -> list[tuple[str, str, str]]:
    """(engine spec id, voice id, label) for every installed voice of an
    available engine. Labels flag voices whose licence is not yet reviewed."""
    out = []
    for e in voice_engines:
        st = e.status()
        if not st.available:
            continue
        for v in st.voices:
            label = f"{v.name} ({e.display_name}"
            label += ")" if v.license_ok else ", licence not reviewed)"
            out.append((f"voice:{e.engine_id}", v.name, label))
    return out
