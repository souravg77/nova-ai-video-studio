"""Turn what the user set on the Generate screen into an engine request.

Three modes, as in a frame-based filmmaking flow:
* text       - the prompt only;
* frames     - the shot's start frame, and optionally its end frame;
* characters - the approved designs of the shot's characters as references.

A character without an approved design is never sent: that is a blocker,
not something to work around. Nothing here talks to the network.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..adapters.gemini_omni import CAPABILITIES as OMNI_CAPS, ImageInput, OmniRequest
from ..performance.characters import production_readiness

MODES = ("text", "frames", "characters")
MODE_LABELS = {"text": "Text to video",
               "frames": "Start / end frame to video",
               "characters": "Video from approved characters"}
MAX_OUTPUTS = 4


@dataclass
class GenerateSpec:
    shot_id: str
    mode: str
    prompt: str
    outputs: int = 1
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    duration_s: Optional[float] = None


@dataclass
class Prepared:
    request: Optional[OmniRequest]
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.request is not None and not self.blockers


def prepare(spec: GenerateSpec, project, caps=OMNI_CAPS) -> Prepared:
    """``caps`` are the selected engine's declared capabilities."""
    blockers, warnings, images = [], [], []
    shot = next((s for s in project.shots if s.id == spec.shot_id), None)
    if shot is None:
        return Prepared(None, [f"Shot {spec.shot_id} no longer exists."])
    if spec.mode not in MODES:
        blockers.append(f"Unknown mode {spec.mode}.")
    if not spec.prompt.strip():
        blockers.append("Describe the shot first.")
    if not 1 <= spec.outputs <= MAX_OUTPUTS:
        blockers.append(f"Ask for 1 to {MAX_OUTPUTS} versions at a time.")
    if spec.mode == "frames" and not caps.start_end_frames:
        blockers.append("This engine can't start from a frame.")
    elif spec.mode == "characters" and caps.max_reference_images < 1:
        blockers.append("This engine can't take character references.")
    elif spec.mode == "frames":
        if not shot.start_frame:
            blockers.append("Set the shot's start frame first.")
        for role, p in (("first_frame", shot.start_frame), ("last_frame", shot.end_frame)):
            if not p:
                continue
            if not Path(p).is_file():
                blockers.append(f"The {role.replace('_', ' ')} image is missing: {p}")
            else:
                images.append(ImageInput(Path(p), role))
    elif spec.mode == "characters":
        if not shot.character_ids:
            blockers.append("This shot has no characters. Add them in the shot plan.")
        for cid in shot.character_ids:
            c = project.character(cid)
            if c is None:
                blockers.append(f"Character {cid} no longer exists.")
                continue
            r = production_readiness(c)
            if not r.ok:
                blockers.append(r.reason)
                continue
            if c.approved.is_placeholder:
                blockers.append(f"{c.name}'s approved design is a placeholder; "
                                f"approve a real image before generating with it.")
                continue
            warnings += r.warnings
            p = Path(c.approved.image_path)
            if not p.is_file():
                blockers.append(f"{c.name}'s approved image is missing: {p}")
            else:
                images.append(ImageInput(p, "reference"))
        if len(images) > caps.max_reference_images:
            blockers.append(f"This engine takes at most "
                            f"{caps.max_reference_images} character "
                            f"references per shot; this shot has {len(images)}.")
    if spec.duration_s is not None and caps.max_duration_s and not (
            caps.min_duration_s <= spec.duration_s <= caps.max_duration_s):
        blockers.append(f"This engine makes {caps.min_duration_s:g}-"
                        f"{caps.max_duration_s:g} s clips.")
    if caps.aspect_ratios and spec.aspect_ratio not in caps.aspect_ratios:
        blockers.append(f"This engine doesn't make {spec.aspect_ratio} video.")
    for img in images:
        if img.path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            blockers.append(f"{img.path.name}: Gemini accepts PNG or JPEG images only.")
    if blockers:
        return Prepared(None, blockers, warnings)
    req = OmniRequest(prompt=spec.prompt.strip(), aspect_ratio=spec.aspect_ratio,
                      resolution=spec.resolution, duration_s=spec.duration_s,
                      images=images)
    return Prepared(req, [], warnings, [str(i.path) for i in images])


def usage_text(spec: GenerateSpec, engine_name: str = "Gemini Omni Flash",
               is_cloud: bool = True) -> str:
    """What one press of Generate sends and uses, stated before it is sent."""
    secs = spec.duration_s or OMNI_CAPS.max_duration_s
    n = spec.outputs
    if not is_cloud:
        return (f"Runs {n} time{'s' if n != 1 else ''} on this PC with "
                f"{engine_name}. Nothing is sent over the internet.")
    return (f"This sends {n} request{'s' if n != 1 else ''} to Google "
            f"({engine_name}, cloud), each making one {secs:g} s clip at "
            f"{spec.resolution}: about {n * secs:g} s of video billed to your "
            f"Gemini API key. Google sets the price; NOVA can't see your bill.")
