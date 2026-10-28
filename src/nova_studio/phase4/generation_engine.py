"""Talking-head generation engine interface + capability gates (Phase 4, P4.3).

Describes talking-head engines (SadTalker, Wav2Lip, etc.), their supported
features, licenses and hardware requirements, and — critically — GATES
generation against the real machine before any job runs.

On the current Intel-iGPU target, generation is UNSUPPORTED and reported as
such with the exact blocker. No fake clip is ever produced. This mirrors the
honesty model already used in core/capability.py for video generation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from ..models.hardware_report import HardwareReport


class GenEngineFeature(str, Enum):
    LIP_SYNC = "lip_sync"
    HEAD_MOTION = "head_motion"
    BLINK = "blink"
    EXPRESSION = "expression"


class GenVerdict(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED_ON_THIS_PC = "unsupported_on_this_pc"
    BLOCKED_BY_LICENSE = "blocked_by_license"
    NOT_INSTALLED = "not_installed"


@dataclass
class GenEngineSpec:
    engine_id: str
    display_name: str
    runtime: str                     # cuda | onnx | ...
    features: set[GenEngineFeature]
    requires_cuda: bool = True
    min_vram_mb: int = 0
    min_ram_mb: int = 0
    license: str = "unreviewed"
    commercial_ok: bool = False


@dataclass
class GenDecision:
    verdict: GenVerdict
    engine_id: str
    blocker: str = ""
    suggested_fallback: str = ""
    missing_features: list[str] = field(default_factory=list)

    @property
    def can_attempt(self) -> bool:
        return self.verdict == GenVerdict.SUPPORTED


# Candidate engines. None ships enabled/approved by default (roadmap: P5 — most
# demanding; require benchmark, quality checks and license approval).
def default_gen_engines() -> list[GenEngineSpec]:
    return [
        GenEngineSpec(
            engine_id="sadtalker", display_name="SadTalker",
            runtime="cuda",
            features={GenEngineFeature.LIP_SYNC, GenEngineFeature.HEAD_MOTION,
                      GenEngineFeature.BLINK, GenEngineFeature.EXPRESSION},
            requires_cuda=True, min_vram_mb=6144, min_ram_mb=8192,
            license="Not cleared for commercial use", commercial_ok=False),
        GenEngineSpec(
            engine_id="wav2lip", display_name="Wav2Lip",
            runtime="cuda",
            features={GenEngineFeature.LIP_SYNC},
            requires_cuda=True, min_vram_mb=4096, min_ram_mb=8192,
            license="Not cleared for commercial use", commercial_ok=False),
    ]


def _fallback() -> str:
    return ("Export a video from the prepared still photos with narration and "
            "subtitles (Ken Burns motion), or run talking-head generation "
            "later on a PC with a compatible NVIDIA GPU.")


def evaluate_generation(engine: Optional[GenEngineSpec],
                        report: HardwareReport,
                        installed: bool,
                        commercial_use: bool = False) -> GenDecision:
    """Decide whether talking-head generation may run. Blocks honestly."""
    if engine is None:
        return GenDecision(
            GenVerdict.NOT_INSTALLED, "(none)",
            blocker="No talking-head generation engine is configured.",
            suggested_fallback=_fallback())

    # License gate first.
    if commercial_use and not engine.commercial_ok:
        return GenDecision(
            GenVerdict.BLOCKED_BY_LICENSE, engine.engine_id,
            blocker=f"'{engine.display_name}' is not cleared for commercial "
                    f"use ({engine.license}). Blocked.",
            suggested_fallback=_fallback())

    if not installed:
        return GenDecision(
            GenVerdict.NOT_INSTALLED, engine.engine_id,
            blocker=f"'{engine.display_name}' is not installed. Add its "
                    f"approved weights and runtime first (nothing is "
                    f"downloaded automatically).",
            suggested_fallback=_fallback())

    # Hardware gate — measured, not advertised.
    if engine.requires_cuda and not report.has_nvidia_cuda:
        return GenDecision(
            GenVerdict.UNSUPPORTED_ON_THIS_PC, engine.engine_id,
            blocker=f"'{engine.display_name}' requires a confirmed NVIDIA CUDA "
                    f"GPU. The installed Intel integrated GPU does not meet "
                    f"this model's tested requirements. No talking-head clip "
                    f"will be generated.",
            suggested_fallback=_fallback())
    if engine.min_vram_mb > 0:
        vram = report.max_dedicated_vram_mb
        if vram < engine.min_vram_mb:
            return GenDecision(
                GenVerdict.UNSUPPORTED_ON_THIS_PC, engine.engine_id,
                blocker=f"'{engine.display_name}' needs {engine.min_vram_mb} MB "
                        f"dedicated VRAM; measured {vram} MB. Intel shared "
                        f"memory does not count as VRAM.",
                suggested_fallback=_fallback())
    if engine.min_ram_mb > report.physical_ram_mb:
        return GenDecision(
            GenVerdict.UNSUPPORTED_ON_THIS_PC, engine.engine_id,
            blocker=f"'{engine.display_name}' needs {engine.min_ram_mb} MB RAM; "
                    f"installed {report.physical_ram_mb} MB.",
            suggested_fallback=_fallback())

    return GenDecision(GenVerdict.SUPPORTED, engine.engine_id)


class GenerationEngineRegistry:
    def __init__(self, report: HardwareReport,
                 engines: Optional[list[GenEngineSpec]] = None,
                 installed_ids: Optional[set[str]] = None) -> None:
        self.report = report
        self.engines = engines or default_gen_engines()
        self.installed_ids = installed_ids or set()

    def engine(self, engine_id: str) -> Optional[GenEngineSpec]:
        return next((e for e in self.engines if e.engine_id == engine_id), None)

    def decide(self, engine_id: str, commercial_use: bool = False) -> GenDecision:
        eng = self.engine(engine_id)
        return evaluate_generation(
            eng, self.report, installed=engine_id in self.installed_ids,
            commercial_use=commercial_use)

    def status_report(self) -> list[dict]:
        out = []
        for e in self.engines:
            d = self.decide(e.engine_id)
            out.append({
                "engine_id": e.engine_id, "name": e.display_name,
                "features": sorted(f.value for f in e.features),
                "requires_cuda": e.requires_cuda,
                "min_vram_mb": e.min_vram_mb,
                "installed": e.engine_id in self.installed_ids,
                "verdict": d.verdict.value, "blocker": d.blocker,
            })
        return out
