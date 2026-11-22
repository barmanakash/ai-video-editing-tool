"""Video filters: speed, framing, zoom, colour grading presets and beat-driven punch effects.

Everything returns plain FFmpeg filter fragments built from validated numbers only.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

ZOOM_AMOUNT = 0.15          # zoom_in effect ends 15% closer than it started
PUNCH_ZOOM = 0.07           # beat zoom punch: 7% bigger at the hit, easing back
PUNCH_FLASH = 0.16          # beat flash: brightness added at the hit
PUNCH_DECAY = 14.0          # larger = shorter pulse
PUNCH_WINDOW = 0.4          # seconds a pulse lasts
MAX_PUNCHES = 40

# Colour grading looks. Applied to the whole finished video, before titles.
GRADE_PRESETS: Dict[str, List[str]] = {
    "none": [],
    "clean": [
        "eq=contrast=1.04:saturation=1.06",
        "unsharp=5:5:0.7:5:5:0.0",
    ],
    "vibrant": [
        "eq=contrast=1.08:saturation=1.35:gamma=1.02",
        "unsharp=5:5:0.8:5:5:0.0",
    ],
    "cinematic": [
        "curves=all='0/0 0.25/0.21 0.75/0.8 1/1'",                       # gentle S-curve
        "colorbalance=rs=-0.04:bs=0.05:rh=0.05:bh=-0.04",                # teal shadows, warm highlights
        "eq=saturation=1.08",
        "unsharp=5:5:0.5:5:5:0.0",
        "vignette=angle=PI/6",
    ],
}


def video_chain(clip: Dict[str, Any], width: int, height: int, fit: str, fps: int, duration: float) -> List[str]:
    """Filters applied to one clip piece: speed -> constant fps -> framing -> optional zoom."""
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
    """One `eq` filter for the manual brightness/contrast/saturation sliders, or None if neutral."""
    c = color or {}
    b, ct, s = float(c.get("brightness", 0.0)), float(c.get("contrast", 1.0)), float(c.get("saturation", 1.0))
    if abs(b) < 1e-3 and abs(ct - 1) < 1e-3 and abs(s - 1) < 1e-3:
        return None
    return f"eq=brightness={b:.3f}:contrast={ct:.3f}:saturation={s:.3f}"


def preset_filters(name: Optional[str]) -> List[str]:
    return list(GRADE_PRESETS.get(name or "none", []))


# ------------------------------------------------------------ beat punches
def thin_times(times: List[float], min_gap: float) -> List[float]:
    """Keep times at least `min_gap` apart (earliest first)."""
    out: List[float] = []
    for t in sorted(times):
        if not out or t - out[-1] >= min_gap:
            out.append(t)
    return out


def pulse_expr(times: List[float]) -> str:
    """FFmpeg expression in t: 1.0 at each time, decaying to 0 within PUNCH_WINDOW seconds."""
    terms = [
        f"if(between(t,{b:.3f},{b + PUNCH_WINDOW:.3f}),exp(-(t-{b:.3f})*{PUNCH_DECAY:g}),0)"
        for b in times[:MAX_PUNCHES]
    ]
    return "(" + "+".join(terms) + ")"


def punch_chain(times: List[float], width: int, height: int, zoom: bool, flash: bool, shake: bool) -> List[str]:
    """Zoom punch, camera shake and flash that hit on the given timeline times."""
    if not times or not (zoom or flash or shake):
        return []
    p = pulse_expr(times)
    f: List[str] = []
    if zoom:
        z = f"(1+{PUNCH_ZOOM}*{p})"
        f.append(f"scale=w='trunc({width}*{z}/2)*2':h='trunc({height}*{z}/2)*2':eval=frame")
        f.append(f"crop={width}:{height}")
    if shake:
        f.append(f"scale={int(width * 1.04) // 2 * 2}:{int(height * 1.04) // 2 * 2}")
        amp_x, amp_y = width * 0.006, height * 0.006
        f.append(f"crop={width}:{height}:x='(in_w-out_w)/2+{amp_x:.1f}*{p}*sin(t*70)':"
                 f"y='(in_h-out_h)/2+{amp_y:.1f}*{p}*cos(t*83)'")
    if flash:
        f.append(f"eq=brightness='{PUNCH_FLASH}*{p}':eval=frame")
    return f
