"""API routes for Phase 3: gameplay highlight candidates.

Results keep two things apart:
  detected             = measured facts (scene cuts, loud moments, flashes)
  estimated_highlights = guesses based on motion + audio + visual change
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from app.agents.gameplay_agent import GameplayAnalysisError, analyze_gameplay
from app.analyzers.audio_analyzer import AudioAnalysisError
from app.analyzers.motion_analyzer import FrameAnalysisError
from app.analyzers.scene_analyzer import detect_scenes
from app.services import analysis_service as analyses
from app.services import file_service as fs
from app.services.locks import processing_lock

router = APIRouter(prefix="/gameplay", tags=["gameplay"])


@router.post("/{video_id}/analyze")
def analyze_gameplay_video(
    video_id: str,
    max_seconds: float = Query(default=600, ge=10, le=3600, description="Analyse at most this many seconds"),
    top_k: int = Query(default=8, ge=1, le=20, description="Maximum number of estimated highlights"),
    flow_fps: float = Query(default=2.0, ge=0.5, le=6.0, description="Motion samples per second (lower = faster)"),
    run_scenes: bool = Query(default=True, description="Run scene detection first if it has not been run"),
    force: bool = Query(default=False, description="Re-analyse even if a saved analysis exists"),
) -> Dict[str, Any]:
    """Find candidate highlight moments in a registered gameplay video."""
    try:
        record = fs.load_record(video_id)
    except fs.RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Video not found. Register it first with /videos/register")

    if not force and analyses.gameplay_exists(video_id):
        return analyses.load_gameplay(video_id)

    path = Path(record["path"])
    if not path.is_file():
        raise HTTPException(status_code=410, detail="Source video file no longer exists")

    try:
        with processing_lock:
            if run_scenes and not record.get("scenes"):
                record["scenes"] = detect_scenes(path, record["metadata"]["duration_seconds"])
                fs.save_record(record)
            result = analyze_gameplay(record, max_seconds=max_seconds, top_k=top_k, flow_fps=flow_fps)
    except GameplayAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except (FrameAnalysisError, AudioAnalysisError) as exc:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}")
    except Exception as exc:  # PySceneDetect / OpenCV errors
        raise HTTPException(status_code=500, detail=f"Gameplay analysis failed: {exc}")

    analyses.save_gameplay(result)
    return result


@router.get("/analyses")
def list_gameplay_analyses() -> Dict[str, Any]:
    items = analyses.list_gameplay()
    return {"count": len(items), "analyses": items}


@router.get("/{video_id}/highlights")
def get_highlights(video_id: str) -> Dict[str, Any]:
    try:
        return analyses.load_gameplay(video_id)
    except fs.RecordNotFoundError:
        raise HTTPException(status_code=404, detail="No analysis yet. Run POST /gameplay/{video_id}/analyze")
