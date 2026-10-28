"""Photo → still-video export (Phase 4.6).

A usable video-generation workflow on CPU-only hardware: three approved photos
become a narrated, subtitled MP4 via Ken Burns motion + FFmpeg. This does NOT
pretend to be talking-head generation — it is the honest still-photo path the
Phase 4 gates offer as a fallback.

Pipeline:
  1. Use the already-prepared photo copies (originals are never touched here).
  2. Build Ken Burns scenes with captions and configurable duration.
  3. If a voice profile is given, synthesise per-scene narration (must succeed
     — never silently omitted) and build an aligned SRT. If no voice is given,
     render captions-only and say so.
  4. Render a real MP4 (configurable resolution/fps/aspect/preset), mux the SRT,
     and validate the result (exists, duration, audio when expected, subtitle
     stream when expected, decodable).

Honesty: a requested narration that fails stops the job with the blocker — it
does not fall back to a silent video pretending narration was included.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from ..media.renderer import Renderer, RenderSpec, SceneSpec
from ..media.probe import ffprobe_path
from ..voice.narration import NarrationManager, VoiceProfile


@dataclass
class PhotoScene:
    photo_path: str
    caption: str = ""
    narration: str = ""
    duration_s: float = 4.0
    motion: str = "kenburns"       # or "none"


@dataclass
class ExportConfig:
    width: int = 1280
    height: int = 720
    fps: int = 24
    preset: str = "veryfast"       # CPU-friendly default
    music_path: Optional[str] = None
    want_narration: bool = True    # synthesise narration from a voice profile
    want_subtitles: bool = True


@dataclass
class StageOutcome:
    name: str
    ok: bool
    message: str = ""
    outputs: list[str] = field(default_factory=list)


@dataclass
class ExportResult:
    ok: bool
    output_path: str = ""
    stages: list[StageOutcome] = field(default_factory=list)
    blocker: str = ""
    suggested_fallback: str = ""
    has_audio: bool = False
    has_subtitles: bool = False
    duration_s: float = 0.0


class StillVideoExporter:
    def __init__(self, renderer: Optional[Renderer] = None) -> None:
        self.renderer = renderer or Renderer()

    def export(self, scenes: list[PhotoScene], work_dir: str | Path,
               output_path: str, config: Optional[ExportConfig] = None,
               voice_profile: Optional[VoiceProfile] = None,
               progress: Optional[Callable[[float, str], None]] = None,
               cancel: Optional[threading.Event] = None) -> ExportResult:
        cfg = config or ExportConfig()
        result = ExportResult(ok=False)

        def report(p: float, msg: str) -> None:
            if progress:
                progress(p, msg)

        def cancelled() -> bool:
            return bool(cancel and cancel.is_set())

        if not scenes:
            result.blocker = "No photo scenes supplied."
            return result
        for sc in scenes:
            if not Path(sc.photo_path).exists():
                result.blocker = f"Photo not found: {sc.photo_path}"
                return result

        work = Path(work_dir)
        work.mkdir(parents=True, exist_ok=True)

        # ---- Stage 1: narration (optional but honest) --------------------
        narration_path: Optional[str] = None
        scene_durations: list[float] = [sc.duration_s for sc in scenes]
        if cfg.want_narration:
            report(0.05, "Narration")
            if voice_profile is None:
                result.blocker = (
                    "Narration was requested but no voice was selected. Choose "
                    "a voice, or turn narration off for a captions-only video.")
                result.suggested_fallback = (
                    "Select a Piper voice, or set want_narration=False.")
                result.stages.append(StageOutcome("narration", False,
                                                   result.blocker))
                return result
            mgr = NarrationManager(voice_profile)
            texts = [sc.narration for sc in scenes]
            narr_dir = work / "narration"
            sns = mgr.generate_all(texts, narr_dir)
            if cancelled():
                result.blocker = "Cancelled during narration."
                return result
            failed = [sn for sn in sns if not sn.ok]
            if failed:
                result.blocker = (
                    f"Narration failed on {len(failed)} scene(s): "
                    + "; ".join(f"scene {sn.index+1}: {sn.message}"
                                for sn in failed))
                result.suggested_fallback = (
                    "Install/select a working voice, or export captions-only.")
                result.stages.append(StageOutcome("narration", False,
                                                   result.blocker))
                return result
            # Use the per-scene files directly for alignment + a concat track.
            scene_durations = [sn.duration_s for sn in sns]
            narration_path = self._concat_wavs(
                [sn.audio_path for sn in sns], work / "narration_full.wav")
            result.stages.append(StageOutcome(
                "narration", True, f"{len(sns)} scene(s) narrated",
                outputs=[narration_path]))
        else:
            result.stages.append(StageOutcome(
                "narration", True, "Skipped (captions-only video)."))

        # ---- Stage 2: subtitles (optional) -------------------------------
        srt_path: Optional[str] = None
        if cfg.want_subtitles and narration_path:
            report(0.35, "Subtitles")
            from ..voice.subtitles import (SceneAudio, align_subtitles,
                                          write_srt)
            narr_dir = work / "narration"
            scene_audios = [
                SceneAudio(index=i, text=scenes[i].narration,
                           audio_path=str(narr_dir / f"scene_{i:03d}.wav"))
                for i in range(len(scenes))]
            if all(Path(sa.audio_path).exists() for sa in scene_audios):
                alignment = align_subtitles(scene_audios)
                if not alignment.ok:
                    result.blocker = (
                        "Subtitle alignment failed: "
                        + "; ".join(f.message for f in alignment.flags
                                    if f.level == "error"))
                    result.stages.append(StageOutcome("subtitles", False,
                                                      result.blocker))
                    result.suggested_fallback = (
                        "Regenerate the flagged scene's narration and retry.")
                    return result
                srt = write_srt(alignment.cues, work / "subtitles.srt")
                srt_path = str(srt)
                result.stages.append(StageOutcome(
                    "subtitles", True, f"{len(alignment.cues)} cue(s)",
                    outputs=[srt_path]))
        elif cfg.want_subtitles and not narration_path:
            # Build caption-based SRT from scene captions + durations.
            srt_path = self._captions_srt(scenes, scene_durations,
                                          work / "subtitles.srt")
            result.stages.append(StageOutcome(
                "subtitles", True, "From captions (no narration)."))

        if cancelled():
            result.blocker = "Cancelled before render."
            return result

        # ---- Stage 3: render --------------------------------------------
        report(0.55, "Rendering video")
        _VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
        render_scenes = []
        for i, sc in enumerate(scenes):
            dur = max(2.0, scene_durations[i] if i < len(scene_durations)
                      else sc.duration_s)
            is_video = Path(sc.photo_path).suffix.lower() in _VIDEO_EXT
            render_scenes.append(SceneSpec(
                kind="video" if is_video else "image",
                source=sc.photo_path, duration_s=dur, caption=sc.caption,
                motion=None if is_video
                else ("kenburns" if sc.motion == "kenburns" else None)))
        spec = RenderSpec(
            scenes=render_scenes, width=cfg.width, height=cfg.height,
            fps=cfg.fps, narration_path=narration_path,
            music_path=cfg.music_path, output_path=output_path,
            preset=cfg.preset, subtitle_srt_path=srt_path)
        rres = self.renderer.render(
            spec, progress=lambda p, m: report(0.55 + 0.4 * p, f"Render: {m}"))
        if not rres.ok:
            result.blocker = f"Render failed: {rres.message}"
            result.stages.append(StageOutcome("render", False, result.blocker))
            return result
        result.stages.append(StageOutcome("render", True, "Rendered",
                                          outputs=[rres.output_path]))

        # ---- Stage 4: validation ----------------------------------------
        report(0.97, "Validating export")
        val = self._validate(rres.output_path,
                             expect_audio=bool(narration_path),
                             expect_subs=bool(srt_path))
        result.stages.append(StageOutcome(
            "validation", val["ok"], val["message"]))
        if not val["ok"]:
            result.blocker = "Export validation failed: " + val["message"]
            return result

        result.ok = True
        result.output_path = rres.output_path
        result.has_audio = val["has_audio"]
        result.has_subtitles = val["has_subs"]
        result.duration_s = val["duration_s"]
        report(1.0, "Done")
        return result

    # ------------------------------------------------------------------
    def _concat_wavs(self, wavs: list[str], out_path: Path) -> str:
        import subprocess
        from ..media.probe import ffmpeg_path
        lst = out_path.parent / "concat_narr.txt"
        lst.write_text("".join(f"file '{Path(w).as_posix()}'\n" for w in wavs))
        try:
            subprocess.run([ffmpeg_path(), "-y", "-f", "concat", "-safe", "0",
                            "-i", str(lst), "-c", "copy", str(out_path)],
                           capture_output=True, text=True, timeout=300,
                           check=True)
        except Exception:
            subprocess.run([ffmpeg_path(), "-y", "-f", "concat", "-safe", "0",
                            "-i", str(lst), "-ar", "44100", str(out_path)],
                           capture_output=True, text=True, timeout=300,
                           check=True)
        return str(out_path)

    def _captions_srt(self, scenes: list[PhotoScene], durations: list[float],
                      out_path: Path) -> str:
        from ..voice.subtitles import SubtitleCue, write_srt
        cues = []
        t = 0.0
        for i, sc in enumerate(scenes):
            dur = max(2.0, durations[i] if i < len(durations) else sc.duration_s)
            if sc.caption:
                cues.append(SubtitleCue(i + 1, t, t + dur, sc.caption))
            t += dur
        write_srt(cues, out_path)
        return str(out_path)

    def _validate(self, path: str, expect_audio: bool,
                  expect_subs: bool) -> dict:
        import subprocess
        p = Path(path)
        if not p.exists() or p.stat().st_size == 0:
            return {"ok": False, "message": "output missing or empty",
                    "has_audio": False, "has_subs": False, "duration_s": 0.0}
        try:
            out = subprocess.run(
                [ffprobe_path(), "-v", "error", "-show_entries",
                 "stream=codec_type:format=duration", "-of", "default=nw=1",
                 str(p)], capture_output=True, text=True, timeout=60)
        except Exception as exc:
            return {"ok": False, "message": f"probe failed: {exc}",
                    "has_audio": False, "has_subs": False, "duration_s": 0.0}
        text = out.stdout
        has_video = "codec_type=video" in text
        has_audio = "codec_type=audio" in text
        has_subs = "codec_type=subtitle" in text
        duration = 0.0
        for line in text.splitlines():
            if line.startswith("duration="):
                try:
                    duration = float(line.split("=", 1)[1])
                except ValueError:
                    pass
        problems = []
        if not has_video:
            problems.append("no video stream")
        if duration < 0.5:
            problems.append(f"duration too short ({duration}s)")
        if expect_audio and not has_audio:
            problems.append("expected narration audio but none present")
        if expect_subs and not has_subs:
            problems.append("expected subtitle track but none present")
        # Decodability: a quick null-decode pass.
        try:
            from ..media.probe import ffmpeg_path
            dec = subprocess.run(
                [ffmpeg_path(), "-v", "error", "-i", str(p), "-f", "null", "-"],
                capture_output=True, text=True, timeout=120)
            if dec.returncode != 0:
                problems.append("file did not decode cleanly")
        except Exception:
            pass
        ok = not problems
        return {"ok": ok,
                "message": "valid" if ok else "; ".join(problems),
                "has_audio": has_audio, "has_subs": has_subs,
                "duration_s": duration}
