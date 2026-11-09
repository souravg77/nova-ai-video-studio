"""Persistent user settings (roadmap M1: first-launch setup).

Stored as ``settings.json`` in the user-data workspace, next to the database.
Settings never hold secrets: a future cloud API key belongs in the OS
credential store, not in this file.

Loading is forgiving: a missing file yields defaults, and a corrupt or
unreadable file is set aside as ``settings.json.corrupt`` (never silently
deleted) before defaults are used, so a damaged file cannot stop NOVA from
starting.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

SETTINGS_FILE = "settings.json"
SETTINGS_SCHEMA_VERSION = 1


class CloudSettings(BaseModel):
    """Opt-in cloud engines. Everything is OFF unless the user switches it on."""

    gemini_enabled: bool = False
    gemini_model: str = "gemini-omni-1.1-flash"


class LocalVideoSettings(BaseModel):
    """Experimental CPU text-to-video preview (personal use; research licence)."""

    experimental_preview_enabled: bool = False


class AppSettings(BaseModel):
    schema_version: int = SETTINGS_SCHEMA_VERSION
    # Set once the user has seen and closed the first-launch setup.
    first_run_complete: bool = False
    # Where model weights live. None = <workspace>/models.
    models_dir: Optional[str] = None
    cloud: CloudSettings = Field(default_factory=CloudSettings)
    local_video: LocalVideoSettings = Field(default_factory=LocalVideoSettings)
    # Workspace window layout (Qt saveGeometry/saveState, base64), so panels
    # reopen where the user left them.
    workspace_geometry: Optional[str] = None
    workspace_state: Optional[str] = None


GEMINI_KEY_ENV = "NOVA_GEMINI_API_KEY"


def gemini_api_key() -> Optional[str]:
    """API key provider for the opt-in Gemini engine.

    Read from the NOVA_GEMINI_API_KEY environment variable only; the key is
    never written to settings, project files or logs.
    """
    key = os.environ.get(GEMINI_KEY_ENV, "").strip()
    return key or None


def settings_path(workspace: Path) -> Path:
    return Path(workspace) / SETTINGS_FILE


def load_settings(workspace: Path) -> AppSettings:
    path = settings_path(workspace)
    if not path.exists():
        return AppSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("settings root is not an object")
        return AppSettings.model_validate(data)
    except (OSError, ValueError, ValidationError):
        _set_aside(path)
        return AppSettings()


def save_settings(workspace: Path, settings: AppSettings) -> Path:
    """Write atomically (temp file + replace) so a crash cannot truncate it."""
    path = settings_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def _set_aside(path: Path) -> None:
    try:
        os.replace(path, path.with_name(path.name + ".corrupt"))
    except OSError:
        pass
