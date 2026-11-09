"""What a generation engine declares it can actually do.

NOVA plans every shot against these declarations. A declaration must match the
provider's documentation, never an optimistic guess, and an engine that is not
configured reports itself unavailable instead of failing later.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional, Union


class IdentityPreservation(str, Enum):
    NONE = "none"
    WEAK = "weak"
    REFERENCE_GUIDED = "reference_guided"   # approved images guide generation
    TRAINED_IDENTITY = "trained_identity"   # e.g. a trained LoRA (not built yet)


class Role(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    VOICE = "voice"
    LIPSYNC = "lipsync"


ANY_LANGUAGE = "any"


@dataclass(frozen=True)
class EngineCapabilities:
    image_generation: bool = False
    video_generation: bool = False
    # Generates speech and synchronised performance together with the video.
    native_audio: bool = False
    speech_synthesis: bool = False
    lip_sync: bool = False
    emotion_control: bool = False
    head_motion_control: bool = False
    # Can perform more than one speaking character reliably in one generation.
    multi_speaker_in_one_shot: bool = False
    max_reference_images: int = 0
    identity_preservation: IdentityPreservation = IdentityPreservation.NONE
    start_end_frames: bool = False
    min_duration_s: float = 0.0
    max_duration_s: float = 0.0
    aspect_ratios: tuple[str, ...] = ()
    # Language codes the provider documents as supported, or ANY_LANGUAGE.
    languages: Union[tuple[str, ...], str] = ()
    # Output is a stand-in for workflow testing, never real footage.
    produces_placeholders: bool = False
    # Runs on a remote service; only allowed when the user switched it on.
    is_cloud: bool = False

    def supports_language(self, lang: str) -> bool:
        if self.languages == ANY_LANGUAGE:
            return True
        base = lang.split("-")[0].lower()
        return any(x.lower() == lang.lower() or x.split("-")[0].lower() == base
                   for x in self.languages)


@dataclass
class EngineStatus:
    available: bool
    reason: str = ""


@dataclass
class EngineSpec:
    id: str
    name: str
    roles: frozenset[Role]
    capabilities: EngineCapabilities
    description: str = ""
    # Called on every check so availability is never stale (key removed,
    # cloud switched off, model deleted ...).
    status_fn: Callable[[], EngineStatus] = field(
        default=lambda: EngineStatus(False, "No status check configured"))

    def status(self) -> EngineStatus:
        try:
            return self.status_fn()
        except Exception as exc:  # a broken check must not read as available
            return EngineStatus(False, f"status check failed: {exc}")


class EngineRegistry:
    def __init__(self, engines: Optional[list[EngineSpec]] = None) -> None:
        self._engines: dict[str, EngineSpec] = {}
        for e in engines or []:
            self.register(e)

    def register(self, engine: EngineSpec) -> None:
        self._engines[engine.id] = engine

    def get(self, engine_id: Optional[str]) -> Optional[EngineSpec]:
        return self._engines.get(engine_id) if engine_id else None

    def with_role(self, role: Role) -> list[EngineSpec]:
        return [e for e in self._engines.values() if role in e.roles]
