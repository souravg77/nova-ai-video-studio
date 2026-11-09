"""The real PySide6 workspace shell, driven headless with a real Studio.

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
    import json
    from PySide6.QtWidgets import QApplication, QLabel
    from nova_studio.core.studio import Studio
    from nova_studio.models.job import Job, JobKind, JobState
    from nova_studio.models.project import Scene
    from nova_studio.settings import load_settings
    from nova_studio.ui.workspace import WorkspaceWindow

    app = QApplication([])
    out = {}
    studio = Studio()
    win = WorkspaceWindow(studio)
    win.show(); app.processEvents()

    tabs = win.tabs
    text = lambda i: tabs.tabText(i).replace("&&", "&")
    out["titles"] = [text(i) for i in range(tabs.count())]
    out["current"] = text(tabs.currentIndex())
    out["raw_edit_title"] = tabs.tabText(win._tab_index["edit"])
    out["edit_is_editor"] = tabs.widget(win._tab_index["edit"]) is win.editor

    win.resize(1400, 860)
    win.show_mode("script"); app.processEvents()
    body = tabs.currentWidget().findChild(QLabel, "placeholder_body")
    out["placeholder_fits"] = body.height() >= body.heightForWidth(body.width())
    out["placeholder_text"] = body.text()
    win.show_mode("edit"); app.processEvents()

    # Characters mode is mounted at start-up with the real panels.
    perf = tabs.widget(win._tab_index["characters"])
    out["perf_tabs"] = [perf.tabText(i) for i in range(perf.count())]
    out["perf_video_engines"] = [perf.shots.engine_combos["video"].itemText(i)
                                 for i in range(perf.shots.engine_combos["video"].count())]
    perf.characters.name_edit.setText("Maya"); perf.characters.add_btn.click()
    win._poll_project(); app.processEvents()
    out["character_in_project"] = [c.name for c in win.project.characters]

    # Mount point: a real panel replaces a mode's widget.
    panel = QLabel("character panel")
    win.set_tab_widget("characters", panel)
    out["after_mount"] = [text(i) for i in range(tabs.count())]
    out["mounted"] = tabs.widget(win._tab_index["characters"]) is panel
    out["current_kept"] = text(tabs.currentIndex())
    try:
        win.set_tab_widget("nope", QLabel())
        out["unknown_mode_rejected"] = False
    except KeyError:
        out["unknown_mode_rejected"] = True

    win.show_mode("storyboard")
    out["switched"] = text(tabs.currentIndex())

    # Library + inspector follow the project.
    win.project.add_scene(Scene(title="Opening", duration_s=3.0))
    win._poll_project(); app.processEvents()
    top = [win.library.topLevelItem(i).text(0) for i in range(win.library.topLevelItemCount())]
    out["library_top"] = top
    scenes = win.library.topLevelItem(top.index("Scenes"))
    win.library.setCurrentItem(scenes.child(0)); app.processEvents()
    out["inspector"] = {win.inspector.item(r, 0).text(): win.inspector.item(r, 1).text()
                        for r in range(win.inspector.rowCount())}

    # Jobs panel: insert then update in place.
    job = Job(kind=JobKind.RENDER, state=JobState.QUEUED)
    win._upsert_job(job)
    job.state, job.progress = JobState.RUNNING, 0.5
    win._upsert_job(job)
    out["job_rows"] = win.jobs.rowCount()
    out["job_state"] = win.jobs.item(0, 1).text()
    out["job_progress"] = win.jobs.item(0, 2).text()

    win.save_project()
    out["saved_label"] = win.save_label.text()
    out["engines"] = win.engines_label.text()

    win.close(); app.processEvents()
    s = load_settings(studio.config.paths.workspace)
    out["layout_saved"] = bool(s.workspace_state and s.workspace_geometry)
    out["queue_stopped"] = studio.queue._stop.is_set()
    print("RESULT " + json.dumps(out))
''')


def test_workspace_shell_end_to_end(tmp_path):
    probe = subprocess.run([sys.executable, "-c", "import PySide6.QtWidgets"],
                           capture_output=True)
    if probe.returncode != 0:
        pytest.skip("real PySide6 not installed")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
               PYTHONPATH=str(ROOT / "src"),
               NOVA_STUDIO_HOME=str(tmp_path / "home"))
    env.pop("NOVA_GEMINI_API_KEY", None)
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    if fonts.is_dir():
        env["QT_QPA_FONTDIR"] = str(fonts)
    proc = subprocess.run([sys.executable, "-c", SCRIPT], env=env,
                          capture_output=True, text=True, timeout=180)
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, proc.stdout + proc.stderr
    out = json.loads(lines[0][len("RESULT "):])

    assert out["titles"] == [
        "Script (not built yet)", "Characters",
        "Storyboard (not built yet)", "Generate (not built yet)", "Edit & render"]
    assert out["current"] == "Edit & render" and out["edit_is_editor"]
    # A literal ampersand, not a keyboard-mnemonic underline.
    assert out["raw_edit_title"] == "Edit && render"

    # Placeholder text is complete and not clipped.
    assert out["placeholder_fits"]
    assert "Auto video from brief" in out["placeholder_text"]
    assert out["after_mount"][1] == "Characters" and out["mounted"]
    assert out["after_mount"][0] == "Script (not built yet)"
    assert out["current_kept"] == "Edit & render"
    assert out["unknown_mode_rejected"]
    assert out["switched"] == "Storyboard (not built yet)"

    assert out["perf_tabs"] == ["Character Studio", "Shot plan"]
    assert out["perf_video_engines"][0] == "(none)"
    assert "switched off" in out["perf_video_engines"][1]
    assert out["character_in_project"] == ["Maya"]
    assert "Scenes" in out["library_top"]
    assert out["inspector"]["Title"] == "Opening"
    assert out["inspector"]["Duration (s)"] == "3"

    assert out["job_rows"] == 1
    assert (out["job_state"], out["job_progress"]) == ("running", "50%")

    assert out["saved_label"].startswith("Saved ")
    assert out["engines"] == "Local engines (offline)"
    assert out["layout_saved"] and out["queue_stopped"]
