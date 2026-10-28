"""Studio facade: the application core the UI/CLI drive.

Owns the store, job queue, capability manager and renderer. Provides a small,
honest API: scan hardware, run benchmarks, import assets, render projects, and
ask for a capability verdict.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

from .. import config
from ..adapters.llm import ScriptAdapter
from ..adapters.tts import TTSAdapter
from ..media.renderer import Renderer
from ..media.timeline import build_render_spec
from ..models.job import Job, JobKind
from ..models.project import Project
from ..models.registry import default_registry
from ..storage.asset_registry import import_asset
from ..storage.sqlite_store import ProjectStore, export_project_manifest
from .benchmark import run_baseline_suite
from .capability import CapabilityManager, Profile
from .handlers import (make_auto_video_handler, make_photo_video_handler,
                      make_render_handler)
from .hardware import collect_hardware_report
from .job_queue import JobQueue
from .model_resolver import ModelResolver
from .pipeline import AutoVideoPipeline
from .preflight import check_render_space
from .recovery import recover_interrupted_jobs


class Studio:
    def __init__(self, cfg: Optional[config.AppConfig] = None) -> None:
        self.config = (cfg or config.default_config())
        self.config.ensure()
        self.store = ProjectStore(self.config.paths.db)
        self.queue = JobQueue(self.store)
        self.renderer = Renderer()
        self.registry = default_registry()
        self.report = collect_hardware_report()
        # Model resolver auto-discovers installed GGUF/Piper weights; nothing
        # is downloaded here.
        self.resolver = ModelResolver(self.config.paths.models)
        self.resolver.ensure_dirs()
        self._refresh_capability()
        self.queue.register(JobKind.RENDER, make_render_handler(self.renderer))
        self.queue.register(
            JobKind.AUTO_VIDEO,
            make_auto_video_handler(self._build_pipeline()))
        self.queue.register(
            JobKind.PHOTO_VIDEO,
            make_photo_video_handler(
                self._build_still_video_exporter(),
                profile_builder=self._profile_from_params))
        self.recovered = recover_interrupted_jobs(self.store)
        self.queue.start()

    def _build_still_video_exporter(self):
        from ..phase4.still_video import StillVideoExporter
        return StillVideoExporter(self.renderer)

    def _profile_from_params(self, params: dict):
        """Build a VoiceProfile for a photo-video job from its params, or None
        when the job is captions-only."""
        vp = params.get("voice")
        if not vp:
            return None
        from ..voice.expression import ExpressionSettings
        return self.build_voice_profile(
            vp["engine_id"], vp["voice_path"],
            expression=ExpressionSettings(**vp.get("expression", {})))

    def _build_pipeline(self) -> AutoVideoPipeline:
        script_model = self.resolver.resolve_script_model()
        voice = self.resolver.resolve_tts_voice()
        return AutoVideoPipeline(
            self.capability,
            script_adapter=ScriptAdapter(
                model_path=script_model.path if script_model else None),
            tts_adapter=TTSAdapter(
                voice_path=voice.path if voice else None),
            renderer=self.renderer)

    # ------------------------------------------------------------------
    def _installed_capabilities(self) -> set[str]:
        """Which AI capabilities have their model/voice files on disk now."""
        installed: set[str] = set()
        if self.resolver.resolve_script_model():
            installed.add("script")
        if self.resolver.resolve_tts_voice():
            installed.add("tts")
        if self.resolver.resolve_stt_model():
            installed.add("stt")
        return installed

    def _refresh_capability(self) -> None:
        self.capability = CapabilityManager(
            self.report, benchmarks=self.store.latest_benchmarks(),
            registry=self.registry,
            installed_capabilities=self._installed_capabilities())

    def rescan_hardware(self) -> None:
        self.report = collect_hardware_report()
        # Rebuild capability AND the pipeline so readiness reflects the rescan
        # (newly added models, changed hardware).
        self.refresh_pipeline()

    def run_benchmarks(self, runs: int = 3):
        results = run_baseline_suite(runs=runs)
        for r in results:
            self.store.save_benchmark(r)
        self.refresh_pipeline()
        return results

    def effective_profile(self, requested: Profile = Profile.AUTO):
        return self.capability.select_profile(requested)

    def verdict_for(self, kind: JobKind):
        return self.capability.verdict_for(kind)

    # ------------------------------------------------------------------
    def new_project(self, name: str) -> Project:
        p = Project(name=name)
        self.store.save_project(p)
        return p

    def save_project(self, project: Project) -> None:
        self.store.save_project(project)

    def import_media(self, project: Project, path: str):
        asset = import_asset(project, path)
        self.store.save_project(project)
        return asset

    def render_project(self, project: Project,
                       listener: Optional[Callable[[Job], None]] = None,
                       preset: Optional[str] = None) -> Job:
        out_dir = self.config.paths.projects / project.id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = str(out_dir / f"{project.name or 'output'}.mp4")

        # Storage preflight before spending resources (roadmap section 8).
        pf = check_render_space(self.config.paths.workspace)
        if not pf.ok:
            raise RuntimeError(pf.message)

        spec = build_render_spec(project, out_path)
        if preset:
            spec.preset = preset
        job = Job(project_id=project.id, kind=JobKind.RENDER,
                  params={"render_spec": _spec_to_dict(spec)})
        if listener:
            self.queue.add_listener(listener)
        return self.queue.submit(job)

    def auto_video(self, project: Project, brief: str,
                   visuals: Optional[list[str]] = None,
                   scenes: Optional[int] = None,
                   listener: Optional[Callable[[Job], None]] = None,
                   preset: str = "veryfast") -> Job:
        """Submit the P2 pipeline: script -> narration -> render.

        `visuals` are paths to imported images/clips, one per scene (missing
        ones become a captioned slate). The pipeline stops at the first missing
        model/voice/dependency with a precise blocker — it never fakes a stage.
        """
        out_dir = self.config.paths.projects / project.id
        out_dir.mkdir(parents=True, exist_ok=True)
        pf = check_render_space(self.config.paths.workspace)
        if not pf.ok:
            raise RuntimeError(pf.message)

        if visuals is None:
            # Default to the project's imported image/video assets in order.
            from ..models.project import AssetKind
            visuals = [a.path for a in project.assets
                       if a.kind in (AssetKind.IMAGE, AssetKind.VIDEO)]
        n = scenes or max(1, len(visuals) or 3)
        params = {
            "brief": brief,
            "visuals": visuals,
            "scenes": n,
            "width": project.target_width,
            "height": project.target_height,
            "fps": project.target_fps,
            "preset": preset,
            "work_dir": str(out_dir / "pipeline"),
            "output_path": str(out_dir / f"{project.name or 'auto_video'}.mp4"),
        }
        job = Job(project_id=project.id, kind=JobKind.AUTO_VIDEO, params=params)
        if listener:
            self.queue.add_listener(listener)
        return self.queue.submit(job)

    def pipeline_readiness(self) -> dict:
        """Report, per stage, whether the P2 pipeline can run right now."""
        from ..models.job import JobKind as JK
        script_model = self.resolver.resolve_script_model()
        voice = self.resolver.resolve_tts_voice()
        sv = self.capability.verdict_for(JK.SCRIPT)
        tv = self.capability.verdict_for(JK.TTS)
        return {
            "script": {"ready": sv.can_attempt, "state": sv.state.value,
                       "blocker": sv.blocker,
                       "model": script_model.name if script_model else None},
            "tts": {"ready": tv.can_attempt, "state": tv.state.value,
                    "blocker": tv.blocker,
                    "voice": voice.name if voice else None},
            "render": {"ready": True, "state": "supported"},
        }

    def voice_gallery(self):
        """Voice Studio (Phase 3): installed engines + voices, honestly."""
        from ..voice.registry import VoiceRegistry
        from .model_resolver import TTS_SUBDIR
        return VoiceRegistry(self.config.paths.models / TTS_SUBDIR).gallery()

    def build_voice_profile(self, engine_id: str, voice_path: str,
                            expression=None, pronunciation=None):
        """Construct a VoiceProfile from a gallery engine's real capabilities."""
        from ..voice.expression import ExpressionSettings
        from ..voice.narration import VoiceProfile
        gallery = self.voice_gallery()
        eng = gallery.engine(engine_id)
        caps = eng.capabilities if eng else None
        from ..voice.engine import EngineCapabilities
        return VoiceProfile(
            engine_id=engine_id, voice_path=voice_path,
            capabilities=caps or EngineCapabilities(),
            expression=expression or ExpressionSettings(),
            pronunciation=pronunciation)

    def audition_voice(self, engine_id: str, voice_path: str,
                       text: str = "This is a NOVA voice preview.",
                       expression=None, pronunciation=None) -> dict:
        """Generate a short preview WAV for a voice. Honest blocker if the
        engine/voice is unavailable. Returns {ok, path, message}."""
        from ..voice.narration import NarrationManager
        from ..adapters.tts import TTSAdapter
        profile = self.build_voice_profile(engine_id, voice_path,
                                           expression, pronunciation)
        mgr = NarrationManager(profile, tts_adapter=TTSAdapter(voice_path=voice_path))
        out_dir = self.config.paths.cache / "auditions"
        scenes = mgr.generate_all([text], out_dir)
        sn = scenes[0]
        return {"ok": sn.ok, "path": sn.audio_path if sn.ok else "",
                "message": sn.message,
                "unsupported": sn.unsupported_settings}

    def narrate_project(self, project: Project, voice_profile,
                        out_dir: Optional[str] = None):
        """Produce per-scene narration for a project (Phase 3)."""
        from ..voice.narration import NarrationManager
        from ..adapters.tts import TTSAdapter
        od = Path(out_dir) if out_dir else (
            self.config.paths.projects / project.id / "narration")
        mgr = NarrationManager(
            voice_profile, tts_adapter=TTSAdapter(voice_path=voice_profile.voice_path))
        texts = [s.script or s.caption or "" for s in project.scenes]
        return mgr, mgr.generate_all(texts, od)

    def regenerate_scene_narration(self, mgr, scenes, index: int,
                                   out_dir: str, new_text: Optional[str] = None):
        """Regenerate a single scene's narration without redoing the rest."""
        return mgr.regenerate_scene(scenes, index, out_dir, new_text=new_text)

    # ---- Phase 4: Three-Photo Identity & Motion Studio ---------------
    def intake_photos(self, paths: list):
        """Validate candidate identity photos (P4.1)."""
        from ..phase4.intake import intake_photos as _intake
        return _intake(paths)

    def prepare_identity(self, sources: list, project: Project,
                         target_size: int = 512,
                         remove_background: bool = False):
        """Crop/align identity photos into project-local copies (P4.2)."""
        from ..phase4.identity_prep import prepare_all
        out = self.config.paths.projects / project.id / "identity"
        return prepare_all(sources, out, target_size, remove_background)

    def generation_registry(self, installed_ids: Optional[set] = None):
        """Talking-head generation engines + honest gates (P4.3)."""
        from ..phase4.generation_engine import GenerationEngineRegistry
        return GenerationEngineRegistry(
            self.report, installed_ids=installed_ids or set())

    def authorize_talking_head(self, likeness, voice_consent, intended_use):
        """Likeness + voice authorization gate (P4.5)."""
        from ..phase4.provenance import authorize_generation
        return authorize_generation(likeness, voice_consent, intended_use)

    def photo_video(self, project: Project, scenes: list,
                    config: Optional[dict] = None,
                    voice: Optional[dict] = None,
                    listener: Optional[Callable[[Job], None]] = None) -> Job:
        """P4.6: submit a photo -> narration -> subtitles -> MP4 export job.

        `scenes`: list of dicts {photo_path, caption, narration, duration_s,
        motion}. `voice`: {engine_id, voice_path, expression} or None for a
        captions-only video. Runs on CPU; no GPU required.
        """
        out_dir = self.config.paths.projects / project.id
        out_dir.mkdir(parents=True, exist_ok=True)
        pf = check_render_space(self.config.paths.workspace)
        if not pf.ok:
            raise RuntimeError(pf.message)
        params = {
            "scenes": scenes,
            "config": config or {},
            "voice": voice,
            "work_dir": str(out_dir / "photo_video"),
            "output_path": str(out_dir / f"{project.name or 'photo_video'}.mp4"),
        }
        job = Job(project_id=project.id, kind=JobKind.PHOTO_VIDEO, params=params)
        if listener:
            self.queue.add_listener(listener)
        return self.queue.submit(job)

    def export_manifest(self, project: Project) -> Path:
        out = self.config.paths.projects / project.id / "project.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        return export_project_manifest(project, out)

    def cancel_job(self, job_id: str) -> bool:
        """Request cancellation of a running/queued job."""
        return self.queue.cancel(job_id)

    def refresh_pipeline(self) -> None:
        """Rebuild the pipeline after models are added or hardware rescanned."""
        self._refresh_capability()
        self.queue.register(
            JobKind.AUTO_VIDEO,
            make_auto_video_handler(self._build_pipeline()))

    def shutdown(self) -> None:
        self.queue.stop()
        self.store.close()


def _spec_to_dict(spec) -> dict:
    return {
        "scenes": [s.__dict__ for s in spec.scenes],
        "width": spec.width, "height": spec.height, "fps": spec.fps,
        "narration_path": spec.narration_path, "music_path": spec.music_path,
        "music_volume": spec.music_volume, "output_path": spec.output_path,
        "preset": spec.preset,
    }
