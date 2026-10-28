"""Job queue with a background worker (roadmap section 7, milestone 4).

States: queued/running/failed/cancelled/completed, with logs, progress, retry
and cancellation. The UI stays responsive because work runs on a worker
thread; AI adapters that need heavy/conflicting deps should be dispatched to
separate worker *processes* (the handler map makes that swappable).

A job is only COMPLETED_AND_VALIDATED when its outputs exist and pass checks —
honesty is enforced at the queue level, not left to each handler.
"""
from __future__ import annotations

import queue
import threading
from typing import Callable, Optional

from ..models.job import GenerationState, Job, JobKind, JobState
from ..storage.sqlite_store import ProjectStore

# A handler takes (job, cancel_event) and returns a list of output paths.
Handler = Callable[[Job, threading.Event], list[str]]


class JobQueue:
    def __init__(self, store: ProjectStore) -> None:
        self.store = store
        self._handlers: dict[JobKind, Handler] = {}
        self._q: "queue.Queue[str]" = queue.Queue()
        self._jobs: dict[str, Job] = {}
        self._cancels: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._listeners: list[Callable[[Job], None]] = []

    # ------------------------------------------------------------------
    def register(self, kind: JobKind, handler: Handler) -> None:
        self._handlers[kind] = handler

    def add_listener(self, fn: Callable[[Job], None]) -> None:
        self._listeners.append(fn)

    def _notify(self, job: Job) -> None:
        self.store.save_job(job)
        for fn in list(self._listeners):
            try:
                fn(job)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def submit(self, job: Job) -> Job:
        with self._lock:
            self._jobs[job.id] = job
            self._cancels[job.id] = threading.Event()
        job.state = JobState.QUEUED
        job.log("Queued.")
        self._notify(job)
        self._q.put(job.id)
        return job

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            ev = self._cancels.get(job_id)
            job = self._jobs.get(job_id)
        if ev is None or job is None:
            return False
        ev.set()
        if job.state == JobState.QUEUED:
            job.mark_cancelled()
            job.log("Cancelled before start.")
            self._notify(job)
        return True

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._stop.clear()
        self._worker = threading.Thread(target=self._run, daemon=True,
                                        name="nova-job-worker")
        self._worker.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._q.put("__stop__")
        if self._worker:
            self._worker.join(timeout=timeout)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job_id = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            if job_id == "__stop__":
                break
            job = self._jobs.get(job_id)
            if job is None:
                continue
            cancel = self._cancels.get(job_id, threading.Event())
            if cancel.is_set():
                continue
            self._execute(job, cancel)

    def _execute(self, job: Job, cancel: threading.Event) -> None:
        handler = self._handlers.get(job.kind)
        if handler is None:
            job.mark_failed(f"No handler registered for job kind '{job.kind.value}'.")
            self._notify(job)
            return
        job.mark_running()
        job.log("Started.")
        self._notify(job)
        try:
            outputs = handler(job, cancel)
            if cancel.is_set():
                job.mark_cancelled()
                job.log("Cancelled during run.")
                self._notify(job)
                return
            job.outputs = list(outputs or [])
            # Honesty gate: a render/generation job is only 'completed and
            # validated' if it declared outputs that exist.
            from pathlib import Path
            validated = bool(job.outputs) and all(
                Path(o).exists() for o in job.outputs)
            job.mark_completed(validated=validated)
            if validated:
                job.log(f"Completed and validated. Outputs: {job.outputs}")
            else:
                job.log("Completed but no validated output files were produced.",
                        level="warning")
                if job.generation_state is None:
                    job.generation_state = GenerationState.FAILED_AT_RUNTIME
            self._notify(job)
        except Exception as exc:  # handler crash — preserve logs
            job.mark_failed(f"{type(exc).__name__}: {exc}")
            self._notify(job)
