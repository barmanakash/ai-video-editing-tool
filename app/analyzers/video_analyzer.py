"""Video metadata (ffprobe) and thumbnails (ffmpeg).

Every external call uses an argument list (no shell) and a timeout.
Thumbnails are produced one at a time with fast seeking, so only a single
frame is ever decoded into memory.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings


class VideoProbeError(RuntimeError):
    """Raised when a file cannot be read as a valid video."""


def _require(executable: str, label: str) -> str:
    path = shutil.which(executable)
    if not path:
        raise VideoProbeError(f"{label} not found. Install FFmpeg and make sure it is on PATH.")
    return path


def _parse_rate(value: Optional[str]) -> float:
    if not value or value == "0/0":
        return 0.0
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return 0.0


def run_ffprobe(path: Path) -> Dict[str, Any]:
    ffprobe = _require(settings.ffprobe_path, "ffprobe")
    cmd = [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
        )
    except subprocess.TimeoutExpired as exc:
        raise VideoProbeError("ffprobe timed out while reading the file") from exc
    if proc.returncode != 0:
        raise VideoProbeError(f"Not a readable video file: {proc.stderr.strip()[:300]}")
    try:
        return json.loads(proc.stdout)
    except ValueError as exc:
        raise VideoProbeError("ffprobe returned invalid JSON") from exc


def extract_metadata(path: Path) -> Dict[str, Any]:
    """Return a compact metadata dict. Raises VideoProbeError for invalid videos."""
    probe = run_ffprobe(path)
    streams = probe.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise VideoProbeError("File has no video stream")

    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)

    # Phones / some recorders store rotation as metadata.
    rotation = 0
    try:
        rotation = int(float(video.get("tags", {}).get("rotate", 0)))
    except (TypeError, ValueError):
        pass
    for sd in video.get("side_data_list", []) or []:
        if "rotation" in sd:
            try:
                rotation = int(float(sd["rotation"]))
            except (TypeError, ValueError):
                pass
    if abs(rotation) % 180 == 90:
        width, height = height, width

    fmt = probe.get("format", {})
    duration = 0.0
    for candidate in (fmt.get("duration"), video.get("duration")):
        try:
            duration = float(candidate)
            if duration > 0:
                break
        except (TypeError, ValueError):
            continue

    if width <= 0 or height <= 0:
        raise VideoProbeError("Video has invalid dimensions")
    if duration <= 0:
        raise VideoProbeError("Video has no valid duration")

    fps = _parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate"))
    ratio = Fraction(width, height).limit_denominator(100)

    return {
        "duration_seconds": round(duration, 3),
        "size_bytes": int(fmt.get("size") or path.stat().st_size),
        "container": fmt.get("format_name"),
        "bit_rate": int(fmt["bit_rate"]) if fmt.get("bit_rate") else None,
        "video": {
            "codec": video.get("codec_name"),
            "width": width,
            "height": height,
            "fps": round(fps, 3),
            "aspect_ratio": f"{ratio.numerator}:{ratio.denominator}",
            "orientation": "portrait" if height > width else "landscape" if width > height else "square",
            "rotation": rotation,
        },
        "audio": (
            {
                "codec": audio.get("codec_name"),
                "sample_rate": int(audio["sample_rate"]) if audio.get("sample_rate") else None,
                "channels": audio.get("channels"),
            }
            if audio
            else None
        ),
    }


def generate_thumbnails(
    path: Path, out_dir: Path, duration: float, count: int, width: int
) -> List[Dict[str, Any]]:
    """Extract `count` evenly spaced JPEG thumbnails. Old thumbnails are replaced."""
    ffmpeg = _require(settings.ffmpeg_path, "ffmpeg")
    count = max(1, min(int(count), 12))
    width = max(64, min(int(width), 1280))

    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    thumbs: List[Dict[str, Any]] = []
    for i in range(count):
        t = duration * (i + 1) / (count + 1)
        name = f"thumb_{i + 1:02d}.jpg"
        cmd = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{t:.3f}", "-i", str(path),
            "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4",
            str(out_dir / name),
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
            )
        except subprocess.TimeoutExpired:
            continue
        if proc.returncode == 0 and (out_dir / name).is_file():
            thumbs.append({"file": name, "time_seconds": round(t, 3)})
    return thumbs
