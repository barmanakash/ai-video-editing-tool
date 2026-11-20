"""Storage for reusable reference style profiles (one JSON file per video id).

Profiles are tiny (a few KB) and independent of the source video, so you can
delete a large reference video to free disk space and keep its profile.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from app.config import settings
from app.services import file_service as fs


def _path(video_id: str) -> Path:
    return settings.reference_profiles_dir / f"{fs.validate_video_id(video_id)}.json"


def save_profile(profile: Dict[str, Any]) -> Path:
    path = _path(profile["id"])
    fs.atomic_write_json(path, profile)
    return path


def load_profile(video_id: str) -> Dict[str, Any]:
    path = _path(video_id)
    if not path.is_file():
        raise fs.RecordNotFoundError(video_id)
    return json.loads(path.read_text(encoding="utf-8"))


def profile_exists(video_id: str) -> bool:
    return _path(video_id).is_file()


def list_profiles() -> List[Dict[str, Any]]:
    """Short listing (id, name, summary, tags). Use load_profile for the full JSON."""
    out: List[Dict[str, Any]] = []
    folder = settings.reference_profiles_dir
    if not folder.is_dir():
        return out
    for f in sorted(folder.glob("*.json")):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({
            "id": p.get("id"),
            "name": p.get("name"),
            "created_at": p.get("created_at"),
            "summary": p.get("summary"),
            "style_tags": p.get("style_tags", []),
        })
    return out


def delete_profile(video_id: str) -> None:
    path = _path(video_id)
    if not path.is_file():
        raise fs.RecordNotFoundError(video_id)
    path.unlink()
