"""Mounts Character Studio and the shot plan into the workspace's
Characters mode.

The planner's engines are rebuilt each time the mode is opened, so a voice
installed or the Gemini switch flipped in Setup shows up without a restart.
Gemini Omni Flash is only offered when it is switched on in Settings; its key
comes from the environment and is never stored.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QTabWidget

from ..performance.catalog import build_registry, voice_choices
from ..performance.engines import EngineRegistry
from .character_studio import CharacterStudioPanel
from .shot_plan import ShotPlanPanel


def omni_engine(studio):
    """Gemini Omni Flash, reading the switch and key fresh on every use."""
    from ..adapters.gemini_omni import GeminiOmniEngine
    from ..settings import gemini_api_key, load_settings
    workspace = studio.config.paths.workspace
    return GeminiOmniEngine(
        api_key_provider=gemini_api_key,
        cloud_enabled=lambda: load_settings(workspace).cloud.gemini_enabled)


def default_engines(studio) -> tuple[list, list]:
    """(voice engines, extra planner specs) for this PC and these settings."""
    from ..core.model_resolver import TTS_SUBDIR
    from ..voice.registry import VoiceRegistry

    voices = VoiceRegistry(studio.config.paths.models / TTS_SUBDIR).engines
    return voices, [omni_engine(studio).spec()]


class PerformanceTab(QTabWidget):
    def __init__(self, project, engines: Callable[[], tuple[list, list]],
                 on_changed: Callable[[], None] = lambda: None,
                 voicer=None, audio_dir=None, media_dir=None,
                 video_engine=None, generations_dir=None,
                 scene_out=None) -> None:
        super().__init__()
        self._engines = engines
        voices, extra = engines()
        self._voices = voices
        self.characters = CharacterStudioPanel(
            project, on_changed=on_changed,
            voice_choices=lambda: voice_choices(self._voices),
            media_dir=media_dir)
        self.shots = ShotPlanPanel(project, build_registry(voices, extra),
                                   on_changed=on_changed, voicer=voicer,
                                   audio_dir=audio_dir)
        self.addTab(self.characters, "Character Studio")
        self.addTab(self.shots, "Shot plan")
        self.generate = None
        if generations_dir is not None:
            from .generate_panel import GeneratePanel
            self.generate = GeneratePanel(project, engine=video_engine,
                                          generations_dir=generations_dir,
                                          on_changed=on_changed)
            self.addTab(self.generate, "Generate")
        self.scene = None
        if generations_dir is not None and scene_out is not None:
            from .scene_panel import ScenePanel
            self.scene = ScenePanel(project, generations_dir, scene_out)
            self.addTab(self.scene, "Scene")
        self.currentChanged.connect(lambda _i: self.refresh())

    def registry(self) -> EngineRegistry:
        return self.shots.registry

    def refresh(self) -> None:
        voices, extra = self._engines()
        self._voices = voices
        self.shots.registry = build_registry(voices, extra)
        self.characters.refresh()
        self.shots.refresh()
        if self.generate is not None and not self.generate.busy():
            self.generate.refresh()
        if self.scene is not None and not self.scene.busy():
            self.scene.refresh()


def mount_performance(window) -> PerformanceTab:
    from ..core.model_resolver import TTS_SUBDIR
    from ..director.direction import approved_direction
    from ..generate.versions import generations_dir
    from ..storage.asset_registry import safe_filename
    from ..performance.voicing import DialogueVoicer
    paths = window.studio.config.paths
    tab = PerformanceTab(
        window.project, lambda: default_engines(window.studio),
        on_changed=lambda: (window.save_project(), window._poll_project()),
        voicer=DialogueVoicer(
            paths.models / TTS_SUBDIR,
            # Only directions the user approved; suggestions never reach audio.
            direction_for=lambda line: approved_direction(window.project, line.id)),
        audio_dir=paths.projects / window.project.id / "dialogue",
        media_dir=paths.projects / window.project.id / "characters",
        video_engine=omni_engine(window.studio),
        generations_dir=generations_dir(paths.projects, window.project.id),
        scene_out=lambda: paths.projects / window.project.id / (
            safe_filename(window.project.name or "scene") + "_scene.mp4"))
    window.set_tab_widget("characters", tab)
    key = window._tab_index["characters"]
    window.tabs.currentChanged.connect(
        lambda i: tab.refresh() if i == key else None)
    return tab
