"""Speed ramps: normal speed -> eased slow motion -> normal speed, inside ONE plan clip.

A ramp clip uses `speed` as the SLOWEST speed (for example 0.4) and an optional `peak`
(source time of the slowest moment; default = middle of the clip).

The ramp is built from five constant-speed pieces, which reads as a smooth ease in/out:

    speed 1.0 | mid | slowest | mid | 1.0        mid = (1 + slowest) / 2

The renderer turns each piece into its own seeked input of the same source file and joins
them with hard cuts (the footage is contiguous, so the joins are invisible).

This module is pure maths (no imports from the rest of the app) so both the plan schema
and the renderer can use it.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

MIN_PIECE = 0.08          # source seconds; shorter pieces are dropped
MAX_ZONE = 2.4            # longest single piece of the slow zone (source seconds)

Piece = Tuple[float, float, float]      # (source_start, source_end, speed)


def segments(clip: Dict[str, Any]) -> List[Piece]:
    start, end = float(clip["start"]), float(clip["end"])
    length = end - start
    slowest = min(max(float(clip["speed"]), 0.25), 1.0)
    raw_peak = clip.get("peak")
    peak = start + length / 2 if raw_peak is None else min(max(float(raw_peak), start), end)

    w = min(0.3 * length, MAX_ZONE)                     # width of each of the three slow-zone pieces
    zs = min(max(peak - 1.5 * w, start), end - 3 * w)   # slow zone start, kept inside the clip
    mid = (1.0 + slowest) / 2.0
    bounds = [start, zs, zs + w, zs + 2 * w, zs + 3 * w, end]
    speeds = [1.0, mid, slowest, mid, 1.0]

    pieces: List[Piece] = []
    for i, speed in enumerate(speeds):
        a, b = bounds[i], bounds[i + 1]
        if b - a >= MIN_PIECE:
            pieces.append((round(a, 3), round(b, 3), round(speed, 4)))
    if not pieces:                                       # degenerate: play the whole clip slowly
        pieces = [(round(start, 3), round(end, 3), round(slowest, 4))]
    return pieces


def duration(clip: Dict[str, Any]) -> float:
    """Seconds the ramped clip occupies in the final video."""
    return sum((b - a) / s for a, b, s in segments(clip))
