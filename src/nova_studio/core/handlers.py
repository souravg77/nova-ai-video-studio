"""Job handlers: wire renderer + adapters + capability manager into the queue.

Every generation handler consults the CapabilityManager FIRST and writes an
honest GenerationState + blocker onto the job before doing work. Render jobs
run the FFmpeg pipeline directly.
"""
from __future__ import annotations

import threading

from ..media.renderer import Renderer, RenderSpec, SceneSpec
from ..media.quality_checks import validate_output
from ..models.job import GenerationState, Job, JobKind
from .capability import CapabilityManager
from .pipeline import AutoVideoPipeline


def make_render_handler(renderer: Renderer | None = None):
    r = renderer or Renderer()

    def handle(job: Job, cancel: threading.Event) -> list[str]:
        spec_dict = job.params.get("render_spec")
        if not spec_dict:
            raise ValueError("Render job missing 'render_spec'.")
        scenes = [SceneSpec(**s) for s in spec_dict.get("scenes", [])]
        spec = RenderSpec(**{**spec_dict, "scenes": scenes})

        def prog(p: float, msg: str) -> None:
            job.progress = p
            job.log(msg)

        result = r.render(spec, progress=prog)
        if not result.ok:
            job.generation_state = GenerationState.FAILED_AT_RUNTIME
            raise RuntimeError(result.message)
        report = validate_output(result.output_path,
                                 expect_audio=bool(spec.narration_path or spec.music_path))
        if not report.ok:
            raise RuntimeError("Validation failed: " + "; ".join(report.reasons))
        job.generation_state = GenerationState.COMPLETED_AND_VALIDATED
        return [result.output_path]

    return handle


def make_gated_handler(kind: JobKind, cap_manager: CapabilityManager,
                       adapter_run):
    """For AI generation jobs: enforce the honest verdict before running."""

    def handle(job: Job, cancel: threading.Event) -> list[str]:
        verdict = cap_manager.verdict_for(kind)
        job.generation_state = verdict.state
        job.blocker = verdict.blocker
        job.suggested_fallback = verdict.suggested_fallback
        if not verdict.can_attempt:
            # Do NOT spend resources; return no outputs. The queue will see no
            # validated output and mark the job accordingly.
            job.log(f"{kind.value}: {verdict.state.value} — {verdict.blocker}",
                    level="warning")
            job.log(f"Suggested fallback: {verdict.suggested_fallback}")
            return []
        result = adapter_run(job, cancel)
        if not result.ok:
            raise RuntimeError(result.message)
        return result.outputs

    return handle


def make_auto_video_handler(pipeline: AutoVideoPipeline):
    """P2 pipeline handler: script -> narration -> render, honestly gated.

    On a blocked stage it records the specific blocker + fallback on the job
    and returns no outputs (the queue then marks it not-completed), rather than
    faking a later stage.
    """

    def handle(job: Job, cancel: threading.Event) -> list[str]:
        def prog(p: float, msg: str) -> None:
            job.progress = p
            job.log(msg)

        result = pipeline.run(job.params, progress=prog, cancel=cancel)
        # Record per-stage outcome for transparency.
        for st in result.stages:
            job.log(f"[{st.name}] {st.state.value}"
                    + (f" — {st.blocker}" if st.blocker else ""))
        if not result.ok:
            job.generation_state = (
                result.stages[-1].state if result.stages
                else GenerationState.FAILED_AT_RUNTIME)
            job.blocker = result.blocker
            job.suggested_fallback = result.suggested_fallback
            # A blocked (not crashed) stage is an honest "can't", not an error.
            job.log(f"Pipeline stopped at '{result.blocked_stage}': "
                    f"{result.blocker}", level="warning")
            if result.suggested_fallback:
                job.log(f"Suggested fallback: {result.suggested_fallback}")
            return []
        job.generation_state = GenerationState.COMPLETED_AND_VALIDATED
        return [result.output_path]

    return handle


def make_photo_video_handler(exporter, profile_builder=None):
    """P4.6 handler: three photos -> narration -> subtitles -> validated MP4.

    `profile_builder(params)` returns a VoiceProfile or None. A blocked/failed
    stage records the blocker and returns no outputs; it never fakes a video or
    silently drops narration/subtitles.
    """
    from ..phase4.still_video import ExportConfig, PhotoScene

    def handle(job: Job, cancel: threading.Event) -> list[str]:
        def prog(p: float, msg: str) -> None:
            job.progress = p
            job.log(msg)

        p = job.params
        scenes = [PhotoScene(**s) for s in p["scenes"]]
        cfg = ExportConfig(**p.get("config", {}))
        profile = profile_builder(p) if profile_builder else None
        result = exporter.export(
            scenes, work_dir=p["work_dir"], output_path=p["output_path"],
            config=cfg, voice_profile=profile, progress=prog, cancel=cancel)
        for st in result.stages:
            job.log(f"[{st.name}] {'ok' if st.ok else 'failed'}"
                    + (f" — {st.message}" if st.message else ""))
        if not result.ok:
            job.generation_state = GenerationState.FAILED_AT_RUNTIME
            job.blocker = result.blocker
            job.suggested_fallback = result.suggested_fallback
            job.log(f"Photo-video stopped: {result.blocker}", level="warning")
            if result.suggested_fallback:
                job.log(f"Suggested fallback: {result.suggested_fallback}")
            return []
        job.generation_state = GenerationState.COMPLETED_AND_VALIDATED
        return [result.output_path]

    return handle
