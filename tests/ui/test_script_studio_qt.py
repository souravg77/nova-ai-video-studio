"""The real PySide6 Script mode, driven headless with a fake local model.

Runs in a subprocess: other UI tests install a PySide6 stub into sys.modules.
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
    import json, sys, time
    from pathlib import Path
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from nova_studio.models.project import Project
    from nova_studio.performance.planner import DialogueLine
    from nova_studio.ui import script_studio as ss

    app = QApplication([])
    models = Path(sys.argv[1])
    out = {}

    # Fake local model: always "sadness / strong / slow".
    def fake_complete(_model_path):
        def complete(system, user):
            n = sum(1 for ln in user.splitlines() if ln[:1].isdigit())
            return json.dumps({"lines": [{"n": i + 1, "emotion": "sadness",
                                          "intensity": "strong", "pace": "slow"}
                                         for i in range(n)]})
        return complete
    ss.llama_complete = fake_complete

    p = Project()
    panel = ss.ScriptStudioPanel(p, models)
    out["no_model_reason"] = panel.suggest_btn.toolTip()
    out["suggest_enabled_before"] = panel.suggest_btn.isEnabled()

    panel.editor.setPlainText(
        "INT. HALL - NIGHT\\n\\nARTHUR\\nYou came back!\\n\\n"
        "ELAINE\\n(angrily)\\nI had to.\\n")
    out["breakdown_ok"] = panel.break_down()
    out["rows"] = panel.table.rowCount()
    out["line_col_width"] = panel.table.columnWidth(3)
    out["summary"] = panel.summary.text()
    out["characters"] = [(c.name, c.approved is None) for c in p.characters]
    out["row1_source"] = panel.table.item(1, ss._SRC).text()
    out["row1_emotion"] = panel.table.cellWidget(1, ss._EMO).currentText()

    # Pretend a model is installed, then run suggestions in the worker thread.
    ss.script_model_status = lambda d: ("C:/models/qwen2.5-1.5b.gguf", "")
    panel.refresh()
    out["suggest_enabled"] = panel.suggest_btn.isEnabled()
    panel.suggest()
    t0 = time.time()
    while panel._thread is not None and time.time() - t0 < 20:
        app.processEvents(); time.sleep(0.02)
    out["after_suggest"] = [(panel.table.item(r, ss._SRC).text(),
                             panel.table.cellWidget(r, ss._EMO).currentText())
                            for r in range(panel.table.rowCount())]
    out["status"] = panel.status.text()

    # The user picks a value: that line becomes theirs and approved.
    panel.table.cellWidget(0, ss._EMO).setCurrentText("happiness")
    out["row0_after_edit"] = (panel.table.item(0, ss._SRC).text(),
                              panel.table.item(0, ss._APP).text())

    # Plan approval needs every line approved.
    panel.toggle_plan()
    out["plan_refused"] = p.director.plan_approved
    panel.table.selectRow(1)
    panel.approve_selected()
    panel.toggle_plan()
    out["plan_approved"] = p.director.plan_approved
    out["breakdown_locked"] = not panel.breakdown_btn.isEnabled() and panel.editor.isReadOnly()
    panel.toggle_plan()

    # Hand-made dialogue is only replaced after confirmation.
    p.dialogue.append(DialogueLine(id="mine", order=9, speaker_id="x", text="Hand-made"))
    out["refused_without_confirm"] = panel.break_down(confirm=lambda m: False)
    out["kept_mine"] = any(d.id == "mine" for d in p.dialogue)
    out["replaced_with_confirm"] = panel.break_down(confirm=lambda m: True)
    out["mine_gone"] = not any(d.id == "mine" for d in p.dialogue)
    out["export_disabled_without_dir"] = not panel.animatic_btn.isEnabled()

    # Animatic export through the button, with a fake renderer (no FFmpeg).
    from nova_studio.media.renderer import RenderResult
    class FakeRenderer:
        ffmpeg = "unused"
        def render(self, spec, progress=None):
            out["rendered_scenes"] = len(spec.scenes)
            out["has_narration"] = spec.narration_path is not None
            return RenderResult(True, spec.output_path, duration_s=9.5)
    panel2 = ss.ScriptStudioPanel(p, models, export_dir=models / "exports",
                                  audio_dir=models / "dialogue",
                                  renderer_factory=FakeRenderer)
    out["export_enabled"] = panel2.animatic_btn.isEnabled()
    panel2.export_animatic()
    t0 = time.time()
    while panel2._export_thread is not None and time.time() - t0 < 20:
        app.processEvents(); time.sleep(0.02)
    out["export_status"] = panel2.status.text()
    print("RESULT " + json.dumps(out))
''')


def test_script_mode_end_to_end(tmp_path):
    probe = subprocess.run([sys.executable, "-c", "import PySide6.QtWidgets"],
                           capture_output=True)
    if probe.returncode != 0:
        pytest.skip("real PySide6 not installed")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(ROOT / "src"))
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    if fonts.is_dir():
        env["QT_QPA_FONTDIR"] = str(fonts)
    proc = subprocess.run([sys.executable, "-c", SCRIPT, str(tmp_path / "models")],
                          env=env, capture_output=True, text=True, timeout=120)
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, proc.stdout + proc.stderr
    out = json.loads(lines[0][len("RESULT "):])

    # No model installed: the button is off and says why.
    assert out["suggest_enabled_before"] is False
    assert out["no_model_reason"]

    assert out["breakdown_ok"] and out["rows"] == 2
    assert out["line_col_width"] >= 250      # dialogue stays readable
    assert "1 scene(s), 2 line(s)" in out["summary"]
    assert "New characters (unapproved): Arthur, Elaine." in out["summary"]
    assert out["characters"] == [["Arthur", True], ["Elaine", True]]
    assert (out["row1_source"], out["row1_emotion"]) == ("script", "anger")

    assert out["suggest_enabled"]
    # The model fills Arthur's line; Elaine's '(angrily)' stays the writer's.
    assert out["after_suggest"] == [["suggested", "sadness"], ["script", "anger"]]
    assert "1 line(s) suggested; 1 kept the script's direction" in out["status"]

    assert out["row0_after_edit"] == ["you", "yes"]
    assert out["plan_refused"] is False
    assert out["plan_approved"] is True and out["breakdown_locked"]
    assert out["refused_without_confirm"] is False and out["kept_mine"]
    assert out["replaced_with_confirm"] and out["mine_gone"]

    assert out["export_disabled_without_dir"] and out["export_enabled"]
    assert out["rendered_scenes"] >= 2 and out["has_narration"] is False
    assert "Animatic exported" in out["export_status"]
    assert "shown as text only (no audio)" in out["export_status"]   # nothing voiced
    assert "_animatic.mp4" in out["export_status"]
