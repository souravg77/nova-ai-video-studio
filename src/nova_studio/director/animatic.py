"""Animatic export: the film as planned, watchable before any AI video exists.

Every shot of the breakdown becomes a timed segment:
* the approved design of the first approved character in the shot (never a
  draft or placeholder image), or a dark title card describing the shot;
* each voiced line plays its recorded take at the position computed by the
  shared timing model (performance.timing) - no second timing model here;
* a line without a current take gets its text on screen and in the subtitle
  track but NO audio, and is listed in the report. No stand-in voice is used;
* a shot too short for its voiced lines is lengthened to the timing model's
  suggested length, and that is reported too.

Later, real generated shots can replace animatic segments one by one.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from ..media.renderer import RenderSpec, Renderer, SceneSpec
from ..performance.characters import production_readiness
from ..performance.timing import (GAP_S, LEAD_IN_S, TAIL_S, VOICED, read_manifest,
                                  shot_timing)
from ..sheets.locations import approved_frame
from ..voice.subtitles import SubtitleCue, write_srt

SLATE_COLOR = "0x1d1f26"
MAX_CAPTION = 90


@dataclass
class UnvoicedLine:
    shot_index: int
    speaker: str
    text: str
    status: str
    reason: str


@dataclass
class AnimaticReport:
    ok: bool
    output_path: str = ""
    duration_s: float = 0.0
    shots: int = 0
    image_frames: int = 0
    location_frames: int = 0
    title_cards: int = 0
    voiced_lines: int = 0
    unvoiced: list[UnvoicedLine] = field(default_factory=list)
    lengthened: list[tuple[int, float, float]] = field(default_factory=list)  # (shot, from, to)
    captions: list[str] = field(default_factory=list)   # on-screen text per shot
    message: str = ""

    def summary(self) -> str:
        if not self.ok:
            return f"Animatic failed: {self.message}"
        parts = [f"Animatic exported: {self.shots} shot(s), {self.duration_s:.1f} s. "
                 f"{self.image_frames} shot(s) use an approved design, "
                 f"{self.location_frames} an approved location, "
                 f"{self.title_cards} use a title card."]
        parts.append(f"{self.voiced_lines} line(s) voiced.")
        if self.unvoiced:
            parts.append(f"{len(self.unvoiced)} line(s) have no current take and are "
                         f"shown as text only (no audio):")
            parts += [f"  shot {u.shot_index + 1}, {u.speaker}: “{u.text}” - {u.status}"
                      for u in self.unvoiced]
        for i, a, b in self.lengthened:
            parts.append(f"Shot {i + 1} lengthened from {a:g} s to {b:g} s to fit its recorded lines.")
        return "\n".join(parts)


def _short(text: str, n: int = MAX_CAPTION) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _frame_for(shot, characters) -> Optional[str]:
    """The approved, real design of the first ready character in the shot."""
    by_id = {c.id: c for c in characters}
    for cid in shot.character_ids:
        c = by_id.get(cid)
        if c is None or not production_readiness(c).ok or c.approved.is_placeholder:
            continue
        if Path(c.approved.image_path).is_file():
            return c.approved.image_path
    return None


def _mix_dialogue(renderer: Renderer, clips: list[tuple[float, str]], total_s: float,
                  out: Path) -> Path:
    """One WAV with every take placed at its absolute start time."""
    args = [renderer.ffmpeg, "-y", "-f", "lavfi", "-t", f"{total_s:.3f}",
            "-i", "anullsrc=channel_layout=mono:sample_rate=44100"]
    parts = []
    for i, (start, path) in enumerate(clips, start=1):
        args += ["-i", path]
        ms = int(round(start * 1000))
        parts.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=mono,"
                     f"adelay={ms}:all=1[a{i}]")
    mix_in = "[0:a]" + "".join(f"[a{i}]" for i in range(1, len(clips) + 1))
    parts.append(f"{mix_in}amix=inputs={len(clips) + 1}:duration=first:normalize=0[out]")
    args += ["-filter_complex", ";".join(parts), "-map", "[out]",
             "-t", f"{total_s:.3f}", str(out)]
    proc = subprocess.run(args, capture_output=True, text=True, timeout=600,
                          stdin=subprocess.DEVNULL,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                          if sys.platform == "win32" else 0)
    if proc.returncode != 0 or not out.exists():
        raise RuntimeError(f"Mixing dialogue failed: {proc.stderr.strip()[-400:]}")
    return out


def build_animatic(project, renderer: Renderer, audio_dir: Optional[Path], out_path: str | Path,
                   width: int = 1280, height: int = 720, fps: int = 24,
                   preset: str = "veryfast",
                   progress: Optional[Callable[[float, str], None]] = None) -> AnimaticReport:
    if not project.shots:
        return AnimaticReport(False, message="There are no shots yet. Break down a script first.")
    manifest = read_manifest(audio_dir)
    names = {c.id: c.name for c in project.characters}
    director = project.director
    rep = AnimaticReport(ok=False, shots=len(project.shots))

    scenes: list[SceneSpec] = []
    cues: list[SubtitleCue] = []
    clips: list[tuple[float, str]] = []
    t0 = 0.0
    for i, shot in enumerate(project.shots):
        timing = shot_timing(shot, project.dialogue, project.characters, manifest)
        dur = shot.duration_s
        need = timing.suggested_s() if timing.lines and timing.complete else None
        if need is not None and not timing.fits:
            rep.lengthened.append((i, shot.duration_s, need))
            dur = need

        note = director.shot_note(shot.id)
        frame = _frame_for(shot, project.characters)
        if frame:
            rep.image_frames += 1
        elif note is not None:
            # No approved character in the shot: the scene's approved location.
            frame = approved_frame(director.location_for_scene(note.scene_index))
            if frame:
                rep.location_frames += 1
        spoken = [f"{names.get(lt.speaker_id, '?')}: {lt.text}" for lt in timing.lines]
        label = (note.description if note and note.description else f"Shot {i + 1}")
        # Dialogue shots show the line; every other shot shows what happens in
        # it, whether its frame is an approved design or a title card (an image
        # with no text left action shots unexplained).
        caption = _short(" / ".join(spoken) if spoken else label)
        if frame:
            scenes.append(SceneSpec("image", frame, dur, caption=caption))
        else:
            rep.title_cards += 1
            scenes.append(SceneSpec("color", None, dur, caption=caption, color=SLATE_COLOR))
        rep.captions.append(caption)

        # Voiced lines at the timing model's positions; others share what is left.
        voiced = [lt for lt in timing.lines if lt.status == VOICED]
        silent = [lt for lt in timing.lines if lt.status != VOICED]
        for lt in voiced:
            clips.append((t0 + lt.start_s, lt.audio_path))
            cues.append(SubtitleCue(len(cues), round(t0 + lt.start_s, 3),
                                    round(t0 + lt.end_s, 3), lt.text))
            rep.voiced_lines += 1
        if silent:
            start = (voiced[-1].end_s + GAP_S) if voiced else LEAD_IN_S
            end = max(start + 0.8 * len(silent), dur - TAIL_S)
            step = (end - start) / len(silent)
            for k, lt in enumerate(silent):
                a = t0 + start + k * step
                cues.append(SubtitleCue(len(cues), round(a, 3), round(a + step, 3), lt.text))
                rep.unvoiced.append(UnvoicedLine(i, names.get(lt.speaker_id, "?"),
                                                 lt.text, lt.status, lt.reason))
        t0 += dur

    with tempfile.TemporaryDirectory(prefix="nova_animatic_") as td:
        tmp = Path(td)
        narration = None
        try:
            if clips:
                if progress:
                    progress(0.02, "Placing recorded lines")
                narration = str(_mix_dialogue(renderer, clips, t0, tmp / "dialogue.wav"))
        except RuntimeError as exc:
            rep.message = str(exc)
            return rep
        srt = str(write_srt(cues, tmp / "dialogue.srt")) if cues else None
        spec = RenderSpec(scenes=scenes, width=width, height=height, fps=fps,
                          narration_path=narration, subtitle_srt_path=srt,
                          output_path=str(out_path), preset=preset)
        result = renderer.render(spec, progress=progress)

    rep.ok = result.ok
    rep.output_path = result.output_path
    rep.duration_s = round(result.duration_s, 2)
    rep.message = result.message
    return rep
