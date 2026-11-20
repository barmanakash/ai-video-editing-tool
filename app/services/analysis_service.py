"""Storage for gameplay highlight analyses.

One small JSON file per video: data/analysis/<video_id>/gameplay.json
(next to the video.json record, so deleting a video removes both).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from app.config import settings
from app.services import file_service as fs


def _path(video_id: str) -> Path:
    return settings.analysis_dir / fs.validate_video_id(video_id) / "gameplay.json"


def save_gameplay(analysis: Dict[str, Any]) -> Path:
    path = _path(analysis["video_id"])
    fs.atomic_write_json(path, analysis)
    return path


def load_gameplay(video_id: str) -> Dict[str, Any]:
    path = _path(video_id)
    if not path.is_file():
        raise fs.RecordNotFoundError(video_id)
    return json.loads(path.read_text(encoding="utf-8"))


def gameplay_exists(video_id: str) -> bool:
    try:
        return _path(video_id).is_file()
    except fs.RecordNotFoundError:
        return False


def list_gameplay() -> List[Dict[str, Any]]:
    """Short listing. Use load_gameplay for the full analysis."""
    out: List[Dict[str, Any]] = []
    if not settings.analysis_dir.is_dir():
        return out
    for entry in sorted(settings.analysis_dir.iterdir()):
        f = entry / "gameplay.json"
        if not (entry.is_dir() and f.is_file()):
            continue
        try:
            a = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({
            "video_id": a.get("video_id"),
            "name": (a.get("source") or {}).get("original_name"),
            "created_at": a.get("created_at"),
            "highlight_count": len(a.get("estimated_highlights", [])),
            "truncated": (a.get("source") or {}).get("truncated", False),
        })
    return out
