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


def default_engines(studio) -> tuple[list, list]:
    """(voice engines, extra planner specs) for this PC and these settings."""
    from ..adapters.gemini_omni import GeminiOmniEngine
    from ..core.model_resolver import TTS_SUBDIR
    from ..settings import gemini_api_key, load_settings
    from ..voice.registry import VoiceRegistry

    voices = VoiceRegistry(studio.config.paths.models / TTS_SUBDIR).engines
    workspace = studio.config.paths.workspace
    omni = GeminiOmniEngine(
        api_key_provider=gemini_api_key,
        cloud_enabled=lambda: load_settings(workspace).cloud.gemini_enabled)
    return voices, [omni.spec()]


class PerformanceTab(QTabWidget):
    def __init__(self, project, engines: Callable[[], tuple[list, list]],
                 on_changed: Callable[[], None] = lambda: None,
                 voicer=None, audio_dir=None) -> None:
        super().__init__()
        self._engines = engines
        voices, extra = engines()
        self._voices = voices
        self.characters = CharacterStudioPanel(
            project, on_changed=on_changed,
            voice_choices=lambda: voice_choices(self._voices))
        self.shots = ShotPlanPanel(project, build_registry(voices, extra),
                                   on_changed=on_changed, voicer=voicer,
                                   audio_dir=audio_dir)
        self.addTab(self.characters, "Character Studio")
        self.addTab(self.shots, "Shot plan")
        self.currentChanged.connect(lambda _i: self.refresh())

    def registry(self) -> EngineRegistry:
        return self.shots.registry

    def refresh(self) -> None:
        voices, extra = self._engines()
        self._voices = voices
        self.shots.registry = build_registry(voices, extra)
        self.characters.refresh()
        self.shots.refresh()


def mount_performance(window) -> PerformanceTab:
    from ..core.model_resolver import TTS_SUBDIR
    from ..performance.voicing import DialogueVoicer
    paths = window.studio.config.paths
    tab = PerformanceTab(
        window.project, lambda: default_engines(window.studio),
        on_changed=window._poll_project,
        voicer=DialogueVoicer(paths.models / TTS_SUBDIR),
        audio_dir=paths.projects / window.project.id / "dialogue")
    window.set_tab_widget("characters", tab)
    key = window._tab_index["characters"]
    window.tabs.currentChanged.connect(
        lambda i: tab.refresh() if i == key else None)
    return tab
