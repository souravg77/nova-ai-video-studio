"""Extend a generated clip: Google continues it from where it ends.

Google's docs say a continuation is 3-10 s but not whether the returned
file holds the whole clip or only the new part, so NOVA measures it:
* clearly longer than the original: it is the whole clip and is kept as is;
* otherwise: it is only the continuation and is joined after the original.
Either way the new version records which, and its real measured length.
Extending again extends the new version, so long shots are built step by
step. The original version is never changed.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable, Optional

from ..adapters.gemini_omni import ENGINE_ID, OmniError, OmniRequest
from ..media.probe import probe
from .versions import Version, VersionStore, new_version_id, now

# A returned file this much longer than the original is the whole clip.
WHOLE_CLIP_MARGIN_S = 1.0


def can_extend(v: Optional[Version]) -> Optional[str]:
    """Why this version can't be extended, or None."""
    if v is None:
        return "Pick a version first."
    if not v.usable:
        return "Only a version with a playable file can be extended."
    if v.engine_id != ENGINE_ID or not v.interaction_id:
        return "Only clips made with Gemini Omni Flash can be extended."
    return None


def extend_version(engine, parent: Version, prompt: str, seconds: float,
                   store: VersionStore,
                   on_progress: Optional[Callable[[str], None]] = None) -> Version:
    say = on_progress or (lambda _m: None)
    why = can_extend(parent)
    if why:
        raise ValueError(why)
    if not prompt.strip():
        raise ValueError("Describe how the action continues.")
    vid = new_version_id()
    out = store.root / parent.shot_id / f"{vid}.mp4"
    v = Version(id=vid, shot_id=parent.shot_id, mode="extend", prompt=prompt,
                ok=False, engine_id=parent.engine_id, model=getattr(engine, "model", ""),
                created_at=now(), aspect_ratio=parent.aspect_ratio,
                resolution=parent.resolution, requested_duration_s=seconds,
                parent_id=parent.id)
    with tempfile.TemporaryDirectory(prefix="nova_extend_") as td:
        part = Path(td) / "continuation.mp4"
        try:
            take = engine.generate(OmniRequest(
                prompt=prompt.strip(), aspect_ratio=parent.aspect_ratio,
                resolution=parent.resolution, duration_s=seconds,
                previous_interaction_id=parent.interaction_id), part,
                on_progress=say)
        except OmniError as exc:
            v.message = str(exc)
            store.add(v)
            return v
        got = take.duration_s or 0.0
        before = parent.duration_s or 0.0
        out.parent.mkdir(parents=True, exist_ok=True)
        if got >= before + WHOLE_CLIP_MARGIN_S:
            part.replace(out)
            how = "Google returned the whole clip"
        else:
            say("Joining the continuation after the original")
            from ..scene.export import export_scene
            from ..scene.sequence import CLIP, ResolvedCut
            cuts = [ResolvedCut(parent.shot_id, CLIP, parent.path, 0.0, before,
                                has_audio=bool(parent.has_audio)),
                    ResolvedCut(parent.shot_id, CLIP, str(part), 0.0, got,
                                has_audio=bool(take.has_audio))]
            joined = export_scene(cuts, out, width=parent.width or 1280,
                                  height=parent.height or 720)
            if not joined.ok:
                v.message = f"Could not join the continuation: {joined.message}"
                store.add(v)
                return v
            how = "Google returned only the new part; NOVA joined it on"
    info = probe(out)
    if not info.ok or not info.has_video:
        out.unlink(missing_ok=True)
        v.message = "The extended clip failed validation."
        store.add(v)
        return v
    v.ok = True
    v.path = str(out)
    v.interaction_id = take.interaction_id
    v.duration_s = info.duration_s
    v.has_audio = info.has_audio
    v.width, v.height = info.width, info.height
    v.message = (f"Extended from {before:.1f} s to {info.duration_s or 0:.1f} s. {how}.")
    store.add(v)
    return v
