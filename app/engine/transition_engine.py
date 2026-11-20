"""Transitions: chains clips together inside one FFmpeg filter graph.

  cut        -> concat filter (no overlap)
  others     -> xfade (video) + acrossfade (audio), overlapping by `td` seconds

The transition length is limited to 40% of each neighbouring clip so a short clip can
have a transition on both sides without the overlaps colliding.
"""
from __future__ import annotations

from typing import List, Tuple

from app.config import settings

XFADE_NAMES = {
    "crossfade": "fade",
    "fadeblack": "fadeblack",
    "fadewhite": "fadewhite",
    "slideleft": "slideleft",
}
MIN_TRANSITION = 0.08
MAX_SHARE = 0.4


def transition_duration(name: str, len_a: float, len_b: float) -> float:
    """Overlap in seconds (0.0 means a hard cut)."""
    if name not in XFADE_NAMES:
        return 0.0
    td = min(float(settings.transition_seconds), MAX_SHARE * len_a, MAX_SHARE * len_b)
    return round(td, 3) if td >= MIN_TRANSITION else 0.0


def join_streams(j: int, cur_v: str, cur_a: str, cur_len: float, next_len: float,
                 name: str, td: float, fps: int) -> Tuple[List[str], str, str, float]:
    """Join the running stream with clip j ([v{j}] / [a{j}]).

    Returns (graph_lines, new_video_label, new_audio_label, new_length).
    """
    if td <= 0 or name not in XFADE_NAMES:
        lines = [
            f"{cur_v}{cur_a}[v{j}][a{j}]concat=n=2:v=1:a=1[cv{j}][ca{j}]",
            # concat resets the timebase; fps restores 1/fps so a later xfade accepts it
            f"[cv{j}]fps={fps}[vj{j}]",
        ]
        return lines, f"[vj{j}]", f"[ca{j}]", cur_len + next_len
    lines = [
        f"{cur_v}[v{j}]xfade=transition={XFADE_NAMES[name]}:duration={td:.3f}:offset={cur_len - td:.3f}[vj{j}]",
        f"{cur_a}[a{j}]acrossfade=d={td:.3f}:c1=tri:c2=tri[aj{j}]",
    ]
    return lines, f"[vj{j}]", f"[aj{j}]", cur_len + next_len - td
