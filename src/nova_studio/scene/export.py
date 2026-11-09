"""Export the scene as one MP4: clips with their own sound, gaps as stills.

Every cut is rendered to the same size, frame rate and audio format, then
joined. A clip's sound is kept; a still or card gets silence (never a
stand-in voice). The result only counts if FFprobe finds video and audio.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Optional

from ..media.probe import ffmpeg_path, probe
from .sequence import CARD, CLIP, ResolvedCut, total_s

CARD_COLOR = "0x1d1f26"


@dataclass
class SceneExport:
    ok: bool
    path: str = ""
    duration_s: float = 0.0
    message: str = ""
    gaps: list[str] = field(default_factory=list)   # shot ids without a clip


def _run(args: list[str]) -> None:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=1800,
                          stdin=subprocess.DEVNULL,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                          if sys.platform == "win32" else 0)
    if proc.returncode != 0:
        raise RuntimeError("FFmpeg failed: " + (proc.stderr or "").strip()[-400:])


def _segment(c: ResolvedCut, out: Path, w: int, h: int, fps: int, ff: str) -> None:
    dur = f"{c.duration_s:.3f}"
    fit = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
           f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p")
    silence = ["-f", "lavfi", "-t", dur, "-i",
               "anullsrc=channel_layout=stereo:sample_rate=48000"]
    if c.kind == CLIP:
        args = [ff, "-y", "-ss", f"{c.in_s:.3f}", "-t", dur, "-i", c.source]
        if c.has_audio:
            args += ["-vf", fit, "-af", "aresample=48000,aformat=channel_layouts=stereo,apad",
                     "-map", "0:v:0", "-map", "0:a:0"]
        else:
            args += silence + ["-vf", fit, "-map", "0:v:0", "-map", "1:a:0"]
    elif c.kind == CARD:
        args = [ff, "-y", "-f", "lavfi", "-t", dur, "-i",
                f"color=c={CARD_COLOR}:s={w}x{h}:r={fps}"] + silence + [
                "-vf", "setsar=1,format=yuv420p", "-map", "0:v:0", "-map", "1:a:0"]
    else:
        args = [ff, "-y", "-loop", "1", "-framerate", str(fps), "-t", dur,
                "-i", c.source] + silence + ["-vf", fit, "-map", "0:v:0", "-map", "1:a:0"]
    args += ["-t", dur, "-c:v", "libx264", "-preset", "veryfast", "-r", str(fps),
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(out)]
    _run(args)


def export_scene(cuts: list[ResolvedCut], out_path: Path, width: int = 1280,
                 height: int = 720, fps: int = 24,
                 progress: Optional[Callable[[str], None]] = None) -> SceneExport:
    say = progress or (lambda _m: None)
    if not cuts:
        return SceneExport(False, message="There are no shots in the scene.")
    gaps = [c.shot_id for c in cuts if c.kind != CLIP]
    if len(gaps) == len(cuts):
        return SceneExport(False, gaps=gaps, message=(
            "No shot has a chosen clip yet. Choose versions on the Generate "
            "screen, or export the animatic from the Script tab instead."))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        ff = ffmpeg_path()
        with tempfile.TemporaryDirectory(prefix="nova_scene_") as td:
            tmp = Path(td)
            parts = []
            for i, c in enumerate(cuts):
                say(f"Preparing shot {i + 1} of {len(cuts)}")
                if c.kind == CLIP:
                    # Trust the file, not the record: map sound only if the
                    # clip really has an audio stream.
                    info = probe(c.source)
                    if not info.ok or not info.has_video:
                        raise RuntimeError(f"Shot {c.shot_id}'s clip can't be read: "
                                           f"{info.error or 'no video stream'}")
                    c = replace(c, has_audio=info.has_audio)
                seg = tmp / f"cut_{i:03d}.mp4"
                _segment(c, seg, width, height, fps, ff)
                parts.append(seg)
            say("Joining shots")
            lst = tmp / "list.txt"
            lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts),
                           encoding="utf-8")
            part = out_path.with_suffix(".part.mp4")
            _run([ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                  "-c", "copy", "-movflags", "+faststart", str(part)])
    except (RuntimeError, OSError) as exc:
        return SceneExport(False, gaps=gaps, message=str(exc))
    info = probe(part)
    if not info.ok or not info.has_video or not info.has_audio:
        part.unlink(missing_ok=True)
        return SceneExport(False, gaps=gaps, message="The exported file failed "
                           "validation: " + (info.error or "missing video or audio"))
    part.replace(out_path)
    msg = f"Exported {info.duration_s or total_s(cuts):.1f} s."
    if gaps:
        msg += (f" {len(gaps)} shot(s) have no clip yet and show a still or card: "
                + ", ".join(gaps) + ".")
    return SceneExport(True, str(out_path), info.duration_s or 0.0, msg, gaps)
