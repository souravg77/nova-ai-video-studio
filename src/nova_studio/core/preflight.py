"""Storage + environment preflight checks (roadmap sections 1, 6, 8).

Estimates a job's output/cache needs before it starts and refuses to proceed
when free space is below the relevant floor — addressing the '15 GB free'
warning in the roadmap.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .. import config


@dataclass
class PreflightResult:
    ok: bool
    free_gb: float
    required_gb: float
    message: str


def _free_gb(path: Path) -> float:
    try:
        return round(shutil.disk_usage(path).free / (1024 ** 3), 1)
    except Exception:
        return 0.0


def check_render_space(workspace: Path, estimated_output_gb: float = 1.0) -> PreflightResult:
    """Ensure there is room for a render + its working cache."""
    required = max(config.MIN_FREE_GB_RENDER, estimated_output_gb * 3)
    free = _free_gb(workspace)
    ok = free >= required
    msg = (
        f"{free} GB free; render needs ~{required} GB (output + cache). OK."
        if ok else
        f"Only {free} GB free; render needs ~{required} GB. Free space or use "
        f"another drive before rendering."
    )
    return PreflightResult(ok, free, required, msg)


def check_model_download_space(workspace: Path, model_size_gb: float) -> PreflightResult:
    required = max(config.MIN_FREE_GB_MODEL_DOWNLOAD, model_size_gb * 2)
    free = _free_gb(workspace)
    ok = free >= required
    msg = (
        f"{free} GB free; model download needs ~{required} GB. OK."
        if ok else
        f"Only {free} GB free; downloading this model needs ~{required} GB "
        f"(weights + extraction). Not enough space."
    )
    return PreflightResult(ok, free, required, msg)


def check_dev_setup_space(workspace: Path) -> PreflightResult:
    free = _free_gb(workspace)
    required = config.MIN_FREE_GB_DEV
    ok = free >= required
    msg = (
        f"{free} GB free; recommended dev floor is {required} GB. OK."
        if ok else
        f"{free} GB free is below the recommended {required} GB for model "
        f"downloads, cache and projects. Large video models can require much "
        f"more."
    )
    return PreflightResult(ok, free, required, msg)
