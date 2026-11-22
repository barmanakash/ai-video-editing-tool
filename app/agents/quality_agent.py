"""Quality checking module (Phase 6).

A render is only marked "completed" when every error-level check passes:
  file exists and is not tiny | can be probed | resolution is right |
  duration is right | audio present | the whole file decodes without errors.
Warnings (for example some black frames) are reported but do not fail the render.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from app.analyzers.video_analyzer import VideoProbeError, extract_metadata
from app.config import settings

MIN_FILE_BYTES = 10 * 1024
_BLACK = re.compile(r"black_start:([\d.]+)\s+black_end:([\d.]+)\s+black_duration:([\d.]+)")
_ERROR_LINE = re.compile(r"error|invalid data|corrupt|failed|non-monotonic|truncated", re.I)


def _decode_scan(path: Path, duration: float) -> Dict[str, Any]:
    """Decode the whole file once (video and audio) and look for errors and black frames."""
    ffmpeg = shutil.which(settings.ffmpeg_path)
    if not ffmpeg:
        return {"ok": False, "errors": ["FFmpeg not found"], "black_seconds": 0.0}
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-v", "info", "-xerror", "-i", str(path),
           "-vf", "fps=4,blackdetect=d=0.5:pix_th=0.10", "-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           timeout=max(120.0, duration * 8))          # 4K files decode slowly on a CPU
    except subprocess.TimeoutExpired:
        return {"ok": False, "errors": ["decoding took far too long"], "black_seconds": 0.0}
    black = sum(float(m.group(3)) for m in _BLACK.finditer(r.stderr))
    errors = [ln.strip() for ln in r.stderr.splitlines()
              if ln.startswith("[") and "blackdetect" not in ln and _ERROR_LINE.search(ln)][:5]
    if r.returncode != 0 and not errors:
        errors = [f"FFmpeg exited with code {r.returncode}"]
    return {"ok": r.returncode == 0 and not errors, "errors": errors, "black_seconds": round(black, 2)}


def check_output(path: Any, expected: Dict[str, Any], deep: bool = True) -> Dict[str, Any]:
    """expected = {"width", "height", "duration", "has_audio"}. Returns a report dict."""
    path = Path(path)
    checks: List[Dict[str, Any]] = []
    warnings: List[str] = []

    def add(name: str, ok: bool, detail: str) -> bool:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    size = path.stat().st_size if path.is_file() else 0
    if not add("file_exists", size >= MIN_FILE_BYTES,
               f"{size} bytes" if size else "output file is missing or empty"):
        return {"passed": False, "checks": checks, "warnings": warnings}

    try:
        meta = extract_metadata(path)
    except VideoProbeError as exc:
        add("readable", False, f"cannot be opened as a video: {exc}")
        return {"passed": False, "checks": checks, "warnings": warnings}
    add("readable", True, "ffprobe can read the file")

    v = meta["video"]
    add("resolution", (v["width"], v["height"]) == (expected["width"], expected["height"]),
        f"{v['width']}x{v['height']} (expected {expected['width']}x{expected['height']})")

    exp_d = float(expected["duration"])
    got_d = float(meta["duration_seconds"])
    tol = max(0.75, 0.03 * exp_d)
    add("duration", abs(got_d - exp_d) <= tol, f"{got_d:.2f}s (expected {exp_d:.2f}s +/- {tol:.2f}s)")

    has_audio = meta.get("audio") is not None
    if expected.get("has_audio", True):
        add("audio_present", has_audio, "audio stream found" if has_audio else "no audio stream in the output")

    if deep:
        scan = _decode_scan(path, got_d)
        add("decodes_cleanly", scan["ok"], "whole file decoded without errors" if scan["ok"] else "; ".join(scan["errors"]))
        black = scan["black_seconds"]
        if got_d > 0 and black / got_d > 0.5:
            add("not_mostly_black", False, f"{black:.1f}s of {got_d:.1f}s is black")
        elif black > 0:
            warnings.append(f"{black:.1f}s of black frames detected (may be intentional fades)")

    return {"passed": all(c["ok"] for c in checks), "checks": checks, "warnings": warnings}
