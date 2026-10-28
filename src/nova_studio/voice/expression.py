"""Pronunciation dictionary + expression settings (Phase 3, P3.3).

A pronunciation dictionary rewrites names/difficult words before synthesis.
Expression settings (speed, pause, emphasis, emotion) are validated against the
chosen engine's real capabilities: a setting the engine does not support is
reported as unsupported and NOT applied — never silently dropped and claimed.

These transforms produce the concrete text + engine parameters actually sent
to the TTS adapter, so "supported settings affect actual generated audio."
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .engine import EngineCapabilities


@dataclass
class PronunciationDict:
    """Case-insensitive whole-word replacements applied before synthesis."""
    entries: dict[str, str] = field(default_factory=dict)

    def add(self, word: str, say_as: str) -> None:
        self.entries[word.strip()] = say_as.strip()

    def apply(self, text: str) -> str:
        out = text
        # Longest keys first so multi-word entries win.
        for word in sorted(self.entries, key=len, reverse=True):
            say_as = self.entries[word]
            pattern = r"\b" + re.escape(word) + r"\b"
            out = re.sub(pattern, say_as, out, flags=re.IGNORECASE)
        return out


@dataclass
class ExpressionSettings:
    """Requested expressive controls. Validated against engine capabilities."""
    speed: float = 1.0           # 1.0 = normal; <1 slower, >1 faster
    pause_sentence_ms: int = 0   # extra silence between sentences
    emphasis_words: list[str] = field(default_factory=list)
    emotion: Optional[str] = None  # e.g. "cheerful", "serious"


@dataclass
class ResolvedExpression:
    """What will actually be sent to the engine, plus honest unsupported list."""
    text: str
    engine_params: dict
    applied: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)


def resolve_expression(text: str, settings: ExpressionSettings,
                       caps: EngineCapabilities,
                       pron: Optional[PronunciationDict] = None
                       ) -> ResolvedExpression:
    """Turn requested settings + text into concrete engine params.

    Each requested, non-default setting is either applied (recorded in
    `applied`) or reported in `unsupported` when the engine can't do it.
    """
    applied: list[str] = []
    unsupported: list[str] = []
    params: dict = {}

    # Pronunciation first (text rewrite).
    final_text = text
    if pron and pron.entries:
        if caps.pronunciation:
            final_text = pron.apply(text)
            applied.append("pronunciation")
        else:
            unsupported.append("pronunciation")

    # Speed.
    if abs(settings.speed - 1.0) > 1e-6:
        if caps.speed:
            # Piper uses length_scale = 1/speed (higher = slower).
            params["length_scale"] = round(1.0 / settings.speed, 3)
            params["speed"] = settings.speed
            applied.append("speed")
        else:
            unsupported.append("speed")

    # Pause.
    if settings.pause_sentence_ms > 0:
        if caps.pause:
            params["sentence_silence_s"] = settings.pause_sentence_ms / 1000.0
            applied.append("pause")
        else:
            unsupported.append("pause")

    # Emphasis.
    if settings.emphasis_words:
        if caps.emphasis:
            params["emphasis_words"] = list(settings.emphasis_words)
            applied.append("emphasis")
        else:
            unsupported.append("emphasis")

    # Emotion.
    if settings.emotion:
        if caps.emotion:
            params["emotion"] = settings.emotion
            applied.append("emotion")
        else:
            unsupported.append("emotion")

    return ResolvedExpression(text=final_text, engine_params=params,
                              applied=applied, unsupported=unsupported)
