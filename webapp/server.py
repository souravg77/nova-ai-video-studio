"""Flask backend for the NOVA Studio desktop dashboard."""
from __future__ import annotations

import shutil
import sys
import threading
import uuid
from pathlib import Path

# Ensure the engine is importable from source and from a PyInstaller bundle.
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_SRC = _ROOT / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from flask import Flask, abort, jsonify, request, send_file, send_from_directory  # noqa: E402

STATIC = _HERE / "static"
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff", ".heic", ".heif", ".avif", ".jfif"}
_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".wmv", ".flv", ".mpeg", ".mpg", ".3gp", ".3g2", ".ts", ".mts", ".m2ts"}
_AUDIO_EXTS = {".wav", ".mp3", ".aac", ".m4a", ".flac", ".ogg", ".opus", ".wma", ".m4b"}


def _media_kind(name: str) -> str | None:
    ext = Path(name).suffix.lower()
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _VIDEO_EXTS:
        return "video"
    if ext in _AUDIO_EXTS:
        return "audio"
    return None


def _probe_media(path: Path, label: str) -> dict:
    """Probe uploaded media; use image/video libraries if ffprobe is unavailable."""
    from nova_studio.media.probe import FFmpegNotFound, MediaInfo, probe
    kind = _media_kind(label) or _media_kind(path.name)
    try:
        info = probe(path)
        if info.ok:
            return {"ok": True, "name": label, "data": info}
    except FFmpegNotFound:
        info = None
    except Exception as exc:
        info = None
        probe_error = str(exc)
    else:
        probe_error = info.error if info else "Could not inspect media."

    # Pillow handles still images without needing ffprobe, including formats
    # supported by the installed Pillow codecs.
    if kind == "image":
        try:
            from PIL import Image
            with Image.open(path) as image:
                width, height = image.size
                image.verify()
            return {"ok": True, "name": label, "data": MediaInfo(
                path=str(path), ok=True, width=width, height=height)}
        except Exception as exc:
            return {"ok": False, "name": label, "message": f"Image could not be decoded: {exc}"}

    # OpenCV is a fallback for video metadata when ffprobe is unavailable.
    if kind == "video":
        try:
            import cv2
            cap = cv2.VideoCapture(str(path))
            try:
                if cap.isOpened():
                    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
                    count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
                    if width > 0 and height > 0:
                        duration = count / fps if fps > 0 else None
                        return {"ok": True, "name": label, "data": MediaInfo(
                            path=str(path), ok=True, width=width, height=height,
                            duration_s=duration)}
            finally:
                cap.release()
        except Exception:
            pass
    return {"ok": False, "name": label, "message": locals().get("probe_error", "ffprobe could not read this file.")}


def _add_piper_to_path(models_dir: Path) -> None:
    import os
    root = Path(models_dir) / "tts" / "piper"
    for candidate in (root, root / "piper"):
        exe = candidate / ("piper.exe" if os.name == "nt" else "piper")
        if exe.exists():
            os.environ["PATH"] = str(candidate) + os.pathsep + os.environ.get("PATH", "")
            return


def _cpu_percent() -> int:
    try:
        import psutil
        return int(psutil.cpu_percent(interval=0.1))
    except Exception:
        return 0


class RenderJob:
    def __init__(self, job_id: str) -> None:
        self.id = job_id
        self.state = "running"
        self.progress = 0.0
        self.stage = "Starting…"
        self.output_path = ""
        self.has_audio = False
        self.has_subtitles = False
        self.duration_s = 0.0
        self.blocker = ""
        self.fallback = ""


