"""NOVA reopens the last project instead of starting empty every launch."""
from nova_studio.core.studio import Studio
from nova_studio.performance.characters import create_character


def test_reopens_most_recent_project_and_creates_one_only_when_none(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVA_STUDIO_HOME", str(tmp_path / "home"))
    s = Studio()
    try:
        first = s.open_recent_project()
        assert len(s.store.list_projects()) == 1
        first.put_character(create_character("maya", "Maya"))
        s.save_project(first)
        again = s.open_recent_project()
        assert again.id == first.id and [c.name for c in again.characters] == ["Maya"]
        assert len(s.store.list_projects()) == 1   # no empty project per launch
    finally:
        s.shutdown()


def test_unreadable_newer_project_is_skipped_not_overwritten(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("NOVA_STUDIO_HOME", str(tmp_path / "home"))
    s = Studio()
    try:
        ok = s.new_project("Older")
        future = {"schema_version": 999, "id": "future", "name": "From a newer NOVA",
                  "created_at": "2099-01-01", "updated_at": "2099-01-01"}
        s.store._write("INSERT INTO projects(id,name,created_at,updated_at,manifest) "
                       "VALUES(?,?,?,?,?)", ("future", "From a newer NOVA",
                       "2099-01-01", "2099-01-01", json.dumps(future)))
        assert s.open_recent_project().id == ok.id
        row = s.store._fetchone("SELECT manifest FROM projects WHERE id='future'")
        assert json.loads(row["manifest"])["schema_version"] == 999
    finally:
        s.shutdown()
