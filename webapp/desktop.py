"""NOVA Studio desktop launcher — opens the dashboard in a native window.

This is the app entry point for the Windows build. It:
  * starts the Flask backend on a free 127.0.0.1 port in a background thread,
  * opens a native desktop window (pywebview) pointed at it — NO console, NO
    browser chrome, NO command prompt, and
  * falls back to the default browser only if pywebview is unavailable.

The frozen .exe runs this with a windowed bootloader, so nothing shows on
screen except the NOVA Studio window itself.
"""
from __future__ import annotations

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
    # Prefer waitress (production-grade, bundled on Windows); fall back to
    # Flask's dev server. threaded=True so renders don't block the UI.
    try:
        from waitress import serve
        serve(app, host="127.0.0.1", port=port, threads=8)
    except Exception:
        app.run(host="127.0.0.1", port=port, threaded=True,
                debug=False, use_reloader=False)


def _wait_ready(port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.15)
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
        import webview  # pywebview
        window = webview.create_window(
            "NOVA Studio", url, width=1480, height=920, min_size=(1100, 720),
            background_color="#0b0e14")
        webview.start()  # blocks until the window closes
        return 0
    except Exception:
        # No native webview available: open the default browser instead.
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
