"""Time a shot from its real voiced lines.

A line's length comes only from a verified take (an audio file that FFprobe
measured when it was voiced). A take no longer counts when:

* its audio file is gone,
* the line's text changed after it was voiced, or
* the speaker's voice changed after it was voiced.

Those lines are reported as needing a (re)take; their length is never
estimated from word counts and shown as if measured. A shot's timing is only
complete when every line has a current take.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .planner import DialogueLine, Shot

LEAD_IN_S = 0.4   # silence before the first line
GAP_S = 0.3       # pause between lines
TAIL_S = 0.6      # hold after the last line

VOICED, NOT_VOICED, STALE = "voiced", "not voiced", "out of date"


def read_manifest(out_dir: Optional[Path]) -> dict:
    """takes.json written by voicing.write_manifest, or {} if there is none."""
    if out_dir is None:
        return {}
    path = Path(out_dir) / "takes.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


@dataclass
class LineTiming:
    line_id: str
    speaker_id: str
    text: str
    status: str
    reason: str = ""
    duration_s: Optional[float] = None
    start_s: Optional[float] = None
    end_s: Optional[float] = None
    audio_path: str = ""


@dataclass
class ShotTiming:
    shot_id: str
    shot_s: float
    lines: list[LineTiming] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return all(t.status == VOICED for t in self.lines)

    @property
    def needs_take(self) -> list[LineTiming]:
        return [t for t in self.lines if t.status != VOICED]

    @property
    def needed_s(self) -> Optional[float]:
        """Shot length the voiced lines need, with lead-in, gaps and tail."""
        if not self.lines or not self.complete:
            return None
        return round(self.lines[-1].end_s + TAIL_S, 2)

    @property
    def fits(self) -> Optional[bool]:
        need = self.needed_s
        return None if need is None else need <= self.shot_s + 1e-6

    def suggested_s(self) -> Optional[float]:
        """The shot length that fits the lines, rounded up to 0.1 s."""
        need = self.needed_s
        return None if need is None else math.ceil(need * 10 - 1e-6) / 10


def _take_state(line: DialogueLine, entry: Optional[dict],
                speaker) -> tuple[str, str]:
    if not entry or not entry.get("ok") or not entry.get("audio_path"):
        return NOT_VOICED, "No take yet."
    if not Path(entry["audio_path"]).is_file():
        return NOT_VOICED, "The take's audio file is missing."
    if entry.get("text", "").strip() != line.text.strip():
        return STALE, "The line was edited after it was voiced."
    if speaker is not None and entry.get("voice_id") != speaker.voice.voice_id:
        return STALE, "The speaker's voice changed after this take."
    if not entry.get("duration_s"):
        return NOT_VOICED, "The take has no measured length."
    return VOICED, ""


def shot_timing(shot: Shot, dialogue: list[DialogueLine], characters,
                manifest: dict) -> ShotTiming:
    by_id = {d.id: d for d in dialogue}
    speakers = {c.id: c for c in characters}
    out = ShotTiming(shot_id=shot.id, shot_s=shot.duration_s)
    cursor = LEAD_IN_S
    for lid in shot.dialogue_line_ids:
        line = by_id.get(lid)
        if line is None:
            continue
        entry = manifest.get(lid)
        status, reason = _take_state(line, entry, speakers.get(line.speaker_id))
        t = LineTiming(line_id=lid, speaker_id=line.speaker_id, text=line.text,
                       status=status, reason=reason)
        if status == VOICED:
            t.duration_s = float(entry["duration_s"])
            t.audio_path = entry["audio_path"]
            t.start_s = round(cursor, 2)
            t.end_s = round(cursor + t.duration_s, 2)
            cursor = t.end_s + GAP_S
        out.lines.append(t)
    return out


def timing_text(t: ShotTiming) -> str:
    if not t.lines:
        return "No dialogue: the shot length is up to you."
    if not t.complete:
        n = len(t.needs_take)
        return (f"{n} line(s) need a take before this shot can be timed. "
                f"Lengths come from the recorded voices, never estimates.")
    need = t.needed_s
    if t.fits:
        spare = round(t.shot_s - need, 1)
        return (f"The lines need {need:.1f} s with pauses; the shot is "
                f"{t.shot_s:g} s ({spare:g} s spare).")
    return (f"Too short: the lines need {need:.1f} s with pauses, but the "
            f"shot is {t.shot_s:g} s. Use \"Fit shot to its lines\" or cut a line.")


def line_suffix(t: LineTiming) -> str:
    if t.status == VOICED:
        return f"  [{t.start_s:.1f}-{t.end_s:.1f} s]"
    return f"  ({t.status})"
