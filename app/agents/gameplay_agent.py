"""Gameplay Analysis agent: finds CANDIDATE highlight moments.

Honest by design. The output keeps two things strictly apart:

  detected     = measured facts (scene cuts, loud moments, brightness flashes)
  estimated    = "estimated_highlights": moments where motion, audio and visual
                 change are unusually high. These are guesses about excitement,
                 NOT recognised fights, explosions or chases.

A future semantic detector (see event_detectors.py) can add real labelled
events without changing anything else.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from app.analyzers.audio_analyzer import analyze_audio_detailed
from app.analyzers.event_detectors import registered_names, run_detectors
from app.analyzers.motion_analyzer import analyze_frames

ANALYSIS_VERSION = 1
MIN_SEPARATION = 6      # seconds between two highlights
MIN_SCORE = 0.35        # never report a "highlight" weaker than this
SEMANTIC_BONUS = 0.25   # added to seconds inside a semantic event

WEIGHTS_WITH_AUDIO = {"motion": 0.30, "diff": 0.15, "audio": 0.30, "onsets": 0.10, "cuts": 0.10, "flash": 0.05}
WEIGHTS_NO_AUDIO = {"motion": 0.45, "diff": 0.25, "cuts": 0.20, "flash": 0.10}


class GameplayAnalysisError(RuntimeError):
    pass


def _norm(x: np.ndarray) -> np.ndarray:
    """Robust 0..1 scaling (10th to 95th percentile) so one huge spike doesn't flatten everything."""
    if x.size == 0:
        return x
    lo, hi = float(np.percentile(x, 10)), float(np.percentile(x, 95))
    if hi - lo < 1e-9:
        return np.zeros_like(x, dtype=float)
    return np.clip((x - lo) / (hi - lo), 0.0, 1.0)


