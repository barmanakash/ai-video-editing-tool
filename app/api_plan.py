"""API routes for the editing plan (Phase 4) and rendering (Phases 5-6)."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.agents import orchestrator
from app.agents.orchestrator import OrchestratorError
from app.config import settings
from app.engine.text_overlay import clean_text
from app.services import file_service as fs
from app.services import plan_service as plans
from app.services import render_jobs
from app.services.locks import processing_lock

router = APIRouter(prefix="/plans", tags=["plans"])


class PlanRequest(BaseModel):
    instructions: str = Field(..., min_length=3, max_length=2000,
                              description="What you want, e.g. 'Find the best fights, smooth transitions, slow motion on big moments'")
    gameplay_ids: List[str] = Field(..., description="Ids of registered gameplay videos (1 to 8)")
    reference_id: Optional[str] = Field(default=None, description="Id of a registered reference video (optional)")
    format: str = Field(default="youtube", description="youtube (16:9) or instagram (9:16)")
    quality: str = Field(default="test", description="test (small and fast) or full (1080p)")
    fit: str = Field(default="crop", description="crop (fill the frame) or pad (black bars)")
    target_duration: float = Field(default=30.0, ge=5, le=600, description="Desired length in seconds")
    music_path: Optional[str] = Field(default=None, description="Path to music you have permission to use (optional)")
    music_volume: float = Field(default=0.7, ge=0, le=1.5)
    use_llm: bool = Field(default=True, description="false = skip Qwen and use the deterministic planner")
    # ---- look (Phase 7A) ----
    grade: Literal["auto", "none", "clean", "vibrant", "cinematic"] = Field(
        default="auto", description="Colour look. auto = the planner picks (cinematic by default)")
    punch: Literal["auto", "off", "cuts", "beats"] = Field(
        default="auto", description="Zoom/flash/shake hits. auto = on the music beats if you gave music, otherwise on the cuts")
    zoom_punch: bool = Field(default=True, description="Zoom pulse on each hit")
    flash: bool = Field(default=False, description="Brightness flash on each hit")
    shake: bool = Field(default=False, description="Camera shake on each hit")
    title: Optional[str] = Field(default=None, max_length=60, description="Big title shown at the start")
    subtitle: Optional[str] = Field(default=None, max_length=60, description="Smaller line under the title")
    end_text: Optional[str] = Field(default=None, max_length=60, description="Text shown at the end, e.g. Thanks for watching")


def _error(exc: OrchestratorError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


def _build_look(req: PlanRequest) -> Dict[str, Any]:
    """The user's look choices, in the shape the planner and plan schema expect."""
    punch = req.punch if req.punch != "auto" else ("beats" if req.music_path else "cuts")
    look: Dict[str, Any] = {
        "fx": {"punch": punch, "zoom_punch": req.zoom_punch, "flash": req.flash, "shake": req.shake},
        "titles": [],
    }
    if req.grade != "auto":
        look["preset"] = req.grade
    for text, position, size, at in ((req.title, "center", "large", "start"), (req.subtitle, "lower", "small", "start"),
                                     (req.end_text, "center", "medium", "end")):
        cleaned = clean_text(text)          # characters FFmpeg could misread are removed; empty text is skipped
        if cleaned:
            look["titles"].append({"text": cleaned, "position": position, "size": size, "at": at, "duration": 2.5})
    return look


def _get_or_404(plan_id: str) -> Dict[str, Any]:
    try:
        return plans.load_plan(plan_id)
    except fs.RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Plan not found")


@router.post("/generate")
def generate_plan(req: PlanRequest) -> Dict[str, Any]:
    """Analyse (if needed), ask Qwen for a plan, validate it and save it as a draft.

    Review the returned plan, edit it with PUT /plans/{id} if you like, then render it.
    This call can take a few minutes on CPU while the 3B model thinks.
    """
    try:
        with processing_lock:
            return orchestrator.create_plan(
                instructions=req.instructions,
                gameplay_ids=req.gameplay_ids,
                reference_id=req.reference_id,
                fmt=req.format,
                quality=req.quality,
                fit=req.fit,
                target_duration=req.target_duration,
                music_path=req.music_path,
                music_volume=req.music_volume,
                use_llm=req.use_llm,
                look=_build_look(req),
            )
    except OrchestratorError as exc:
        raise _error(exc)
    except fs.RecordNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Video not found: {exc}")
    except Exception as exc:  # analysis / OpenCV / FFmpeg errors
        raise HTTPException(status_code=500, detail=f"Planning failed: {exc}")


@router.get("")
def list_plans() -> Dict[str, Any]:
    items = plans.list_plans()
    return {"count": len(items), "plans": items}


@router.get("/{plan_id}")
def get_plan(plan_id: str) -> Dict[str, Any]:
    return _get_or_404(plan_id)


