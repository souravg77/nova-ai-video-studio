"""Image-generation adapter (roadmap: benchmark-gated, experimental).

On the target Intel-iGPU PC this is experimental at best. The adapter never
auto-downloads gigabytes of weights and never claims an image was produced
unless a file exists.
"""
from __future__ import annotations

import threading
from typing import Optional

from .base import AdapterResult, Availability, AIAdapter


class ImageGenAdapter(AIAdapter):
    capability = "image"
    runtime = "none"

    def __init__(self, model_path: Optional[str] = None) -> None:
        self.model_path = model_path

    def availability(self) -> Availability:
        # Image generation on shared-memory iGPU is experimental. We require
        # an explicitly installed, approved runtime+model. None ships by
        # default, so this reports Unavailable honestly.
        try:
            import torch  # noqa: F401
        except Exception:
            return Availability(
                False,
                "No image-generation runtime installed. This capability is "
                "experimental on integrated graphics and is disabled until an "
                "approved lightweight model passes its benchmark.",
                runtime=self.runtime)
        if not self.model_path:
            return Availability(
                False,
                "No approved image model configured. Image generation stays "
                "experimental/disabled until one is added and benchmarked.",
                runtime="torch")
        return Availability(True, runtime="torch")

    def run(self, params: dict, cancel: Optional[threading.Event] = None) -> AdapterResult:
        avail = self.availability()
        if not avail.available:
            return AdapterResult(False, message=avail.reason)
        return AdapterResult(
            False,
            message="Image generation is gated behind a passing benchmark and "
                    "license approval; no image was produced.")
