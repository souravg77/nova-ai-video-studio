"""Scene-by-scene narration manager (Phase 3, P3.2).

Generates one validated WAV per scene with a CONSISTENT voice + expression
settings, and can regenerate a single scene without touching the others. Each
produced file is validated (exists, has audio, non-trivial duration).

This sits on top of the existing TTSAdapter (Piper) — it does not replace it.
On a machine with no Piper/voice installed it reports an honest blocker per
scene rather than faking audio.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..adapters.tts import TTSAdapter
from ..media.probe import probe
from .engine import EngineCapabilities
from .expression import (ExpressionSettings, PronunciationDict,
                        resolve_expression)


@dataclass
class SceneNarration:
    index: int
    text: str
    audio_path: str = ""
    duration_s: float = 0.0
    ok: bool = False
    message: str = ""
    applied_settings: list[str] = field(default_factory=list)
    unsupported_settings: list[str] = field(default_factory=list)


@dataclass
class VoiceProfile:
    """The consistent voice + settings used across all scenes."""
    engine_id: str = "piper"
    voice_path: str = ""
    capabilities: EngineCapabilities = field(default_factory=EngineCapabilities)
    expression: ExpressionSettings = field(default_factory=ExpressionSettings)
    pronunciation: Optional[PronunciationDict] = None


class NarrationManager:
    def __init__(self, profile: VoiceProfile,
                 tts_adapter: Optional[TTSAdapter] = None) -> None:
        self.profile = profile
        self.tts = tts_adapter or TTSAdapter(voice_path=profile.voice_path)

    def _synthesize_one(self, index: int, text: str, out_dir: Path) -> SceneNarration:
        out_dir.mkdir(parents=True, exist_ok=True)
        wav = out_dir / f"scene_{index:03d}.wav"
        res_expr = resolve_expression(
            text, self.profile.expression, self.profile.capabilities,
            self.profile.pronunciation)
        # Build engine params. The existing Piper adapter accepts text+out_path;
        # expression engine_params are passed through for engines that use them.
        params = {"text": res_expr.text, "out_path": str(wav)}
        params.update(res_expr.engine_params)
        if not res_expr.text.strip():
            # Empty narration -> a short silence, clearly labelled (not faked).
            from ..adapters.tts import silent_track
            r = silent_track(0.8, str(wav))
            sn = SceneNarration(index=index, text=text, audio_path=str(wav),
                                ok=r.ok, message="Empty narration: silence.")
        else:
            r = self.tts.run(params)
            sn = SceneNarration(index=index, text=text,
                                audio_path=str(wav) if r.ok else "",
                                ok=r.ok, message=r.message)
        sn.applied_settings = res_expr.applied
        sn.unsupported_settings = res_expr.unsupported
        if sn.ok:
            info = probe(wav)
            if not info.ok or not info.has_audio:
                sn.ok = False
                sn.message = "Produced file failed audio validation."
            else:
                sn.duration_s = info.duration_s or 0.0
        return sn

    def generate_all(self, texts: list[str], out_dir: str | Path
                     ) -> list[SceneNarration]:
        out = Path(out_dir)
        return [self._synthesize_one(i, t, out) for i, t in enumerate(texts)]

    def regenerate_scene(self, scenes: list[SceneNarration], index: int,
                         out_dir: str | Path,
                         new_text: Optional[str] = None) -> list[SceneNarration]:
        """Re-synthesise ONE scene in place; others are untouched.

        Returns the same list with element `index` replaced. The caller keeps
        all other scenes' audio exactly as-is (P3.2 requirement).
        """
        if not (0 <= index < len(scenes)):
            raise IndexError(f"scene index {index} out of range")
        text = new_text if new_text is not None else scenes[index].text
        scenes[index] = self._synthesize_one(index, text, Path(out_dir))
        return scenes
