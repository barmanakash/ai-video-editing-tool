"""Titles and text overlays (FFmpeg drawtext).

Text is sanitised by the plan validator (clean_text) and drawn with expansion disabled, so
nothing a user or the LLM types can become an FFmpeg expression or command.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_UNSAFE = re.compile(r"[^\w .,!?&()+\-#@/]", re.UNICODE)
FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]
SIZE_FACTOR = {"large": 0.11, "medium": 0.075, "small": 0.05}      # of the shorter video side
FADE = 0.3


def clean_text(value: Any, max_len: int = 60) -> str:
    """Keep letters, digits, spaces and a few safe symbols. Everything else is removed."""
    if not isinstance(value, str):
        return ""
    return _UNSAFE.sub("", _CONTROL.sub("", value)).strip()[:max_len]


def find_font() -> Optional[str]:
    """Font file for drawtext: GVE_FONT, then common system fonts. None if nothing is found."""
    env = os.environ.get("GVE_FONT")
    for cand in ([env] if env else []) + FONT_CANDIDATES:
        if cand and "'" not in cand and Path(cand).is_file():
            return cand.replace("\\", "/")
    return None


@lru_cache(maxsize=1)
def drawtext_available() -> bool:
    ffmpeg = shutil.which(settings.ffmpeg_path)
    if not ffmpeg:
        return False
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return " drawtext " in r.stdout


def _escape_font(path: str) -> str:
    return path.replace(":", "\\:")                  # C:/Windows/... -> C\:/Windows/...


def build_filters(titles: Optional[List[Dict[str, Any]]], total: float, width: int, height: int) -> Tuple[List[str], List[str]]:
    """Return (drawtext filters, notes). Titles that cannot be drawn are skipped with a note."""
    if not titles:
        return [], []
    if not drawtext_available():
        return [], ["titles skipped: this FFmpeg build has no drawtext filter"]
    font = find_font()
    if not font:
        return [], ["titles skipped: no font found (set GVE_FONT to a .ttf file)"]

    filters: List[str] = []
    short_side = min(width, height)
    for t in titles:
        text = clean_text(t.get("text"))
        if not text:
            continue
        dur = min(float(t.get("duration", 2.5)), total)
        at = t.get("at", "start")
        start = 0.0 if at == "start" else max(total - dur, 0.0) if at == "end" else float(t.get("start", 0.0))
        start = min(max(start, 0.0), max(total - 0.5, 0.0))
        end = min(start + dur, total)
        if end - start < 0.4:
            continue

        size = short_side * SIZE_FACTOR.get(t.get("size", "large"), 0.11)
        size = min(size, 0.9 * width / (0.58 * max(len(text), 1)))          # never wider than the frame
        size = max(int(size), 12)
        pos = t.get("position", "center")
        y = {"center": "(h-text_h)/2", "lower": "h*0.74", "top": "h*0.09"}.get(pos, "(h-text_h)/2")
        alpha = f"min(1,min((t-{start:.2f})/{FADE},({end:.2f}-t)/{FADE}))"
        parts = [
            f"fontfile='{_escape_font(font)}'",
            f"text='{text}'",
            f"fontsize={size}",
            "fontcolor=white",
            f"borderw={max(size // 22, 2)}",
            "bordercolor=black@0.85",
            "shadowx=2", "shadowy=2",
            "x=(w-text_w)/2",
            f"y={y}",
            f"enable='between(t,{start:.2f},{end:.2f})'",
            f"alpha='{alpha}'",
            "expansion=none",
        ]
        if pos == "lower":
            parts += ["box=1", "boxcolor=black@0.35", f"boxborderw={max(size // 3, 6)}"]
        filters.append("drawtext=" + ":".join(parts))
    return filters, []
