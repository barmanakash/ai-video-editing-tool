"""Smart vertical crop, step 1: where is the action horizontally? (Phase 7C)

For a clip we watch the video at low resolution (a few frames per second), measure which
image columns are changing the most, and follow that. The result is a list of keyframes
(seconds from the start of the clip, horizontal position 0.0 = left edge, 1.0 = right edge).

This is an ESTIMATE based on motion, not recognition of the player or enemies:
  * whole-screen camera movement spreads motion everywhere, so the crop stays near the centre;
  * a localised event (an explosion, a running character) pulls the crop towards it;
  * when almost nothing moves, the crop holds still instead of wandering.

Only one small grayscale frame is in memory at a time.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

from app.config import settings

PROBE_FPS = 6.0
PROBE_WIDTH = 160
BUCKET = 0.5             # seconds per keyframe
MIN_ACTIVITY = 1.2       # mean column activity below this = nothing worth following
MAX_STEP = 0.22          # biggest move between keyframes (fraction of the frame width)
SMOOTHING = 0.55         # 1.0 = jumpy, small = slow and smooth
MIN_ACTIVE_SHARE = 0.25  # if fewer buckets than this have motion, just stay centred


def focus_track(path: Path, start: float, end: float, src_width: int, src_height: int) -> Dict[str, Any]:
    """Keyframes following the horizontal centre of motion between `start` and `end` (source seconds)."""
    ffmpeg = shutil.which(settings.ffmpeg_path)
    length = max(end - start, 0.1)
    if not ffmpeg or src_width <= 0 or src_height <= 0:
        return {"keyframes": [(0.0, 0.5), (length, 0.5)], "active_share": 0.0, "centred": True}

    w = PROBE_WIDTH
    h = max(2, int(round(src_height * w / src_width / 2)) * 2)
    cmd = [ffmpeg, "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(path), "-an",
           "-vf", f"fps={PROBE_FPS},scale={w}:{h}", "-pix_fmt", "gray", "-f", "rawvideo", "-"]
    import cv2

    xs = np.arange(w, dtype=np.float32)
    raw: List[Tuple[float, float, float]] = []      # (time, centroid 0..1, activity)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=w * h * 4)
    prev = None
    index = 0
    try:
        while True:
            buf = proc.stdout.read(w * h)
            if len(buf) < w * h:
                break
            frame = np.frombuffer(buf, dtype=np.uint8).reshape(h, w)
            if prev is not None:
                diff = cv2.GaussianBlur(cv2.absdiff(frame, prev), (5, 5), 0).astype(np.float32)
                col = diff.sum(axis=0) / h                     # activity per column
                total = float(col.sum())
                centroid = float((col * xs).sum() / total / (w - 1)) if total > 1e-6 else 0.5
                raw.append((index / PROBE_FPS, centroid, float(col.mean())))
            prev = frame
            index += 1
    finally:
        try:
            proc.stdout.close()
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()

    buckets = int(np.ceil(length / BUCKET)) + 1
    values: List[float] = []
    active = 0
    last = 0.5
    for b in range(buckets):
        lo, hi = b * BUCKET, (b + 1) * BUCKET
        chunk = [(c, a) for t, c, a in raw if lo <= t < hi]
        if chunk and float(np.mean([a for _, a in chunk])) >= MIN_ACTIVITY:
            weights = np.asarray([a for _, a in chunk])
            last = float(np.average([c for c, _ in chunk], weights=weights))
            active += 1
        values.append(last)                                    # hold the last position when quiet

    share = active / max(buckets, 1)
    if share < MIN_ACTIVE_SHARE:
        return {"keyframes": [(0.0, 0.5), (length, 0.5)], "active_share": round(share, 2), "centred": True}

    smoothed: List[float] = []
    cur = values[0]
    for v in values:
        target = cur + SMOOTHING * (v - cur)
        cur = cur + max(-MAX_STEP, min(MAX_STEP, target - cur))
        smoothed.append(cur)
    keyframes = [(round(min(i * BUCKET, length), 3), round(float(x), 4)) for i, x in enumerate(smoothed)]
    keyframes[-1] = (round(length, 3), keyframes[-1][1])
    return {"keyframes": keyframes, "active_share": round(share, 2), "centred": False}
