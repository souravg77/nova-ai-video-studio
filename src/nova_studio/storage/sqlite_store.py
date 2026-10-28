"""SQLite + JSON project store (roadmap section 5).

Projects, scenes, jobs and benchmark records persist here. Project content is
stored as a JSON manifest blob (portable across PCs) with indexed columns for
listing. A project reopens after restart (section 7, milestone 1 acceptance).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from ..models.benchmark import BenchmarkResult
from ..models.job import Job
from ..models.project import Project

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT,
    manifest TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    kind TEXT,
    state TEXT,
    created_at TEXT,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS benchmarks (
    id TEXT PRIMARY KEY,
    capability TEXT,
    backend_path TEXT,
    outcome TEXT,
    collected_at TEXT,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project_id);
CREATE INDEX IF NOT EXISTS idx_bench_cap ON benchmarks(capability);
"""


class ProjectStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        # The job-queue worker runs on a separate thread. check_same_thread=
        # False plus a serialising lock lets the main thread and the single
        # worker share one connection safely.
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "ProjectStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- low-level, lock-guarded helpers -----------------------------
    def _write(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def _fetchone(self, sql: str, params: tuple = ()):
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def _fetchall(self, sql: str, params: tuple = ()):
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # ---- projects ----------------------------------------------------
    def save_project(self, project: Project) -> None:
        project.touch()
        self._write(
            "INSERT INTO projects(id,name,created_at,updated_at,manifest) "
            "VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "name=excluded.name, updated_at=excluded.updated_at, "
            "manifest=excluded.manifest",
            (project.id, project.name, project.created_at, project.updated_at,
             project.model_dump_json()),
        )

    def load_project(self, project_id: str) -> Optional[Project]:
        row = self._fetchone(
            "SELECT manifest FROM projects WHERE id=?", (project_id,))
        if not row:
            return None
        return Project.model_validate_json(row["manifest"])

    def list_projects(self) -> list[dict]:
        rows = self._fetchall(
            "SELECT id,name,updated_at FROM projects ORDER BY updated_at DESC")
        return [dict(r) for r in rows]

    def delete_project(self, project_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
            self._conn.execute("DELETE FROM jobs WHERE project_id=?", (project_id,))
            self._conn.commit()

    # ---- jobs --------------------------------------------------------
    def save_job(self, job: Job) -> None:
        self._write(
            "INSERT INTO jobs(id,project_id,kind,state,created_at,data) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "state=excluded.state, data=excluded.data",
            (job.id, job.project_id, job.kind.value, job.state.value,
             job.created_at, job.model_dump_json()),
        )

    def load_job(self, job_id: str) -> Optional[Job]:
        row = self._fetchone("SELECT data FROM jobs WHERE id=?", (job_id,))
        return Job.model_validate_json(row["data"]) if row else None

    def list_jobs(self, project_id: Optional[str] = None) -> list[Job]:
        if project_id:
            rows = self._fetchall(
                "SELECT data FROM jobs WHERE project_id=? ORDER BY created_at DESC",
                (project_id,))
        else:
            rows = self._fetchall(
                "SELECT data FROM jobs ORDER BY created_at DESC")
        return [Job.model_validate_json(r["data"]) for r in rows]

    # ---- benchmarks --------------------------------------------------
    def save_benchmark(self, result: BenchmarkResult) -> None:
        self._write(
            "INSERT INTO benchmarks(id,capability,backend_path,outcome,"
            "collected_at,data) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE "
            "SET outcome=excluded.outcome, data=excluded.data",
            (result.id, result.capability, result.backend_path,
             result.outcome.value, result.collected_at,
             result.model_dump_json()),
        )

    def list_benchmarks(self, capability: Optional[str] = None) -> list[BenchmarkResult]:
        if capability:
            rows = self._fetchall(
                "SELECT data FROM benchmarks WHERE capability=? "
                "ORDER BY collected_at DESC", (capability,))
        else:
            rows = self._fetchall(
                "SELECT data FROM benchmarks ORDER BY collected_at DESC")
        return [BenchmarkResult.model_validate_json(r["data"]) for r in rows]

    def latest_benchmarks(self) -> list[BenchmarkResult]:
        """Most recent result per (capability, backend_path)."""
        seen: set[tuple[str, str]] = set()
        latest: list[BenchmarkResult] = []
        for b in self.list_benchmarks():
            key = (b.capability, b.backend_path)
            if key not in seen:
                seen.add(key)
                latest.append(b)
        return latest


def export_project_manifest(project: Project, path: str | Path) -> Path:
    """Write a portable JSON manifest (section 8: projects portable across PCs)."""
    p = Path(path)
    p.write_text(json.dumps(project.model_dump(), indent=2))
    return p
