"""Frozen Windows launcher entry point.

Used as the PyInstaller entry script. It:
  * makes a bundled FFmpeg/FFprobe discoverable (the installer ships them next
    to the exe, or in a 'ffmpeg' subfolder), and
  * launches the PySide6 GUI.

Running from source, this behaves exactly like `python -m nova_studio.app`.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _bundle_dir() -> Path:
    """Directory of the running app (frozen exe dir, or the source tree)."""
    if getattr(sys, "frozen", False):
        # PyInstaller sets sys._MEIPASS for the temp extract dir, but bundled
        # external tools (FFmpeg) live next to the exe in an onedir build.
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _ensure_ffmpeg_on_path() -> None:
    """Prepend a bundled FFmpeg location to PATH if present.

    Looks for ffmpeg(.exe) next to the app and in a 'ffmpeg'/'ffmpeg/bin'
    subfolder. If none is found, PATH is left as-is (the app will then report a
    clear FFmpeg-missing error at render time).
    """
    base = _bundle_dir()
    candidates = [base, base / "ffmpeg", base / "ffmpeg" / "bin"]
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    for d in candidates:
        if (d / exe).exists():
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
            return


def main() -> int:
    _ensure_ffmpeg_on_path()
    # Import after PATH is set so the media layer sees the bundled FFmpeg.
    from nova_studio.app import main as app_main
    return app_main([sys.argv[0]])


if __name__ == "__main__":
    raise SystemExit(main())
