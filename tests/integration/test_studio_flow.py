"""End-to-end: Studio drives import -> queue render -> validated output."""
import threading

import pytest

from nova_studio.core.studio import Studio
from nova_studio.models.job import JobState, GenerationState
from nova_studio.models.project import Scene

pytestmark = pytest.mark.integration


def test_full_render_flow(app_config, assets):
    s = Studio(app_config)
    try:
        p = s.new_project("FlowTest")
        img = s.import_media(p, str(assets["img"]))
        clip = s.import_media(p, str(assets["clip"]))
        s.import_media(p, str(assets["narr"]))
        p.target_width, p.target_height, p.target_fps = 640, 360, 24
        p.add_scene(Scene(title="A", caption="one", visual_asset_id=img.id,
                          duration_s=2, motion_effect="kenburns"))
        p.add_scene(Scene(title="B", caption="two", visual_asset_id=clip.id,
                          duration_s=2))
        s.save_project(p)

        done = threading.Event()
        box = {}

        def listener(job):
            if job.state in (JobState.COMPLETED, JobState.FAILED,
                             JobState.CANCELLED):
                box["job"] = job
                done.set()

        s.render_project(p, listener=listener, preset="ultrafast")
        assert done.wait(timeout=120), "render did not finish"
        job = box["job"]
        assert job.state == JobState.COMPLETED
        assert job.generation_state == GenerationState.COMPLETED_AND_VALIDATED
        assert job.outputs
        from pathlib import Path
        assert Path(job.outputs[0]).exists()

        # Persistence: reopen.
        reopened = s.store.load_project(p.id)
        assert reopened.name == "FlowTest"
        assert len(reopened.scenes) == 2
    finally:
        s.shutdown()


def test_import_rejects_bad_file(app_config, tmp_path):
    s = Studio(app_config)
    try:
        bad = tmp_path / "notmedia.xyz"
        bad.write_text("nope")
        p = s.new_project("RejectTest")
        with pytest.raises(ValueError):
            s.import_media(p, str(bad))
    finally:
        s.shutdown()
