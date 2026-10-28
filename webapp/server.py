"""Flask backend for the NOVA Studio dashboard.

Serves the dashboard and exposes a small JSON API that drives the REAL,
tested NOVA engine (hardware detection, voices, photo intake, still-video
export). It binds to 127.0.0.1 only — this is a local desktop app, not a
public server.

Every endpoint is honest: capability states, blockers and validation come
from the same modules the test suite covers. Rendering produces a real,
validated MP4 via phase4.still_video.StillVideoExporter.
"""
from __future__ import annotations

import sys
import threading
import uuid
from pathlib import Path

# Make the bundled src importable whether run from source or frozen.
_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from flask import (Flask, jsonify, request, send_from_directory,  # noqa: E402
                   send_file, abort)

STATIC = _HERE / "static"


def _add_piper_to_path(models_dir: Path) -> None:
    """Prepend the downloaded Piper engine dir (if any) to PATH."""
    import os
    piper_root = Path(models_dir) / "tts" / "piper"
    if not piper_root.exists():
        return
    # The archive may extract into tts/piper/ or tts/piper/piper/.
    for cand in (piper_root, piper_root / "piper"):
        exe = cand / ("piper.exe" if os.name == "nt" else "piper")
        if exe.exists():
            os.environ["PATH"] = str(cand) + os.pathsep + os.environ.get("PATH", "")
            return


def _cpu_percent() -> int:
    try:
        import psutil  # optional
        return int(psutil.cpu_percent(interval=0.1))
    except Exception:
        # Lightweight estimate from load average when psutil is absent.
        try:
            import os
            la = os.getloadavg()[0]
            cores = os.cpu_count() or 1
            return min(99, int(la / cores * 100))
        except Exception:
            return 0


