"""Scene (shot-cut) detection with PySceneDetect.

IMPORTANT: this finds *visual cuts*, not gameplay events. A scene boundary
does not mean a fight, explosion or chase happened. Semantic event detection
is intentionally out of scope for Phase 1.

Memory use: PySceneDetect streams frames one by one and downscales them
automatically, so the full video is never loaded into RAM.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from app.config import settings


def _seconds(timecode) -> float:
    # PySceneDetect 0.7+ uses the `.seconds` property; older versions use get_seconds().
    value = getattr(timecode, "seconds", None)
    return float(value if value is not None else timecode.get_seconds())


def detect_scenes(
    path: Path,
    duration_seconds: float,
    threshold: float | None = None,
    frame_skip: int | None = None,
    min_scene_len: int | None = None,
) -> Dict[str, Any]:
    from scenedetect import ContentDetector, SceneManager, open_video

    threshold = settings.scene_threshold if threshold is None else threshold
    frame_skip = settings.scene_frame_skip if frame_skip is None else frame_skip
    min_scene_len = settings.scene_min_len_frames if min_scene_len is None else min_scene_len

    video = open_video(str(path))
    manager = SceneManager()
    manager.add_detector(ContentDetector(threshold=threshold, min_scene_len=min_scene_len))
    manager.detect_scenes(video, frame_skip=frame_skip, show_progress=False)
    raw = manager.get_scene_list()

    scenes: List[Dict[str, Any]] = []
    for i, (start, end) in enumerate(raw):
        s, e = _seconds(start), _seconds(end)
        scenes.append({"index": i, "start": round(s, 3), "end": round(e, 3), "duration": round(e - s, 3)})

    # No cuts found => the whole video is a single continuous shot.
    if not scenes:
        scenes.append(
            {"index": 0, "start": 0.0, "end": round(duration_seconds, 3), "duration": round(duration_seconds, 3)}
        )

    count = len(scenes)
    avg = sum(s["duration"] for s in scenes) / count
    cuts_per_minute = ((count - 1) / duration_seconds * 60) if duration_seconds > 0 else 0.0

    return {
        "settings": {"threshold": threshold, "frame_skip": frame_skip, "min_scene_len_frames": min_scene_len},
        "scene_count": count,
        "average_scene_duration": round(avg, 3),
        "cuts_per_minute": round(cuts_per_minute, 2),
        "scenes": scenes,
        "note": "Scenes are detected visual cuts, not gameplay events.",
    }
