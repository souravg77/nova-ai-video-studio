"""Voice each dialogue line with its speaker's own voice.

Every spoken line is a character performance, so:

* a line is only voiced with the voice assigned to its speaker in Character
  Studio. A missing or uninstalled voice is a blocker for that line; NOVA
  never substitutes a default or another character's voice;
* cloning engines (XTTS-v2) are refused here: they need a consent record and
  a licence review first (see voice/cloning.py);
* a take counts only if a real audio file comes back and FFprobe finds an
  audio stream in it (the TTS adapter checks this); a failed take leaves no
  file behind;
* one line can be re-voiced without touching any other line's audio, and a
  failed retake keeps the previous good take (in the file and the manifest);
* a line's approved direction (``direction_for``) sets its pace through
  Piper's length_scale. Piper has no emotion or intensity control, so those
  are reported on the take as not applied, never claimed.

Takes are returned to the caller, and ``write_manifest`` records them next to
the audio, so the project file format does not change here.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

from ..adapters.tts import TTSAdapter
from .planner import DialogueLine

PIPER = "voice:piper"

# Piper length_scale per approved pace: >1 is slower, <1 is faster.
PACE_SCALE = {"slow": 1.2, "normal": None, "fast": 0.85}


@dataclass
class LineTake:
    line_id: str
    character_id: str
    text: str
    ok: bool
    message: str = ""
    audio_path: str = ""
    duration_s: Optional[float] = None
    engine_id: str = ""
    voice_id: str = ""
    length_scale: Optional[float] = None
    # What of the approved direction was not applied, e.g. emotion.
    direction_note: str = ""


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name) or "line"


def line_audio_path(out_dir: Path, line: DialogueLine) -> Path:
    return out_dir / f"{line.order:04d}_{_safe(line.id)}.wav"


class DialogueVoicer:
    def __init__(self, voices_dir: Path,
                 tts_factory: Callable[[str], TTSAdapter] = lambda p: TTSAdapter(voice_path=p),
                 pace_for: Optional[Callable[[DialogueLine], Optional[float]]] = None,
                 direction_for: Optional[Callable[[DialogueLine], object]] = None
                 ) -> None:
        self.voices_dir = Path(voices_dir)
        self._tts = tts_factory
        # Returns Piper's length_scale for a line (>1 slower, <1 faster), or
        # None for the voice's own pace.
        self._pace_for = pace_for
        # Returns the line's approved direction (emotion, intensity, pace) or
        # None; see director.direction.approved_direction.
        self._direction_for = direction_for or (lambda _line: None)

    def scale_for(self, line: DialogueLine) -> Optional[float]:
        """The length_scale this line is voiced with now."""
        if self._pace_for is not None:
            return self._pace_for(line)
        d = self._direction_for(line)
        return PACE_SCALE.get(getattr(d, "pace", None) or "normal")

    def direction_note(self, line: DialogueLine) -> str:
        d = self._direction_for(line)
        if d is None:
            return ""
        skipped = []
        emotion = getattr(d, "emotion", None)
        if emotion and emotion != "neutral":
            skipped.append(f"emotion '{emotion}'")
        if getattr(d, "intensity", None) and emotion and emotion != "neutral":
            skipped.append(f"intensity '{d.intensity}'")
        if not skipped:
            return ""
        return (f"Piper can't perform {' or '.join(skipped)}; only the pace "
                f"of the approved direction was applied.")

    def check_line(self, line: DialogueLine, characters) -> Optional[str]:
        """Why this line can't be voiced, or None if it can be tried."""
        if not line.text.strip():
            return "The line is empty."
        speaker = next((c for c in characters if c.id == line.speaker_id), None)
        if speaker is None:
            return f"Speaker '{line.speaker_id}' is not a character in this project."
        v = speaker.voice
        if not v.voice_id:
            return (f"{speaker.name} has no voice assigned. Choose one in "
                    f"Character Studio; NOVA won't use a default voice.")
        if v.engine_id and v.engine_id != PIPER:
            return (f"{speaker.name}'s voice uses {v.engine_id}, which NOVA can't "
                    f"run for dialogue yet (cloning needs consent and a licence "
                    f"review).")
        if not (self.voices_dir / v.voice_id).is_file():
            return (f"{speaker.name}'s voice '{v.voice_id}' is not installed in "
                    f"{self.voices_dir}.")
        return None

    def voice_line(self, line: DialogueLine, characters, out_dir: Path) -> LineTake:
        speaker = next((c for c in characters if c.id == line.speaker_id), None)
        take = LineTake(line_id=line.id, character_id=line.speaker_id,
                        text=line.text, ok=False,
                        engine_id=(speaker.voice.engine_id or PIPER) if speaker else "",
                        voice_id=speaker.voice.voice_id if speaker else "")
        blocker = self.check_line(line, characters)
        if blocker:
            take.message = blocker
            return take
        out_dir.mkdir(parents=True, exist_ok=True)
        wav = line_audio_path(out_dir, line)
        tmp = wav.with_suffix(".tmp.wav")
        tmp.unlink(missing_ok=True)
        params = {"text": line.text, "out_path": str(tmp)}
        scale = self.scale_for(line)
        take.direction_note = self.direction_note(line)
        if scale is not None:
            params["length_scale"] = scale
            take.length_scale = scale
        res = self._tts(str(self.voices_dir / speaker.voice.voice_id)).run(params)
        if not res.ok:
            tmp.unlink(missing_ok=True)
            take.message = res.message
            return take
        # Replace the previous take only once the new one is verified.
        tmp.replace(wav)
        take.ok = True
        take.audio_path = str(wav)
        take.duration_s = (res.metrics or {}).get("duration_s")
        take.message = "Voiced."
        return take

    def voice_all(self, dialogue: list[DialogueLine], characters, out_dir: Path,
                  line_ids: Optional[list[str]] = None) -> list[LineTake]:
        wanted = set(line_ids) if line_ids is not None else None
        lines = sorted((d for d in dialogue if wanted is None or d.id in wanted),
                       key=lambda d: d.order)
        return [self.voice_line(d, characters, Path(out_dir)) for d in lines]


def write_manifest(takes: list[LineTake], out_dir: Path) -> Path:
    """Merge these takes into out_dir/takes.json (other lines' entries kept).

    A failed retake does not erase a line's good take, whose audio is still
    on disk: the good entry stays and the failure is noted beside it."""
    path = Path(out_dir) / "takes.json"
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    for t in takes:
        prev = data.get(t.line_id)
        if (not t.ok and isinstance(prev, dict) and prev.get("ok")
                and Path(prev.get("audio_path", "")).is_file()):
            prev["last_error"] = t.message
            continue
        data[t.line_id] = asdict(t)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path
