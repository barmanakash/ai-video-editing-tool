"""API routes for the editing plan (Phase 4) and rendering (Phases 5-6)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from app.agents import orchestrator
from app.agents.orchestrator import OrchestratorError
from app.services import file_service as fs
from app.services import plan_service as plans
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


def _error(exc: OrchestratorError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


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
    try:
        return orchestrator.update_plan(plan_id, plan)
    except OrchestratorError as exc:
        raise _error(exc)
    except fs.RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Plan not found")


@router.delete("/{plan_id}")
def delete_plan(plan_id: str, delete_output: bool = False) -> Dict[str, Any]:
    _get_or_404(plan_id)
    plans.delete_plan(plan_id, delete_output=delete_output)
    return {"deleted": plan_id}
