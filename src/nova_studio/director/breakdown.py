"""Turn a parsed script into the project's characters, dialogue and shots.

Rules:
* Speakers become characters through performance.characters.create_character.
  A speaker that matches an existing character (case-insensitive name) reuses
  it untouched, so approved identities and their history are never altered.
  New characters always start unapproved and unlocked.
* Dialogue and shots made by an earlier breakdown are replaced; dialogue or
  shots the director did not create are never overwritten unless the caller
  explicitly asks for it, and an approved plan blocks any new breakdown.
* One establishing shot per scene, one shot per action paragraph and one per
  dialogue line. Durations are estimated from word counts so the plan has a
  realistic running time before anything is generated.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..performance.characters import create_character
from ..performance.planner import DialogueLine, Shot
from .direction import apply_script_directions
from .model import (DirectorData, LineDirection, LocationRef, SceneInfo,
                    ShotKind, ShotNote)
from .parser import Element, ElementKind, ParsedScript

WORDS_PER_SECOND = 2.5          # ~150 words per minute, natural speech
DIALOGUE_PAD_S = 0.6
MIN_DIALOGUE_S = 1.5
PAUSE_WORDS = ("beat", "pause", "silence", "a moment")
PAUSE_S = 1.0
ACTION_WORDS_PER_SECOND = 3.0
MIN_ACTION_S, MAX_ACTION_S = 2.0, 12.0
ESTABLISHING_S = 3.0


class BreakdownError(RuntimeError):
    pass


@dataclass
class BreakdownSummary:
    scenes: int = 0
    lines: int = 0
    shots: int = 0
    new_characters: list[str] = field(default_factory=list)
    reused_characters: list[str] = field(default_factory=list)
    new_locations: list[str] = field(default_factory=list)
    running_time_s: float = 0.0
    warnings: list[str] = field(default_factory=list)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _words(text: str) -> int:
    return len(re.findall(r"\w+(?:'\w+)?", text))


def dialogue_seconds(text: str, parenthetical: str = "") -> float:
    secs = _words(text) / WORDS_PER_SECOND + DIALOGUE_PAD_S
    if any(w in parenthetical.lower() for w in PAUSE_WORDS):
        secs += PAUSE_S
    return round(max(MIN_DIALOGUE_S, secs), 1)


def action_seconds(text: str) -> float:
    secs = _words(text) / ACTION_WORDS_PER_SECOND
    return round(min(MAX_ACTION_S, max(MIN_ACTION_S, secs)), 1)


def _mentioned(text: str, characters) -> list[str]:
    """Characters named in an action paragraph (whole-word, case-insensitive)."""
    found = []
    for c in characters:
        first = c.name.split()[0]
        if re.search(rf"\b{re.escape(c.name)}\b|\b{re.escape(first)}\b", text, re.I):
            found.append(c.id)
    return found


def _short(text: str, n: int = 120) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def apply_breakdown(project, parsed: ParsedScript, script_text: str,
                    replace_existing: bool = False) -> BreakdownSummary:
    """Write the parsed script into ``project`` and return a summary."""
    director: DirectorData = project.director
    if director.plan_approved:
        raise BreakdownError(
            "The production plan is approved. Unapprove it before breaking "
            "the script down again, so approved work is not replaced.")

    owned_lines = {d.line_id for d in director.lines}
    owned_shots = {n.shot_id for n in director.shot_notes}
    foreign = ([d for d in project.dialogue if d.id not in owned_lines] +
               [s for s in project.shots if s.id not in owned_shots])
    if foreign and not replace_existing:
        raise BreakdownError(
            f"This project already has {len(foreign)} dialogue line(s) or shot(s) "
            f"that were not made from the script. Confirm replacing them first.")
    if not parsed.dialogue and not any(e.kind == ElementKind.ACTION for e in parsed.elements):
        raise BreakdownError("Nothing to break down: " + "; ".join(parsed.warnings or ["empty script"]))

    summary = BreakdownSummary(warnings=list(parsed.warnings))

    # ---- characters: reuse by name, create the rest (never approved) ------
    by_name = {c.name.strip().lower(): c for c in project.characters}
    speaker_ids: dict[str, str] = {}
    for name in parsed.speakers:
        existing = by_name.get(name.lower())
        if existing:
            speaker_ids[name.lower()] = existing.id
            summary.reused_characters.append(existing.name)
            continue
        c = create_character(_id("char"), name, language=project.language)
        project.put_character(c)
        by_name[name.lower()] = c
        speaker_ids[name.lower()] = c.id
        summary.new_characters.append(name)

    # ---- scenes, dialogue, shots ------------------------------------------
    dialogue: list[DialogueLine] = []
    shots: list[Shot] = []
    lines: list[LineDirection] = []
    notes: list[ShotNote] = []
    scenes = [SceneInfo(index=s.index, heading=s.heading, int_ext=s.int_ext,
                        location=s.location, time_of_day=s.time_of_day,
                        implicit=s.implicit) for s in parsed.scenes]

    def add_shot(kind: ShotKind, scene_index: int, duration: float, description: str,
                 character_ids: list[str], line_ids: list[str]) -> None:
        sid = _id("shot")
        shots.append(Shot(id=sid, duration_s=duration, character_ids=character_ids,
                          dialogue_line_ids=line_ids))
        notes.append(ShotNote(shot_id=sid, scene_index=scene_index, kind=kind,
                              description=description))

    by_scene: dict[int, list[Element]] = {}
    for e in parsed.elements:
        by_scene.setdefault(e.scene_index, []).append(e)

    for scene in parsed.scenes:
        elems = by_scene.get(scene.index, [])
        if not scene.implicit and scene.heading:
            add_shot(ShotKind.ESTABLISHING, scene.index, ESTABLISHING_S,
                     f"Establish {scene.location or scene.heading}"
                     + (f", {scene.time_of_day.lower()}" if scene.time_of_day else ""),
                     [], [])
        for e in elems:
            if e.kind == ElementKind.ACTION:
                add_shot(ShotKind.ACTION, scene.index, action_seconds(e.text),
                         _short(e.text), _mentioned(e.text, project.characters), [])
            elif e.kind == ElementKind.DIALOGUE:
                lid = _id("line")
                speaker = speaker_ids[e.speaker.lower()]
                dialogue.append(DialogueLine(id=lid, order=len(dialogue),
                                             speaker_id=speaker, text=e.text))
                lines.append(LineDirection(
                    line_id=lid, scene_index=scene.index,
                    parenthetical=e.parenthetical, extension=e.extension))
                add_shot(ShotKind.DIALOGUE, scene.index,
                         dialogue_seconds(e.text, e.parenthetical),
                         f"{e.speaker}: “{_short(e.text, 80)}”",
                         [speaker], [lid])
            # Transitions shape the edit, not a shot; they stay in the script.

    keep_dialogue = [] if replace_existing else [
        d for d in project.dialogue if d.id not in owned_lines]
    keep_shots = [] if replace_existing else [
        s for s in project.shots if s.id not in owned_shots]
    project.dialogue = keep_dialogue + dialogue
    project.shots = keep_shots + shots

    director.script_text = script_text
    director.script_format = parsed.format
    director.script_title = parsed.title
    director.scenes = scenes
    # One location per distinct place in the headings; existing locations
    # (and their approved views) are reused by name, never replaced.
    for sc in scenes:
        if sc.location and director.location_named(sc.location) is None:
            director.locations.append(LocationRef(id=_id("loc"), name=sc.location))
            summary.new_locations.append(sc.location)
    director.lines = lines
    director.shot_notes = notes
    director.breakdown_at = datetime.now(timezone.utc).isoformat()
    # The writer's own directions ("(angrily)", "(beat)") are read right away;
    # like everything else they still need the user's approval.
    apply_script_directions(director)
    project.touch()

    summary.scenes = len(scenes)
    summary.lines = len(dialogue)
    summary.shots = len(shots)
    summary.running_time_s = round(sum(s.duration_s for s in shots), 1)
    return summary
