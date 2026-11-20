"""Background render jobs.

Rendering can take minutes on a CPU-only laptop, so the API starts it in a background thread
and the user polls for progress. Only ONE heavy job runs at a time (the same lock the
analysis endpoints use), which keeps RAM and CPU use low on an 8 GB machine.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from app.services.locks import processing_lock


class JobBusyError(RuntimeError):
    pass


@dataclass
class RenderJob:
    plan_id: str
    state: str = "queued"            # queued | running | completed | failed_quality | failed | cancelled
    progress: float = 0.0            # 0.0 - 1.0
    error: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    cancel: threading.Event = field(default_factory=threading.Event)

    @property
    def active(self) -> bool:
        return self.state in ("queued", "running")

    def to_dict(self) -> Dict[str, Any]:
        end = self.finished_at or time.time()
        elapsed = end - self.started_at
        eta = None
        if self.active and self.progress > 0.03:
            eta = round(elapsed * (1.0 - self.progress) / self.progress)
        return {
            "plan_id": self.plan_id,
            "state": self.state,
            "progress_percent": round(self.progress * 100, 1),
            "elapsed_seconds": round(elapsed),
            "eta_seconds": eta,
            "error": self.error,
        }


_jobs: Dict[str, RenderJob] = {}
_guard = threading.Lock()


def get(plan_id: str) -> Optional[RenderJob]:
    with _guard:
        return _jobs.get(plan_id)


def is_active(plan_id: str) -> bool:
    job = get(plan_id)
    return bool(job and job.active)


def start(plan_id: str) -> RenderJob:
    """Start rendering in the background. Raises JobBusyError if another heavy job is running."""
    if not processing_lock.acquire(blocking=False):
        raise JobBusyError("Another heavy job (analysis, planning or rendering) is running. Try again when it finishes.")
    job = RenderJob(plan_id)
    with _guard:
        _jobs[plan_id] = job
    thread = threading.Thread(target=_run, args=(job,), name=f"render-{plan_id}", daemon=True)
    try:
        thread.start()
    except BaseException:
        processing_lock.release()
        raise
    return job


def cancel(plan_id: str) -> bool:
    job = get(plan_id)
    if job and job.active:
        job.cancel.set()
        return True
    return False


def _run(job: RenderJob) -> None:
    # Imported here so this module stays light and easy to test.
    from app.engine.renderer import RenderCancelled

    state: str = "failed"
    error: Optional[str] = None
    try:
        from app.agents import orchestrator   # inside the try: an import problem must still release the lock

        job.state = "running"

        def on_progress(fraction: float) -> None:
            job.progress = max(job.progress, min(float(fraction), 1.0))

        record = orchestrator.render_plan(job.plan_id, progress_cb=on_progress, cancel=job.cancel)
        state = record.get("status", "completed")
        if state == "completed":
            job.progress = 1.0
        else:
            report = (record.get("render") or {}).get("quality_report") or {}
            error = report.get("summary")
    except RenderCancelled:
        state, error = "cancelled", "Rendering was cancelled"
    except Exception as exc:  # RenderError, OrchestratorError, anything unexpected
        state, error = "failed", str(exc)
    finally:
        # Release the lock BEFORE publishing the final state, so a client that sees a finished
        # job can immediately start the next one without a spurious "busy" answer.
        processing_lock.release()
        job.error = error
        job.finished_at = time.time()
        job.state = state