class RenderJob:
    def __init__(self, job_id: str) -> None:
        self.id = job_id
        self.state = "running"      # running | completed | failed
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

    ws = workspace or (Path.home() / ".nova_home")
    cfg = AppConfig(paths=Paths.create(ws))

    # If the user downloaded the Piper engine via the AI Models panel, it lives
    # in <models>/tts/piper. Put it on PATH so narration finds it.
    _add_piper_to_path(cfg.paths.models)

    studio = Studio(cfg)

    app = Flask(__name__, static_folder=None)
    jobs: dict[str, RenderJob] = {}

    # ---- static ------------------------------------------------------
    @app.route("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.route("/<path:path>")
    def assets(path):
        target = STATIC / path
        if not target.exists():
            abort(404)
        return send_from_directory(STATIC, path)

    # ---- API ---------------------------------------------------------
    @app.route("/api/hardware")
    def hardware():
        r = studio.report
        reg = studio.generation_registry(installed_ids={"sadtalker"})
        th = reg.decide("sadtalker")
        return jsonify({
            "cpu_name": r.cpu_name,
            "cpu_pct": _cpu_percent(),
            "ram_gb": r.physical_ram_gb,
            "has_gpu": r.has_nvidia_cuda,
            "render_ready": "ffmpeg" in r.backends_available,
            "summary": r.human_summary(),
            "talking_head_supported": th.can_attempt,
            "talking_head_blocker": th.blocker,
        })

    @app.route("/api/voices")
    def voices():
        gallery = studio.voice_gallery()
        names = []
        for e in gallery.engines:
            if e.available:
                for v in e.voices:
                    names.append(f"{e.display_name}: {v.name}")
        return jsonify({"voices": names,
                        "engines": [{"id": e.engine_id, "available": e.available,
                                     "reason": e.reason} for e in gallery.engines]})

    @app.route("/api/audition", methods=["POST"])
    def audition():
        data = request.get_json(force=True, silent=True) or {}
        voice = studio.resolver.resolve_tts_voice()
        if not voice:
            return jsonify({"ok": False,
                            "message": "No Piper voice installed (add one to "
                                       "models/tts)."})
        from nova_studio.voice.expression import ExpressionSettings
        res = studio.audition_voice(
            "piper", voice.path, text=data.get("text", "NOVA voice preview."),
            expression=ExpressionSettings(speed=float(data.get("speed", 1.0))))
        return jsonify(res)

    # ---- media upload + serving --------------------------------------
    media_dir = ws / "studio_media"
    media_dir.mkdir(parents=True, exist_ok=True)
    media: dict[str, dict] = {}   # id -> {path, kind, name, w, h, dur}

    _IMG = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"}
    _VID = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
    _AUD = {".wav", ".mp3", ".aac", ".m4a", ".flac", ".ogg"}

    @app.route("/api/upload", methods=["POST"])
    def upload():
        from nova_studio.media.probe import probe
        from werkzeug.utils import secure_filename
        saved = []
        for f in request.files.getlist("files"):
            name = secure_filename(f.filename or "file")
            ext = Path(name).suffix.lower()
            kind = ("image" if ext in _IMG else "video" if ext in _VID
                    else "audio" if ext in _AUD else None)
            if kind is None:
                saved.append({"ok": False, "name": name,
                              "message": f"Unsupported type {ext}"})
                continue
            mid = uuid.uuid4().hex[:12]
            dest = media_dir / f"{mid}{ext}"
            f.save(str(dest))
            info = probe(dest)
            entry = {"id": mid, "path": str(dest), "kind": kind, "name": name,
                     "w": info.width, "h": info.height,
                     "dur": info.duration_s, "ok": info.ok}
            media[mid] = entry
            saved.append({**entry, "url": f"/api/media/{mid}"})
        return jsonify({"files": saved})

    def _register_media(src: Path, name: str) -> dict:
        from nova_studio.media.probe import probe
        ext = src.suffix.lower()
        kind = ("image" if ext in _IMG else "video" if ext in _VID
                else "audio" if ext in _AUD else None)
        if kind is None:
            return {"ok": False, "name": name, "message": f"Unsupported {ext}"}
        mid = uuid.uuid4().hex[:12]
        import shutil
        dest = media_dir / f"{mid}{ext}"
        shutil.copyfile(str(src), str(dest))
        info = probe(dest)
        entry = {"id": mid, "path": str(dest), "kind": kind, "name": name,
                 "w": info.width, "h": info.height, "dur": info.duration_s,
                 "ok": info.ok}
        media[mid] = entry
        return {**entry, "url": f"/api/media/{mid}"}

    @app.route("/api/import_paths", methods=["POST"])
    def import_paths():
        """Import files chosen via the native file dialog (local paths)."""
        data = request.get_json(force=True, silent=True) or {}
        saved = []
        for raw in data.get("paths", []):
            p = Path(raw)
            if not p.exists():
                saved.append({"ok": False, "name": raw,
                              "message": "File not found"})
                continue
            saved.append(_register_media(p, p.name))
        return jsonify({"files": saved})

    @app.route("/api/media/<mid>")
    def serve_media(mid):
        entry = media.get(mid)
        if not entry or not Path(entry["path"]).exists():
            abort(404)
        return send_file(entry["path"])

    @app.route("/api/thumb/<mid>")
    def thumb(mid):
        """A JPEG thumbnail for an image or the first video frame."""
        entry = media.get(mid)
        if not entry:
            abort(404)
        if entry["kind"] == "image":
            return send_file(entry["path"])
        # extract a frame from video/audio-cover via ffmpeg
        from nova_studio.media.probe import ffmpeg_path
        import subprocess
        tp = media_dir / f"{mid}_thumb.jpg"
        if not tp.exists():
            subprocess.run([ffmpeg_path(), "-y", "-i", entry["path"],
                            "-frames:v", "1", "-vf", "scale=160:-1", str(tp)],
                           capture_output=True, timeout=30)
        if tp.exists():
            return send_file(str(tp))
        abort(404)

    # ---- AI model downloader -----------------------------------------
    from webapp.models import ModelDownloader
    downloader = ModelDownloader(studio.config.paths.models)

    @app.route("/api/models/status")
    def models_status():
        return jsonify(downloader.status(studio.resolver))

    @app.route("/api/models/download", methods=["POST"])
    def models_download():
        data = request.get_json(force=True, silent=True) or {}
        key = data.get("key", "")
        try:
            downloader.start(key)
        except KeyError:
            return jsonify({"ok": False, "message": f"Unknown model '{key}'."})
        # A fresh model changes capability; refresh once it lands (polled by UI).
        return jsonify({"ok": True})

    @app.route("/api/models/refresh", methods=["POST"])
    def models_refresh():
        _add_piper_to_path(studio.config.paths.models)
        studio.refresh_pipeline()
        return jsonify({"ok": True})

    @app.route("/api/script", methods=["POST"])
    def script():
        """Auto-write per-scene narration from a brief using the local LLM.

        Returns an honest blocker when the Qwen model/runtime is not installed.
        """
        data = request.get_json(force=True, silent=True) or {}
        brief = (data.get("brief") or "").strip()
        n = int(data.get("scenes", 3))
        if not brief:
            return jsonify({"ok": False, "message": "Enter a topic first."})
        from nova_studio.adapters.llm import ScriptAdapter
        model = studio.resolver.resolve_script_model()
        adapter = ScriptAdapter(model_path=model.path if model else None)
        avail = adapter.availability()
        if not avail.available:
            return jsonify({"ok": False, "message": avail.reason,
                            "need_download": True})
        res = adapter.run({"brief": brief, "scenes": n})
        if not res.ok:
            return jsonify({"ok": False, "message": res.message})
        scenes = res.metrics.get("scenes", [])
        return jsonify({"ok": True, "scenes": scenes})

    @app.route("/api/render", methods=["POST"])
    def render():
        data = request.get_json(force=True, silent=True) or {}
        # Resolve media ids in scenes to real file paths.
        for sc in data.get("scenes", []):
            mid = sc.get("media_id")
            if mid and mid in media:
                sc["photo_path"] = media[mid]["path"]
        job_id = uuid.uuid4().hex[:12]
        job = RenderJob(job_id)
        jobs[job_id] = job
        threading.Thread(target=_run_render, args=(studio, data, job, ws),
                         daemon=True).start()
        return jsonify({"job_id": job_id})

    @app.route("/api/job/<job_id>")
    def job_status(job_id):
        job = jobs.get(job_id)
        if not job:
            abort(404)
        out = {
            "state": job.state, "progress": job.progress, "stage": job.stage,
            "blocker": job.blocker, "fallback": job.fallback,
            "has_audio": job.has_audio, "has_subtitles": job.has_subtitles,
            "duration_s": job.duration_s,
        }
        if job.state == "completed":
            out["output_url"] = f"/api/output/{job_id}"
            out["output_path"] = job.output_path
        return jsonify(out)

    @app.route("/api/output/<job_id>")
    def output(job_id):
        job = jobs.get(job_id)
        if not job or not job.output_path or not Path(job.output_path).exists():
            abort(404)
        return send_file(job.output_path, mimetype="video/mp4")

    return app


def _run_render(studio, data: dict, job: "RenderJob", ws: Path) -> None:
    """Drive the real still-video exporter; update the job as it progresses."""
    from nova_studio.phase4.still_video import (ExportConfig, PhotoScene,
                                               StillVideoExporter)
    from nova_studio.voice.narration import VoiceProfile
    from nova_studio.voice.engine import EngineCapabilities
    from nova_studio.voice.expression import ExpressionSettings

    try:
        work = ws / "studio_render" / job.id
        work.mkdir(parents=True, exist_ok=True)

        # Use each scene's real uploaded image when present; only fall back to
        # a solid colour slate for scenes the user left without media.
        from nova_studio.media.probe import ffmpeg_path
        import subprocess
        scenes_in = data.get("scenes", [])
        colours = ["0x1a2b4c", "0x1f5130", "0x4a2a6a", "0x25507a"]
        scenes = []
        for i, s in enumerate(scenes_in):
            src = s.get("photo_path")
            if src and Path(src).exists():
                photo = src
            else:
                photo = str(work / f"slate_{i}.png")
                subprocess.run([ffmpeg_path(), "-y", "-f", "lavfi",
                                "-i", f"color=c={colours[i % 4]}:s=1920x1080:d=1",
                                "-frames:v", "1", photo],
                               capture_output=True, timeout=60)
            scenes.append(PhotoScene(
                photo_path=photo,
                caption=s.get("caption", ""), narration=s.get("narration", ""),
                duration_s=float(s.get("duration_s", 5)),
                motion=s.get("motion", "kenburns")))

        want_narr = bool(data.get("want_narration", True))
        voice = studio.resolver.resolve_tts_voice()
        profile = None
        if want_narr and voice:
            gallery = studio.voice_gallery()
            eng = gallery.engine("piper")
            profile = VoiceProfile(
                engine_id="piper", voice_path=voice.path,
                capabilities=eng.capabilities if eng else EngineCapabilities(),
                expression=ExpressionSettings())
        elif want_narr and not voice:
            # Honest: no voice installed -> captions-only, say so (no fake audio)
            want_narr = False

        cfg = ExportConfig(
            width=int(data.get("width", 1280)),
            height=int(data.get("height", 720)),
            fps=int(data.get("fps", 24)), preset="veryfast",
            want_narration=want_narr,
            want_subtitles=bool(data.get("want_subtitles", True)))

        out = work / "studio_output.mp4"

        def prog(p, m):
            job.progress = p
            job.stage = m

        exporter = StillVideoExporter(studio.renderer)
        result = exporter.export(scenes, work, str(out), cfg,
                                 voice_profile=profile, progress=prog)
        if result.ok:
            job.state = "completed"
            job.output_path = result.output_path
            job.has_audio = result.has_audio
            job.has_subtitles = result.has_subtitles
            job.duration_s = result.duration_s
            job.progress = 1.0
            job.stage = "Completed and validated"
        else:
            job.state = "failed"
            job.blocker = result.blocker
            job.fallback = result.suggested_fallback
    except Exception as exc:  # pragma: no cover - defensive
        job.state = "failed"
        job.blocker = f"{type(exc).__name__}: {exc}"
