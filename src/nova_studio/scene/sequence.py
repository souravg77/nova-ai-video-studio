"""The scene: which clip plays for each shot, in what order, trimmed how.

A shot's clip is the version chosen on the Generate screen. Order and trims
are kept in <project>/generations/scene.json beside the versions, so the
project file format does not change. A shot with no chosen clip is never
filled with a stand-in clip: it shows its start frame or its approved
character design as a still (an animatic frame) or a plain card, and is
reported as a gap.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..generate.versions import Version, VersionStore
from ..performance.characters import production_readiness

SCENE_FILE = "scene.json"
MIN_CUT_S = 0.5

CLIP, STILL, CARD = "clip", "still", "card"


@dataclass
class ResolvedCut:
    shot_id: str
    kind: str                       # clip | still | card
    source: Optional[str]           # clip or image path; None for a card
    in_s: float
    out_s: float
    version_id: Optional[str] = None
    has_audio: bool = False
    note: str = ""

    @property
    def duration_s(self) -> float:
        return round(self.out_s - self.in_s, 3)


class SceneStore:
    def __init__(self, generations_dir: Path) -> None:
        self.root = Path(generations_dir)

    @property
    def path(self) -> Path:
        return self.root / SCENE_FILE

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("order", [])
        data.setdefault("trims", {})
        return data

    def save(self, data: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    # -- order ---------------------------------------------------------------
    def order(self, project) -> list[str]:
        """Saved order, minus deleted shots, plus new shots at the end."""
        ids = [s.id for s in project.shots]
        saved = [i for i in self.load()["order"] if i in ids]
        return saved + [i for i in ids if i not in saved]

    def move(self, project, shot_id: str, delta: int) -> list[str]:
        order = self.order(project)
        i = order.index(shot_id)
        j = max(0, min(len(order) - 1, i + delta))
        order.insert(j, order.pop(i))
        data = self.load(); data["order"] = order; self.save(data)
        return order

    # -- trims ---------------------------------------------------------------
    def set_trim(self, shot_id: str, version: Version, in_s: float, out_s: float) -> None:
        length = version.duration_s or 0.0
        if not (0.0 <= in_s < out_s <= length + 1e-6):
            raise ValueError(f"Trim must be inside the clip (0-{length:.2f} s).")
        if out_s - in_s < MIN_CUT_S:
            raise ValueError(f"Keep at least {MIN_CUT_S} s of the clip.")
        data = self.load()
        # A trim belongs to one version: choosing another clip resets it.
        data["trims"][shot_id] = {"version_id": version.id,
                                  "in_s": round(in_s, 3), "out_s": round(out_s, 3)}
        self.save(data)

    def trim_for(self, shot_id: str, version: Version) -> tuple[float, float]:
        t = self.load()["trims"].get(shot_id)
        full = (0.0, float(version.duration_s or 0.0))
        if not t or t.get("version_id") != version.id:
            return full
        return float(t["in_s"]), float(t["out_s"])


def _still_for(shot, project) -> Optional[str]:
    if shot.start_frame and Path(shot.start_frame).is_file():
        return shot.start_frame
    for cid in shot.character_ids:
        c = project.character(cid)
        if c is None or not production_readiness(c).ok or c.approved.is_placeholder:
            continue
        if Path(c.approved.image_path).is_file():
            return c.approved.image_path
    return None


def resolve(project, versions: VersionStore, scene: SceneStore) -> list[ResolvedCut]:
    shots = {s.id: s for s in project.shots}
    out = []
    for sid in scene.order(project):
        shot = shots[sid]
        v = versions.chosen(sid)
        if v is not None and v.duration_s:
            a, b = scene.trim_for(sid, v)
            out.append(ResolvedCut(sid, CLIP, v.path, a, b, version_id=v.id,
                                   has_audio=bool(v.has_audio)))
            continue
        still = _still_for(shot, project)
        note = "No clip chosen yet on the Generate screen."
        out.append(ResolvedCut(sid, STILL if still else CARD, still, 0.0,
                               float(shot.duration_s), note=note))
    return out


def cut_row(i: int, c: ResolvedCut) -> str:
    what = {CLIP: f"clip {c.in_s:.1f}-{c.out_s:.1f} s",
            STILL: "still frame (no clip yet)",
            CARD: "blank card (no clip or image yet)"}[c.kind]
    sound = ", with sound" if c.kind == CLIP and c.has_audio else ""
    return f"{i}. {c.shot_id}: {what}{sound}, {c.duration_s:g} s"


def total_s(cuts: list[ResolvedCut]) -> float:
    return round(sum(c.duration_s for c in cuts), 2)
