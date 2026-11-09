"""Every version generated for a shot, kept in <project>/generations.

Nothing is overwritten: a new request adds versions, a failed attempt is
recorded with its reason and no file, and choosing a version only marks it.
"""
from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

MANIFEST = "versions.json"


@dataclass
class Version:
    id: str
    shot_id: str
    mode: str                      # text | frames | characters
    prompt: str
    ok: bool
    message: str = ""
    path: str = ""
    engine_id: str = ""
    model: str = ""
    interaction_id: str = ""
    created_at: str = ""
    aspect_ratio: str = ""
    resolution: str = ""
    requested_duration_s: Optional[float] = None
    duration_s: Optional[float] = None
    has_audio: Optional[bool] = None
    width: Optional[int] = None
    height: Optional[int] = None
    inputs: list[str] = field(default_factory=list)   # image paths sent
    parent_id: str = ""            # the version this one extends

    @property
    def usable(self) -> bool:
        return self.ok and bool(self.path) and Path(self.path).is_file()


def new_version_id() -> str:
    return "ver-" + uuid.uuid4().hex[:10]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class VersionStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self.root / MANIFEST

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("versions", [])
        data.setdefault("chosen", {})
        return data

    def _write(self, data: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, v: Version) -> None:
        with self._lock:
            data = self._read()
            data["versions"].append(asdict(v))
            self._write(data)

    def versions(self, shot_id: str) -> list[Version]:
        names = Version.__dataclass_fields__
        return [Version(**{k: x[k] for k in x if k in names})
                for x in self._read()["versions"] if x.get("shot_id") == shot_id]

    def get(self, version_id: str) -> Optional[Version]:
        return next((v for v in self._all() if v.id == version_id), None)

    def _all(self) -> list[Version]:
        names = Version.__dataclass_fields__
        return [Version(**{k: x[k] for k in x if k in names})
                for x in self._read()["versions"]]

    def choose(self, shot_id: str, version_id: Optional[str]) -> None:
        with self._lock:
            data = self._read()
            if version_id is None:
                data["chosen"].pop(shot_id, None)
            else:
                v = next((x for x in data["versions"] if x["id"] == version_id), None)
                if v is None or v.get("shot_id") != shot_id:
                    raise ValueError("That version doesn't belong to this shot.")
                if not (v.get("ok") and Path(v.get("path", "")).is_file()):
                    raise ValueError("Only a version with a playable file can be chosen.")
                data["chosen"][shot_id] = version_id
            self._write(data)

    def chosen(self, shot_id: str) -> Optional[Version]:
        vid = self._read()["chosen"].get(shot_id)
        v = self.get(vid) if vid else None
        return v if v is not None and v.usable else None


def chosen_clip(generations_dir: Path, shot_id: str) -> Optional[Path]:
    """The chosen, still-present clip for a shot, or None."""
    v = VersionStore(generations_dir).chosen(shot_id)
    return Path(v.path) if v else None


def generations_dir(projects_dir: Path, project_id: str) -> Path:
    return Path(projects_dir) / project_id / "generations"
