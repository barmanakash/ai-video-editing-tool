"""Safe FFmpeg runner. Commands are ALWAYS argument lists (never a shell string),
and every command is built by our own code from validated plan values."""
from __future__ import annotations

import shutil
import subprocess
from typing import List

from app.config import settings


class RenderError(RuntimeError):
    pass


def find_ffmpeg() -> str:
    path = shutil.which(settings.ffmpeg_path)
    if not path:
        raise RenderError("ffmpeg not found. Install FFmpeg and make sure it is on PATH.")
    return path


def run_ffmpeg(cmd: List[str], timeout: float, label: str = "ffmpeg") -> str:
    """Run one FFmpeg command. Returns stderr text. Raises RenderError with a useful tail on failure."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
        )
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"{label} timed out after {timeout:.0f}s") from exc
    except OSError as exc:
        raise RenderError(f"{label} could not start: {exc}") from exc
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-6:]
        raise RenderError(f"{label} failed: " + " | ".join(tail))
    return proc.stderr or ""
