"""Workspace shell logic: honest modes, library, inspector and job rows."""
from types import SimpleNamespace

from nova_studio.models.job import Job, JobKind, JobLogEntry, JobState
from nova_studio.models.project import Asset, AssetKind, Project, Scene
from nova_studio.settings import AppSettings
from nova_studio.ui import workspace_logic as wl


def test_modes_follow_the_production_order_and_only_edit_is_built():
    assert [m.key for m in wl.MODES] == [
        "script", "characters", "storyboard", "generate", "edit"]
    assert [m.key for m in wl.MODES if m.built] == ["edit"]
    assert wl.DEFAULT_MODE == "edit"


def test_placeholders_say_what_is_missing_and_what_to_use_instead():
    for m in wl.MODES:
        if m.built:
            continue
        text = wl.placeholder_text(m)
        assert "not built yet" in text
        assert m.planned and m.planned in text
        assert m.meanwhile and m.meanwhile in text


def _project():
    p = Project(name="Short film")
    clip = p.add_asset(Asset(kind=AssetKind.VIDEO, path="C:/media/clip.mp4",
                             duration_s=2.5, width=1280, height=720,
                             codec="h264", valid=True))
    p.add_asset(Asset(kind=AssetKind.AUDIO, path="C:/media/voice.wav"))
    p.add_scene(Scene(title="Opening", visual_asset_id=clip.id, duration_s=4.0))
    p.add_scene(Scene(title="", duration_s=2.0))
    return p, clip


def test_library_lists_assets_and_scenes_in_order():
    p, _ = _project()
    entries = wl.library_entries(p)
    assert [e.group for e in entries] == ["Assets", "Assets", "Scenes", "Scenes"]
    assert entries[0].label == "[video] clip.mp4"
    assert entries[1].label.endswith("(not validated)")
    assert entries[2].label == "1. Opening (4s)"
    assert entries[3].label == "2. Untitled scene (2s)"


def test_library_includes_characters_when_the_project_has_them():
    char = SimpleNamespace(id="c1", name="Elaine",
                           model_dump=lambda: {"id": "c1", "name": "Elaine",
                                               "approved": True, "refs": []})
    p = SimpleNamespace(assets=[], scenes=[], characters=[char])
    entries = wl.library_entries(p)
    assert entries == [wl.LibraryEntry("Characters", "c1", "Elaine")]
    rows = dict(wl.inspector_rows(p, "Characters", "c1"))
    assert rows["Name"] == "Elaine" and rows["Approved"] == "yes"
    assert "Refs" not in rows


def test_inspector_rows_for_asset_and_scene():
    p, clip = _project()
    a = dict(wl.inspector_rows(p, "Assets", clip.id))
    assert a["Kind"] == "video" and a["Resolution"] == "1280x720"
    assert a["Duration (s)"] == "2.5" and a["Validated"] == "yes"
    s = dict(wl.inspector_rows(p, "Scenes", p.scenes[0].id))
    assert s["Order"] == "1" and s["Visual"] == "C:/media/clip.mp4"
    assert s["Narration"] == "-"
    assert wl.inspector_rows(p, "Assets", "missing") == []


def test_job_row_shows_blocker_before_log():
    job = Job(kind=JobKind.RENDER, state=JobState.RUNNING, progress=0.426,
              logs=[JobLogEntry(message="Render: encoding")])
    assert wl.job_row(job) == ("render", "running", "43%", "Render: encoding")
    job.blocker = "No voice installed"
    assert wl.job_row(job)[3] == "No voice installed"


def test_engines_summary_never_claims_an_unavailable_cloud_engine():
    s = AppSettings()
    assert wl.engines_summary(s, gemini_available=True) == "Local engines (offline)"
    s.cloud.gemini_enabled = True
    assert wl.engines_summary(s, gemini_available=False) == "Local engines (offline)"
    assert "gemini-omni-1.1-flash" in wl.engines_summary(s, gemini_available=True)


def test_library_signature_changes_only_with_content():
    p, _ = _project()
    sig = wl.library_signature(p)
    assert wl.library_signature(p) == sig
    p.scenes[1].title = "Ending"
    assert wl.library_signature(p) != sig
