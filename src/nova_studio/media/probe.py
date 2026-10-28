"""Media probing via ffprobe (roadmap section 7, milestone 5).

Bad inputs are rejected with useful error messages rather than silently
accepted.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class FFmpegNotFound(RuntimeError):
    pass


def ffprobe_path() -> str:
    p = shutil.which("ffprobe")
    if not p:
        raise FFmpegNotFound(
            "ffprobe not found on PATH. Install a trusted FFmpeg build and "
            "ensure ffmpeg/ffprobe are reachable (roadmap section 6C).")
    return p


def ffmpeg_path() -> str:
    p = shutil.which("ffmpeg")
    if not p:
        raise FFmpegNotFound(
            "ffmpeg not found on PATH. Install a trusted FFmpeg build "
            "(roadmap section 6C).")
    return p


@dataclass
class MediaInfo:
    path: str
    ok: bool
    duration_s: float | None = None
    width: int | None = None
    height: int | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    has_video: bool = False
    has_audio: bool = False
    error: str = ""


def probe(path: str | Path) -> MediaInfo:
    p = Path(path)
    if not p.exists():
        return MediaInfo(path=str(p), ok=False, error="File does not exist.")
    try:
        out = subprocess.run(
            [ffprobe_path(), "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(p)],
            capture_output=True, text=True, timeout=60,
        )
    except FFmpegNotFound:
        raise
    except Exception as exc:
        return MediaInfo(path=str(p), ok=False, error=f"ffprobe failed: {exc}")

    if out.returncode != 0:
        return MediaInfo(path=str(p), ok=False,
                         error=out.stderr.strip() or "ffprobe returned error.")
    try:
        data = json.loads(out.stdout)
    except Exception as exc:
        return MediaInfo(path=str(p), ok=False, error=f"Bad ffprobe output: {exc}")

    info = MediaInfo(path=str(p), ok=True)
    fmt = data.get("format", {})
    try:
        info.duration_s = float(fmt.get("duration")) if fmt.get("duration") else None
    except (TypeError, ValueError):
        info.duration_s = None

    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not info.has_video:
            info.has_video = True
            info.video_codec = s.get("codec_name")
            info.width = s.get("width")
            info.height = s.get("height")
        elif s.get("codec_type") == "audio" and not info.has_audio:
            info.has_audio = True
            info.audio_codec = s.get("codec_name")

    if not info.has_video and not info.has_audio:
        info.ok = False
        info.error = "No video or audio streams found; unsupported input."
    return info
