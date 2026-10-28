"""Subtitle alignment + SRT export (Phase 3, P3.4).

Builds SRT timing from the REAL per-scene narration durations (measured by
ffprobe), so subtitles stay aligned with the produced audio. Also validates
each scene's audio and flags missing, silent, clipped or unexpectedly short
tracks before they reach the renderer.

Long narration lines are split into readable subtitle cues within a scene's
time window.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..media.probe import probe


@dataclass
class SceneAudio:
    index: int
    text: str
    audio_path: str
    duration_s: float = 0.0


@dataclass
class AudioFlag:
    index: int
    level: str          # "error" | "warning"
    kind: str           # missing | silent | clipped | too_short | ok
    message: str


@dataclass
class SubtitleCue:
    index: int
    start_s: float
    end_s: float
    text: str


@dataclass
class AlignmentResult:
    cues: list[SubtitleCue]
    flags: list[AudioFlag]
    total_duration_s: float

    @property
    def ok(self) -> bool:
        return not any(f.level == "error" for f in self.flags)


def _srt_ts(t: float) -> str:
    if t < 0:
        t = 0.0
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _split_text(text: str, max_chars: int = 42) -> list[str]:
    """Split a long line into subtitle-sized chunks on word boundaries."""
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    cur = ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > max_chars:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


def validate_scene_audio(scene: SceneAudio,
                         min_ratio: float = 0.4) -> AudioFlag:
    """Flag a scene's audio as missing/silent/short/clipped/ok.

    `min_ratio`: expected minimum duration relative to a rough estimate from
    word count (words / 2.8 wps). Catches unexpectedly short/empty audio.
    """
    p = Path(scene.audio_path)
    if not p.exists() or p.stat().st_size == 0:
        return AudioFlag(scene.index, "error", "missing",
                         f"Scene {scene.index+1}: narration audio is missing "
                         f"or empty.")
    info = probe(p)
    if not info.ok or not info.has_audio:
        return AudioFlag(scene.index, "error", "missing",
                         f"Scene {scene.index+1}: no valid audio stream "
                         f"({info.error or 'unknown'}).")
    dur = info.duration_s or 0.0
    if dur <= 0.05:
        return AudioFlag(scene.index, "error", "silent",
                         f"Scene {scene.index+1}: audio is silent/zero length.")
    # Expected length from word count (very rough): ~2.8 words/sec.
    words = len(scene.text.split())
    if words:
        expected = words / 2.8
        if dur < expected * min_ratio:
            return AudioFlag(
                scene.index, "warning", "too_short",
                f"Scene {scene.index+1}: narration ({dur:.1f}s) is much shorter "
                f"than expected (~{expected:.1f}s) for {words} words — possible "
                f"clipping or truncated synthesis.")
    return AudioFlag(scene.index, "info", "ok", f"Scene {scene.index+1}: ok.")


def align_subtitles(scenes: list[SceneAudio]) -> AlignmentResult:
    """Build SRT cues aligned to real audio durations, with validation flags."""
    cues: list[SubtitleCue] = []
    flags: list[AudioFlag] = []
    t = 0.0
    cue_index = 1
    for scene in scenes:
        flag = validate_scene_audio(scene)
        flags.append(flag)
        info = probe(scene.audio_path) if Path(scene.audio_path).exists() else None
        dur = (info.duration_s if info and info.ok else scene.duration_s) or 0.0
        scene.duration_s = dur
        # Split scene text across its window proportionally by chunk length.
        chunks = _split_text(scene.text)
        total_chars = sum(len(c) for c in chunks) or 1
        start = t
        for chunk in chunks:
            frac = (len(chunk) / total_chars) if total_chars else 1.0 / len(chunks)
            seg = dur * frac
            cues.append(SubtitleCue(cue_index, start, start + seg, chunk))
            start += seg
            cue_index += 1
        t += dur
    return AlignmentResult(cues=cues, flags=flags, total_duration_s=t)


def to_srt(cues: list[SubtitleCue]) -> str:
    blocks = []
    for i, c in enumerate(cues, 1):
        blocks.append(
            f"{i}\n{_srt_ts(c.start_s)} --> {_srt_ts(c.end_s)}\n{c.text}\n")
    return "\n".join(blocks)


def write_srt(cues: list[SubtitleCue], out_path: str | Path) -> Path:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(to_srt(cues), encoding="utf-8")
    return p
