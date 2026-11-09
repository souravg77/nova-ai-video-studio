"""Regressions found by the end-to-end studio review (2026-11-09)."""
import json
import threading

from nova_studio.adapters.llm import parse_scenes, scenes_schema
from nova_studio.core.job_queue import JobQueue
from nova_studio.models.job import Job, JobKind, JobState
from nova_studio.storage.asset_registry import safe_filename
from nova_studio.storage.sqlite_store import ProjectStore


def test_safe_filename_for_windows():
    assert safe_filename("My film: part 1?") == "My film- part 1"
    assert safe_filename(r'a<b>c"d/e\f|g*h') == "a-b-c-d-e-f-g-h"
    assert safe_filename("Ending...  ") == "Ending"
    assert safe_filename("CON") == "CON_"
    assert safe_filename("nul.txt") == "nul.txt_"
    assert safe_filename("   ") == "output"
    assert safe_filename(None, "auto_video") == "auto_video"
    assert safe_filename("???", "photo_video") == "photo_video"
    assert len(safe_filename("x" * 300)) == 80


def test_job_listener_sees_only_its_job_and_is_removed_when_done(tmp_path):
    q = JobQueue(ProjectStore(tmp_path / "db.sqlite3"))
    seen = []
    a, b = Job(kind=JobKind.RENDER), Job(kind=JobKind.RENDER)
    q.watch(a.id, lambda j: seen.append((j.id, j.state)))
    q._notify(b)                                   # another job: ignored
    a.state = JobState.RUNNING
    q._notify(a)
    a.state = JobState.COMPLETED
    q._notify(a)
    assert seen == [(a.id, JobState.RUNNING), (a.id, JobState.COMPLETED)]
    assert q._listeners == []                      # removed after finishing


def test_listener_errors_do_not_keep_it_registered(tmp_path):
    q = JobQueue(ProjectStore(tmp_path / "db.sqlite3"))
    job = Job(kind=JobKind.RENDER, state=JobState.FAILED)

    def boom(j):
        raise RuntimeError("UI closed")
    q.watch(job.id, boom)
    q._notify(job)
    assert q._listeners == []


def test_script_adapter_accepts_schema_constrained_reply():
    reply = json.dumps({"scenes": [
        {"title": "Dawn", "narration": "The lamp goes out.", "caption": "Dawn"},
        {"title": "Sea", "narration": "Waves.", "caption": ""}]})
    assert [s["title"] for s in parse_scenes(reply, 2)] == ["Dawn", "Sea"]
    sch = scenes_schema(3)["properties"]["scenes"]
    assert sch["minItems"] == sch["maxItems"] == 3
    # Old-style bare arrays still parse.
    assert parse_scenes('[{"title": "A", "narration": "n", "caption": "c"}]', 1)[0]["title"] == "A"


def test_piper_installed_by_nova_is_found(tmp_path, monkeypatch):
    import os
    import shutil
    from nova_studio.core.model_resolver import ensure_piper_on_path
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert ensure_piper_on_path(tmp_path / "models") is None
    exe_dir = tmp_path / "models" / "tts" / "piper" / "piper"
    exe_dir.mkdir(parents=True)
    exe = exe_dir / ("piper.exe" if os.name == "nt" else "piper")
    exe.write_bytes(b"")
    exe.chmod(0o755)
    assert ensure_piper_on_path(tmp_path / "models") == exe_dir
    assert shutil.which("piper") is not None
    before = os.environ["PATH"]
    ensure_piper_on_path(tmp_path / "models")       # idempotent
    assert os.environ["PATH"] == before
