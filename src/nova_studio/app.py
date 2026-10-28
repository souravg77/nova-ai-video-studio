"""Application entrypoint.

Launches the PySide6 desktop UI. If PySide6 is not installed it prints a clear
message and points to the headless hardware CLI, rather than crashing.
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv
    # Hardware report, used by the Start Menu "Hardware report" shortcut:
    # NOVA-Studio.exe --hardware. The exe is windowed (no console), so when a
    # GUI is available the report is shown in a dialog; otherwise it prints.
    if "--hardware" in args[1:]:
        return _hardware_report(args)

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


def _hardware_report(argv: list[str]) -> int:
    """Build the hardware report text and show it in a dialog (GUI) or print."""
    from .core.hardware import collect_hardware_report
    from .core.capability import CapabilityManager, Profile
    from .models.registry import default_registry

    report = collect_hardware_report()
    mgr = CapabilityManager(report, registry=default_registry())
    tier = mgr.detected_tier()
    eff, reason = mgr.select_profile(Profile.AUTO)
    text = (
        f"{report.human_summary()}\n\n"
        f"Installed RAM: {report.physical_ram_gb} GB\n"
        f"Detected tier: {int(tier)} ({tier.name})\n"
        f"Auto profile: {eff.value}\n{reason}"
    )
    if report.warnings:
        text += "\n\nNotices:\n" + "\n".join(f"- {w}" for w in report.warnings)

    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication(argv[:1])
        box = QMessageBox()
        box.setWindowTitle("NOVA - Hardware report")
        box.setText(text)
        box.exec()
        return 0
    except Exception:
        print(text)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
