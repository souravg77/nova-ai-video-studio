"""Job model with honest lifecycle + generation states.

The GenerationState enum encodes roadmap section 8 verbatim: the app must be
able to say *why* something cannot be done, before spending resources.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobState(str, Enum):
    """Queue lifecycle (roadmap section 7, milestone 4)."""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GenerationState(str, Enum):
    """Honest capability states for a generation job (roadmap section 8).

    These are the ONLY truthful answers the app may give about whether a
    requested output can be produced.
    """
    SUPPORTED = "supported"
    SUPPORTED_WITH_LIMITS = "supported_with_limits"
    EXPERIMENTAL = "experimental"
    UNSUPPORTED_ON_THIS_PC = "unsupported_on_this_pc"
    BLOCKED_BY_LICENSE = "blocked_by_license"
    FAILED_AT_RUNTIME = "failed_at_runtime"
    COMPLETED_AND_VALIDATED = "completed_and_validated"


class JobKind(str, Enum):
    RENDER = "render"             # FFmpeg assembly/export (Tier 0, always)
    SCRIPT = "script"            # LLM script generation
    TTS = "tts"
    STT = "stt"
    IMAGE_GEN = "image_gen"
    FACE_ANIM = "face_anim"
    VIDEO_GEN = "video_gen"
    BENCHMARK = "benchmark"
    # P2: script -> narration -> render, chained and verified end to end.
    AUTO_VIDEO = "auto_video"
    # P4.6: three approved photos -> narration -> subtitles -> validated MP4.
    PHOTO_VIDEO = "photo_video"


class JobLogEntry(BaseModel):
    at: str = Field(default_factory=_now)
    level: str = "info"
    message: str


class Job(BaseModel):
    id: str = Field(default_factory=_uid)
    project_id: Optional[str] = None
    kind: JobKind
    state: JobState = JobState.QUEUED

    # For generation-type jobs, the honest capability verdict.
    generation_state: Optional[GenerationState] = None
    # Human-readable blocker + suggested fallback shown to the user.
    blocker: str = ""
    suggested_fallback: str = ""

    progress: float = 0.0  # 0..1
    created_at: str = Field(default_factory=_now)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    params: dict[str, Any] = Field(default_factory=dict)
    # Output artifacts actually produced (paths). A job is only
    # COMPLETED_AND_VALIDATED when these exist and pass checks.
    outputs: list[str] = Field(default_factory=list)
    logs: list[JobLogEntry] = Field(default_factory=list)

    def log(self, message: str, level: str = "info") -> None:
        self.logs.append(JobLogEntry(level=level, message=message))

    def mark_running(self) -> None:
        self.state = JobState.RUNNING
        self.started_at = _now()

    def mark_completed(self, validated: bool) -> None:
        self.state = JobState.COMPLETED
        self.finished_at = _now()
        self.progress = 1.0
        if validated:
            self.generation_state = GenerationState.COMPLETED_AND_VALIDATED

    def mark_failed(self, reason: str) -> None:
        self.state = JobState.FAILED
        self.finished_at = _now()
        self.blocker = reason
        if self.kind in (JobKind.IMAGE_GEN, JobKind.FACE_ANIM, JobKind.VIDEO_GEN):
            self.generation_state = GenerationState.FAILED_AT_RUNTIME
        self.log(reason, level="error")

    def mark_cancelled(self) -> None:
        self.state = JobState.CANCELLED
        self.finished_at = _now()
