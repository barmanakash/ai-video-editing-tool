"""Single-pass visual analysis: brightness, colour, motion, zoom/pan, transitions.

FFmpeg decodes the video once, downscales every frame to ~160 px wide and pipes
raw frames to Python. Only ONE small frame (about 43 KB) lives in memory at a
time; the video is never loaded into RAM.

All outputs are heuristic estimates and are labelled that way.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

from app.config import settings

CUT_DIFF = 30.0          # mean frame difference above this = hard cut, skip optical flow
ZOOM_THRESHOLD = 0.15    # scale change per second counted as a zoom
PAN_THRESHOLD = 0.25     # frame-widths per second counted as a pan
DUP_THRESHOLD = 0.25     # mean abs diff below this = duplicated frame
DARK_LEVEL = 15.0        # mean gray below this = near-black frame
FLASH_DELTA = 60.0       # brightness jump above the 1 s average = flash


class FrameAnalysisError(RuntimeError):
    pass


def _moving_average(a: np.ndarray, k: int) -> np.ndarray:
    if k <= 1 or a.size == 0:
        return a
    padded = np.pad(a, (k // 2, k - 1 - k // 2), mode="edge")
    return np.convolve(padded, np.ones(k) / k, mode="valid")[: a.size]


def _runs(mask: np.ndarray, min_len: int = 1) -> List[Tuple[int, int]]:
    """(start, end_exclusive) of consecutive True runs at least min_len long."""
    if mask.size == 0:
        return []
    padded = np.concatenate(([False], mask.astype(bool), [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(s), int(e)) for s, e in zip(edges[::2], edges[1::2]) if e - s >= min_len]


def _flow_stats(flow: np.ndarray, fps: float, xc: np.ndarray, yc: np.ndarray, denom: float):
    u, v = flow[..., 0], flow[..., 1]
    frame_w = flow.shape[1]
    pan_x, pan_y = float(u.mean()), float(v.mean())
    magnitude = float(np.sqrt(u * u + v * v).mean())
    zoom = float((xc * (u - pan_x) + yc * (v - pan_y)).sum() / denom)  # scale change per frame
    scale = fps / frame_w
    return magnitude * scale, float(np.hypot(pan_x, pan_y)) * scale, zoom * fps


def _zoom_events(flows: List[Tuple[float, float, float, float]], gap: float) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    cur = None
    for t, _mag, _pan, zoom in flows:
        direction = "in" if zoom > ZOOM_THRESHOLD else "out" if zoom < -ZOOM_THRESHOLD else None
        if direction and cur and cur["direction"] == direction and t - cur["last"] <= gap * 1.5:
            cur["last"] = t
            cur["peak"] = max(cur["peak"], abs(zoom))
        else:
            if cur:
                events.append(cur)
            cur = {"direction": direction, "start": t, "last": t, "peak": abs(zoom)} if direction else None
    if cur:
        events.append(cur)
    out = []
    for e in events:
        length = e["last"] - e["start"] + gap
        if length >= 0.5:
            out.append({
                "direction": e["direction"],
                "start": round(e["start"], 2),
                "end": round(e["last"] + gap, 2),
                "peak_rate_per_s": round(e["peak"], 2),
            })
    return out


def analyze_frames(
    path: Path,
    src_width: int,
    src_height: int,
    native_fps: float,
    duration: float,
    max_seconds: float,
    flow_fps: float = 4.0,
    width: int = 160,
    fps_cap: float = 60.0,
    include_series: bool = False,
) -> Dict[str, Any]:
    import cv2

    ffmpeg = shutil.which(settings.ffmpeg_path)
    if not ffmpeg:
        raise FrameAnalysisError("ffmpeg not found")

    fps = min(max(native_fps if native_fps > 0 else 30.0, 1.0), max(fps_cap, 1.0))  # cap work
    w = max(32, width - width % 2)
    h = max(2, int(round(src_height * w / src_width / 2)) * 2)
    window = min(duration, max_seconds)
    frame_bytes = w * h * 3
    step = max(1, int(round(fps / max(flow_fps, 0.5))))

    # fps filter forces constant frame rate so frame index -> time is exact
    cmd = [
        ffmpeg, "-v", "error", "-t", f"{window:.3f}", "-i", str(path), "-an",
        "-vf", f"fps={fps:.3f},scale={w}:{h}", "-pix_fmt", "bgr24", "-f", "rawvideo", "-",
    ]

    xs, ys = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    xc, yc = xs - (w - 1) / 2.0, ys - (h - 1) / 2.0
    denom = float((xc * xc + yc * yc).sum())

    brightness: List[float] = []
    diffs: List[float] = []
    saturation: List[float] = []
    contrast: List[float] = []
    rgb: List[Tuple[float, float, float]] = []
    flows: List[Tuple[float, float, float, float]] = []

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=frame_bytes * 4)
    prev = None
    index = 0
    try:
        while True:
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            frame = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 3)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            brightness.append(float(gray.mean()))
            diff = float(cv2.absdiff(gray, prev).mean()) if prev is not None else 0.0
            diffs.append(diff)

            if index % step == 0:
                hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                saturation.append(float(hsv[..., 1].mean()))
                contrast.append(float(gray.std()))
                b, g, r = frame.reshape(-1, 3).mean(axis=0)
                rgb.append((float(r), float(g), float(b)))
                if prev is not None and diff < CUT_DIFF:
                    flow = cv2.calcOpticalFlowFarneback(prev, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
                    mag, pan, zoom = _flow_stats(flow, fps, xc, yc, denom)
                    flows.append((index / fps, mag, pan, zoom))
            prev = gray
            index += 1
    finally:
        try:
            proc.stdout.close()
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()

    n = len(brightness)
    if n < 2:
        raise FrameAnalysisError("No frames could be decoded from the video")

    b_arr = np.asarray(brightness)
    d_arr = np.asarray(diffs[1:])  # first value is a placeholder

    # ---- colour ---------------------------------------------------------
    mean_rgb = np.asarray(rgb).mean(axis=0)
    warm_cool = float(mean_rgb[0] - mean_rgb[2])
    mean_b = float(b_arr.mean())
    mean_sat = float(np.mean(saturation))
    mean_con = float(np.mean(contrast))
    color = {
        "brightness_mean": round(mean_b, 1),
        "brightness_label": "dark" if mean_b < 80 else "bright" if mean_b > 170 else "balanced",
        "brightness_variation": round(float(b_arr.std()), 1),
        "contrast_mean": round(mean_con, 1),
        "contrast_label": "high" if mean_con > 60 else "low" if mean_con < 35 else "medium",
        "saturation_mean": round(mean_sat, 1),
        "saturation_label": "vibrant" if mean_sat > 120 else "muted" if mean_sat < 60 else "natural",
        "average_rgb": [round(float(c), 1) for c in mean_rgb],
        "tone": "warm" if warm_cool > 8 else "cool" if warm_cool < -8 else "neutral",
    }

    # ---- motion / zoom / pan -------------------------------------------
    if flows:
        mags = np.asarray([f[1] for f in flows])
        pans = np.asarray([f[2] for f in flows])
        zooms = np.asarray([f[3] for f in flows])
        avg_motion = float(mags.mean())
        events = _zoom_events(flows, step / fps)
        minutes = max(n / fps / 60.0, 1e-6)
        motion = {
            "samples": len(flows),
            "average_motion": round(avg_motion, 3),
            "motion_label": "calm" if avg_motion < 0.15 else "intense" if avg_motion > 0.6 else "moderate",
            "pan_ratio": round(float((pans > PAN_THRESHOLD).mean()), 3),
            "zoom_in_ratio": round(float((zooms > ZOOM_THRESHOLD).mean()), 3),
            "zoom_out_ratio": round(float((zooms < -ZOOM_THRESHOLD).mean()), 3),
            "zoom_events_per_minute": round(len(events) / minutes, 2),
            "zoom_events": events[:40],
            "note": "Zoom is measured as image expansion. In gameplay, moving the camera forward looks the same as a digital zoom.",
        }
    else:
        motion = {"samples": 0, "note": "Not enough motion samples (video too short or all hard cuts)."}

    # ---- transitions (hints only) ---------------------------------------
    k = max(2, int(round(fps)))
    spikes = (b_arr - _moving_average(b_arr, k)) > FLASH_DELTA
    flashes = _runs(spikes)
    dark = _runs(b_arr < DARK_LEVEL, min_len=max(2, int(0.15 * fps)))
    transitions = {
        "dark_dips": len(dark),
        "dark_dip_times": [round(s / fps, 2) for s, _ in dark[:20]],
        "bright_flashes": len(flashes),
        "bright_flash_times": [round(s / fps, 2) for s, _ in flashes[:20]],
        "note": "Only fades through black and white flashes are estimated. Dissolves, wipes and stylised transitions are NOT detected.",
    }

    # ---- slow motion hint (frame duplication pattern) -------------------
    win = max(2, int(round(fps)))
    slow_windows = 0
    total_windows = 0
    for start in range(0, d_arr.size - win + 1, win):
        chunk = d_arr[start:start + win]
        dup = float((chunk < DUP_THRESHOLD).mean())
        moving = chunk[chunk >= DUP_THRESHOLD]
        active = moving.size > 0 and float(moving.mean()) > 0.8
        total_windows += 1
        if 0.3 <= dup <= 0.8 and active:
            slow_windows += 1
    ratio = slow_windows / total_windows if total_windows else 0.0
    constant = ratio > 0.85
    slow_motion = {
        "window_ratio": round(ratio, 3),
        "likely_used": bool(ratio > 0.05 and not constant),
        "constant_frame_duplication": bool(constant),
        "confidence": "low",
        "note": (
            "Whole video repeats frames: probably a low-fps source in a higher-fps file, not slow motion."
            if constant else
            "Heuristic based on repeated frames. Interpolated (smooth) slow motion is not detectable this way."
        ),
    }

    result = {
        "analysis_fps": round(fps, 3),
        "frames_analyzed": n,
        "analyzed_seconds": round(n / fps, 2),
        "analysis_resolution": f"{w}x{h}",
        "color": color,
        "motion": motion,
        "transitions": transitions,
        "slow_motion": slow_motion,
    }

    if include_series:  # per-second curves used by the gameplay highlight finder
        secs = int(np.ceil(n / fps))
        frame_sec = np.minimum((np.arange(n) / fps).astype(int), secs - 1)
        counts = np.maximum(np.bincount(frame_sec, minlength=secs), 1)
        diff_s = np.bincount(frame_sec, weights=np.asarray(diffs), minlength=secs) / counts
        bright_s = np.bincount(frame_sec, weights=b_arr, minlength=secs) / counts
        flow_s = np.zeros(secs)
        if flows:
            f_sec = np.minimum(np.asarray([f[0] for f in flows]).astype(int), secs - 1)
            f_cnt = np.maximum(np.bincount(f_sec, minlength=secs), 1)
            flow_s = np.bincount(f_sec, weights=np.asarray([f[1] for f in flows]), minlength=secs) / f_cnt
        result["series"] = {
            "seconds": secs,
            "diff": [round(float(x), 3) for x in diff_s],
            "flow": [round(float(x), 3) for x in flow_s],
            "brightness": [round(float(x), 1) for x in bright_s],
        }
    return result
