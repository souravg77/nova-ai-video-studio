"""Schema versioning: old projects keep opening; newer data is refused."""
import json
import sqlite3

import pytest

from nova_studio.models.project import Project, Scene
from nova_studio.storage.migrations import (DB_SCHEMA_VERSION,
                                            PROJECT_SCHEMA_VERSION,
                                            NewerSchemaError, db_version,
                                            migrate_project_manifest)
from nova_studio.storage.sqlite_store import (ProjectStore,
                                              export_project_manifest,
                                              load_project_manifest)


def _v0_manifest() -> dict:
    """A manifest exactly as NOVA 0.1.0 wrote it (no schema_version)."""
    p = Project(name="Legacy film")
    p.add_scene(Scene(title="Opening", script="Hello", duration_s=4.0))
    data = json.loads(p.model_dump_json())
    data.pop("schema_version")
    return data


def _make_v0_db(path, manifest: dict) -> None:
    """Build a database the way 0.1.0 did: tables, no user_version."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL,
            created_at TEXT, updated_at TEXT, manifest TEXT NOT NULL);
        CREATE TABLE jobs (id TEXT PRIMARY KEY, project_id TEXT, kind TEXT,
            state TEXT, created_at TEXT, data TEXT NOT NULL);
        CREATE TABLE benchmarks (id TEXT PRIMARY KEY, capability TEXT,
            backend_path TEXT, outcome TEXT, collected_at TEXT,
            data TEXT NOT NULL);
    """)
    conn.execute("INSERT INTO projects VALUES (?,?,?,?,?)",
                 (manifest["id"], manifest["name"], manifest["created_at"],
                  manifest["updated_at"], json.dumps(manifest)))
    conn.commit()
    assert db_version(conn) == 0
    conn.close()


def test_v0_database_and_project_still_open(tmp_path):
    db = tmp_path / "nova_studio.sqlite3"
    legacy = _v0_manifest()
    _make_v0_db(db, legacy)

    with ProjectStore(db) as store:
        p = store.load_project(legacy["id"])
        assert p is not None
        assert p.name == "Legacy film"
        assert p.scenes[0].title == "Opening"
        assert p.schema_version == PROJECT_SCHEMA_VERSION
        assert db_version(store._conn) == DB_SCHEMA_VERSION
        store.save_project(p)

    # Reopening an already-migrated database is a no-op and still loads.
    with ProjectStore(db) as store:
        p2 = store.load_project(legacy["id"])
        assert p2.scenes[0].script == "Hello"
        assert json.loads(store._fetchone(
            "SELECT manifest FROM projects WHERE id=?",
            (legacy["id"],))["manifest"])["schema_version"] == PROJECT_SCHEMA_VERSION


def test_v0_exported_manifest_opens(tmp_path):
    f = tmp_path / "legacy.json"
    f.write_text(json.dumps(_v0_manifest()), encoding="utf-8")
    p = load_project_manifest(f)
    assert p.schema_version == PROJECT_SCHEMA_VERSION
    assert p.scenes[0].duration_s == 4.0


def test_export_roundtrip_records_version(tmp_path):
    p = Project(name="Roundtrip")
    out = export_project_manifest(p, tmp_path / "p.json")
    assert json.loads(out.read_text(encoding="utf-8"))["schema_version"] == PROJECT_SCHEMA_VERSION
    assert load_project_manifest(out).id == p.id


def test_newer_project_is_refused_not_truncated():
    data = _v0_manifest()
    data["schema_version"] = PROJECT_SCHEMA_VERSION + 1
    with pytest.raises(NewerSchemaError, match="newer NOVA"):
        migrate_project_manifest(data)


def test_newer_database_is_refused(tmp_path):
    db = tmp_path / "future.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute(f"PRAGMA user_version = {DB_SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()
    with pytest.raises(NewerSchemaError):
        ProjectStore(db)


def test_new_project_records_current_schema_version():
    from nova_studio.models.project import Project
    from nova_studio.storage.migrations import PROJECT_SCHEMA_VERSION
    assert Project().schema_version == PROJECT_SCHEMA_VERSION


def _v1_manifest() -> dict:
    """A manifest as Phase 1 wrote it: schema 1, no performance fields."""
    data = _v0_manifest()
    data["schema_version"] = 1
    for k in ("language", "characters", "dialogue", "shots", "engine_selection"):
        data.pop(k, None)
    return data


def test_v1_project_upgrades_to_v2_without_losing_scenes():
    from nova_studio.storage.sqlite_store import project_from_manifest
    p = project_from_manifest(_v1_manifest())
    assert p.schema_version == 2
    assert p.scenes[0].title == "Opening"
    assert p.characters == [] and p.shots == [] and p.engine_selection.video is None


def test_characters_and_pinned_shots_survive_save_and_reload(tmp_path):
    from nova_studio.performance.characters import (
        Candidate, CandidateSource, add_candidates, approve_candidate,
        create_character, lock_identity)
    from nova_studio.performance.planner import (
        DialogueLine, EngineSelection, Shot, pin_shot)
    p = Project(name="Short film")
    maya = add_candidates(create_character("maya", "Maya"), [Candidate(
        id="c1", image_path="/m.png", source=CandidateSource.UPLOADED)])
    maya = lock_identity(approve_candidate(maya, "c1"))
    p.put_character(maya)
    p.dialogue.append(DialogueLine(id="l1", order=1, speaker_id="maya", text="Hi."))
    p.shots.append(pin_shot(Shot(id="s1", duration_s=6, character_ids=["maya"],
                                 dialogue_line_ids=["l1"]), p.characters))
    p.engine_selection = EngineSelection(video="gemini-omni-flash")

    with ProjectStore(tmp_path / "db.sqlite3") as store:
        store.save_project(p)
        back = store.load_project(p.id)
    assert back.character("maya").locked
    assert back.character("maya").history[-1].action == "locked"
    assert back.shots[0].pins[0].reference_id == maya.approved.reference_id
    assert back.engine_selection.video == "gemini-omni-flash"

    out = export_project_manifest(back, tmp_path / "film.json")
    assert json.loads(out.read_text())["schema_version"] == 2
    assert "api_key" not in out.read_text().lower()
    assert load_project_manifest(out).character("maya").approved.version == 1
