"""Trim + effects for ONE clip, rendered to a small intermediate file.

Clips are rendered one at a time, so only one FFmpeg process runs and disk use
stays small. Every intermediate has identical size, fps and audio format, which
lets the join step stitch them together safely.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from app.engine.effects_engine import audio_filters, video_filters
from app.engine.ffmpeg_utils import run_ffmpeg
from app.engine.plan_schema import effective_duration


def render_clip(
    ffmpeg: str,
    clip: Dict[str, Any],
    source: Dict[str, Any],
    out_path: Path,
    width: int,
    height: int,
    fps: int,
    fit: str,
    color: Dict[str, float],
    game_volume: float,
    preset: str,
    crf: int,
) -> float:
    """Render one clip. Returns its effective duration in seconds."""
    eff = effective_duration(clip)
    src_len = float(clip["end"]) - float(clip["start"])
    has_audio = bool(source.get("has_audio"))

    cmd = [
        ffmpeg, "-v", "error", "-y",
        "-ss", f"{clip['start']:.3f}", "-t", f"{src_len:.3f}", "-i", str(source["path"]),
    ]
    if has_audio:
        audio_in = "[0:a]"
    else:  # silent source: generate silence so every clip has an audio track
        cmd += ["-f", "lavfi", "-t", f"{eff:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        audio_in = "[1:a]"

    graph = (
        f"[0:v]{video_filters(clip, width, height, fps, fit, color)}[v];"
        f"{audio_in}{audio_filters(clip, has_audio, game_volume)}[a]"
    )
    cmd += [
        "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(out_path),
    ]
    run_ffmpeg(cmd, timeout=max(300.0, eff * 40), label=f"clip {out_path.name}")
    return eff
