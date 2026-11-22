"""Export settings (Phase 7B): resolutions, codecs, quality levels and Intel QSV hardware encoding.

Nothing here runs a user-supplied string: every FFmpeg argument comes from the tables below,
chosen by validated plan values.

Hardware encoding (Intel Quick Sync) is used only when a real test encode succeeds on this
computer; being listed in `ffmpeg -encoders` is not enough. If a QSV render fails for any
reason, the renderer retries with the CPU encoder automatically.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings

# Landscape sizes. Instagram (9:16) output swaps width and height.
LANDSCAPE_SIZES: Dict[str, Tuple[int, int]] = {
    "test": (854, 480),        # fast preview of the same edit
    "full": (1920, 1080),
    "1440p": (2560, 1440),
    "4k": (3840, 2160),
}
QUALITY_LABELS = {"test": "Preview 480p", "full": "Full HD 1080p", "1440p": "2K 1440p", "4k": "4K 2160p"}

# (preset, crf) per encoder and quality level
_X264 = {"fast": ("veryfast", 23), "high": ("medium", 17)}
_X265 = {"fast": ("veryfast", 27), "standard": ("veryfast", 24), "high": ("fast", 20)}
_QSV = {"fast": ("veryfast", 26), "standard": ("medium", 23), "high": ("medium", 19)}


def output_size(fmt: str, quality: str) -> Tuple[int, int]:
    try:
        w, h = LANDSCAPE_SIZES[quality]
    except KeyError:
        raise ValueError(f"Unsupported quality {quality!r}")
    if fmt == "instagram":
        return h, w
    if fmt != "youtube":
        raise ValueError(f"Unsupported format {fmt!r}")
    return w, h


@dataclass
class EncoderChoice:
    name: str                       # libx264 | libx265 | h264_qsv | hevc_qsv
    args: List[str]
    hardware: bool
    label: str
    notes: List[str] = field(default_factory=list)


# --------------------------------------------------------------- detection
@lru_cache(maxsize=1)
def _listed_encoders(ffmpeg: str) -> str:
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20)
        return r.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def encoder_listed(ffmpeg: str, name: str) -> bool:
    return re.search(rf"\s{re.escape(name)}\s", _listed_encoders(ffmpeg)) is not None


@lru_cache(maxsize=8)
def probe_encoder(ffmpeg: str, name: str) -> bool:
    """True only if a tiny real encode with this encoder works on this computer."""
    cmd = [ffmpeg, "-hide_banner", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=0.3",
           "-frames:v", "5", "-c:v", name, "-f", "null", "-"]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=40).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def hardware_status(ffmpeg: Optional[str] = None) -> Dict[str, Any]:
    """Which encoders can this computer really use? (shown on the System tab)"""
    ffmpeg = ffmpeg or shutil.which(settings.ffmpeg_path) or settings.ffmpeg_path
    status: Dict[str, Any] = {}
    for name in ("libx264", "libx265", "h264_qsv", "hevc_qsv"):
        listed = encoder_listed(ffmpeg, name)
        status[name] = {"listed": listed, "usable": bool(listed and probe_encoder(ffmpeg, name))}
    return status


# --------------------------------------------------------------- selection
def choose_encoder(ffmpeg: str, codec: str, encoder: str, quality: str, level: str, fps: int = 30) -> EncoderChoice:
    """Pick the encoder and its arguments. Never raises: falls back to H.264 on the CPU."""
    notes: List[str] = []
    threads = ["-threads", str(settings.render_threads)] if settings.render_threads > 0 else []

    if quality == "test":                          # preview: always the fastest possible encode
        if codec != "h264" or encoder == "qsv":
            notes.append("preview renders always use fast H.264 on the CPU (codec/encoder apply to the real export)")
        return EncoderChoice("libx264", ["-c:v", "libx264", "-preset", settings.test_preset, "-crf", str(settings.test_crf),
                                         "-pix_fmt", "yuv420p"] + threads, False, "H.264 (CPU, preview)", notes)

    want_hevc = codec == "hevc"
    if want_hevc and not encoder_listed(ffmpeg, "libx265") and not encoder_listed(ffmpeg, "hevc_qsv"):
        notes.append("this FFmpeg build has no HEVC encoder: used H.264 instead")
        want_hevc = False

    # --- hardware (Intel QSV) ---
    hw_name = "hevc_qsv" if want_hevc else "h264_qsv"
    use_hw = False
    if encoder == "qsv":
        use_hw = True
    elif encoder == "auto":
        # The CPU is too slow for these cases, so try the hardware encoder when it works.
        use_hw = quality in ("1440p", "4k") or want_hevc
    if use_hw:
        if encoder_listed(ffmpeg, hw_name) and probe_encoder(ffmpeg, hw_name):
            preset, q = _QSV[level]
            args = ["-c:v", hw_name, "-global_quality", str(q), "-preset", preset]
            if want_hevc:
                args += ["-tag:v", "hvc1"]
            return EncoderChoice(hw_name, args, True, f"{'HEVC' if want_hevc else 'H.264'} (Intel QSV hardware)", notes)
        if encoder == "qsv":
            notes.append("Intel QSV is not usable on this computer: used the CPU encoder instead")

    # --- CPU ---
    if want_hevc and encoder_listed(ffmpeg, "libx265"):
        preset, crf = _X265[level]
        args = ["-c:v", "libx265", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-tag:v", "hvc1",
                "-x265-params", "log-level=error"] + threads
        if quality in ("1440p", "4k"):
            notes.append("HEVC on the CPU at this resolution is very slow; expect long render times")
        return EncoderChoice("libx265", args, False, "HEVC (CPU)", notes)
    if want_hevc:                                   # only hevc_qsv exists but it is not usable
        notes.append("HEVC is not available here: used H.264 instead")
    preset, crf = (settings.full_preset, settings.full_crf) if level == "standard" else _X264[level]
    args = ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p"] + threads
    if quality == "4k":
        notes.append("4K on the CPU is slow; Intel QSV (if your FFmpeg supports it) is several times faster")
    return EncoderChoice("libx264", args, False, "H.264 (CPU)", notes)


def cpu_fallback(choice: EncoderChoice, ffmpeg: str, codec: str, quality: str, level: str) -> EncoderChoice:
    """The CPU encoder to retry with after a hardware encode failed."""
    return choose_encoder(ffmpeg, codec, "cpu", quality, level)


# ---------------------------------------------------------------- planning
def estimate_size_mb(width: int, height: int, fps: int, seconds: float, codec: str, level: str) -> float:
    """Rough output size, used to refuse a render that cannot fit on the disk."""
    mbps = 8.0 * (width * height) / (1920 * 1080) * (fps / 30.0) ** 0.7
    mbps *= {"fast": 0.8, "standard": 1.0, "high": 1.6}.get(level, 1.0)
    if codec == "hevc":
        mbps *= 0.6
    return mbps * seconds / 8.0 + seconds * 0.024        # video + 192 kbps audio


def upscale_notes(plan_clips: List[Dict[str, Any]], sources: Dict[str, Dict[str, Any]], width: int, height: int,
                  fps: int, fit: str) -> List[str]:
    """Honest warnings: bigger output than the source has real detail for, or more fps than it has."""
    notes: List[str] = []
    worst = 0.0
    src_fps = 0.0
    for c in plan_clips:
        s = sources.get(c["source"]) or {}
        sw, sh = s.get("width"), s.get("height")
        if sw and sh:
            scale = max(width / sw, height / sh) if fit == "crop" else min(width / sw, height / sh)
            worst = max(worst, scale)
        if s.get("fps"):
            src_fps = max(src_fps, float(s["fps"]))
    if worst > 1.05:
        notes.append(f"the sources are smaller than the output: video is scaled up about x{worst:.2f} "
                     "(bigger file, but no extra detail)")
    if src_fps and fps > src_fps * 1.2:
        notes.append(f"the sources are {src_fps:.0f} fps and the output is {fps} fps: frames are repeated, "
                     "so motion is not smoother")
    return notes
