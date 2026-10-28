"""Project store persistence + recovery."""
from nova_studio.models.job import Job, JobKind, JobState
from nova_studio.models.project import Project, Scene
from nova_studio.storage.sqlite_store import ProjectStore
from nova_studio.core.recovery import recover_interrupted_jobs


def test_project_roundtrip(tmp_path):
    store = ProjectStore(tmp_path / "db.sqlite3")
    p = Project(name="My Project")
    p.add_scene(Scene(title="S1", caption="hello"))
    store.save_project(p)
    loaded = store.load_project(p.id)
    assert loaded is not None
    assert loaded.name == "My Project"
    assert len(loaded.scenes) == 1
    assert loaded.scenes[0].caption == "hello"
    store.close()


def test_interrupted_job_recovery(tmp_path):
    store = ProjectStore(tmp_path / "db.sqlite3")
    job = Job(kind=JobKind.RENDER)
    job.mark_running()
    store.save_job(job)
    # Simulate restart: recover.
    recovered = recover_interrupted_jobs(store)
    assert job.id in recovered
    reloaded = store.load_job(job.id)
    assert reloaded.state == JobState.FAILED
    assert "Interrupted" in reloaded.blocker
    store.close()
