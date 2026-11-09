"""Save one frame of a clip as an image (e.g. the next shot's start frame)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..media.probe import ffmpeg_path


def save_frame(video: Path, at_s: float, out_png: Path) -> Path:
    """Extract the frame at ``at_s`` seconds. Raises ValueError on failure."""
    video, out_png = Path(video), Path(out_png)
    if not video.is_file():
        raise ValueError(f"The clip is missing: {video}")
    out_png.parent.mkdir(parents=True, exist_ok=True)
    out_png.unlink(missing_ok=True)
    try:
        proc = subprocess.run(
            [ffmpeg_path(), "-y", "-v", "error", "-ss", f"{max(at_s, 0.0):.3f}",
             "-i", str(video), "-frames:v", "1", str(out_png)],
            capture_output=True, text=True, timeout=120)
    except Exception as exc:
        raise ValueError(f"Could not run FFmpeg: {exc}") from None
    if proc.returncode != 0 or not out_png.is_file() or out_png.stat().st_size == 0:
        out_png.unlink(missing_ok=True)
        raise ValueError("No frame could be read at that time"
                         + (f": {proc.stderr.strip()[:200]}" if proc.stderr.strip() else "."))
    return out_png
