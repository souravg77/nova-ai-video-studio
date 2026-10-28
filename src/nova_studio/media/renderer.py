"""FFmpeg renderer (roadmap sections 1, 7-milestone-6, 10-P1).

The primary supported workflow on ANY tier: assemble imported footage/images
into a finished, validated MP4 with narration, burned-in captions and music.
No AI model is required. This is what lets the app produce a useful video on
the target Intel-iGPU PC even without generative AI.

Design choices for reliability over a shared-memory CPU machine:
  * libx264, yuv420p, faststart — universally playable output.
  * Still images get a Ken Burns (pan/zoom) motion effect via zoompan.
  * Captions are drawn with drawtext (escaped) so no external .ass is needed.
  * Every stage uses explicit argument lists (no shell string interpolation).
"""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .probe import ffmpeg_path, probe


@dataclass
class SceneSpec:
    """One timeline segment to render."""
    kind: str                      # 'image' | 'video' | 'color'
    source: Optional[str] = None   # path for image/video; None for color
    duration_s: float = 5.0
    caption: str = ""
    motion: Optional[str] = None   # 'kenburns' for images
    color: str = "black"           # for 'color' kind


@dataclass
class RenderSpec:
    scenes: list[SceneSpec]
    width: int = 1920
    height: int = 1080
    fps: int = 30
    narration_path: Optional[str] = None
    music_path: Optional[str] = None
    music_volume: float = 0.18     # ducked under narration
    output_path: str = "output.mp4"
    # x264 preset. 'medium' for quality; 'veryfast'/'ultrafast' when the
    # capability manager reports a weak CPU (Balanced profile).
    preset: str = "medium"
    # Optional SRT subtitle file (Phase 3). When set, it is muxed into the MP4
    # as a soft subtitle track (mov_text) so it travels with the video.
    subtitle_srt_path: Optional[str] = None


@dataclass
class RenderResult:
    ok: bool
    output_path: str
    duration_s: float = 0.0
    width: int = 0
    height: int = 0
    av_sync_ok: bool = False
    message: str = ""
    log_tail: str = ""


def _esc_drawtext(text: str) -> str:
    """Escape text for ffmpeg drawtext."""
    if not text:
        return ""
    # Order matters: backslash first.
    text = text.replace("\\", "\\\\")
    text = text.replace(":", "\\:").replace("'", "’")
    text = text.replace("%", "\\%")
    return text


