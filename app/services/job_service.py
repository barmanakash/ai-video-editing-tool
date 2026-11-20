"""Background render jobs.

Rendering takes minutes, so the API starts it in a thread and the client polls for progress.
Only one heavy task runs at a time (shared `processing_lock`), which protects an 8 GB machine.
Job state lives in memory; the final result is also stored inside the plan record.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

from app.agents import orchestrator
from app.engine.renderer import RenderCancelled
from app.services import plan_service as plans
from app.services.locks import processing_lock


class Job:
    def __init__(self, plan_id: str):
        self.plan_id = plan_id
        self.state = "queued"            # queued | rendering | completed | failed_quality | failed | cancelled
        self.progress = 0.0
        self.error: Optional[str] = None
        self.started_at = time.time()
        self.finished_at: Optional[float] = None
        self.cancel = threading.Event()

    @property
    def active(self) -> bool:
        return self.state in ("queued", "rendering")

    def to_dict(self) -> Dict[str, Any]:
        return {"plan_id": self.plan_id, "state": self.state, "progress_percent": round(self.progress, 1),
                "error": self.error, "elapsed_seconds": round((self.finished_at or time.time()) - self.started_at, 1)}


_jobs: Dict[str, Job] = {}
_guard = threading.Lock()


def start(plan_id: str) -> Job:
    """Start a render. Raises RuntimeError if this plan is already rendering."""
    with _guard:
        old = _jobs.get(plan_id)
        if old and old.active:
            raise RuntimeError("This plan is already rendering")
        job = Job(plan_id)
        _jobs[plan_id] = job
    threading.Thread(target=_run, args=(job,), name=f"render-{plan_id}", daemon=True).start()
    return job


def get(plan_id: str) -> Optional[Job]:
    return _jobs.get(plan_id)


def cancel(plan_id: str) -> bool:
    job = _jobs.get(plan_id)
    if job and job.active:
        job.cancel.set()
        return True
    return False


def _run(job: Job) -> None:
    try:
        with processing_lock:
            if job.cancel.is_set():
                job.state = "cancelled"
                return
            job.state = "rendering"

            def on_progress(p: float) -> None:
                job.progress = p

            record = orchestrator.render_plan(job.plan_id, progress_cb=on_progress, cancel=job.cancel)
            job.state = record["status"]
            job.progress = 100.0
    except RenderCancelled:
        job.state = "cancelled"
        _store_failure(job, "cancelled", "Render cancelled")
    except Exception as exc:
        job.state = "failed"
        job.error = str(exc)
        _store_failure(job, "failed", str(exc))
    finally:
        job.finished_at = time.time()


def _store_failure(job: Job, state: str, message: str) -> None:
    try:
        rec = plans.load_plan(job.plan_id)
        rec["status"] = "draft" if state == "cancelled" else "failed"
        rec["render"] = {"state": state, "error": message}
        plans.save_plan(rec)
    except Exception:
        pass
