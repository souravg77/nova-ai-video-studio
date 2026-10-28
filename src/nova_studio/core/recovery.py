"""Crash/interruption recovery (roadmap section 7, milestone 9).

On startup, any job left in RUNNING state from a previous session is marked
FAILED with a clear reason (an interrupted job must not corrupt the project
or masquerade as completed).
"""
from __future__ import annotations

from ..models.job import JobState
from ..storage.sqlite_store import ProjectStore


def recover_interrupted_jobs(store: ProjectStore) -> list[str]:
    """Return ids of jobs that were interrupted and are now marked failed."""
    recovered: list[str] = []
    for job in store.list_jobs():
        if job.state == JobState.RUNNING:
            job.mark_failed(
                "Interrupted by application exit or crash in a previous "
                "session. No completed output is claimed; re-run if needed.")
            store.save_job(job)
            recovered.append(job.id)
    return recovered
