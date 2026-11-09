"""Local video engine: LTX-Video 2B on the CPU through OpenVINO.

Personal, non-commercial preview only: the LTX-Video 2B v0.9 weights are
under a RAIL-M licence whose permitted purpose is academic and research use.
Measured on an i5-12400 (INT8, 10 steps): about 1 s of 512x320 video per
minute; faces are soft. It is a motion preview, not a final shot.

It never runs silently: status() is unavailable (with the reason) until the
user switches the experimental preview on in Setup & diagnostics and both
the OpenVINO GenAI runtime and converted weights are installed. Same
interface as GeminiOmniEngine so the Generate screen can use either.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

from ..performance.engines import (EngineCapabilities, EngineSpec, EngineStatus,
                                   IdentityPreservation, Role)
from .gemini_omni import OmniError, OmniRequest, OmniTake

ENGINE_ID = "ltx-video-local"
VIDEO_SUBDIR = "video"
FPS = 24
# LTX needs frame counts of the form 8k+1 and sides divisible by 32.
SIZES = {"16:9": (512, 288), "9:16": (288, 512)}
MIN_FRAMES, MAX_FRAMES = 9, 49
DEFAULT_STEPS = 20
LICENCE_NOTE = ("Personal, non-commercial preview: LTX-Video 2B v0.9 weights are "
                "RAIL-M licensed for research use.")

CAPABILITIES = EngineCapabilities(
    image_generation=False,
    video_generation=True,
    native_audio=False,
    speech_synthesis=False,
    lip_sync=False,
    emotion_control=False,
    head_motion_control=False,
    multi_speaker_in_one_shot=False,
    max_reference_images=0,          # text-to-video only in this build
    identity_preservation=IdentityPreservation.NONE,
    start_end_frames=False,
    min_duration_s=round(MIN_FRAMES / FPS, 2),
    max_duration_s=round(MAX_FRAMES / FPS, 2),
    aspect_ratios=tuple(SIZES),
    languages=("en",),
    produces_placeholders=False,
    is_cloud=False,
)


def find_weights(models_dir: str | Path) -> Optional[Path]:
    """An OpenVINO-converted LTX-Video pipeline folder under models/video."""
    root = Path(models_dir) / VIDEO_SUBDIR
    if not root.is_dir():
        return None
    for index in sorted(root.glob("*/model_index.json")):
        try:
            cls = json.loads(index.read_text(encoding="utf-8")).get("_class_name", "")
        except (OSError, ValueError):
            continue
        folder = index.parent
        if cls.startswith("LTX") and (folder / "transformer").is_dir():
            return folder
    return None


def runtime_available() -> bool:
    try:
        import openvino_genai  # noqa: F401
        return hasattr(openvino_genai, "Text2VideoPipeline")
    except Exception:
        return False


def frames_for(duration_s: Optional[float]) -> int:
    """Nearest valid LTX frame count (8k+1) for a duration, clamped."""
    want = (duration_s or 1.0) * FPS
    k = max(1, round((want - 1) / 8))
    return max(MIN_FRAMES, min(MAX_FRAMES, 8 * k + 1))


class LtxLocalEngine:
    resolutions = ("288p",)
    model = "LTX-Video 2B (INT8, CPU)"

    def __init__(self, weights_dir: Optional[Path],
                 preview_enabled: Callable[[], bool],
                 runtime_ok: Callable[[], bool] = runtime_available,
                 device: str = "CPU", steps: int = DEFAULT_STEPS,
                 pipeline_factory: Optional[Callable[[str, str], object]] = None,
                 probe: Optional[Callable] = None,
                 ffmpeg: Optional[Callable[[], str]] = None) -> None:
        self.weights_dir = Path(weights_dir) if weights_dir else None
        self._enabled = preview_enabled
        self._runtime_ok = runtime_ok
        self.device = device
        self.steps = steps
        self._factory = pipeline_factory
        self._probe = probe
        self._ffmpeg = ffmpeg
        self._pipe = None
        self._lock = threading.Lock()

    # -- availability --------------------------------------------------------
    def status(self) -> EngineStatus:
        if not self._enabled():
            return EngineStatus(False, "Switch on 'Experimental local video preview' in "
                                       "Setup & diagnostics. " + LICENCE_NOTE)
        if not self._runtime_ok():
            return EngineStatus(False, "The OpenVINO GenAI runtime is not installed in this NOVA build.")
        if self.weights_dir is None or not (self.weights_dir / "model_index.json").is_file():
            return EngineStatus(False, "No converted LTX-Video weights in models/video.")
        return EngineStatus(True)

    def spec(self) -> EngineSpec:
        return EngineSpec(
            id=ENGINE_ID, name="LTX-Video local preview (this PC)",
            roles=frozenset({Role.VIDEO}), capabilities=CAPABILITIES,
            description=("Text-to-video on this PC's CPU, no internet. About 1 s of "
                         "512x288 per minute; soft detail, no sound. " + LICENCE_NOTE),
            status_fn=self.status)

    # -- generation ------------------------------------------------------------
    def _pipeline(self):
        with self._lock:
            if self._pipe is None:
                if self._factory is not None:
                    self._pipe = self._factory(str(self.weights_dir), self.device)
                else:
                    import openvino_genai as g  # type: ignore
                    self._pipe = g.Text2VideoPipeline(str(self.weights_dir), self.device)
            return self._pipe

    def generate(self, req: OmniRequest, out_path: Path,
                 on_progress: Optional[Callable[[str], None]] = None) -> OmniTake:
        st = self.status()
        if not st.available:
            raise OmniError(st.reason)
        say = on_progress or (lambda _m: None)
        if not req.prompt.strip():
            raise OmniError("The shot has no prompt.")
        if req.images:
            raise OmniError("The local preview makes video from text only; it cannot "
                            "use reference images or start/end frames.")
        if req.aspect_ratio not in SIZES:
            raise OmniError(f"Aspect ratio {req.aspect_ratio} is not supported locally "
                            f"(use {' or '.join(SIZES)}).")
        if req.resolution and req.resolution not in self.resolutions:
            raise OmniError(f"The local preview renders {self.resolutions[0]} only.")
        w, h = SIZES[req.aspect_ratio]
        n = frames_for(req.duration_s)
        say(f"Loading LTX-Video on this PC ({self.device})")
        pipe = self._pipeline()
        say(f"Generating {n} frames at {w}x{h} ({self.steps} steps; this takes minutes)")
        try:
            res = pipe.generate(req.prompt, width=w, height=h, num_frames=n,
                                num_inference_steps=self.steps, guidance_scale=3.0,
                                frame_rate=FPS,
                                negative_prompt="worst quality, blurry, jittery, distorted")
        except Exception as exc:
            raise OmniError(f"Local generation failed: {type(exc).__name__}: {exc}") from None
        say("Encoding the take")
        import numpy as np
        frames = np.asarray(res.video.data)[0]          # (frames, H, W, 3) uint8 RGB
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        self._encode(frames, out_path)
        return self._verify(out_path, req.duration_s)

    def _encode(self, frames, out_path: Path) -> None:
        ff = self._ffmpeg() if self._ffmpeg else None
        if ff is None:
            from ..media.probe import ffmpeg_path
            ff = ffmpeg_path()
        n, h, w = frames.shape[:3]
        proc = subprocess.run(
            [ff, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
             "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-crf", "18", str(out_path)],
            input=frames.tobytes(), capture_output=True, timeout=300,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0)
        if proc.returncode != 0:
            out_path.unlink(missing_ok=True)
            raise OmniError("Encoding the take failed: "
                            + proc.stderr.decode(errors="replace").strip()[-300:])

    def _verify(self, path: Path, requested: Optional[float]) -> OmniTake:
        if not path.exists() or path.stat().st_size == 0:
            raise OmniError("No video was written.")
        probe_fn = self._probe
        if probe_fn is None:
            from ..media.probe import probe as probe_fn  # type: ignore[assignment]
        info = probe_fn(path)
        if not getattr(info, "ok", False) or not getattr(info, "has_video", False):
            path.unlink(missing_ok=True)
            raise OmniError("The local take is not a playable video: "
                            f"{getattr(info, 'error', '') or 'no video stream'}.")
        return OmniTake(path=path, interaction_id="", duration_s=info.duration_s,
                        has_audio=info.has_audio, width=info.width, height=info.height,
                        requested_duration_s=requested, watermark="", model=self.model)


def engine_for_studio(studio) -> Optional[LtxLocalEngine]:
    """The local engine when its runtime and weights are installed, else None."""
    from ..settings import load_settings
    if not runtime_available():
        return None
    weights = find_weights(studio.config.paths.models)
    if weights is None:
        return None
    ws = studio.config.paths.workspace
    return LtxLocalEngine(
        weights,
        preview_enabled=lambda: load_settings(ws).local_video.experimental_preview_enabled)
