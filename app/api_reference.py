"""API routes for Phase 2: reference video style profiles."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from app.agents.reference_agent import ReferenceAnalysisError, build_reference_profile
from app.analyzers.audio_analyzer import AudioAnalysisError
from app.analyzers.motion_analyzer import FrameAnalysisError
from app.analyzers.scene_analyzer import detect_scenes
from app.services import file_service as fs
from app.services import profile_service as profiles
from app.services.locks import processing_lock

router = APIRouter(prefix="/reference", tags=["reference"])


@router.post("/{video_id}/analyze")
def analyze_reference(
    video_id: str,
    max_seconds: float = Query(default=300, ge=5, le=1800, description="Analyse at most this many seconds"),
    flow_fps: float = Query(default=4, ge=1, le=10, description="Motion samples per second (lower = faster)"),
    force: bool = Query(default=False, description="Re-analyse even if a saved profile exists"),
    name: Optional[str] = Query(default=None, max_length=120, description="Friendly name for this style"),
) -> Dict[str, Any]:
    """Analyse a registered video and save its reusable style profile.

    The video must already be registered (POST /videos/register, role "reference").
    If a profile already exists it is returned unchanged unless force=true.
    """
    try:
        record = fs.load_record(video_id)
    except fs.RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Video not found. Register it first with /videos/register")

    if not force and profiles.profile_exists(video_id):
        return profiles.load_profile(video_id)

    try:
        with processing_lock:
            # Scene detection is reused from the video record when it already exists.
            if not record.get("scenes"):
                record["scenes"] = detect_scenes(Path(record["path"]), record["metadata"]["duration_seconds"])
                fs.save_record(record)
            profile = build_reference_profile(record, max_seconds=max_seconds, flow_fps=flow_fps, name=name)
    except ReferenceAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except (FrameAnalysisError, AudioAnalysisError) as exc:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}")
    except Exception as exc:  # PySceneDetect / OpenCV errors
        raise HTTPException(status_code=500, detail=f"Reference analysis failed: {exc}")

    profiles.save_profile(profile)
    return profile


@router.get("/profiles")
def list_reference_profiles() -> Dict[str, Any]:
    items = profiles.list_profiles()
    return {"count": len(items), "profiles": items}


@router.get("/profiles/{video_id}")
def get_reference_profile(video_id: str) -> Dict[str, Any]:
    try:
        return profiles.load_profile(video_id)
    except fs.RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Profile not found")


@router.delete("/profiles/{video_id}")
def delete_reference_profile(video_id: str) -> Dict[str, Any]:
    try:
        profiles.delete_profile(video_id)
    except fs.RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"deleted": video_id}