class Renderer:
    def __init__(self, ffmpeg: Optional[str] = None) -> None:
        self.ffmpeg = ffmpeg or ffmpeg_path()

    # ------------------------------------------------------------------
    def _caption_filter(self, caption: str, height: int) -> str:
        if not caption:
            return ""
        esc = _esc_drawtext(caption)
        fontsize = max(18, int(height * 0.045))
        # Semi-transparent box, bottom-centred — readable on any footage.
        return (
            f",drawtext=text='{esc}':fontcolor=white:fontsize={fontsize}"
            f":box=1:boxcolor=black@0.5:boxborderw=12"
            f":x=(w-text_w)/2:y=h-text_h-{int(height*0.06)}"
        )

    def _render_segment(self, scene: SceneSpec, spec: RenderSpec,
                        out: Path) -> None:
        w, h, fps = spec.width, spec.height, spec.fps
        dur = max(0.5, scene.duration_s)
        cap = self._caption_filter(scene.caption, h)
        args = [self.ffmpeg, "-y"]

        if scene.kind == "image":
            total_frames = max(1, int(round(dur * fps)))
            if scene.motion == "kenburns":
                # Slow zoom-in, centred. Feed a SINGLE still frame and let
                # zoompan synthesise exactly `total_frames` output frames.
                # (Looping the input would multiply frames per input frame and
                # blow up the clip length — a classic zoompan trap.)
                uw, uh = int(w * 1.5), int(h * 1.5)
                vf = (
                    f"scale={uw}:{uh}:force_original_aspect_ratio=increase,"
                    f"crop={uw}:{uh},"
                    f"zoompan=z='min(zoom+0.0010,1.3)':d={total_frames}:fps={fps}"
                    f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                    f":s={w}x{h},"
                    f"setsar=1{cap}"
                )
                # One input image; zoompan d= controls total output frames.
                args += ["-i", str(scene.source), "-vf", vf,
                         "-frames:v", str(total_frames)]
            else:
                vf = (
                    f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                    f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1{cap}"
                )
                args += ["-loop", "1", "-framerate", str(fps), "-t", f"{dur}",
                         "-i", str(scene.source), "-vf", vf]
        elif scene.kind == "video":
            vf = (
                f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}{cap}"
            )
            args += ["-t", f"{dur}", "-i", str(scene.source), "-vf", vf]
        else:  # color / fallback slate
            src = f"color=c={scene.color}:s={w}x{h}:r={fps}:d={dur}"
            vf = f"setsar=1{cap}" if cap else "setsar=1"
            args += ["-f", "lavfi", "-i", src, "-vf", vf]

        args += ["-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                 "-preset", spec.preset, "-r", str(fps), str(out)]
        self._run(args)

    def _run(self, args: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            tail = (proc.stderr or "").strip().splitlines()[-8:]
            raise RuntimeError("ffmpeg failed:\n" + "\n".join(tail))
        return proc

    # ------------------------------------------------------------------
    def render(self, spec: RenderSpec,
               progress: Optional[Callable[[float, str], None]] = None) -> RenderResult:
        def report(p: float, msg: str) -> None:
            if progress:
                progress(p, msg)

        if not spec.scenes:
            return RenderResult(False, spec.output_path,
                                message="No scenes to render.")

        out_path = Path(spec.output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="nova_render_") as td:
            tmp = Path(td)
            segment_files: list[Path] = []
            n = len(spec.scenes)
            try:
                for i, scene in enumerate(spec.scenes):
                    seg = tmp / f"seg_{i:03d}.mp4"
                    report(i / (n + 2), f"Rendering scene {i+1}/{n}")
                    self._render_segment(scene, spec, seg)
                    segment_files.append(seg)

                # Concatenate silent video segments.
                report(n / (n + 2), "Joining scenes")
                concat_list = tmp / "concat.txt"
                concat_list.write_text(
                    "".join(f"file '{s.as_posix()}'\n" for s in segment_files))
                silent = tmp / "joined.mp4"
                self._run([self.ffmpeg, "-y", "-f", "concat", "-safe", "0",
                           "-i", str(concat_list), "-c", "copy", str(silent)])

                # Mix audio (narration + ducked music) and mux.
                report((n + 1) / (n + 2), "Mixing audio and exporting")
                final = self._mux_audio(silent, spec, tmp, out_path)
                # Optionally mux soft subtitles (Phase 3).
                if (spec.subtitle_srt_path
                        and Path(spec.subtitle_srt_path).exists()):
                    report((n + 1.5) / (n + 2), "Adding subtitles")
                    final = self._mux_subtitles(final, spec.subtitle_srt_path,
                                                tmp, out_path)
            except RuntimeError as exc:
                return RenderResult(False, str(out_path),
                                    message=str(exc),
                                    log_tail=str(exc)[-500:])

        # Validate the output actually exists and plays (section 7 DoD).
        info = probe(final)
        if not info.ok or not info.has_video:
            return RenderResult(False, str(final),
                                message="Output failed validation: "
                                        + (info.error or "no video stream"))
        av_sync = True
        if spec.narration_path or spec.music_path:
            av_sync = info.has_audio
        report(1.0, "Done")
        return RenderResult(
            ok=True, output_path=str(final),
            duration_s=info.duration_s or 0.0,
            width=info.width or 0, height=info.height or 0,
            av_sync_ok=av_sync,
            message="Rendered and validated.",
        )

    def _mux_audio(self, silent: Path, spec: RenderSpec, tmp: Path,
                   out_path: Path) -> Path:
        has_narr = bool(spec.narration_path and Path(spec.narration_path).exists())
        has_music = bool(spec.music_path and Path(spec.music_path).exists())

        if not has_narr and not has_music:
            # No audio: add a silent track so players have consistent output.
            self._run([
                self.ffmpeg, "-y", "-i", str(silent),
                "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-c:v", "copy", "-c:a", "aac", "-shortest",
                "-movflags", "+faststart", str(out_path)])
            return out_path

        args = [self.ffmpeg, "-y", "-i", str(silent)]
        inputs = 1
        filter_parts = []
        amix_inputs = []
        if has_narr:
            args += ["-i", str(spec.narration_path)]
            filter_parts.append(f"[{inputs}:a]aresample=44100[narr]")
            amix_inputs.append("[narr]")
            inputs += 1
        if has_music:
            args += ["-i", str(spec.music_path)]
            filter_parts.append(
                f"[{inputs}:a]aresample=44100,volume={spec.music_volume}[mus]")
            amix_inputs.append("[mus]")
            inputs += 1

        if len(amix_inputs) == 1:
            filter_parts.append(f"{amix_inputs[0]}apad[aout]")
        else:
            filter_parts.append(
                "".join(amix_inputs)
                + f"amix=inputs={len(amix_inputs)}:duration=longest:dropout_transition=2[aout]")
        filter_complex = ";".join(filter_parts)

        args += [
            "-filter_complex", filter_complex,
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart", str(out_path),
        ]
        self._run(args)
        return out_path

    def _mux_subtitles(self, video: Path, srt_path: str, tmp: Path,
                       out_path: Path) -> Path:
        """Add the SRT as a soft subtitle track (mov_text) to the MP4."""
        subbed = tmp / "with_subs.mp4"
        self._run([
            self.ffmpeg, "-y", "-i", str(video), "-i", str(srt_path),
            "-map", "0", "-map", "1",
            "-c", "copy", "-c:s", "mov_text",
            "-movflags", "+faststart", str(subbed),
        ])
        # Replace the output with the subtitled version.
        subbed.replace(out_path)
        return out_path
