"""Per-clip video filters: speed, framing (crop or pad), zoom, and the final colour grade.

Everything returns plain FFmpeg filter fragments built from validated numbers only.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

ZOOM_AMOUNT = 0.15      # zoom_in effect ends 15% closer than it started


def video_chain(clip: Dict[str, Any], width: int, height: int, fit: str, fps: int, duration: float) -> List[str]:
    """Filters applied to one clip: speed -> constant fps -> framing -> optional zoom."""
    speed = float(clip["speed"])
    f = [f"setpts=(PTS-STARTPTS)/{speed:.4f}", f"fps={fps}"]
    if fit == "pad":
        f.append(f"scale={width}:{height}:force_original_aspect_ratio=decrease")
        f.append(f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black")
    else:
        f.append(f"scale={width}:{height}:force_original_aspect_ratio=increase")
        f.append(f"crop={width}:{height}")
    if clip.get("effect") == "zoom_in":
        d = max(duration, 0.1)
        grow = f"(1+{ZOOM_AMOUNT}*min(t/{d:.3f},1))"
        f.append(f"scale=w='trunc({width}*{grow}/2)*2':h='trunc({height}*{grow}/2)*2':eval=frame")
        f.append(f"crop={width}:{height}")
    f += ["setsar=1", "format=yuv420p"]
    return f


def color_filter(color: Optional[Dict[str, Any]]) -> Optional[str]:
    """One `eq` filter for the whole video, or None when the grade is neutral."""
    c = color or {}
    b, ct, s = float(c.get("brightness", 0.0)), float(c.get("contrast", 1.0)), float(c.get("saturation", 1.0))
    if abs(b) < 1e-3 and abs(ct - 1) < 1e-3 and abs(s - 1) < 1e-3:
        return None
    return f"eq=brightness={b:.3f}:contrast={ct:.3f}:saturation={s:.3f}"
