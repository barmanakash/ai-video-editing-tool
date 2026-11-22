"""Orchestrator: the main controller of the editing workflow.

It owns no heavy logic itself. It coordinates the lightweight modules:

  analysis (reference profile, gameplay highlights)  ->  planner (Qwen)  ->
  validation  ->  renderer (FFmpeg)  ->  quality check

Locking: functions that do heavy work (`create_plan`, `render_plan`) are meant to be
called while holding `processing_lock` (the API / job service does that). Helpers here
never take the lock themselves, so there is no deadlock.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.agents.editing_agent import PlannerContext, generate_plan
from app.agents.gameplay_agent import GameplayAnalysisError, analyze_gameplay
from app.agents.reference_agent import ReferenceAnalysisError, build_reference_profile
from app.analyzers.scene_analyzer import detect_scenes
from app.engine.plan_schema import PlanValidationError, validate_plan
from app.services import analysis_service as analyses
from app.services import file_service as fs
from app.services import plan_service as plans
from app.services import profile_service as profiles


class OrchestratorError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------ sources
def build_sources(video_ids: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
    """Map video id -> info the planner, validator and renderer need (gameplay videos only)."""
    if video_ids is None:
        records = fs.list_records()
    else:
        records = []
        for vid in video_ids:
            try:
                records.append(fs.load_record(vid))
            except fs.RecordNotFoundError:
                raise OrchestratorError(f"Gameplay video '{vid}' is not registered", 404)
    out: Dict[str, Dict[str, Any]] = {}
    for r in records:
        if r.get("role") != "gameplay":
            if video_ids is not None:
                raise OrchestratorError(f"Video '{r['id']}' has role '{r.get('role')}', expected 'gameplay'", 400)
            continue
        meta = r["metadata"]
        vmeta = meta.get("video") or {}
        out[r["id"]] = {
            "duration_seconds": float(meta["duration_seconds"]),
            "has_audio": meta.get("audio") is not None,
            "path": r["path"],
            "name": r.get("original_name"),
            "width": vmeta.get("width"),
            "height": vmeta.get("height"),
            "fps": vmeta.get("fps"),
            "available": Path(r["path"]).is_file(),
        }
    return out


# ----------------------------------------------------------------- analysis
def ensure_gameplay_analysis(video_id: str, force: bool = False) -> Dict[str, Any]:
    if not force and analyses.gameplay_exists(video_id):
        return analyses.load_gameplay(video_id)
    record = fs.load_record(video_id)
    path = Path(record["path"])
    if not path.is_file():
        raise OrchestratorError(f"Source file for '{video_id}' no longer exists", 410)
    if not record.get("scenes"):
        record["scenes"] = detect_scenes(path, record["metadata"]["duration_seconds"])
        fs.save_record(record)
    try:
        result = analyze_gameplay(record)
    except GameplayAnalysisError as exc:
        raise OrchestratorError(str(exc), 422)
    analyses.save_gameplay(result)
    return result


def ensure_reference_profile(reference_id: str) -> Dict[str, Any]:
    if profiles.profile_exists(reference_id):
        return profiles.load_profile(reference_id)
    try:
        record = fs.load_record(reference_id)
    except fs.RecordNotFoundError:
        raise OrchestratorError(f"Reference video '{reference_id}' is not registered", 404)
    path = Path(record["path"])
    if not path.is_file():
        raise OrchestratorError("Reference video file no longer exists", 410)
    try:
        if not record.get("scenes"):
            record["scenes"] = detect_scenes(path, record["metadata"]["duration_seconds"])
            fs.save_record(record)
        profile = build_reference_profile(record)
    except ReferenceAnalysisError as exc:
        raise OrchestratorError(str(exc), 422)
    profiles.save_profile(profile)
    return profile


# ----------------------------------------------------------------- planning
def create_plan(
    instructions: str,
    gameplay_ids: List[str],
    reference_id: Optional[str] = None,
    fmt: str = "youtube",
    quality: str = "test",
    fit: str = "crop",
    target_duration: float = 30.0,
    music_path: Optional[str] = None,
    music_volume: float = 0.7,
    use_llm: bool = True,
    look: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Analyse (if needed), ask the planner for an editing plan, validate and save it as a draft."""
    ids = list(dict.fromkeys(gameplay_ids))           # de-duplicate, keep order
    if not ids:
        raise OrchestratorError("Select at least one gameplay video")
    if len(ids) > 8:
        raise OrchestratorError("At most 8 gameplay videos per project")

    sources = build_sources(ids)
    missing = [v["name"] for v in sources.values() if not v["available"]]
    if missing:
        raise OrchestratorError(f"Source file(s) no longer exist: {', '.join(map(str, missing))}", 410)

    gameplay = {vid: ensure_gameplay_analysis(vid) for vid in sources}
    profile = ensure_reference_profile(reference_id) if reference_id else None

    ctx = PlannerContext(
        instructions=instructions.strip(),
        sources=sources,
        analyses=gameplay,
        profile=profile,
        output={"format": fmt, "quality": quality, "fit": fit},
        target_duration=float(target_duration),
        audio={
            "use_uploaded_music": bool(music_path),
            "music_path": music_path,
            "music_volume": music_volume,
            "sync_cuts_to_music": True,
        },
        look=look or {},
    )
    try:
        plan, meta = generate_plan(ctx, use_llm=use_llm)
    except PlanValidationError as exc:
        raise OrchestratorError("Could not build a valid plan: " + "; ".join(exc.errors), 422)

    record = {
        "id": plans.new_plan_id(),
        "created_at": fs.utc_now(),
        "status": "draft",
        "instructions": ctx.instructions,
        "inputs": {
            "gameplay_ids": list(sources),
            "reference_id": reference_id,
            "target_duration": ctx.target_duration,
            "format": fmt,
            "quality": quality,
            "fit": fit,
            "look": look or {},
        },
        "planner": meta,
        "plan": plan,
        "render": None,
    }
    plans.save_plan(record)
    return record


