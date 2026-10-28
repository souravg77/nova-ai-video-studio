"""Project, Scene and Asset models."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AssetKind(str, Enum):
    VIDEO = "video"
    IMAGE = "image"
    AUDIO = "audio"
    SUBTITLE = "subtitle"
    GENERATED = "generated"


class Asset(BaseModel):
    id: str = Field(default_factory=_uid)
    kind: AssetKind
    path: str
    # Probed metadata (populated by media.probe). None until probed.
    duration_s: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    codec: Optional[str] = None
    valid: bool = False
    note: str = ""


class Scene(BaseModel):
    id: str = Field(default_factory=_uid)
    index: int = 0
    title: str = ""
    # Script text for narration / on-screen; produced by LLM adapter or typed.
    script: str = ""
    narration_asset_id: Optional[str] = None
    visual_asset_id: Optional[str] = None
    caption: str = ""
    duration_s: float = 5.0
    # 'kenburns' etc. for still-photo motion effects (Tier 0 supported).
    motion_effect: Optional[str] = None


class Project(BaseModel):
    id: str = Field(default_factory=_uid)
    name: str = "Untitled Project"
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)

    # Target output settings the USER requested. The app never silently
    # changes these; it asks before any fallback (roadmap section 8).
    target_width: int = 1920
    target_height: int = 1080
    target_fps: int = 30

    scenes: list[Scene] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)

    # Warnings/metadata stored so a project reopens honestly on other PCs.
    generation_notes: list[str] = Field(default_factory=list)

    def touch(self) -> None:
        self.updated_at = _now()

    def add_asset(self, asset: Asset) -> Asset:
        self.assets.append(asset)
        self.touch()
        return asset

    def asset_by_id(self, asset_id: str) -> Optional[Asset]:
        return next((a for a in self.assets if a.id == asset_id), None)

    def add_scene(self, scene: Scene) -> Scene:
        scene.index = len(self.scenes)
        self.scenes.append(scene)
        self.touch()
        return scene