def _smooth(x: np.ndarray, k: int = 3) -> np.ndarray:
    if x.size == 0 or k <= 1:
        return x
    padded = np.pad(x, (k // 2, k - 1 - k // 2), mode="edge")
    return np.convolve(padded, np.ones(k) / k, mode="valid")[: x.size]


def _fit(a: np.ndarray, n: int, fill: float) -> np.ndarray:
    """Trim or pad a per-second array to exactly n entries."""
    a = np.asarray(a, dtype=float)
    if a.size >= n:
        return a[:n]
    return np.concatenate([a, np.full(n - a.size, fill)])


def _top_loud_moments(db: np.ndarray, count: int = 10, gap: int = 3) -> List[Dict[str, float]]:
    if db.size == 0:
        return []
    work = db.copy()
    out: List[Dict[str, float]] = []
    for _ in range(count):
        i = int(np.argmax(work))
        if work[i] <= -90:
            break
        out.append({"time": float(i) + 0.5, "peak_dbfs": round(float(db[i]), 1)})
        work[max(0, i - gap): i + gap + 1] = -100
    return out


def analyze_gameplay(
    record: Dict[str, Any],
    max_seconds: float = 600.0,
    top_k: int = 8,
    flow_fps: float = 2.0,
    fps_cap: float = 10.0,
    lead: float = 4.0,
    tail: float = 5.0,
) -> Dict[str, Any]:
    meta = record["metadata"]
    path = Path(record["path"])
    if not path.is_file():
        raise GameplayAnalysisError("Source video file no longer exists")

    duration = float(meta["duration_seconds"])
    window = min(duration, float(max_seconds))
    video = meta["video"]

    frames = analyze_frames(
        path, video["width"], video["height"], video["fps"], duration, max_seconds,
        flow_fps=flow_fps, fps_cap=fps_cap, include_series=True,
    )
    has_audio = meta.get("audio") is not None
    audio, onset_times, audio_db, onset_counts = analyze_audio_detailed(path, has_audio, window)
    audio_ok = bool(audio.get("analyzed"))

    series = frames["series"]
    secs = int(series["seconds"])
    diff = np.asarray(series["diff"], dtype=float)
    flow = np.asarray(series["flow"], dtype=float)
    bright = np.asarray(series["brightness"], dtype=float)

    # ---- detected facts: scene cuts ------------------------------------
    scene_result = record.get("scenes")
    cut_times: List[float] = []
    if scene_result and scene_result.get("scenes"):
        cut_times = [float(s["start"]) for s in scene_result["scenes"][1:] if float(s["start"]) < window]
    cut_counts = np.zeros(secs)
    for t in cut_times:
        cut_counts[min(int(t), secs - 1)] += 1

    # ---- per-second components (each 0..1) -----------------------------
    components: Dict[str, np.ndarray] = {
        "motion": _norm(flow),
        "diff": _norm(diff),
        "cuts": np.minimum(cut_counts, 2.0) / 2.0,
        "flash": _norm(np.abs(np.diff(bright, prepend=bright[0]))),
    }
    if audio_ok:
        components["audio"] = _norm(_fit(audio_db, secs, -90.0))
        components["onsets"] = _norm(_fit(onset_counts.astype(float), secs, 0.0))
    weights = WEIGHTS_WITH_AUDIO if audio_ok else WEIGHTS_NO_AUDIO

    excitement = sum(weights[k] * components[k] for k in weights)

    # ---- optional semantic events (none registered in the first version) ----
    semantic_events, detector_errors = run_detectors(str(path), record)
    for e in semantic_events:
        a, b = int(e["start"]), min(int(np.ceil(e["end"])), secs)
        if b > a:
            excitement[a:b] += SEMANTIC_BONUS * float(e["confidence"])
    excitement = _smooth(np.clip(excitement, 0.0, 1.5), 3)

    # ---- pick well-separated peaks -------------------------------------
    threshold = max(MIN_SCORE, float(np.percentile(excitement, 75))) if secs else MIN_SCORE
    work = excitement.copy()
    peaks: List[int] = []
    for _ in range(max(1, int(top_k))):
        t = int(np.argmax(work))
        if work[t] < threshold:
            break
        peaks.append(t)
        work[max(0, t - MIN_SEPARATION): t + MIN_SEPARATION + 1] = -1.0

    highlights: List[Dict[str, Any]] = []
    for rank, t in enumerate(peaks, start=1):
        start = max(0.0, t - lead)
        end = min(window, t + tail)
        if end - start < 2.0:
            continue
        comp_at = {k: float(components[k][t]) for k in weights}
        reasons = [k for k, v in sorted(comp_at.items(), key=lambda kv: -kv[1]) if v >= 0.5][:3]
        if not reasons:
            reasons = [max(comp_at, key=comp_at.get)]
        highlights.append({
            "id": f"h{rank}",
            "kind": "estimated_highlight",
            "start": round(start, 2),
            "end": round(end, 2),
            "peak_time": round(t + 0.5, 2),
            "score": round(float(excitement[t]), 3),
            "reasons": reasons,
            "confidence": "estimate",
        })

    return {
        "analysis_version": ANALYSIS_VERSION,
        "video_id": record["id"],
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "original_name": record.get("original_name"),
            "duration_seconds": duration,
            "analyzed_seconds": round(window, 2),
            "truncated": duration > max_seconds,
        },
        "analysis_settings": {
            "max_seconds": max_seconds, "top_k": top_k, "flow_fps": flow_fps,
            "frame_analysis_fps": frames["analysis_fps"], "weights": weights,
            "audio_used": audio_ok,
        },
        "detected": {
            "scene_cuts": [round(t, 2) for t in cut_times[:300]],
            "scene_cuts_available": bool(scene_result),
            "loud_moments": _top_loud_moments(_fit(audio_db, secs, -100.0)) if audio_ok else [],
            "brightness_flashes": frames["transitions"]["bright_flash_times"],
            "audio": ({k: audio[k] for k in ("mean_rms_dbfs", "peak_window_dbfs", "onset_count", "loudness_label")} if audio_ok else audio),
        },
        "estimated_highlights": highlights,
        "semantic_events": semantic_events,
        "semantic_detectors_registered": registered_names(),
        "detector_errors": detector_errors,
        "series": {"seconds": secs, "excitement": [round(float(x), 3) for x in excitement]},
        "limitations": [
            "Highlights are estimates from motion, audio loudness and visual change. They do NOT mean a fight, explosion or chase was recognised.",
            "Loud game music or constant gunfire can raise scores everywhere and blur the peaks.",
            "Scene cuts are only available if scene detection was run for this video.",
            "Add a semantic detector (event_detectors.py) later for real event recognition.",
        ] + ([f"Only the first {max_seconds:.0f} s were analysed."] if duration > max_seconds else []),
    }