def update_plan(plan_id: str, plan_in: Any) -> Dict[str, Any]:
    """Replace a plan with a user-edited one (validated). Resets the render state."""
    try:
        record = plans.load_plan(plan_id)
    except fs.RecordNotFoundError:
        raise OrchestratorError("Plan not found", 404)
    try:
        record["plan"] = validate_plan(plan_in, build_sources())
    except PlanValidationError as exc:
        raise OrchestratorError("Plan rejected: " + "; ".join(exc.errors), 422)
    record["status"] = "draft"
    record["render"] = None
    record.setdefault("planner", {})["edited_by_user"] = True
    plans.save_plan(record)
    return record


# ---------------------------------------------------------------- rendering
def check_renderable(plan_id: str) -> Dict[str, Any]:
    """Quick checks done before a render job starts, so the user gets an immediate answer."""
    try:
        record = plans.load_plan(plan_id)
    except fs.RecordNotFoundError:
        raise OrchestratorError("Plan not found", 404)
    if record.get("status") == "rendering":
        raise OrchestratorError("This plan is already being rendered", 409)
    sources = build_sources()
    try:
        plan = validate_plan(record["plan"], sources)
    except PlanValidationError as exc:
        raise OrchestratorError("Plan is not valid: " + "; ".join(exc.errors), 422)
    gone = sorted({str(sources[c["source"]]["name"]) for c in plan["clips"] if not sources[c["source"]]["available"]})
    if gone:
        raise OrchestratorError(f"Source file(s) no longer exist: {', '.join(gone)}", 410)
    return record


def set_output(plan_id: str, fmt: Optional[str] = None, quality: Optional[str] = None, fit: Optional[str] = None,
               **extra: Any) -> Dict[str, Any]:
    """Change only the output settings of a plan (format, quality, fit, fps, codec, encoder, quality_level).

    Validated like any other edit, so unknown values are rejected.
    """
    try:
        record = plans.load_plan(plan_id)
    except fs.RecordNotFoundError:
        raise OrchestratorError("Plan not found", 404)
    plan = dict(record["plan"])
    out = dict(plan.get("output") or {})
    for key, value in (("format", fmt), ("quality", quality), ("fit", fit), *extra.items()):
        if value is not None:
            out[key] = value
    plan["output"] = out
    try:
        record["plan"] = validate_plan(plan, build_sources())
    except PlanValidationError as exc:
        raise OrchestratorError("Output settings rejected: " + "; ".join(exc.errors), 422)
    record["status"] = "draft"
    record["render"] = None
    plans.save_plan(record)
    return record


def render_plan(
    plan_id: str,
    progress_cb: Optional[Callable[[float], None]] = None,
    cancel: Any = None,
) -> Dict[str, Any]:
    """Re-validate the stored plan, render it with FFmpeg, run quality checks, store the result."""
    from app.agents import quality_agent
    from app.engine import renderer

    try:
        record = plans.load_plan(plan_id)
    except fs.RecordNotFoundError:
        raise OrchestratorError("Plan not found", 404)

    sources = build_sources()
    try:
        plan = validate_plan(record["plan"], sources)
    except PlanValidationError as exc:
        raise OrchestratorError("Plan is no longer valid: " + "; ".join(exc.errors), 422)
    gone = sorted({sources[c["source"]]["name"] for c in plan["clips"] if not sources[c["source"]]["available"]})
    if gone:
        raise OrchestratorError(f"Source file(s) no longer exist: {', '.join(map(str, gone))}", 410)

    record["status"] = "rendering"
    record["render"] = None
    plans.save_plan(record)

    try:
        result = renderer.render(plan, sources, plan_id, progress_cb=progress_cb, cancel=cancel)
    except renderer.RenderCancelled as exc:
        record["status"] = "cancelled"
        record["render"] = {"state": "cancelled", "error": str(exc), "finished_at": fs.utc_now()}
        plans.save_plan(record)
        raise
    except BaseException as exc:
        record["status"] = "failed"
        record["render"] = {"state": "failed", "error": str(exc), "finished_at": fs.utc_now()}
        plans.save_plan(record)
        raise

    report = quality_agent.check_output(
        result["output_path"],
        {"width": result["width"], "height": result["height"],
         "duration": result["expected_duration"], "has_audio": result["has_audio"]},
    )
    record["status"] = "completed" if report["passed"] else "failed_quality"
    record["render"] = {
        "state": record["status"],
        "finished_at": fs.utc_now(),
        "output_path": result["output_path"],
        "output_name": Path(result["output_path"]).name,
        "resolution": f"{result['width']}x{result['height']}",
        "expected_duration": round(result["expected_duration"], 2),
        "render_seconds": result["elapsed"],
        "beat_snapped_cuts": result["snapped_cuts"],
        "notes": result["notes"],
        "quality_report": report,
    }
    plans.save_plan(record)
    return record
