"""The real PySide6 Setup & Diagnostics dialog, driven headless.

Runs in a subprocess: other UI tests install a PySide6 stub into sys.modules,
so the real Qt must not be imported into this test process.
"""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

SCRIPT = textwrap.dedent('''
    import json, sys
    from pathlib import Path
    from PySide6.QtWidgets import QApplication
    from nova_studio import config
    from nova_studio.core.capability import CapabilityManager
    from nova_studio.models.hardware_report import HardwareReport
    from nova_studio.models.registry import default_registry
    from nova_studio.settings import load_settings
    from nova_studio.ui.setup_dialog import SetupDialog

    ws = Path(sys.argv[1])
    app = QApplication([])
    report = HardwareReport(physical_ram_mb=32000, backends_available=[])

    class FakeStudio:
        pass
    studio = FakeStudio()
    studio.config = config.AppConfig(paths=config.Paths.create(ws)).ensure()
    studio.report = report
    studio.capability = CapabilityManager(report, registry=default_registry())

    out = {}
    dlg = SetupDialog(studio, first_run=True)
    out["n_items"] = len(dlg.items)
    out["keys"] = [i.key for i in dlg.items]
    out["gemini_widget_enabled"] = dlg.gemini_check.isEnabled()
    out["gemini_checked"] = dlg.gemini_check.isChecked()
    out["preview_widget_enabled"] = dlg.preview_check.isEnabled()
    out["default_models"] = dlg.collect_settings().models_dir
    out["min_width"] = dlg.minimumSizeHint().width()
    dlg.reject()
    out["seen_after_close"] = load_settings(ws).first_run_complete

    dlg2 = SetupDialog(studio)
    dlg2.models_edit.setText(str(ws / "elsewhere"))
    dlg2.accept()
    out["saved_models"] = load_settings(ws).models_dir
    out["restart_needed"] = dlg2.restart_needed
    print("RESULT " + json.dumps(out))
''')


def test_setup_dialog_end_to_end(tmp_path):
    probe = subprocess.run([sys.executable, "-c", "import PySide6.QtWidgets"],
                           capture_output=True)
    if probe.returncode != 0:
        pytest.skip("real PySide6 not installed")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
               PYTHONPATH=str(ROOT / "src"))
    env.pop("NOVA_GEMINI_API_KEY", None)
    # The offscreen platform has no fonts of its own; without real fonts every
    # glyph is a placeholder box and widths are meaningless.
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    if fonts.is_dir():
        env["QT_QPA_FONTDIR"] = str(fonts)
    ws = tmp_path / "ws"
    proc = subprocess.run([sys.executable, "-c", SCRIPT, str(ws)], env=env,
                          capture_output=True, text=True, timeout=120)
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, proc.stdout + proc.stderr
    out = json.loads(lines[0][len("RESULT "):])

    assert out["n_items"] >= 8
    for key in ("hardware", "ffmpeg", "workspace", "models_dir", "offline", "gemini"):
        assert key in out["keys"]
    # The Gemini adapter ships now: a real switch, off by default.
    assert out["gemini_widget_enabled"] is True and out["gemini_checked"] is False
    # Engines that are not in this build are shown disabled, never as switches.
    assert out["preview_widget_enabled"] is False
    assert out["default_models"] is None
    # Long unwrappable text must not force the dialog wider than a laptop screen.
    if fonts.is_dir():
        assert out["min_width"] < 900, out["min_width"]
    assert out["seen_after_close"] is True
    assert Path(out["saved_models"]) == ws / "elsewhere"
    assert out["restart_needed"] is True
