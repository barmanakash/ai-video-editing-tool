"""Clip cutting: turns a plan clip into FFmpeg input arguments.

Seeking is done on the INPUT side (-ss before -i, -t as an input option), so FFmpeg
jumps straight to the clip and only decodes the seconds that are actually used.
Arguments are always a list (never a shell string).
"""
from __future__ import annotations

from typing import Any, Dict, List


def clip_length(clip: Dict[str, Any]) -> float:
    return float(clip["end"]) - float(clip["start"])


def input_args(clip: Dict[str, Any], path: str) -> List[str]:
    return ["-ss", f"{float(clip['start']):.3f}", "-t", f"{clip_length(clip):.3f}", "-i", str(path)]
