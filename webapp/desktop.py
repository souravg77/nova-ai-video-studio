"""NOVA Studio desktop launcher — opens the dashboard in a native window.

This is the app entry point for the Windows build. It:
  * starts the Flask backend on a free 127.0.0.1 port in a background thread,
  * opens a native desktop window (pywebview) pointed at it — NO console, NO
    browser chrome, NO command prompt, and
  * exposes a small JS API for a NATIVE file-open dialog and for opening the
    finished video in the system player, so the app never has to rely on the
    WebView2 HTML file dialog (which can pop a blank secondary window).

The frozen .exe runs this with a windowed bootloader, so nothing shows on
screen except the NOVA Studio window itself.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _workspace() -> Path:
    try:
        from platformdirs import user_data_dir
        return Path(user_data_dir("NovaStudio", "NovaStudio"))
    except Exception:
        return Path.home() / ".nova_home"


def _serve(app, port: int) -> None:
    try:
        from waitress import serve
        serve(app, host="127.0.0.1", port=port, threads=8)
    except Exception:
        app.run(host="127.0.0.1", port=port, threaded=True,
                debug=False, use_reloader=False)


def _wait_ready(port: int, timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.15)
    return False


class JsApi:
    """Exposed to the page as window.pywebview.api.* — native integrations."""

    def __init__(self) -> None:
        self._window = None

    def set_window(self, window) -> None:
        self._window = window

    # Native "open file" dialog -> returns a list of local file paths.
    def pick_files(self, kinds: str = "all") -> list[str]:
        try:
            import webview
            if kinds == "image":
                ft = ("Images (*.png;*.jpg;*.jpeg;*.bmp;*.webp;*.gif)",)
            elif kinds == "audio":
                ft = ("Audio (*.wav;*.mp3;*.aac;*.m4a;*.flac;*.ogg)",)
            elif kinds == "video":
                ft = ("Video (*.mp4;*.mov;*.mkv;*.avi;*.webm;*.m4v)",)
            else:
                ft = ("Media (*.png;*.jpg;*.jpeg;*.bmp;*.webp;*.gif;"
                      "*.mp4;*.mov;*.mkv;*.avi;*.webm;*.m4v;"
                      "*.wav;*.mp3;*.aac;*.m4a;*.flac;*.ogg)",
                      "All files (*.*)")
            result = self._window.create_file_dialog(
                webview.OPEN_DIALOG, allow_multiple=True, file_types=ft)
            return list(result or [])
        except Exception:
            return []

    # Open a finished file (the rendered video) in the OS default player.
    def open_path(self, path: str) -> bool:
        try:
            p = str(Path(path))
            if os.name == "nt":
                os.startfile(p)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", p])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", p])
            return True
        except Exception:
            return False


def main() -> int:
    from webapp.server import create_app

    port = _free_port()
    app = create_app(workspace=_workspace())
    threading.Thread(target=_serve, args=(app, port), daemon=True).start()
    if not _wait_ready(port):
        print("NOVA Studio failed to start its local server.", file=sys.stderr)
        return 1

    url = f"http://127.0.0.1:{port}/"

    try:
        import webview
        api = JsApi()
        window = webview.create_window(
            "NOVA Studio", url, js_api=api, width=1480, height=920,
            min_size=(1100, 720), background_color="#0b0e14")
        api.set_window(window)
        # Keep everything in one window: block pop-ups / new-window requests.
        try:
            webview.settings["ALLOW_DOWNLOADS"] = False
        except Exception:
            pass
        webview.start()  # blocks until the window closes
        return 0
    except Exception:
        import webbrowser
        webbrowser.open(url)
        print(f"NOVA Studio is running at {url} (press Ctrl+C to stop).")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
