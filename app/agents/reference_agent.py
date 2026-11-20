"""Reference Video Analysis agent.

Builds a reusable JSON *style profile* from a registered reference video by
combining: scene cuts (PySceneDetect, already stored on the record), a single
streamed visual pass (OpenCV) and a streamed audio pass (FFmpeg + NumPy).

This module is plain Python (no LLM). The profile is later handed to Qwen as
context in Phase 4. No audio or video content is copied from the reference.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from app.analyzers.audio_analyzer import analyze_audio
from app.analyzers.motion_analyzer import analyze_frames

PROFILE_VERSION = 1
SYNC_TOLERANCE = 0.12  # seconds: a cut this close to an audio onset counts as "on the beat"


class ReferenceAnalysisError(RuntimeError):
    pass


# ------------------------------------------------------------------ pacing
def _clip_scenes(scenes: List[Dict[str, Any]], window: float) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for s in scenes:
        end = min(float(s["end"]), window)
        length = end - float(s["start"])
        if length > 0.05:
            out.append({"start": round(float(s["start"]), 3), "end": round(end, 3), "duration": round(length, 3)})
    return out


def _pacing(scenes: List[Dict[str, Any]], window: float) -> Dict[str, Any]:
    durations = [s["duration"] for s in scenes]
    n = len(durations)
    avg = sum(durations) / n
    stdev = statistics.pstdev(durations) if n > 1 else 0.0
    cv = stdev / avg if avg > 0 else 0.0

    trend = "unknown"
    if n >= 6:
        mid = window / 2.0
        first = [s["duration"] for s in scenes if s["start"] < mid]
        second = [s["duration"] for s in scenes if s["start"] >= mid]
        if first and second:
            a, b = sum(first) / len(first), sum(second) / len(second)
            trend = "accelerating" if b < a * 0.8 else "slowing_down" if b > a * 1.25 else "steady"

    return {
        "scene_count": n,
        "average_scene_duration": round(avg, 2),
        "median_scene_duration": round(statistics.median(durations), 2),
        "shortest_scene": round(min(durations), 2),
        "longest_scene": round(max(durations), 2),
        "cuts_per_minute": round((n - 1) / window * 60.0, 2) if window > 0 else 0.0,
        "pace_label": "very_fast" if avg < 1.5 else "fast" if avg < 3 else "medium" if avg < 6 else "slow",
        "duration_variability": round(cv, 2),
        "rhythm_regularity": "regular" if cv < 0.35 else "varied" if cv < 0.8 else "very_varied",
        "pace_trend": trend,
    }


def _rhythm(scenes: List[Dict[str, Any]], onset_times: np.ndarray, window: float, audio: Dict[str, Any]) -> Dict[str, Any]:
    cuts = np.asarray([s["start"] for s in scenes[1:]], dtype=float)
    if not audio.get("analyzed"):
        return {"available": False, "reason": "No usable audio"}
    if cuts.size < 3:
        return {"available": False, "reason": "Fewer than 3 cuts"}
    if onset_times.size == 0:
        return {"available": False, "reason": "No audio onsets detected"}
    idx = np.searchsorted(onset_times, cuts)
    left = onset_times[np.clip(idx - 1, 0, onset_times.size - 1)]
    right = onset_times[np.clip(idx, 0, onset_times.size - 1)]
    dist = np.minimum(np.abs(cuts - left), np.abs(cuts - right))
    matched = float((dist <= SYNC_TOLERANCE).mean())
    chance = min(1.0, (onset_times.size / max(window, 1e-6)) * 2 * SYNC_TOLERANCE)
    return {
        "available": True,
        "tolerance_seconds": SYNC_TOLERANCE,
        "cuts_on_audio_onsets_ratio": round(matched, 3),
        "chance_level": round(chance, 3),
        "cuts_synced_to_audio": bool(matched >= 0.4 and matched >= chance + 0.2),
        "note": "Compare the ratio with chance_level. A ratio near chance means no real sync.",
    }


# ------------------------------------------------------- tags and summary
def _style_tags(p: Dict[str, Any]) -> List[str]:
    tags: List[str] = [f"{p['pacing']['pace_label']}_cuts", f"{p['pacing']['rhythm_regularity']}_shot_lengths"]
    if p["pacing"]["pace_trend"] in ("accelerating", "slowing_down"):
        tags.append(p["pacing"]["pace_trend"])
    cam = p["camera"]
    if cam.get("samples"):
        tags.append(f"{cam['motion_label']}_motion")
        if cam["zoom_events_per_minute"] > 3:
            tags.append("frequent_zoom_punch_ins")
    t = p["transitions"]
    if t["dark_dips"] >= 2:
        tags.append("uses_fades_through_black")
    if t["bright_flashes"] >= 2:
        tags.append("uses_flash_transitions")
    if p["slow_motion"]["likely_used"]:
        tags.append("slow_motion_likely")
    c = p["color"]
    tags += [f"{c['brightness_label']}_look", f"{c['contrast_label']}_contrast", f"{c['saturation_label']}_colors", f"{c['tone']}_tone"]
    a = p["audio"]
    if a.get("analyzed"):
        tags.append(f"{a['loudness_label']}_audio")
    if p["rhythm"].get("cuts_synced_to_audio"):
        tags.append("cuts_synced_to_audio")
    if p["format"]["orientation"] == "portrait":
        tags.append("vertical_format")
    return tags


def _summary(p: Dict[str, Any]) -> str:
    pc, f, c = p["pacing"], p["format"], p["color"]
    parts = [
        f"{pc['pace_label'].replace('_', ' ').capitalize()}-paced edit: average shot {pc['average_scene_duration']} s, "
        f"about {pc['cuts_per_minute']} cuts per minute, {pc['rhythm_regularity']} shot lengths.",
        f"{f['width']}x{f['height']} ({f['aspect_ratio']}, {f['orientation']}) at {f['fps']} fps.",
        f"Look: {c['brightness_label']}, {c['contrast_label']} contrast, {c['saturation_label']} colours, {c['tone']} tone.",
    ]
    if p["slow_motion"]["likely_used"]:
        parts.append("Slow motion probably used (low confidence).")
    cam = p["camera"]
    if cam.get("samples") and cam["zoom_events_per_minute"] > 3:
        parts.append(f"Frequent zoom moments (~{cam['zoom_events_per_minute']} per minute, estimated).")
    if p["rhythm"].get("cuts_synced_to_audio"):
        parts.append("Cuts appear synchronised with audio hits.")
    return " ".join(parts)


def _planner_hints(p: Dict[str, Any]) -> Dict[str, Any]:
    avg = p["pacing"]["average_scene_duration"]
    t = p["transitions"]
    total = t["hard_cuts"] + t["dark_dips"] + t["bright_flashes"]
    mix = (
        {"cut": round(t["hard_cuts"] / total, 2), "fade": round(t["dark_dips"] / total, 2), "flash": round(t["bright_flashes"] / total, 2)}
        if total else {"cut": 1.0, "fade": 0.0, "flash": 0.0}
    )
    return {
        "clip_length_seconds": {
            "min": round(max(0.5, avg * 0.5), 1),
            "target": round(avg, 1),
            "max": round(max(avg * 2.0, 1.0), 1),
        },
        "transition_mix": mix,
        "prefer_cuts_on_audio_onsets": bool(p["rhythm"].get("cuts_synced_to_audio")),
        "use_slow_motion": bool(p["slow_motion"]["likely_used"]),
        "use_zoom_punch_ins": bool(p["camera"].get("zoom_events_per_minute", 0) > 3),
        "output_orientation": p["format"]["orientation"],
        "brightness_target": p["color"]["brightness_mean"],
        "contrast_target": p["color"]["contrast_mean"],
    }


# --------------------------------------------------------------------- main
def build_reference_profile(
    record: Dict[str, Any],
    max_seconds: float = 300.0,
    flow_fps: float = 4.0,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """`record` must already contain `scenes` (run scene detection first)."""
    meta = record["metadata"]
    path = Path(record["path"])
    if not path.is_file():
        raise ReferenceAnalysisError("Source video file no longer exists")
    scene_result = record.get("scenes")
    if not scene_result or not scene_result.get("scenes"):
        raise ReferenceAnalysisError("Scene detection has not been run for this video")

    duration = float(meta["duration_seconds"])
    window = min(duration, float(max_seconds))
    scenes = _clip_scenes(scene_result["scenes"], window)
    if not scenes:
        scenes = [{"start": 0.0, "end": round(window, 3), "duration": round(window, 3)}]

    video = meta["video"]
    frames = analyze_frames(path, video["width"], video["height"], video["fps"], duration, max_seconds, flow_fps)
    audio, onset_times = analyze_audio(path, meta.get("audio") is not None, window)

    pacing = _pacing(scenes, window)
    profile: Dict[str, Any] = {
        "profile_version": PROFILE_VERSION,
        "id": record["id"],
        "name": name or record.get("original_name"),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "original_name": record.get("original_name"),
            "duration_seconds": duration,
            "analyzed_seconds": round(window, 2),
            "truncated": duration > max_seconds,
        },
        "analysis_settings": {
            "max_seconds": max_seconds,
            "flow_fps": flow_fps,
            "frame_analysis_fps": frames["analysis_fps"],
            "frame_analysis_resolution": frames["analysis_resolution"],
            "scene_detection": scene_result.get("settings"),
        },
        "format": {
            "width": video["width"],
            "height": video["height"],
            "aspect_ratio": video["aspect_ratio"],
            "orientation": video["orientation"],
            "fps": video["fps"],
        },
        "pacing": pacing,
        "transitions": {"hard_cuts": pacing["scene_count"] - 1, **frames["transitions"]},
        "slow_motion": frames["slow_motion"],
        "camera": frames["motion"],
        "color": frames["color"],
        "audio": audio,
        "rhythm": _rhythm(scenes, onset_times, window, audio),
        "music_policy": "No audio is copied from the reference. Supply your own music that you have permission to use.",
    }
    profile["style_tags"] = _style_tags(profile)
    profile["summary"] = _summary(profile)
    profile["planner_hints"] = _planner_hints(profile)
    profile["limitations"] = [
        "All values are lightweight estimates, not ground truth.",
        "Scene detection finds hard visual cuts; dissolves, wipes and stylised transitions are not detected.",
        "Zoom is image expansion; camera moving forward in gameplay looks the same as a digital zoom.",
        "Slow motion is a low-confidence frame-duplication heuristic.",
        "Tempo and audio onsets are only meaningful if music dominates the audio.",
    ]
    if profile["source"]["truncated"]:
        profile["limitations"].append(f"Only the first {max_seconds:.0f} s of the video were analysed.")
    return profile
