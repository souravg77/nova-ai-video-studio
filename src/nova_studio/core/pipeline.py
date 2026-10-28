"""Auto-video pipeline: script -> narration -> render (P2).

Chains three real stages, each gated by the capability manager's honest verdict
and verified by actual output files:

  1. ScriptAdapter (Qwen2.5 via llama.cpp) -> parsed scene list
  2. TTSAdapter (Piper), per scene -> one validated narration WAV
  3. Renderer (FFmpeg) -> validated MP4 with captions + narration

If any model, voice, dependency or hardware capability is missing, the pipeline
stops at that stage and returns the SPECIFIC blocker and suggested fallback —
it never simulates a later stage's success. Visual assets are supplied by the
caller (imported footage/images); the pipeline does NOT fabricate visuals.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from ..adapters.llm import ScriptAdapter
from ..adapters.tts import TTSAdapter, narrate_scenes
from ..media.renderer import Renderer, RenderSpec, SceneSpec
from ..media.quality_checks import validate_output
from ..models.job import GenerationState, JobKind
from .capability import CapabilityManager


@dataclass
class StageResult:
    name: str
    ok: bool
    state: GenerationState
    blocker: str = ""
    fallback: str = ""
    outputs: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


@dataclass
class PipelineResult:
    ok: bool
    stages: list[StageResult] = field(default_factory=list)
    output_path: str = ""
    # The stage that stopped the pipeline, if it failed.
    blocked_stage: str = ""
    blocker: str = ""
    suggested_fallback: str = ""


class AutoVideoPipeline:
    def __init__(self, capability: CapabilityManager,
                 script_adapter: Optional[ScriptAdapter] = None,
                 tts_adapter: Optional[TTSAdapter] = None,
                 renderer: Optional[Renderer] = None) -> None:
        self.capability = capability
        self.script_adapter = script_adapter or ScriptAdapter()
        self.tts_adapter = tts_adapter or TTSAdapter()
        self.renderer = renderer or Renderer()

    def run(self, params: dict,
            progress: Optional[Callable[[float, str], None]] = None,
            cancel: Optional[threading.Event] = None) -> PipelineResult:
        def report(p: float, msg: str) -> None:
            if progress:
                progress(p, msg)

        result = PipelineResult(ok=False)
        work_dir = Path(params["work_dir"])
        work_dir.mkdir(parents=True, exist_ok=True)
        visuals: list[str] = params.get("visuals", [])
        brief = params.get("brief", "")
        n_scenes = int(params.get("scenes", max(1, len(visuals) or 3)))
        width = int(params.get("width", 1280))
        height = int(params.get("height", 720))
        fps = int(params.get("fps", 24))
        preset = params.get("preset", "veryfast")
        out_path = params.get("output_path", str(work_dir / "auto_video.mp4"))

        # ---- Stage 1: script (gated) -------------------------------------
        report(0.05, "Stage 1/3: script generation")
        v = self.capability.verdict_for(JobKind.SCRIPT)
        if not v.can_attempt:
            stage = StageResult("script", False, v.state, v.blocker,
                                v.suggested_fallback)
            return _stop(result, stage)
        sres = self.script_adapter.run({"brief": brief, "scenes": n_scenes},
                                       cancel=cancel)
        if not sres.ok:
            stage = StageResult("script", False,
                                GenerationState.FAILED_AT_RUNTIME, sres.message,
                                "Write the script manually, or try the 0.5B "
                                "model.")
            return _stop(result, stage)
        scenes = sres.metrics.get("scenes", [])
        if not scenes:
            stage = StageResult("script", False,
                                GenerationState.FAILED_AT_RUNTIME,
                                "No parseable scenes from the model.",
                                "Write the script manually.")
            return _stop(result, stage)
        result.stages.append(StageResult(
            "script", True, GenerationState.COMPLETED_AND_VALIDATED,
            detail={"scene_count": len(scenes),
                    "runtime_s": sres.metrics.get("runtime_s")}))

        # ---- Stage 2: narration (gated) ----------------------------------
        report(0.4, "Stage 2/3: narration (per scene)")
        v = self.capability.verdict_for(JobKind.TTS)
        if not v.can_attempt:
            stage = StageResult("tts", False, v.state, v.blocker,
                                v.suggested_fallback)
            return _stop(result, stage)
        scene_texts = [s.get("narration", "") for s in scenes]
        nres = narrate_scenes(self.tts_adapter, scene_texts,
                              str(work_dir / "narration"))
        if not nres.ok:
            stage = StageResult("tts", False,
                                GenerationState.FAILED_AT_RUNTIME, nres.message,
                                "Import a recorded narration track instead.")
            return _stop(result, stage)
        narration_path = nres.outputs[0]
        scene_durations = nres.metrics.get("scene_durations", [])
        result.stages.append(StageResult(
            "tts", True, GenerationState.COMPLETED_AND_VALIDATED,
            outputs=[narration_path],
            detail={"total_duration_s": nres.metrics.get("total_duration_s")}))

        # ---- Stage 2b: subtitles (Phase 3) -------------------------------
        # Build an SRT aligned to the per-scene narration WAVs, validating each.
        srt_path = None
        try:
            from ..voice.subtitles import (SceneAudio, align_subtitles,
                                          write_srt)
            narr_dir = Path(work_dir) / "narration"
            scene_audios = [
                SceneAudio(index=i, text=scenes[i].get("narration", ""),
                           audio_path=str(narr_dir / f"narr_{i:03d}.wav"))
                for i in range(len(scenes))]
            if all(Path(sa.audio_path).exists() for sa in scene_audios):
                alignment = align_subtitles(scene_audios)
                srt_file = Path(work_dir) / "subtitles.srt"
                write_srt(alignment.cues, srt_file)
                srt_path = str(srt_file)
                result.stages.append(StageResult(
                    "subtitles",
                    alignment.ok,
                    GenerationState.COMPLETED_AND_VALIDATED if alignment.ok
                    else GenerationState.FAILED_AT_RUNTIME,
                    blocker="" if alignment.ok else "; ".join(
                        f.message for f in alignment.flags if f.level == "error"),
                    outputs=[srt_path] if alignment.ok else [],
                    detail={"cues": len(alignment.cues),
                            "flags": [f.kind for f in alignment.flags]}))
                if not alignment.ok:
                    # Subtitles failed validation (e.g. missing/silent audio).
                    stage = result.stages[-1]
                    result.ok = False
                    result.blocked_stage = "subtitles"
                    result.blocker = stage.blocker
                    result.suggested_fallback = (
                        "Regenerate the flagged scene's narration, then retry.")
                    return result
        except Exception as exc:
            # Subtitles are additive; a failure here must not fake success, but
            # it should be reported, not swallowed silently.
            result.stages.append(StageResult(
                "subtitles", False, GenerationState.FAILED_AT_RUNTIME,
                blocker=f"Subtitle generation error: {exc}"))
            srt_path = None

        # ---- Stage 3: render (always supported) --------------------------
        report(0.7, "Stage 3/3: rendering video")
        render_scenes: list[SceneSpec] = []
        for i, scene in enumerate(scenes):
            # Scene length follows its real narration duration (min 2s).
            dur = max(2.0, scene_durations[i] if i < len(scene_durations) else 3.0)
            visual = visuals[i] if i < len(visuals) else None
            caption = scene.get("caption", "") or scene.get("title", "")
            if visual and Path(visual).exists():
                kind = "image" if Path(visual).suffix.lower() in (
                    ".png", ".jpg", ".jpeg", ".bmp", ".webp") else "video"
                render_scenes.append(SceneSpec(
                    kind=kind, source=visual, duration_s=dur, caption=caption,
                    motion="kenburns" if kind == "image" else None))
            else:
                render_scenes.append(SceneSpec(
                    kind="color", color="black", duration_s=dur,
                    caption=caption))

        spec = RenderSpec(scenes=render_scenes, width=width, height=height,
                          fps=fps, narration_path=narration_path,
                          output_path=out_path, preset=preset,
                          subtitle_srt_path=srt_path)
        rres = self.renderer.render(spec, progress=lambda p, m: report(
            0.7 + 0.28 * p, f"Render: {m}"))
        if not rres.ok:
            stage = StageResult("render", False,
                                GenerationState.FAILED_AT_RUNTIME, rres.message)
            return _stop(result, stage)
        report(0.99, "Validating output")
        report_v = validate_output(rres.output_path, expect_audio=True)
        if not report_v.ok:
            stage = StageResult("render", False,
                                GenerationState.FAILED_AT_RUNTIME,
                                "; ".join(report_v.reasons))
            return _stop(result, stage)

        result.stages.append(StageResult(
            "render", True, GenerationState.COMPLETED_AND_VALIDATED,
            outputs=[rres.output_path],
            detail={"duration_s": rres.duration_s,
                    "resolution": f"{rres.width}x{rres.height}"}))
        result.ok = True
        result.output_path = rres.output_path
        report(1.0, "Done")
        return result


def _stop(result: PipelineResult, stage: StageResult) -> PipelineResult:
    result.stages.append(stage)
    result.ok = False
    result.blocked_stage = stage.name
    result.blocker = stage.blocker
    result.suggested_fallback = stage.fallback
    return result
