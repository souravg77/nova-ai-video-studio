"""Schema versioning and forward migrations for stored projects.

Two things are versioned independently:

* the SQLite database layout, tracked with ``PRAGMA user_version``;
* each project manifest (the JSON blob in ``projects.manifest`` and exported
  ``.json`` files), tracked with a ``schema_version`` field.

Records written before versioning existed carry no version and are treated as
version 0. Migrations only ever move data forward one step at a time, so a
project saved by any earlier NOVA release keeps opening. A manifest written by
a NEWER release is refused with a clear message rather than being silently
truncated by an older app.
"""
from __future__ import annotations

import sqlite3
from typing import Callable

# Bump when the Project model changes shape, and add a step below.
PROJECT_SCHEMA_VERSION = 2
# Bump when tables/indexes change, and add a step below.
DB_SCHEMA_VERSION = 1


class NewerSchemaError(RuntimeError):
    """Data was written by a newer NOVA release than this one."""


# ---- project manifests ------------------------------------------------------

def _project_v0_to_v1(data: dict) -> dict:
    # v0 (NOVA 0.1.0) manifests have the same fields as v1; v1 only starts
    # recording the version itself.
    return data


def _project_v1_to_v2(data: dict) -> dict:
    # v2 adds character performance data. Older projects start with none and
    # keep their scenes/assets exactly as they were.
    data.setdefault("language", "en")
    data.setdefault("characters", [])
    data.setdefault("dialogue", [])
    data.setdefault("shots", [])
    data.setdefault("engine_selection", {})
    return data


_PROJECT_STEPS: dict[int, Callable[[dict], dict]] = {
    0: _project_v0_to_v1,
    1: _project_v1_to_v2,
}


def manifest_version(data: dict) -> int:
    try:
        return int(data.get("schema_version", 0))
    except (TypeError, ValueError):
        return 0


def migrate_project_manifest(data: dict) -> dict:
    """Return ``data`` upgraded to PROJECT_SCHEMA_VERSION (mutates a copy)."""
    data = dict(data)
    version = manifest_version(data)
    if version > PROJECT_SCHEMA_VERSION:
        raise NewerSchemaError(
            f"Project '{data.get('name', '?')}' was saved by a newer NOVA "
            f"(project schema {version}; this version supports up to "
            f"{PROJECT_SCHEMA_VERSION}). Update NOVA to open it.")
    while version < PROJECT_SCHEMA_VERSION:
        data = _PROJECT_STEPS[version](data)
        version += 1
        data["schema_version"] = version
    return data


# ---- database ---------------------------------------------------------------

def _db_v0_to_v1(conn: sqlite3.Connection) -> None:
    # v0 databases already have the projects/jobs/benchmarks tables (created by
    # ProjectStore's CREATE IF NOT EXISTS). v1 only starts recording the version.
    pass


_DB_STEPS: dict[int, Callable[[sqlite3.Connection], None]] = {
    0: _db_v0_to_v1,
}


def db_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate_db(conn: sqlite3.Connection) -> int:
    """Upgrade the database in place; each step commits atomically."""
    version = db_version(conn)
    if version > DB_SCHEMA_VERSION:
        raise NewerSchemaError(
            f"The NOVA database was created by a newer NOVA (database schema "
            f"{version}; this version supports up to {DB_SCHEMA_VERSION}). "
            f"Update NOVA to open it.")
    while version < DB_SCHEMA_VERSION:
        with conn:
            _DB_STEPS[version](conn)
            version += 1
            conn.execute(f"PRAGMA user_version = {version}")
    return version
