"""Clip cutting: FFmpeg input arguments for the part of a source video that a plan clip uses.

Each clip becomes its own seeked input, so FFmpeg only decodes the seconds that are
actually used (important for long gameplay recordings on an 8 GB machine).
"""
from __future__ import annotations

from typing import Any, Dict, List


def input_args(clip: Dict[str, Any], path: str) -> List[str]:
    """Arguments for one clip: seek to its start and read only its length."""
    start = float(clip["start"])
    length = float(clip["end"]) - start
    return ["-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(path)]
