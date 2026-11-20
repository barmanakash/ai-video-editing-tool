"""Storage for editing plans (one JSON file per plan in data/plans).

A plan record looks like:
{
  "id", "created_at", "updated_at", "status",     # draft | rendering | completed | failed | failed_quality
  "instructions", "inputs": {...},                 # what the user asked for
  "planner": {"mode", "attempts", "warnings"},     # how the plan was produced
  "plan": {...validated plan...},
  "render": null | {...result of the last render...}
}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from app.config import settings
from app.services import file_service as fs


def new_plan_id() -> str:
    return fs.new_video_id()


def _path(plan_id: str) -> Path:
    return settings.plans_dir / f"{fs.validate_video_id(plan_id)}.json"


def save_plan(record: Dict[str, Any]) -> Path:
    record["updated_at"] = fs.utc_now()
    path = _path(record["id"])
    fs.atomic_write_json(path, record)
    return path


def load_plan(plan_id: str) -> Dict[str, Any]:
    path = _path(plan_id)
    if not path.is_file():
        raise fs.RecordNotFoundError(plan_id)
    return json.loads(path.read_text(encoding="utf-8"))


def plan_exists(plan_id: str) -> bool:
    try:
        return _path(plan_id).is_file()
    except fs.RecordNotFoundError:
        return False


def list_plans() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    folder = settings.plans_dir
    if not folder.is_dir():
        return out
    for f in sorted(folder.glob("*.json")):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        plan = r.get("plan") or {}
        out.append({
            "id": r.get("id"),
            "created_at": r.get("created_at"),
            "status": r.get("status"),
            "instructions": (r.get("instructions") or "")[:120],
            "style": plan.get("style"),
            "clip_count": len(plan.get("clips", [])),
            "estimated_seconds": plan.get("total_duration_estimate"),
            "output_format": (plan.get("output") or {}).get("format"),
            "planner_mode": (r.get("planner") or {}).get("mode"),
            "output_name": (r.get("render") or {}).get("output_name"),
        })
    return out


def delete_plan(plan_id: str, delete_output: bool = False) -> None:
    record = load_plan(plan_id)
    if delete_output:
        out = (record.get("render") or {}).get("output_path")
        if out:
            p = Path(out)
            try:  # only ever delete files that live inside the outputs folder
                p.resolve().relative_to(settings.outputs_dir.resolve())
                p.unlink(missing_ok=True)
            except (ValueError, OSError):
                pass
    _path(plan_id).unlink(missing_ok=True)


def recover_interrupted() -> int:
    """Call once at startup: a plan still marked 'rendering' lost its render (crash / restart)."""
    fixed = 0
    folder = settings.plans_dir
    if not folder.is_dir():
        return fixed
    for f in folder.glob("*.json"):
        try:
            record = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if record.get("status") == "rendering":
            record["status"] = "failed"
            record["render"] = {
                "state": "failed",
                "error": "The render was interrupted (the application stopped). Start it again.",
                "finished_at": fs.utc_now(),
            }
            save_plan(record)
            fixed += 1
    return fixed
