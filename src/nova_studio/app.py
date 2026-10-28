"""Application entrypoint.

Launches the PySide6 desktop UI. If PySide6 is not installed it prints a clear
message and points to the headless hardware CLI, rather than crashing.
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:
        print("PySide6 is not installed. Install the UI environment:\n"
              "    python -m pip install -r requirements/ui.txt\n\n"
              "You can still run the headless hardware report:\n"
              "    python -m nova_studio.core.hardware_cli")
        return 1

    from .core.studio import Studio
    from .ui.main_window import MainWindow

    app = QApplication(argv if argv is not None else sys.argv)
    studio = Studio()
    window = MainWindow(studio)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