def create_app(workspace: Path | None = None) -> Flask:
    from nova_studio.config import AppConfig, Paths
    from nova_studio.core.studio import Studio

    ws = Path(workspace) if workspace else Path.home() / ".nova_home"
    cfg = AppConfig(paths=Paths.create(ws))
    _add_piper_to_path(cfg.paths.models)
    studio = Studio(cfg)
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024
    jobs: dict[str, RenderJob] = {}
    media_dir = ws / "studio_media"
    media_dir.mkdir(parents=True, exist_ok=True)
    media: dict[str, dict] = {}

    @app.route("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.route("/<path:path>")
    def assets(path):
        if not (STATIC / path).exists():
            abort(404)
        return send_from_directory(STATIC, path)

    @app.route("/api/health")
    def health():
        return jsonify({"ok": True})

    @app.route("/api/hardware")
    def hardware():
        report = studio.report
        talking = studio.generation_registry(installed_ids={"sadtalker"}).decide("sadtalker")
        return jsonify({"cpu_name": report.cpu_name, "cpu_pct": _cpu_percent(),
                        "ram_gb": report.physical_ram_gb,
                        "has_gpu": report.has_nvidia_cuda,
                        "render_ready": "ffmpeg" in report.backends_available,
                        "summary": report.human_summary(),
                        "talking_head_supported": talking.can_attempt,
                        "talking_head_blocker": talking.blocker})

    @app.route("/api/voices")
    def voices():
        gallery = studio.voice_gallery()
        names = [f"{engine.display_name}: {voice.name}" for engine in gallery.engines
                 if engine.available for voice in engine.voices]
        return jsonify({"voices": names,
                        "engines": [{"id": e.engine_id, "available": e.available,
                                     "reason": e.reason} for e in gallery.engines]})

    @app.route("/api/audition", methods=["POST"])
    def audition():
        data = request.get_json(silent=True) or {}
        voice = studio.resolver.resolve_tts_voice()
        if not voice:
            return jsonify({"ok": False, "message": "No Piper voice installed (add one to models/tts)."})
        from nova_studio.voice.expression import ExpressionSettings
        result = studio.audition_voice("piper", voice.path,
            text=data.get("text", "NOVA voice preview."),
            expression=ExpressionSettings(speed=float(data.get("speed", 1.0))))
        return jsonify(result)

    @app.route("/api/upload", methods=["POST"])
    def upload():
        from werkzeug.utils import secure_filename
        results = []
        for file in request.files.getlist("files"):
            name = secure_filename(file.filename or "file")
            kind = _media_kind(name)
            if not kind:
                results.append({"ok": False, "name": name, "message": f"Unsupported type: {Path(name).suffix or 'unknown'}"})
                continue
            media_id = uuid.uuid4().hex[:12]
            dest = media_dir / f"{media_id}{Path(name).suffix.lower()}"
            file.save(dest)
            results.append(_save_media(dest, name, kind, media_id))
        return jsonify({"files": results})

    def _save_media(path: Path, name: str, kind: str, media_id: str | None = None) -> dict:
        media_id = media_id or uuid.uuid4().hex[:12]
        result = _probe_media(path, name)
        if not result["ok"]:
            path.unlink(missing_ok=True)
            return {"ok": False, "name": name, "message": result["message"]}
        info = result["data"]
        entry = {"id": media_id, "path": str(path), "kind": kind, "name": name,
                 "w": info.width, "h": info.height, "dur": info.duration_s, "ok": True}
        media[media_id] = entry
        return {**entry, "url": f"/api/media/{media_id}"}

    @app.route("/api/import_paths", methods=["POST"])
    def import_paths():
        data = request.get_json(silent=True) or {}
        results = []
        for raw in data.get("paths", []):
            source = Path(raw)
            if not source.is_file():
                results.append({"ok": False, "name": str(raw), "message": "File not found"})
                continue
            name = source.name
            kind = _media_kind(name)
            if not kind:
                results.append({"ok": False, "name": name, "message": f"Unsupported type: {source.suffix or 'unknown'}"})
                continue
            media_id = uuid.uuid4().hex[:12]
            dest = media_dir / f"{media_id}{source.suffix.lower()}"
            try:
                shutil.copyfile(source, dest)
                results.append(_save_media(dest, name, kind, media_id))
            except OSError as exc:
                results.append({"ok": False, "name": name, "message": f"Could not copy file: {exc}"})
        return jsonify({"files": results})

    @app.route("/api/media/<media_id>")
    def serve_media(media_id):
        entry = media.get(media_id)
        if not entry or not Path(entry["path"]).is_file():
            abort(404)
        return send_file(entry["path"])

    @app.route("/api/thumb/<media_id>")
    def thumb(media_id):
        entry = media.get(media_id)
        if not entry:
            abort(404)
        if entry["kind"] == "image":
            return send_file(entry["path"])
        from nova_studio.media.probe import ffmpeg_path
        import subprocess
        thumbnail = media_dir / f"{media_id}_thumb.jpg"
        if not thumbnail.exists():
            try:
                subprocess.run([ffmpeg_path(), "-y", "-i", entry["path"], "-frames:v", "1", "-vf", "scale=160:-1", str(thumbnail)], capture_output=True, timeout=30, check=True)
            except Exception:
                abort(404)
        return send_file(str(thumbnail))

    from webapp.models import ModelDownloader
    downloader = ModelDownloader(studio.config.paths.models)

    @app.route("/api/models/status")
    def models_status():
        return jsonify(downloader.status(studio.resolver))

    @app.route("/api/models/download", methods=["POST"])
    def models_download():
        data = request.get_json(silent=True) or {}
        try:
            downloader.start(data.get("key", ""))
        except KeyError:
            return jsonify({"ok": False, "message": f"Unknown model '{data.get('key', '')}'."}), 400
        return jsonify({"ok": True})

    @app.route("/api/models/refresh", methods=["POST"])
    def models_refresh():
        _add_piper_to_path(studio.config.paths.models)
        studio.refresh_pipeline()
        return jsonify({"ok": True})

    @app.route("/api/script", methods=["POST"])
    def script():
        data = request.get_json(silent=True) or {}
        brief = (data.get("brief") or "").strip()
        if not brief:
            return jsonify({"ok": False, "message": "Enter a topic first."}), 400
        from nova_studio.adapters.llm import ScriptAdapter
        model = studio.resolver.resolve_script_model()
        adapter = ScriptAdapter(model_path=model.path if model else None)
        available = adapter.availability()
        if not available.available:
            return jsonify({"ok": False, "message": available.reason, "need_download": True})
        result = adapter.run({"brief": brief, "scenes": int(data.get("scenes", 3))})
        if not result.ok:
            return jsonify({"ok": False, "message": result.message})
        return jsonify({"ok": True, "scenes": result.metrics.get("scenes", [])})

    @app.route("/api/render", methods=["POST"])
    def render():
        data = request.get_json(silent=True) or {}
        for scene in data.get("scenes", []):
            media_id = scene.get("media_id")
            if media_id in media:
                scene["photo_path"] = media[media_id]["path"]
        job_id = uuid.uuid4().hex[:12]
        job = RenderJob(job_id)
        jobs[job_id] = job
        threading.Thread(target=_run_render, args=(studio, data, job, ws), daemon=True).start()
        return jsonify({"job_id": job_id})

    @app.route("/api/job/<job_id>")
    def job_status(job_id):
        job = jobs.get(job_id)
        if not job:
            abort(404)
        result = {"state": job.state, "progress": job.progress, "stage": job.stage,
                  "blocker": job.blocker, "fallback": job.fallback,
                  "has_audio": job.has_audio, "has_subtitles": job.has_subtitles,
                  "duration_s": job.duration_s}
        if job.state == "completed":
            result["output_url"] = f"/api/output/{job_id}"
            result["output_path"] = job.output_path
        return jsonify(result)

    @app.route("/api/output/<job_id>")
    def output(job_id):
        job = jobs.get(job_id)
        if not job or not job.output_path or not Path(job.output_path).exists():
            abort(404)
        return send_file(job.output_path, mimetype="video/mp4")

    return app


def _run_render(studio, data: dict, job: RenderJob, workspace: Path) -> None:
    from nova_studio.phase4.still_video import ExportConfig, PhotoScene, StillVideoExporter
    from nova_studio.voice.narration import VoiceProfile
    from nova_studio.voice.engine import EngineCapabilities
    from nova_studio.voice.expression import ExpressionSettings
    try:
        work = workspace / "studio_render" / job.id
        work.mkdir(parents=True, exist_ok=True)
        from nova_studio.media.probe import ffmpeg_path
        import subprocess
        colors = ["0x1a2b4c", "0x1f5130", "0x4a2a6a", "0x25507a"]
        scenes = []
        for i, scene in enumerate(data.get("scenes", [])):
            photo = scene.get("photo_path")
            if not photo or not Path(photo).is_file():
                photo = str(work / f"slate_{i}.png")
                subprocess.run([ffmpeg_path(), "-y", "-f", "lavfi", "-i", f"color=c={colors[i % len(colors)]}:s=1920x1080:d=1", "-frames:v", "1", photo], capture_output=True, timeout=60, check=True)
            scenes.append(PhotoScene(photo_path=str(photo), caption=scene.get("caption", ""),
                narration=scene.get("narration", ""), duration_s=float(scene.get("duration_s", 5)),
                motion=scene.get("motion", "kenburns")))
        voice = studio.resolver.resolve_tts_voice() if data.get("want_narration", True) else None
        profile = None
        if voice:
            engine = studio.voice_gallery().engine("piper")
            profile = VoiceProfile(engine_id="piper", voice_path=voice.path,
                capabilities=engine.capabilities if engine else EngineCapabilities(),
                expression=ExpressionSettings())
        config = ExportConfig(width=int(data.get("width", 1280)), height=int(data.get("height", 720)),
            fps=int(data.get("fps", 24)), preset="veryfast", want_narration=bool(profile),
            want_subtitles=bool(data.get("want_subtitles", True)))
        output_path = work / "studio_output.mp4"
        def progress(value, message):
            job.progress, job.stage = value, message
        result = StillVideoExporter(studio.renderer).export(scenes, work, str(output_path), config,
            voice_profile=profile, progress=progress)
        if result.ok:
            job.state, job.output_path, job.has_audio = "completed", result.output_path, result.has_audio
            job.has_subtitles, job.duration_s = result.has_subtitles, result.duration_s
            job.progress, job.stage = 1.0, "Completed and validated"
        else:
            job.state, job.blocker, job.fallback = "failed", result.blocker, result.suggested_fallback
    except Exception as exc:
        job.state, job.blocker = "failed", f"{type(exc).__name__}: {exc}"
