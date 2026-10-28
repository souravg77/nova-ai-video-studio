"""Model resolver: discover locally-installed model files (P2).

Finds GGUF script models and Piper voices under the workspace models directory
without hardcoded paths and without downloading anything. Records SHA-256 so a
benchmark/approval decision can be tied to an exact file (roadmap section 3:
"store model hashes").

Layout (created on demand, never auto-populated):
    <workspace>/models/
        script/*.gguf          quantized LLM weights (Qwen2.5 ...)
        tts/*.onnx (+ *.onnx.json)   Piper voices
        stt/*.bin              whisper.cpp models

Nothing here reaches the network. Downloads are a separate, consented step
(see security.model_download).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


SCRIPT_SUBDIR = "script"
TTS_SUBDIR = "tts"
STT_SUBDIR = "stt"

# Preference order for script models: a 1.5B build first, then 0.5B fallback,
# then anything else present (roadmap: 1.5B recommended, 0.5B fallback).
_SCRIPT_PREFERENCE = ("1.5b", "0.5b")


@dataclass
class ResolvedModel:
    path: str
    name: str
    sha256: str
    size_mb: float


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _describe(path: Path) -> ResolvedModel:
    return ResolvedModel(
        path=str(path), name=path.name, sha256=_sha256(path),
        size_mb=round(path.stat().st_size / (1024 * 1024), 1))


class ModelResolver:
    def __init__(self, models_dir: str | Path) -> None:
        self.models_dir = Path(models_dir)

    def _dir(self, sub: str) -> Path:
        return self.models_dir / sub

    def ensure_dirs(self) -> None:
        for sub in (SCRIPT_SUBDIR, TTS_SUBDIR, STT_SUBDIR):
            self._dir(sub).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    def list_script_models(self) -> list[Path]:
        d = self._dir(SCRIPT_SUBDIR)
        return sorted(d.glob("*.gguf")) if d.exists() else []

    def resolve_script_model(self) -> Optional[ResolvedModel]:
        """Pick the preferred GGUF script model, or None if none present."""
        candidates = self.list_script_models()
        if not candidates:
            return None

        def rank(p: Path) -> int:
            low = p.name.lower()
            for i, token in enumerate(_SCRIPT_PREFERENCE):
                if token in low:
                    return i
            return len(_SCRIPT_PREFERENCE)

        best = sorted(candidates, key=lambda p: (rank(p), p.name))[0]
        return _describe(best)

    # ------------------------------------------------------------------
    def list_tts_voices(self) -> list[Path]:
        d = self._dir(TTS_SUBDIR)
        if not d.exists():
            return []
        # A Piper voice is an .onnx with a sibling .onnx.json config.
        voices = []
        for onnx in sorted(d.glob("*.onnx")):
            if onnx.with_suffix(onnx.suffix + ".json").exists():
                voices.append(onnx)
            else:
                voices.append(onnx)  # still list it; adapter will flag config
        return voices

    def resolve_tts_voice(self) -> Optional[ResolvedModel]:
        voices = self.list_tts_voices()
        if not voices:
            return None
        return _describe(voices[0])

    # ------------------------------------------------------------------
    def list_stt_models(self) -> list[Path]:
        d = self._dir(STT_SUBDIR)
        return sorted(d.glob("*.bin")) if d.exists() else []

    def resolve_stt_model(self) -> Optional[ResolvedModel]:
        models = self.list_stt_models()
        return _describe(models[0]) if models else None
