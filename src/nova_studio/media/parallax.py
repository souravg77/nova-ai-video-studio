"""2.5D camera moves: a still image becomes a short shot with parallax.

A depth map (1 = near, 0 = far) drives how far each pixel moves, so near
things shift more than the background, unlike a flat Ken Burns zoom. Runs
on the CPU with NumPy/OpenCV and pipes frames straight into FFmpeg.

Depth sources, reported honestly in every result:
* ``DepthAnythingOnnx`` - a real monocular depth model (Depth Anything V2
  Small, ONNX), used when onnxruntime and the model file are installed;
* ``ApproximateDepth`` - no model: assumes the bottom of the frame is near
  and the top far. Gentle, plausible for most shots, but not measured.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

import numpy as np

MOVES = ("push_in", "pull_out", "truck_left", "truck_right", "orbit")


class DepthSource(Protocol):
    name: str
    measured: bool

    def depth(self, rgb: np.ndarray) -> np.ndarray: ...


class ApproximateDepth:
    """No depth model: bottom of frame near, top far, centre slightly nearer."""

    name = "approximate (no depth model installed)"
    measured = False

    def depth(self, rgb: np.ndarray) -> np.ndarray:
        h, w = rgb.shape[:2]
        y = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
        x = np.linspace(-1.0, 1.0, w, dtype=np.float32)[None, :]
        d = 0.15 + 0.7 * y + 0.15 * (1.0 - x * x)
        return np.clip(d / d.max(), 0.0, 1.0)


class DepthAnythingOnnx:
    """Depth Anything V2 Small (Apache-2.0) via onnxruntime on the CPU."""

    name = "Depth Anything V2 Small (measured)"
    measured = True
    SIZE = 518

    def __init__(self, model_path: str | Path) -> None:
        import onnxruntime as ort  # type: ignore
        self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0].name

    def depth(self, rgb: np.ndarray) -> np.ndarray:
        import cv2
        h, w = rgb.shape[:2]
        # As the model's preprocessor: keep the aspect ratio, short side ~518,
        # both sides a multiple of 14 (the ViT patch size).
        s = self.SIZE / min(h, w)
        nh, nw = (max(14, int(round(v * s / 14)) * 14) for v in (h, w))
        x = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_CUBIC)
        x = (x.astype(np.float32) / 255.0 - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
        x = x.transpose(2, 0, 1)[None].astype(np.float32)
        out = np.asarray(self.session.run(None, {self.input: x})[0]).squeeze()
        out = cv2.resize(out.astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
        lo, hi = np.percentile(out, 2), np.percentile(out, 98)
        return np.clip((out - lo) / max(hi - lo, 1e-6), 0.0, 1.0)   # relative inverse depth: 1 = near


def find_depth_model(models_dir: str | Path) -> Optional[Path]:
    d = Path(models_dir) / "depth"
    found = sorted(d.glob("*.onnx")) if d.is_dir() else []
    return found[0] if found else None


def depth_source(models_dir: Optional[str | Path]) -> DepthSource:
    """The best depth source installed on this PC."""
    if models_dir:
        model = find_depth_model(models_dir)
        if model is not None:
            try:
                return DepthAnythingOnnx(model)
            except Exception:
                pass   # onnxruntime missing or the file is unusable: say so via the name
    return ApproximateDepth()


@dataclass
class MoveResult:
    ok: bool
    path: str
    frames: int = 0
    depth: str = ""
    message: str = ""


def _flow(depth: np.ndarray, move: str, t: float, strength: float) -> tuple[np.ndarray, np.ndarray]:
    """Backward map (where each output pixel samples the source) at time t in [0, 1]."""
    h, w = depth.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    d = depth
    if move in ("push_in", "pull_out"):
        tt = t if move == "push_in" else 1.0 - t
        scale = 1.0 + strength * tt * (0.35 + 0.65 * d)        # near grows faster
        return cx + (xx - cx) / scale, cy + (yy - cy) / scale
    if move in ("truck_left", "truck_right"):
        sign = 1.0 if move == "truck_left" else -1.0          # camera left: scene moves right
        shift = sign * strength * w * 0.5 * (t - 0.5) * (0.25 + 0.75 * d)
        return xx - shift, yy
    if move == "orbit":
        shift = strength * w * 0.5 * (t - 0.5) * (d - 0.5) * 2.0   # near and far move apart
        scale = 1.0 + 0.3 * strength * t
        return cx + (xx - shift - cx) / scale, cy + (yy - cy) / scale
    raise ValueError(f"unknown camera move: {move}")


def render_move(image_path: str | Path, out_path: str | Path, move: str,
                duration_s: float, ffmpeg: str, depth: Optional[DepthSource] = None,
                width: int = 1280, height: int = 720, fps: int = 24,
                strength: float = 0.12, preset: str = "veryfast") -> MoveResult:
    """Render a camera move over a still into an MP4 (no audio)."""
    import cv2
    if move not in MOVES:
        return MoveResult(False, str(out_path), message=f"Unknown camera move: {move}")
    src = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if src is None:
        return MoveResult(False, str(out_path), message=f"Cannot read image: {image_path}")
    # Fill the frame (cover), with a margin so moves never reveal an edge.
    margin = 1.0 + strength
    ih, iw = src.shape[:2]
    cover = max(width * margin / iw, height * margin / ih)
    big = cv2.resize(src, (int(round(iw * cover)), int(round(ih * cover))), interpolation=cv2.INTER_AREA)
    y0, x0 = (big.shape[0] - height) // 2, (big.shape[1] - width) // 2
    rgb = cv2.cvtColor(big, cv2.COLOR_BGR2RGB)

    depth = depth or ApproximateDepth()
    dmap = depth.depth(rgb)
    k = max(3, int(min(dmap.shape) * 0.03) | 1)
    dmap = cv2.GaussianBlur(dmap.astype(np.float32), (k, k), 0)   # soften edges: less tearing

    frames = max(1, int(round(duration_s * fps)))
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [ffmpeg, "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}",
         "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-preset", preset, str(out)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0)
    try:
        for i in range(frames):
            t = i / max(1, frames - 1)
            mx, my = _flow(dmap, move, t, strength)
            frame = cv2.remap(big, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            proc.stdin.write(np.ascontiguousarray(frame[y0:y0 + height, x0:x0 + width]).tobytes())
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="replace")
        code = proc.wait(timeout=300)
    except Exception as exc:  # broken pipe etc.
        proc.kill()
        return MoveResult(False, str(out), message=f"Camera move failed: {exc}")
    if code != 0 or not out.is_file():
        return MoveResult(False, str(out), message=f"FFmpeg failed: {err.strip()[-300:]}")
    return MoveResult(True, str(out), frames=frames, depth=depth.name)
