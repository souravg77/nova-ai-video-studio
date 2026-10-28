"""AI adapter interfaces (roadmap section 5).

One adapter per runtime/model. Each declares:
  * availability (is the runtime importable + model present?),
  * a short self-benchmark, and
  * the actual operation.

Adapters NEVER claim success they cannot prove. When a dependency or model is
missing they report Unavailable with a reason — the capability manager turns
that into an honest GenerationState.
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Availability:
    available: bool
    reason: str = ""
    runtime: str = ""
    model_name: str = ""


@dataclass
class AdapterResult:
    ok: bool
    outputs: list[str] = field(default_factory=list)
    text: str = ""
    message: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)


class AIAdapter(ABC):
    capability: str = "unknown"
    runtime: str = "none"

    @abstractmethod
    def availability(self) -> Availability:
        """Check — without side effects — whether this adapter can run."""

    @abstractmethod
    def run(self, params: dict, cancel: Optional[threading.Event] = None) -> AdapterResult:
        """Perform the operation. Must not claim success without real output."""

    def self_benchmark(self, params: dict) -> AdapterResult:
        """Default: a single timed run. Subclasses may override with fixtures."""
        return self.run(params)
