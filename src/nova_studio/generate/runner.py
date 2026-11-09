"""Run one Generate press: N separate requests, each kept as a version."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

from ..adapters.gemini_omni import OmniError
from .request import GenerateSpec, prepare
from .versions import Version, VersionStore, new_version_id, now


def run_generation(engine, spec: GenerateSpec, project, store: VersionStore,
                   on_progress: Optional[Callable[[str], None]] = None,
                   cancel: Optional[threading.Event] = None) -> list[Version]:
    say = on_progress or (lambda _m: None)
    es = engine.spec()
    prep = prepare(spec, project, es.capabilities)
    if not prep.ok:
        raise ValueError("\n".join(prep.blockers))
    out: list[Version] = []
    for i in range(spec.outputs):
        if cancel is not None and cancel.is_set():
            say("Stopped before the remaining versions were sent.")
            break
        vid = new_version_id()
        path = store.root / spec.shot_id / f"{vid}.mp4"
        v = Version(id=vid, shot_id=spec.shot_id, mode=spec.mode,
                    prompt=spec.prompt, ok=False, engine_id=es.id,
                    model=getattr(engine, "model", ""), created_at=now(),
                    aspect_ratio=spec.aspect_ratio, resolution=spec.resolution,
                    requested_duration_s=spec.duration_s, inputs=prep.inputs)
        say(f"Version {i + 1} of {spec.outputs}: sending")
        try:
            take = engine.generate(prep.request, path,
                                   on_progress=lambda m, i=i: say(
                                       f"Version {i + 1} of {spec.outputs}: {m}"))
        except OmniError as exc:
            path.unlink(missing_ok=True)
            v.message = str(exc)
        else:
            v.ok = True
            v.path = str(take.path)
            v.interaction_id = take.interaction_id
            v.duration_s = take.duration_s
            v.has_audio = take.has_audio
            v.width, v.height = take.width, take.height
            v.message = "Generated."
        store.add(v)
        out.append(v)
    return out
