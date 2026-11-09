"""Director data stored in a project (Project.director, schema v3).

The shared performance model keeps DialogueLine and Shot deliberately lean.
Everything the director knows beyond that - the script itself, its scenes,
per-line direction and per-shot notes - lives here, keyed by the ids of the
DialogueLine / Shot records it belongs to.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class DirectionSource(str, Enum):
    SCRIPT = "script"        # written in the script itself (e.g. a parenthetical)
    SUGGESTED = "suggested"  # proposed by a model; never used until approved
    USER = "user"            # entered or confirmed by the user


class SceneInfo(BaseModel):
    index: int
    heading: str = ""
    int_ext: str = ""        # "INT", "EXT", "INT/EXT" or ""
    location: str = ""
    time_of_day: str = ""
    implicit: bool = False   # created because the script had no heading here


class LineDirection(BaseModel):
    """Direction for one DialogueLine (same id)."""

    line_id: str
    scene_index: int
    parenthetical: str = ""  # e.g. "(quietly)" exactly as written
    extension: str = ""      # e.g. "V.O.", "O.S."
    emotion: Optional[str] = None
    intensity: Optional[str] = None
    pace: Optional[str] = None
    # Where emotion/intensity/pace came from, and why (e.g. "from '(angrily)'").
    source: Optional[DirectionSource] = None
    note: str = ""
    approved: bool = False


class ShotKind(str, Enum):
    ESTABLISHING = "establishing"
    ACTION = "action"
    DIALOGUE = "dialogue"


class ShotNote(BaseModel):
    """What a Shot (same id) is for, in the script's terms."""

    shot_id: str
    scene_index: int
    kind: ShotKind
    description: str = ""


class LocationRef(BaseModel):
    """A place the script uses, with its reference views (roadmap 7a).

    Created unapproved by the breakdown. While approved, its views are locked;
    unapproving to change them starts the next version.
    """

    id: str
    name: str                       # as written in the scene heading
    description: str = ""
    views: dict[str, str] = Field(default_factory=dict)   # slot -> image path
    approved: bool = False
    version: int = 0                # number of the current/last approval
    approved_at: Optional[str] = None


class DirectorData(BaseModel):
    script_text: str = ""
    script_format: str = ""   # "fountain", "plain" or "mixed"
    script_title: str = ""
    scenes: list[SceneInfo] = Field(default_factory=list)
    lines: list[LineDirection] = Field(default_factory=list)
    shot_notes: list[ShotNote] = Field(default_factory=list)
    locations: list[LocationRef] = Field(default_factory=list)
    breakdown_at: Optional[str] = None
    # Set only by an explicit user approval of the production plan; while set,
    # a new breakdown is refused so approved work is never silently replaced.
    plan_approved: bool = False

    def line(self, line_id: str) -> Optional[LineDirection]:
        return next((d for d in self.lines if d.line_id == line_id), None)

    def shot_note(self, shot_id: str) -> Optional[ShotNote]:
        return next((n for n in self.shot_notes if n.shot_id == shot_id), None)

    def location_named(self, name: str) -> Optional[LocationRef]:
        key = name.strip().lower()
        return next((l for l in self.locations if l.name.strip().lower() == key), None)

    def location_for_scene(self, scene_index: int) -> Optional[LocationRef]:
        scene = next((s for s in self.scenes if s.index == scene_index), None)
        return self.location_named(scene.location) if scene and scene.location else None