@router.put("/{plan_id}")
def edit_plan(plan_id: str, plan: Dict[str, Any] = Body(..., description="A full plan object (copy it from GET /plans/{id} and edit)")) -> Dict[str, Any]:
    """Replace the plan with your edited version. It is validated exactly like a model-made plan."""
    if render_jobs.is_active(plan_id):
        raise HTTPException(status_code=409, detail="This plan is being rendered. Cancel the render first.")
    try:
        return orchestrator.update_plan(plan_id, plan)
    except OrchestratorError as exc:
        raise _error(exc)
    except fs.RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Plan not found")


@router.delete("/{plan_id}")
def delete_plan(plan_id: str, delete_output: bool = False) -> Dict[str, Any]:
    _get_or_404(plan_id)
    if render_jobs.is_active(plan_id):
        raise HTTPException(status_code=409, detail="This plan is being rendered. Cancel the render first.")
    plans.delete_plan(plan_id, delete_output=delete_output)
    return {"deleted": plan_id}


# ----------------------------------------------------------------- rendering
class RenderRequest(BaseModel):
    format: Optional[str] = Field(default=None, description="Change the output: youtube (16:9) or instagram (9:16). Leave empty to keep the plan's setting.")
    quality: Optional[str] = Field(default=None, description="test (480p preview, fast) | full (1080p) | 1440p | 4k")
    fit: Optional[str] = Field(default=None, description="crop (fill the frame) or pad (keep everything, add black bars)")
    fps: Optional[int] = Field(default=None, ge=24, le=60, description="Frames per second, e.g. 30 or 60")
    codec: Optional[Literal["h264", "hevc"]] = Field(default=None, description="h264 (plays everywhere) or hevc (smaller files)")
    encoder: Optional[Literal["auto", "cpu", "qsv"]] = Field(default=None, description="auto, cpu, or qsv (Intel hardware, falls back to cpu)")
    quality_level: Optional[Literal["fast", "standard", "high"]] = Field(default=None, description="Speed versus file quality")


@router.post("/{plan_id}/render", status_code=202)
def start_render(plan_id: str, req: Optional[RenderRequest] = Body(default=None)) -> Dict[str, Any]:
    """Render the plan with FFmpeg in the background. Poll GET /plans/{id}/render for progress.

    Optional body: {"format": "instagram", "quality": "full"} changes the output settings first.
    Only one heavy job runs at a time, so this returns 409 while another one is busy.
    """
    try:
        if render_jobs.is_active(plan_id):
            raise HTTPException(status_code=409, detail="This plan is already being rendered")
        extra = {"fps": req.fps, "codec": req.codec, "encoder": req.encoder, "quality_level": req.quality_level} if req else {}
        if req is not None and any(v is not None for v in (req.format, req.quality, req.fit, *extra.values())):
            orchestrator.set_output(plan_id, req.format, req.quality, req.fit, **extra)
        orchestrator.check_renderable(plan_id)
        job = render_jobs.start(plan_id)
    except OrchestratorError as exc:
        raise _error(exc)
    except render_jobs.JobBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {**job.to_dict(), "status_url": f"/plans/{plan_id}/render", "output_url": f"/plans/{plan_id}/output"}


@router.get("/{plan_id}/render")
def render_status(plan_id: str) -> Dict[str, Any]:
    """Progress of the running render, or the result of the last one (including the quality report)."""
    record = _get_or_404(plan_id)
    job = render_jobs.get(plan_id)
    return {
        "plan_id": plan_id,
        "plan_status": record.get("status"),
        "job": job.to_dict() if job else None,
        "render": record.get("render"),
    }


@router.post("/{plan_id}/render/cancel")
def cancel_render(plan_id: str) -> Dict[str, Any]:
    _get_or_404(plan_id)
    if not render_jobs.cancel(plan_id):
        raise HTTPException(status_code=409, detail="No render is running for this plan")
    return {"plan_id": plan_id, "message": "Cancel requested; FFmpeg is being stopped"}


@router.get("/{plan_id}/output")
def download_output(plan_id: str):
    """Download (or play in the browser) the finished video. Only available after a passed quality check."""
    record = _get_or_404(plan_id)
    render = record.get("render") or {}
    if record.get("status") != "completed" or not render.get("output_path"):
        detail = "The video is not ready."
        if record.get("status") == "failed_quality":
            detail = "The video failed the quality check: " + str((render.get("quality_report") or {}).get("summary"))
        raise HTTPException(status_code=409, detail=detail)
    path = Path(render["output_path"])
    try:  # only ever serve files from the outputs folder
        path.resolve().relative_to(settings.outputs_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Output file is outside the outputs folder")
    if not path.is_file():
        raise HTTPException(status_code=410, detail="The output file was deleted from disk")
    return FileResponse(path, media_type="video/mp4", filename=path.name)
