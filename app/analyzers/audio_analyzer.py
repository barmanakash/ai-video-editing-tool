"""Lightweight audio analysis (loudness, onsets, rough tempo).

Audio is decoded by FFmpeg to mono 16 kHz PCM and streamed through a pipe in
small chunks, so the whole track is never held in RAM. Only a 100 Hz energy
envelope (a few numbers per second) is kept.

Everything here is an ESTIMATE. Onsets are loudness jumps, not musical beats,
and tempo is only meaningful when music dominates the audio.
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.config import settings

SAMPLE_RATE = 16000
HOP = 160  # 10 ms per envelope value
HOP_SECONDS = HOP / SAMPLE_RATE
HOPS_PER_SECOND = SAMPLE_RATE / HOP  # 100


class AudioAnalysisError(RuntimeError):
    pass


def compute_envelope(path, max_seconds: float) -> np.ndarray:
    """RMS amplitude (0..1) for every 10 ms of audio, streamed from FFmpeg."""
    ffmpeg = shutil.which(settings.ffmpeg_path)
    if not ffmpeg:
        raise AudioAnalysisError("ffmpeg not found")
    cmd = [
        ffmpeg, "-v", "error", "-t", f"{max_seconds:.3f}", "-i", str(path),
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    bytes_per_hop = HOP * 2
    chunk_size = bytes_per_hop * 1000  # ~10 s of audio per read
    parts: List[np.ndarray] = []
    leftover = b""
    try:
        while True:
            data = proc.stdout.read(chunk_size)
            if not data:
                break
            data = leftover + data
            usable = (len(data) // bytes_per_hop) * bytes_per_hop
            leftover = data[usable:]
            if usable:
                samples = np.frombuffer(data[:usable], dtype="<i2").astype(np.float32) / 32768.0
                frames = samples.reshape(-1, HOP)
                parts.append(np.sqrt((frames * frames).mean(axis=1)))
    finally:
        proc.stdout.close()
        proc.wait()
    if not parts:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(parts)


def _to_db(env: np.ndarray) -> np.ndarray:
    return 20.0 * np.log10(np.maximum(env, 1e-6))


def _moving_average(a: np.ndarray, k: int) -> np.ndarray:
    if k <= 1 or a.size == 0:
        return a
    padded = np.pad(a, (k // 2, k - 1 - k // 2), mode="edge")
    return np.convolve(padded, np.ones(k) / k, mode="valid")[: a.size]


def detect_onsets(env: np.ndarray) -> np.ndarray:
    """Indices (10 ms units) where loudness jumps up sharply."""
    if env.size < 10:
        return np.zeros(0, dtype=int)
    db = _moving_average(np.maximum(_to_db(env), -70.0), 3)
    flux = np.maximum(0.0, np.diff(db, prepend=db[0]))
    threshold = max(float(flux.mean() + 1.5 * flux.std()), 3.0)
    min_gap = 10  # 100 ms
    onsets: List[int] = []
    for i in range(1, flux.size - 1):
        if flux[i] >= threshold and flux[i] >= flux[i - 1] and flux[i] > flux[i + 1]:
            if onsets and i - onsets[-1] < min_gap:
                if flux[i] > flux[onsets[-1]]:
                    onsets[-1] = i
                continue
            onsets.append(i)
    return np.asarray(onsets, dtype=int)


def estimate_tempo(env: np.ndarray) -> Tuple[Optional[float], str]:
    """Rough BPM (60-180) from autocorrelation of loudness jumps."""
    if env.size < HOPS_PER_SECOND * 6:
        return None, "none"
    db = _moving_average(np.maximum(_to_db(env), -70.0), 3)
    flux = np.maximum(0.0, np.diff(db, prepend=db[0]))
    flux = flux - flux.mean()
    n = flux.size
    size = 1 << (2 * n - 1).bit_length()
    spectrum = np.fft.rfft(flux, size)
    ac = np.fft.irfft(spectrum * np.conj(spectrum), size)[:n]
    if ac[0] <= 0:
        return None, "none"
    lo = int(HOPS_PER_SECOND * 60 / 180)
    hi = min(int(HOPS_PER_SECOND * 60 / 60), n - 1)
    if hi <= lo:
        return None, "none"
    lag = lo + int(np.argmax(ac[lo:hi + 1]))
    strength = float(ac[lag] / ac[0])
    confidence = "high" if strength > 0.3 else "medium" if strength > 0.15 else "low"
    return round(60.0 * HOPS_PER_SECOND / lag, 1), confidence


def analyze_audio(path, has_audio: bool, max_seconds: float) -> Tuple[Dict[str, Any], np.ndarray]:
    """Return (summary, onset_times_in_seconds)."""
    summary, onset_times, _db, _counts = analyze_audio_detailed(path, has_audio, max_seconds)
    return summary, onset_times


def analyze_audio_detailed(path, has_audio: bool, max_seconds: float):
    """Return (summary, onset_times_s, per_second_peak_db, per_second_onset_counts)."""
    empty = np.zeros(0, dtype=float)
    if not has_audio:
        return {"present": False}, empty, empty, empty
    env = compute_envelope(path, max_seconds)
    if env.size < HOPS_PER_SECOND:  # under one second
        return {"present": True, "analyzed": False, "note": "Audio too short or unreadable"}, empty, empty, empty

    db = _to_db(env)
    seconds = env.size * HOP_SECONDS
    mean_rms_db = float(20.0 * np.log10(max(float(np.sqrt((env.astype(np.float64) ** 2).mean())), 1e-6)))
    dynamic_range = float(np.percentile(db, 95) - np.percentile(db, 10))
    silence_ratio = float((db < -50.0).mean())
    label = "loud" if mean_rms_db > -16 else "moderate" if mean_rms_db > -28 else "quiet"

    onset_idx = detect_onsets(env)
    onset_times = (onset_idx + 1) * HOP_SECONDS
    bpm, confidence = estimate_tempo(env)

    summary = {
        "present": True,
        "analyzed": True,
        "analyzed_seconds": round(seconds, 2),
        "mean_rms_dbfs": round(mean_rms_db, 1),
        "peak_window_dbfs": round(float(db.max()), 1),
        "dynamic_range_db": round(dynamic_range, 1),
        "silence_ratio": round(silence_ratio, 3),
        "loudness_label": label,
        "onset_count": int(onset_idx.size),
        "onsets_per_minute": round(onset_idx.size / seconds * 60.0, 1) if seconds > 0 else 0.0,
        "estimated_bpm": bpm,
        "tempo_confidence": confidence,
        "note": "Onsets are loudness jumps, not musical beats. Tempo is only meaningful if music dominates.",
    }

    secs = int(np.ceil(env.size / HOPS_PER_SECOND))
    padded = np.zeros(secs * int(HOPS_PER_SECOND), dtype=np.float32)
    padded[: env.size] = env
    per_second_db = _to_db(padded.reshape(secs, int(HOPS_PER_SECOND)).max(axis=1))
    onset_counts = np.bincount((onset_idx // int(HOPS_PER_SECOND)).astype(int), minlength=secs)[:secs]
    return summary, onset_times, per_second_db, onset_counts
