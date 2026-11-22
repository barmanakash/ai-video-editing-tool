"""API routes for export options (Phase 7B): resolutions, codecs, hardware status, size estimates."""
from __future__ import annotations

import shutil
from typing import Any, Dict, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import settings
from app.engine import encoders

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/options")
def export_options() -> Dict[str, Any]:
    """What this computer can export, including which hardware encoders really work.

    The first call may take a few seconds because it runs tiny test encodes.
    """
    ffmpeg = shutil.which(settings.ffmpeg_path) or settings.ffmpeg_path
    hw = encoders.hardware_status(ffmpeg)
    return {
        "qualities": [
            {"id": q, "label": encoders.QUALITY_LABELS[q],
             "youtube": "x".join(map(str, encoders.output_size("youtube", q))),
             "instagram": "x".join(map(str, encoders.output_size("instagram", q)))}
            for q in encoders.LANDSCAPE_SIZES
        ],
        "fps": [24, 30, 60],
        "codecs": [
            {"id": "h264", "label": "H.264 (plays everywhere, best for Instagram)", "available": hw["libx264"]["usable"]},
            {"id": "hevc", "label": "HEVC / H.265 (smaller files, slower on the CPU)",
             "available": hw["libx265"]["usable"] or hw["hevc_qsv"]["usable"]},
        ],
        "quality_levels": ["fast", "standard", "high"],
        "intel_quick_sync": {"h264": hw["h264_qsv"]["usable"], "hevc": hw["hevc_qsv"]["usable"]},
        "encoders": hw,
        "notes": [
            "A 4K or 1440p export from 1080p recordings is upscaled: the file is bigger but has no extra detail.",
            "Preview (480p) always uses fast H.264 so you can check an edit quickly before the real export.",
        ],
    }


class EstimateRequest(BaseModel):
    seconds: float = Field(..., gt=0, le=3600, description="Length of the finished video")
    format: Literal["youtube", "instagram"] = "youtube"
    quality: Literal["test", "full", "1440p", "4k"] = "full"
    fps: int = Field(default=30, ge=24, le=60)
    codec: Literal["h264", "hevc"] = "h264"
    quality_level: Literal["fast", "standard", "high"] = "standard"


@router.post("/estimate")
def estimate(req: EstimateRequest) -> Dict[str, Any]:
    """Rough file size and a check that it fits on the disk (the renderer refuses if it would not)."""
    settings.ensure_dirs()
    w, h = encoders.output_size(req.format, req.quality)
    size = encoders.estimate_size_mb(w, h, req.fps, req.seconds, req.codec, req.quality_level)
    free = shutil.disk_usage(settings.outputs_dir).free / 1024 ** 2
    need = size * 1.3 + settings.min_free_render_gb * 1024
    return {
        "resolution": f"{w}x{h}",
        "estimated_mb": round(size),
        "free_mb": round(free),
        "fits": free >= need,
        "note": None if free >= need else "Not enough free disk space for this export.",
    }
