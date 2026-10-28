"""Output validation (roadmap DoD: never label 'generated successfully'
unless output files exist and pass validation)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .probe import probe


@dataclass
class ValidationReport:
    ok: bool
    reasons: list[str]
    duration_s: float = 0.0
    width: int = 0
    height: int = 0
    has_audio: bool = False


def validate_output(path: str, expect_audio: bool = False,
                    min_duration_s: float = 0.5) -> ValidationReport:
    reasons: list[str] = []
    p = Path(path)
    if not p.exists():
        return ValidationReport(False, ["Output file does not exist."])
    if p.stat().st_size == 0:
        return ValidationReport(False, ["Output file is empty."])

    info = probe(p)
    if not info.ok:
        return ValidationReport(False, [f"Probe failed: {info.error}"])
    if not info.has_video:
        reasons.append("No video stream in output.")
    if (info.duration_s or 0) < min_duration_s:
        reasons.append(f"Duration {info.duration_s}s below minimum "
                       f"{min_duration_s}s.")
    if expect_audio and not info.has_audio:
        reasons.append("Expected audio but none present.")

    return ValidationReport(
        ok=not reasons, reasons=reasons,
        duration_s=info.duration_s or 0.0,
        width=info.width or 0, height=info.height or 0,
        has_audio=info.has_audio,
    )
