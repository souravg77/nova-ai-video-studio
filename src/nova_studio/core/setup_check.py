"""First-launch setup and diagnostics checks (roadmap M1).

Pure logic, no Qt: the Setup & Diagnostics dialog only displays these items.
Every item is measured on this machine; nothing is assumed from a GPU name or
claimed for an engine that is not installed. No check touches the network.
"""
from __future__ import annotations

import importlib.util
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .. import config
from ..settings import AppSettings, gemini_api_key, GEMINI_KEY_ENV
from .capability import Profile
from .preflight import check_ffmpeg


class Status(str, Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    INFO = "info"


@dataclass
class CheckItem:
    key: str
    title: str
    status: Status
    detail: str
    fix: str = ""


def _free_gb(path: Path) -> float | None:
    p = Path(path)
    while not p.exists() and p.parent != p:
        p = p.parent
    try:
        return round(shutil.disk_usage(p).free / (1024 ** 3), 1)
    except OSError:
        return None


def _writable(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".nova_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def check_hardware(report, capability) -> CheckItem:
    tier = capability.detected_tier()
    profile, reason = capability.select_profile(Profile.AUTO)
    detail = (f"{report.human_summary()}\nDetected tier {int(tier)} "
              f"({tier.name}); automatic profile: {profile.value}. {reason}")
    status = Status.WARN if report.warnings else Status.OK
    fix = "\n".join(report.warnings)
    return CheckItem("hardware", "Hardware & profile", status, detail, fix)


def check_renderer(refresh: bool = False) -> CheckItem:
    diag = check_ffmpeg(refresh=refresh)
    if diag.ok:
        return CheckItem("ffmpeg", "Video engine (FFmpeg)", Status.OK,
                         f"{diag.version}\nUsing: {diag.ffmpeg} ({diag.source})")
    return CheckItem(
        "ffmpeg", "Video engine (FFmpeg)", Status.FAIL, diag.message,
        "Reinstall NOVA (the installer ships FFmpeg), or set NOVA_FFMPEG_DIR "
        "to a folder containing ffmpeg.exe and ffprobe.exe.")


def check_storage(paths: config.Paths) -> list[CheckItem]:
    items = []
    for key, title, d in (("workspace", "Projects & data folder", paths.workspace),
                          ("models_dir", "Models folder", paths.models)):
        free = _free_gb(d)
        free_txt = f"{free} GB free" if free is not None else "free space unknown"
        if not _writable(d):
            items.append(CheckItem(key, title, Status.FAIL,
                                   f"{d}\nNot writable ({free_txt}).",
                                   "Choose a folder you can write to."))
        elif free is not None and free < config.MIN_FREE_GB_RENDER:
            items.append(CheckItem(
                key, title, Status.FAIL, f"{d}\nOnly {free_txt}.",
                f"Free at least {config.MIN_FREE_GB_RENDER} GB before rendering."))
        elif free is not None and free < config.MIN_FREE_GB_MODEL_DOWNLOAD:
            items.append(CheckItem(
                key, title, Status.WARN, f"{d}\n{free_txt}.",
                f"Model downloads need at least {config.MIN_FREE_GB_MODEL_DOWNLOAD} GB free."))
        else:
            items.append(CheckItem(key, title, Status.OK, f"{d}\n{free_txt}."))
    return items


def check_local_models(models_dir: Path) -> list[CheckItem]:
    # Listing only: hashing multi-GB weights here would stall the dialog.
    from .model_resolver import ModelResolver
    r = ModelResolver(models_dir)
    scripts, voices = r.list_script_models(), r.list_tts_voices()
    items = []
    if scripts:
        items.append(CheckItem("script_model", "Script model (local)", Status.OK,
                               ", ".join(p.name for p in scripts)))
    else:
        items.append(CheckItem(
            "script_model", "Script model (local)", Status.INFO,
            "No script model installed; script writing is unavailable.",
            f"Put a Qwen2.5 GGUF file in {Path(models_dir) / 'script'}."))
    runtime = module_available("llama_cpp")
    if scripts and not runtime:
        items.append(CheckItem(
            "script_runtime", "Script runtime (llama.cpp)", Status.WARN,
            "A script model is installed but the llama.cpp runtime is not.",
            "Install llama-cpp-python, or use a NOVA build that bundles it."))
    if voices:
        items.append(CheckItem("voice", "Narration voice (local)", Status.OK,
                               ", ".join(p.name for p in voices)))
    else:
        items.append(CheckItem(
            "voice", "Narration voice (local)", Status.INFO,
            "No Piper voice installed; narration is unavailable.",
            f"Put a Piper voice (.onnx + .onnx.json) in {Path(models_dir) / 'tts'}."))
    return items


def check_network_policy(cfg: config.AppConfig, settings: AppSettings) -> list[CheckItem]:
    items = [CheckItem(
        "offline", "Network policy", Status.OK if cfg.offline_mode else Status.WARN,
        "Offline: NOVA makes no network calls during normal work."
        if cfg.offline_mode else "Offline mode is OFF.")]

    adapter = module_available("nova_studio.adapters.gemini_omni")
    if not settings.cloud.gemini_enabled:
        items.append(CheckItem(
            "gemini", "Cloud engine: Gemini Omni Flash (opt-in)", Status.INFO,
            "Off. Nothing is sent to Google."))
    elif not adapter:
        items.append(CheckItem(
            "gemini", "Cloud engine: Gemini Omni Flash (opt-in)", Status.WARN,
            "Switched on, but this NOVA build does not include the Gemini "
            "engine yet, so nothing will be sent.",
            "Update NOVA to a build with the Gemini engine."))
    elif not gemini_api_key():
        items.append(CheckItem(
            "gemini", "Cloud engine: Gemini Omni Flash (opt-in)", Status.WARN,
            f"Switched on ({settings.cloud.gemini_model}) but no API key is set.",
            f"Set the {GEMINI_KEY_ENV} environment variable to your Gemini API key."))
    else:
        items.append(CheckItem(
            "gemini", "Cloud engine: Gemini Omni Flash (opt-in)", Status.OK,
            f"On ({settings.cloud.gemini_model}). Prompts and attached media "
            f"for jobs you run with it are sent to Google."))
    return items


def run_setup_checks(cfg: config.AppConfig, report, capability,
                     settings: AppSettings, refresh: bool = False) -> list[CheckItem]:
    items = [check_hardware(report, capability), check_renderer(refresh)]
    items += check_storage(cfg.paths)
    items += check_local_models(cfg.paths.models)
    items += check_network_policy(cfg, settings)
    items.append(check_local_video(cfg.paths.models, settings))
    return items


def overall_status(items: list[CheckItem]) -> Status:
    statuses = {i.status for i in items}
    for s in (Status.FAIL, Status.WARN):
        if s in statuses:
            return s
    return Status.OK


def local_preview_unavailable(models_dir: Path) -> str:
    """Why the local LTX-Video preview can't be offered, or '' if it can."""
    if not module_available("nova_studio.adapters.ltx_local"):
        return "not included in this build"
    from ..adapters.ltx_local import find_weights, runtime_available
    if not runtime_available():
        return "OpenVINO GenAI runtime not installed"
    if find_weights(models_dir) is None:
        return "no LTX-Video weights in models\video"
    return ""


def check_local_video(models_dir: Path, settings: AppSettings) -> CheckItem:
    title = "Local video preview (LTX-Video, CPU)"
    reason = local_preview_unavailable(models_dir)
    if reason:
        return CheckItem("local_video", title, Status.INFO, f"Not available: {reason}.")
    if not settings.local_video.experimental_preview_enabled:
        return CheckItem("local_video", title, Status.INFO,
                         "Installed but switched off. Personal, non-commercial use only "
                         "(RAIL-M licence).")
    return CheckItem("local_video", title, Status.OK,
                     "On. About 1 s of 512x288 video per minute on this PC; no sound. "
                     "Personal, non-commercial use only (RAIL-M licence).")
