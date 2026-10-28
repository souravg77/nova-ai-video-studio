"""Benchmark record model (roadmap section 3)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BenchmarkOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIPPED = "skipped"
    ERROR = "error"


class BenchmarkResult(BaseModel):
    id: str = Field(default_factory=_uid)
    capability: str          # 'script' | 'tts' | 'stt' | 'render' | 'image' ...
    model_name: str = ""
    model_hash: str = ""
    model_version: str = ""
    runtime: str = ""        # 'ffmpeg' | 'openvino-cpu' | 'cuda' ...
    backend_path: str = "cpu"  # cpu | intel-gpu | cuda

    outcome: BenchmarkOutcome = BenchmarkOutcome.SKIPPED
    # Metrics (roadmap section 3 benchmark rules).
    median_runtime_s: Optional[float] = None
    runs: list[float] = Field(default_factory=list)
    peak_ram_mb: Optional[int] = None
    idle_ram_mb: Optional[int] = None
    tokens_per_s: Optional[float] = None
    real_time_factor: Optional[float] = None

    settings: dict = Field(default_factory=dict)
    driver_version: str = ""
    evidence: str = ""       # what proved pass/fail (valid JSON, A/V sync, ...)
    collected_at: str = Field(default_factory=_now)

    @property
    def passed(self) -> bool:
        return self.outcome == BenchmarkOutcome.PASS
