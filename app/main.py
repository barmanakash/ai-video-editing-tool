"""FastAPI entry point.

Run:  uvicorn app.main:app --host 127.0.0.1 --port 8000
Docs: http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.analyzers.scene_analyzer import detect_scenes
from app.analyzers.video_analyzer import VideoProbeError, extract_metadata, generate_thumbnails
from app.config import settings
from app.services import file_service as fs
from app.services.locks import processing_lock
from app.services import plan_service
from app.engine import renderer
from app.services.system_check import run_checks
from app.api_gameplay import router as gameplay_router
from app.api_plan import router as plan_router
from app.api_reference import router as reference_router

# Heavy work (ffmpeg / OpenCV) runs one job at a time to protect 8 GB of RAM.
_processing_lock = processing_lock


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    # Nothing is rendering at startup: fix plans stuck in 'rendering' and delete half-finished temp files.
    plan_service.recover_interrupted()
    renderer.cleanup_stale_temp()
    yield


app = FastAPI(title="Local AI Gaming Video Editor", version="1.0.0", lifespan=lifespan)
app.include_router(reference_router)
app.include_router(gameplay_router)
app.include_router(plan_router)


class RegisterRequest(BaseModel):
    path: str
    role: str = "gameplay"


# ---------------------------------------------------------------- helpers
def _public(record: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(record)
    out["thumbnail_urls"] = [f"/videos/{record['id']}/thumbnails/{t['file']}" for t in record.get("thumbnails", [])]
    return out


def _get_or_404(video_id: str) -> Dict[str, Any]:
    try:
        return fs.load_record(video_id)
    except fs.RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Video not found")


def _ingest(path: Path, original_name: str, role: str, source: str, video_id: str) -> Dict[str, Any]:
    with _processing_lock:
        metadata = extract_metadata(path)  # raises VideoProbeError for invalid files
        thumbs = generate_thumbnails(
            path,
            fs.thumbnail_dir(video_id),
            metadata["duration_seconds"],
            settings.thumbnail_count,
            settings.thumbnail_width,
        )
    record = {
        "id": video_id,
        "role": role,
        "original_name": original_name,
        "path": str(path),
        "source": source,  # "upload" (copied into data/uploads) or "local" (referenced in place)
        "created_at": fs.utc_now(),
        "metadata": metadata,
        "thumbnails": thumbs,
        "scenes": None,
    }
    fs.save_record(record)
    return record


# -------------------------------------------------------------- endpoints
@app.get("/health", tags=["system"])
def health() -> Dict[str, Any]:
    """Checks Python, FFmpeg, FFprobe, Ollama, the qwen2.5:3b model and free disk space."""
    return run_checks()


@app.post("/videos/register", tags=["videos"])
def register_video(req: RegisterRequest) -> Dict[str, Any]:
    """Register a video that already exists on your disk. No copy is made (saves space)."""
    try:
        role = fs.validate_role(req.role)
        path = fs.resolve_local_video(req.path)
        return _public(_ingest(path, path.name, role, "local", fs.new_video_id()))
    except fs.FileValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except VideoProbeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/videos/upload", tags=["videos"])
def upload_video(file: UploadFile = File(...), role: str = Form("gameplay")) -> Dict[str, Any]:
    """Upload a video (streamed to disk). For large recordings prefer /videos/register."""
    saved: Optional[Path] = None
    try:
        role = fs.validate_role(role)
        video_id = fs.new_video_id()
        saved, _ = fs.save_upload(file.file, file.filename or "", video_id)
        return _public(_ingest(saved, file.filename or saved.name, role, "upload", video_id))
    except fs.FileTooLargeError as exc:
        if saved:
            saved.unlink(missing_ok=True)
        raise HTTPException(status_code=413, detail=str(exc))
    except fs.FileValidationError as exc:
        if saved:
            saved.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc))
    except VideoProbeError as exc:
        if saved:
            saved.unlink(missing_ok=True)  # do not keep invalid files
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/videos", tags=["videos"])
def list_videos(role: Optional[str] = None) -> Dict[str, Any]:
    records = fs.list_records()
    if role:
        records = [r for r in records if r.get("role") == role]
    return {"count": len(records), "videos": [_public(r) for r in records]}


@app.get("/videos/{video_id}", tags=["videos"])
def get_video(video_id: str) -> Dict[str, Any]:
    return _public(_get_or_404(video_id))


@app.post("/videos/{video_id}/thumbnails", tags=["analysis"])
def regenerate_thumbnails(
    video_id: str,
    count: int = Query(default=settings.thumbnail_count, ge=1, le=12),
    width: int = Query(default=settings.thumbnail_width, ge=64, le=1280),
) -> Dict[str, Any]:
    record = _get_or_404(video_id)
    path = Path(record["path"])
    if not path.is_file():
        raise HTTPException(status_code=410, detail="Source video file no longer exists")
    with _processing_lock:
        record["thumbnails"] = generate_thumbnails(
            path, fs.thumbnail_dir(video_id), record["metadata"]["duration_seconds"], count, width
        )
    fs.save_record(record)
    return _public(record)


@app.post("/videos/{video_id}/scenes", tags=["analysis"])
def run_scene_detection(
    video_id: str,
    threshold: Optional[float] = Query(default=None, ge=1, le=100, description="Lower = more sensitive"),
    frame_skip: Optional[int] = Query(default=None, ge=0, le=10, description="Frames skipped between checks"),
) -> Dict[str, Any]:
    record = _get_or_404(video_id)
    path = Path(record["path"])
    if not path.is_file():
        raise HTTPException(status_code=410, detail="Source video file no longer exists")
    try:
        with _processing_lock:
            record["scenes"] = detect_scenes(
                path,
                record["metadata"]["duration_seconds"],
                threshold=threshold,
                frame_skip=frame_skip,
            )
    except Exception as exc:  # PySceneDetect / OpenCV errors
        raise HTTPException(status_code=500, detail=f"Scene detection failed: {exc}")
    fs.save_record(record)
    return _public(record)


@app.get("/videos/{video_id}/thumbnails/{name}", tags=["videos"])
def get_thumbnail(video_id: str, name: str):
    try:
        folder = fs.thumbnail_dir(video_id)
    except fs.RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Video not found")
    file = folder / Path(name).name  # strip any directory parts
    if not file.is_file():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(file, media_type="image/jpeg")


@app.delete("/videos/{video_id}", tags=["videos"])
def delete_video(video_id: str) -> Dict[str, Any]:
    """Removes analysis data and thumbnails. Your original files are never deleted
    (only copies made by /videos/upload)."""
    _get_or_404(video_id)
    fs.delete_record(video_id)
    return {"deleted": video_id}
