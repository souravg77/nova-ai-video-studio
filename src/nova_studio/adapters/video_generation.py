"""Talking-head / text-to-video adapter (roadmap: most demanding, P5).

This is the capability the roadmap is most emphatic about NOT faking. On the
current target hardware it is Unsupported. The adapter's run() returns the
honest failure report and the suggested fallbacks — it NEVER returns a fake
'generated' clip.
"""
from __future__ import annotations

import threading
from typing import Optional

from .base import AdapterResult, Availability, AIAdapter


class VideoGenAdapter(AIAdapter):
    capability = "video"
    runtime = "cuda"

    def __init__(self, model_path: Optional[str] = None) -> None:
        self.model_path = model_path

    def availability(self) -> Availability:
        try:
            import torch  # type: ignore
            cuda = torch.cuda.is_available()
        except Exception:
            cuda = False
        if not cuda:
            return Availability(
                False,
                "Photorealistic AI text/image-to-video requires a confirmed "
                "CUDA GPU with sufficient measured VRAM. The installed Intel "
                "integrated GPU does not meet this model's tested "
                "requirements. No AI video clip will be generated.",
                runtime=self.runtime)
        if not self.model_path:
            return Availability(
                False,
                "No approved video model configured. Capability remains "
                "unsupported until a licensed model passes its benchmark.",
                runtime="cuda")
        return Availability(True, runtime="cuda")

    def run(self, params: dict, cancel: Optional[threading.Event] = None) -> AdapterResult:
        avail = self.availability()
        return AdapterResult(
            False,
            message=avail.reason or
            "AI video generation is not supported on this PC. No clip was "
            "generated. You can export using imported footage, create a "
            "motion-animated still, or retry with a smaller compatible "
            "model/settings.")
