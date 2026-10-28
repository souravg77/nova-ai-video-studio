"""Speech-to-text / subtitle adapter (roadmap: whisper.cpp)."""
from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path
from typing import Optional

from .base import AdapterResult, Availability, AIAdapter


class STTAdapter(AIAdapter):
    capability = "stt"
    runtime = "whisper_cpp"

    def __init__(self, model_path: Optional[str] = None) -> None:
        self.model_path = model_path

    def availability(self) -> Availability:
        has_cli = shutil.which("whisper-cli") or shutil.which("main")
        has_pkg = False
        try:
            import pywhispercpp  # noqa: F401
            has_pkg = True
        except Exception:
            pass
        if not (has_cli or has_pkg):
            return Availability(
                False,
                "whisper.cpp not installed. Install the STT environment and a "
                "small model to enable transcription/subtitles.",
                runtime=self.runtime)
        if not self.model_path or not Path(self.model_path).exists():
            return Availability(
                False, "No whisper model found in the models directory.",
                runtime=self.runtime)
        return Availability(True, runtime=self.runtime,
                            model_name=Path(self.model_path).name)

    def run(self, params: dict, cancel: Optional[threading.Event] = None) -> AdapterResult:
        avail = self.availability()
        if not avail.available:
            return AdapterResult(False, message=avail.reason)
        audio = params.get("audio_path")
        out_srt = params.get("out_path", "captions.srt")
        t0 = time.time()
        try:
            from pywhispercpp.model import Model  # type: ignore
            model = Model(self.model_path)
            segments = model.transcribe(audio)
            Path(out_srt).write_text(_to_srt(segments))
        except Exception as exc:
            return AdapterResult(False, message=f"Transcription failed: {exc}")
        return AdapterResult(True, outputs=[out_srt],
                             message="Transcribed.",
                             metrics={"runtime_s": round(time.time() - t0, 2)})


def _to_srt(segments) -> str:  # pragma: no cover - needs whisper installed
    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{_ts(seg.t0)} --> {_ts(seg.t1)}")
        lines.append(seg.text.strip())
        lines.append("")
    return "\n".join(lines)


def _ts(centiseconds) -> str:  # pragma: no cover
    ms = int(centiseconds) * 10
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
