"""Voice engine interface + registry (Phase 3, P3.1 step 1).

A VoiceEngine describes what a TTS backend can actually do on this machine:
which settings it supports (speed, pause, emphasis, emotion/style), its
languages, whether it is locally available, and its license status. The
registry reports only what is real — an engine is "available" only if its
runtime imports/CLI exists AND at least one installed voice is present.

Honesty rule: a requested setting an engine does not support is reported as
unsupported; it is never silently dropped and pretended to be applied.
"""
from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class SettingSupport(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


@dataclass
class EngineCapabilities:
    """What an engine can do. Flags are honest per-engine facts."""
    speed: bool = False          # playback rate / length scale
    pause: bool = False          # inter-sentence / explicit pauses
    emphasis: bool = False       # word emphasis
    emotion: bool = False        # emotion / speaking style
    pronunciation: bool = False  # phoneme / lexicon override
    cloning: bool = False        # voice cloning from a reference sample

    def supports(self, setting: str) -> bool:
        return bool(getattr(self, setting, False))


@dataclass
class VoiceInfo:
    name: str
    path: str
    language: str = "unknown"
    quality: str = "unknown"        # e.g. low/medium/high
    license: str = "unreviewed"
    license_ok: bool = False        # approved for intended use
    local: bool = True


@dataclass
class EngineStatus:
    engine_id: str
    display_name: str
    runtime: str
    available: bool
    reason: str = ""
    capabilities: EngineCapabilities = field(default_factory=EngineCapabilities)
    voices: list[VoiceInfo] = field(default_factory=list)


class VoiceEngine(ABC):
    engine_id: str = "base"
    display_name: str = "Base"
    runtime: str = "none"
    capabilities: EngineCapabilities = EngineCapabilities()

    @abstractmethod
    def is_runtime_present(self) -> bool:
        """Whether the engine's binary/package exists (no voice check)."""

    @abstractmethod
    def discover_voices(self) -> list[VoiceInfo]:
        """List locally-installed voices for this engine."""

    def status(self) -> EngineStatus:
        present = self.is_runtime_present()
        voices = self.discover_voices() if present else []
        if not present:
            reason = f"{self.display_name} runtime not installed."
        elif not voices:
            reason = f"{self.display_name} installed but no voices found."
        else:
            reason = ""
        return EngineStatus(
            engine_id=self.engine_id, display_name=self.display_name,
            runtime=self.runtime, available=present and bool(voices),
            reason=reason, capabilities=self.capabilities, voices=voices)


# ---------------------------------------------------------------------------
# Piper engine (local, non-cloning). Capabilities reflect what Piper actually
# supports: length_scale (speed) and sentence silence (pause) via config;
# no per-word emphasis/emotion, no cloning.
# ---------------------------------------------------------------------------
class PiperEngine(VoiceEngine):
    engine_id = "piper"
    display_name = "Piper"
    runtime = "piper"
    capabilities = EngineCapabilities(
        speed=True, pause=True, emphasis=False, emotion=False,
        pronunciation=True, cloning=False)

    def __init__(self, voices_dir: Optional[str | Path] = None) -> None:
        self.voices_dir = Path(voices_dir) if voices_dir else None

    def is_runtime_present(self) -> bool:
        if shutil.which("piper"):
            return True
        try:
            import piper  # noqa: F401
            return True
        except Exception:
            return False

    def discover_voices(self) -> list[VoiceInfo]:
        if not self.voices_dir or not self.voices_dir.exists():
            return []
        voices: list[VoiceInfo] = []
        for onnx in sorted(self.voices_dir.glob("*.onnx")):
            cfg_ok = onnx.with_suffix(onnx.suffix + ".json").exists()
            lang = "unknown"
            # Piper voices are usually named like en_US-amy-medium.onnx
            stem = onnx.stem
            if "_" in stem or "-" in stem:
                lang = stem.split("-")[0]
            quality = "medium"
            for q in ("low", "medium", "high", "x_low"):
                if q in stem.lower():
                    quality = q
            voices.append(VoiceInfo(
                name=onnx.name, path=str(onnx), language=lang,
                quality=quality, license="unreviewed (verify voice terms)",
                license_ok=False, local=True))
            if not cfg_ok:
                voices[-1].license = "missing .onnx.json config"
        return voices


# ---------------------------------------------------------------------------
# XTTS-v2 cloning engine — DISABLED by default. The roadmap warns its license
# is non-commercial; cloning also requires authorization (see cloning.py).
# This engine reports its capabilities honestly but never runs without an
# explicit approval record.
# ---------------------------------------------------------------------------
class XTTSCloningEngine(VoiceEngine):
    engine_id = "xtts_v2"
    display_name = "XTTS-v2 (cloning)"
    runtime = "coqui_tts"
    capabilities = EngineCapabilities(
        speed=True, pause=False, emphasis=False, emotion=True,
        pronunciation=False, cloning=True)

    def is_runtime_present(self) -> bool:
        try:
            import TTS  # noqa: F401  (coqui-tts)
            return True
        except Exception:
            return False

    def discover_voices(self) -> list[VoiceInfo]:
        # Cloning voices are reference samples + authorization; they are not
        # discovered as plain files here. Managed via cloning.py.
        return []

    def status(self) -> EngineStatus:
        st = super().status()
        # Even if present, flag the licensing gate loudly.
        st.reason = (st.reason or "") + (
            " License is non-commercial (XTTS-v2); cloning is blocked without "
            "an approved authorization record.")
        return st
