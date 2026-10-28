"""Text-to-speech adapter (roadmap: Piper).

Runs Piper if the CLI/python package and a licensed voice are present;
otherwise reports Unavailable. A silent-audio fallback of the correct
duration is available so a render can proceed with captions only — clearly
not presented as real narration.
"""
from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from .base import AdapterResult, Availability, AIAdapter
from ..media.probe import ffmpeg_path


class TTSAdapter(AIAdapter):
    capability = "tts"
    runtime = "piper"

    def __init__(self, voice_path: Optional[str] = None) -> None:
        self.voice_path = voice_path

    def availability(self) -> Availability:
        has_cli = shutil.which("piper") is not None
        has_pkg = False
        try:
            import piper  # noqa: F401
            has_pkg = True
        except Exception:
            pass
        if not (has_cli or has_pkg):
            return Availability(
                False,
                "Piper not installed. Install the TTS environment and an "
                "approved voice to enable local narration.",
                runtime=self.runtime)
        if not self.voice_path or not Path(self.voice_path).exists():
            return Availability(
                False,
                "No Piper voice model found. Add a license-approved voice "
                "(.onnx + .onnx.json) to the models/tts directory first.",
                runtime=self.runtime)
        # A Piper voice needs its config sidecar.
        cfg = Path(str(self.voice_path) + ".json")
        if not cfg.exists() and not Path(self.voice_path).with_suffix(".json").exists():
            return Availability(
                False,
                f"Piper voice '{Path(self.voice_path).name}' is missing its "
                f"config JSON sidecar; cannot synthesise reliably.",
                runtime=self.runtime)
        return Availability(True, runtime=self.runtime,
                            model_name=Path(self.voice_path).name)

    def run(self, params: dict, cancel: Optional[threading.Event] = None) -> AdapterResult:
        avail = self.availability()
        if not avail.available:
            return AdapterResult(False, message=avail.reason)
        text = params.get("text", "")
        out_path = params.get("out_path", "narration.wav")
        if not text.strip():
            return AdapterResult(False,
                                 message="No narration text supplied for TTS.")
        t0 = time.time()
        # Resolve the full path to the piper launcher. On Windows subprocess
        # with a bare name does not find .bat/.cmd/.exe on PATH the way the
        # shell does; shutil.which honours PATHEXT and returns the real path,
        # which subprocess can then run directly.
        piper_exe = shutil.which("piper") or "piper"
        try:
            proc = subprocess.run(
                [piper_exe, "--model", self.voice_path,
                 "--output_file", out_path],
                input=text, capture_output=True, text=True, timeout=300)
            if proc.returncode != 0 or not Path(out_path).exists():
                return AdapterResult(False, message=f"Piper failed: {proc.stderr}")
        except Exception as exc:
            return AdapterResult(False, message=f"Piper run failed: {exc}")

        # Verify the WAV is real, playable audio — not just a created file.
        from ..media.probe import probe
        info = probe(out_path)
        if not info.ok or not info.has_audio:
            return AdapterResult(
                False,
                message="Piper wrote a file but it failed audio validation: "
                        + (info.error or "no audio stream"))
        return AdapterResult(
            True, outputs=[out_path], message="Narration synthesised.",
            metrics={"runtime_s": round(time.time() - t0, 2),
                     "duration_s": info.duration_s})


def silent_track(duration_s: float, out_path: str) -> AdapterResult:
    """Generate a silent WAV of a given length (non-AI fallback)."""
    try:
        subprocess.run(
            [ffmpeg_path(), "-y", "-f", "lavfi",
             "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100",
             "-t", f"{duration_s}", out_path],
            capture_output=True, text=True, timeout=120, check=True)
        return AdapterResult(True, outputs=[out_path],
                             message="Silent audio track (no narration model).")
    except Exception as exc:
        return AdapterResult(False, message=f"Could not create silent track: {exc}")


def narrate_scenes(adapter: "TTSAdapter", scene_texts: list[str],
                   out_dir: str) -> AdapterResult:
    """Synthesise one WAV per scene, then concatenate into one narration track.

    Returns the combined track path in outputs[0] and the per-scene durations
    in metrics, so the pipeline can align scene lengths to real narration.
    Any per-scene failure aborts with that scene's blocker — no silent faking.
    """
    from pathlib import Path
    from ..media.probe import probe

    avail = adapter.availability()
    if not avail.available:
        return AdapterResult(False, message=avail.reason)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    parts: list[str] = []
    durations: list[float] = []
    for i, text in enumerate(scene_texts):
        wav = out / f"narr_{i:03d}.wav"
        if not text.strip():
            # Empty scene narration -> a short silence placeholder (labelled).
            r = silent_track(0.8, str(wav))
        else:
            r = adapter.run({"text": text, "out_path": str(wav)})
        if not r.ok:
            return AdapterResult(
                False,
                message=f"Narration failed on scene {i+1}: {r.message}")
        info = probe(wav)
        durations.append(info.duration_s or 0.0)
        parts.append(str(wav))

    combined = out / "narration.wav"
    concat_list = out / "narr_concat.txt"
    concat_list.write_text("".join(f"file '{Path(p).as_posix()}'\n" for p in parts))
    try:
        subprocess.run(
            [ffmpeg_path(), "-y", "-f", "concat", "-safe", "0",
             "-i", str(concat_list), "-c", "copy", str(combined)],
            capture_output=True, text=True, timeout=300, check=True)
    except Exception:
        # Fall back to re-encode concat if stream-copy fails.
        try:
            subprocess.run(
                [ffmpeg_path(), "-y", "-f", "concat", "-safe", "0",
                 "-i", str(concat_list), "-ar", "44100", str(combined)],
                capture_output=True, text=True, timeout=300, check=True)
        except Exception as exc:
            return AdapterResult(
                False, message=f"Could not combine narration tracks: {exc}")

    info = probe(combined)
    if not info.ok or not info.has_audio:
        return AdapterResult(False,
                             message="Combined narration failed validation.")
    return AdapterResult(
        True, outputs=[str(combined)], message="Per-scene narration complete.",
        metrics={"scene_durations": durations,
                 "total_duration_s": info.duration_s})
