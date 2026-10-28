"""Application configuration: paths, constants, offline policy.

User data lives OUTSIDE the install directory (roadmap section 5).
On Windows this resolves to %LOCALAPPDATA%/NovaStudio; platformdirs
handles the equivalent on other platforms for development/testing.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from platformdirs import user_data_dir
except Exception:  # pragma: no cover - platformdirs is a base dep
    user_data_dir = None  # type: ignore

APP_NAME = "NovaStudio"
APP_AUTHOR = "NovaStudio"
APP_VERSION = "0.1.0"

# Storage preflight: minimum free space before we allow model downloads or
# large renders. The roadmap warns a 15 GB free SSD is not enough.
MIN_FREE_GB_DEV = 100          # recommended dev setup floor
MIN_FREE_GB_RENDER = 5         # absolute floor to even attempt a render
MIN_FREE_GB_MODEL_DOWNLOAD = 20  # before fetching any model weights


def _resolve_workspace() -> Path:
    """Pick the user-data workspace.

    Precedence: NOVA_STUDIO_HOME env override > platformdirs > ./.nova_home.
    """
    override = os.environ.get("NOVA_STUDIO_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if user_data_dir is not None:
        return Path(user_data_dir(APP_NAME, APP_AUTHOR)).resolve()
    return (Path.home() / ".nova_home").resolve()


@dataclass(frozen=True)
class Paths:
    """Resolved on-disk locations. All user data is kept here, not in src/."""

    workspace: Path
    projects: Path
    models: Path
    cache: Path
    logs: Path
    benchmarks: Path
    db: Path

    @classmethod
    def create(cls, workspace: Path | None = None) -> "Paths":
        ws = (workspace or _resolve_workspace()).resolve()
        p = cls(
            workspace=ws,
            projects=ws / "projects",
            models=ws / "models",
            cache=ws / "cache",
            logs=ws / "logs",
            benchmarks=ws / "benchmarks",
            db=ws / "nova_studio.sqlite3",
        )
        return p

    def ensure(self) -> "Paths":
        for d in (self.workspace, self.projects, self.models, self.cache,
                  self.logs, self.benchmarks):
            d.mkdir(parents=True, exist_ok=True)
        return self


@dataclass
class AppConfig:
    """Top-level runtime config."""

    paths: Paths = field(default_factory=Paths.create)
    # Offline by default: no network calls during normal operation.
    # Only an explicit "model download mode" may reach the network.
    offline_mode: bool = True
    # When True the model download mode is permitted to use the network.
    allow_model_downloads: bool = False

    def ensure(self) -> "AppConfig":
        self.paths.ensure()
        return self


def default_config() -> AppConfig:
    return AppConfig().ensure()
