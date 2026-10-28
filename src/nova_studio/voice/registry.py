"""Voice engine registry (Phase 3, P3.1).

Collects the status of every known voice engine and the installed voice
gallery. Reports only real availability.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .engine import (EngineStatus, PiperEngine, VoiceEngine, VoiceInfo,
                     XTTSCloningEngine)


@dataclass
class VoiceGallery:
    engines: list[EngineStatus]

    @property
    def available_engines(self) -> list[EngineStatus]:
        return [e for e in self.engines if e.available]

    @property
    def all_voices(self) -> list[VoiceInfo]:
        voices: list[VoiceInfo] = []
        for e in self.engines:
            voices.extend(e.voices)
        return voices

    def engine(self, engine_id: str) -> EngineStatus | None:
        return next((e for e in self.engines if e.engine_id == engine_id), None)


class VoiceRegistry:
    def __init__(self, voices_dir: str | Path) -> None:
        self.voices_dir = Path(voices_dir)
        self._engines: list[VoiceEngine] = [
            PiperEngine(voices_dir=self.voices_dir),
            XTTSCloningEngine(),
        ]

    def gallery(self) -> VoiceGallery:
        return VoiceGallery(engines=[e.status() for e in self._engines])

    def engine_for(self, engine_id: str) -> VoiceEngine | None:
        return next((e for e in self._engines if e.engine_id == engine_id), None)
