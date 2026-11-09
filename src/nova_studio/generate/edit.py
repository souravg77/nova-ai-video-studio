"""Edit a generated clip by prompt: Google's "edit" task.

The prompt says what to change ("make it night", "she wears a red coat").
Google returns a new clip; NOVA measures and validates it and keeps it as a
new version linked to the one it came from. The original is never changed,
and nothing is claimed beyond what the measured file shows.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable, Optional

from ..adapters.gemini_omni import ENGINE_ID, OmniError, OmniRequest
from ..media.probe import probe
from .versions import Version, VersionStore, new_version_id, now


def can_edit(v: Optional[Version]) -> Optional[str]:
    """Why this version can't be edited by prompt, or None."""
    if v is None:
        return "Pick a version first."
    if not v.usable:
        return "Only a version with a playable file can be edited."
    if v.engine_id != ENGINE_ID or not v.interaction_id:
        return "Only clips made with Gemini Omni Flash can be edited by prompt."
    return None


def edit_version(engine, parent: Version, prompt: str, store: VersionStore,
                 on_progress: Optional[Callable[[str], None]] = None) -> Version:
    say = on_progress or (lambda _m: None)
    why = can_edit(parent)
    if why:
        raise ValueError(why)
    if not prompt.strip():
        raise ValueError("Describe what to change.")
    vid = new_version_id()
    out = store.root / parent.shot_id / f"{vid}.mp4"
    v = Version(id=vid, shot_id=parent.shot_id, mode="edit", prompt=prompt,
                ok=False, engine_id=parent.engine_id,
                model=getattr(engine, "model", ""), created_at=now(),
                aspect_ratio=parent.aspect_ratio, resolution=parent.resolution,
                parent_id=parent.id)
    with tempfile.TemporaryDirectory(prefix="nova_edit_") as td:
        part = Path(td) / "edited.mp4"
        try:
            take = engine.generate(OmniRequest(
                prompt=prompt.strip(), aspect_ratio=parent.aspect_ratio,
                resolution=parent.resolution,
                previous_interaction_id=parent.interaction_id, task="edit"),
                part, on_progress=say)
        except OmniError as exc:
            v.message = str(exc)
            store.add(v)
            return v
        info = probe(part)
        if not info.ok or not info.has_video:
            v.message = "The edited clip failed validation."
            store.add(v)
            return v
        out.parent.mkdir(parents=True, exist_ok=True)
        part.replace(out)
    before = parent.duration_s or 0.0
    v.ok = True
    v.path = str(out)
    v.interaction_id = take.interaction_id
    v.duration_s = info.duration_s
    v.has_audio = info.has_audio
    v.width, v.height = info.width, info.height
    length = f"{info.duration_s or 0:.1f} s"
    if before and abs((info.duration_s or 0) - before) > 0.5:
        length += f" (the original was {before:.1f} s)"
    v.message = f"Edited by prompt; the new clip is {length}."
    store.add(v)
    return v
