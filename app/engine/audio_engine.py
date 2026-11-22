"""Audio handling: per-clip audio chains, music mixing, and beat-synchronised cuts."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.engine import transition_engine as tr
from app.engine.plan_schema import effective_duration

AFORMAT = "aformat=sample_fmts=fltp:channel_layouts=stereo"


def atempo_chain(speed: float) -> List[str]:
    """atempo only accepts 0.5-2.0 per filter, so split bigger changes into steps."""
    if abs(speed - 1.0) < 1e-3:
        return []
    parts: List[float] = []
    s = speed
    while s > 2.0:
        parts.append(2.0)
        s /= 2.0
    while s < 0.5:
        parts.append(0.5)
        s /= 0.5
    parts.append(s)
    return [f"atempo={p:.4f}" for p in parts]


def clip_audio_chain(i: int, clip: Dict[str, Any], duration: float, has_audio: bool, volume: float) -> str:
    """Graph line producing [a{i}]: stereo, 48 kHz, exactly `duration` seconds long.

    Sources without audio get silence, so every clip has audio and joins never fail.
    """
    if not has_audio:
        return (f"anullsrc=channel_layout=stereo:sample_rate=48000,"
                f"atrim=duration={duration:.3f},asetpts=PTS-STARTPTS[a{i}]")
    parts = ["asetpts=PTS-STARTPTS", "aresample=48000", AFORMAT] + atempo_chain(float(clip["speed"]))
    if abs(volume - 1.0) > 1e-3:
        parts.append(f"volume={volume:.3f}")
    parts += [f"apad=whole_dur={duration:.3f}", f"atrim=duration={duration:.3f}", "asetpts=PTS-STARTPTS"]
    return f"[{i}:a]" + ",".join(parts) + f"[a{i}]"


def music_chain(index: int, total: float, volume: float) -> str:
    """Graph line producing [m]: the music input (looped by -stream_loop), trimmed to the video length."""
    return (f"[{index}:a]aresample=48000,{AFORMAT},volume={volume:.3f},"
            f"atrim=duration={total:.3f},asetpts=PTS-STARTPTS[m]")


# ------------------------------------------------------------ beat sync
def music_beats(path: str, max_seconds: float = 600.0) -> List[float]:
    """Onset times (seconds) of the music: moments where it gets louder / hits."""
    from app.analyzers.audio_analyzer import analyze_audio

    _summary, onsets = analyze_audio(path, True, max_seconds)
    return [float(t) for t in onsets]


def _nearest(beats: List[float], t: float) -> Optional[float]:
    return min(beats, key=lambda b: abs(b - t)) if beats else None


def snap_clips_to_beats(plan: Dict[str, Any], sources: Dict[str, Dict[str, Any]],
                        beats: List[float], tolerance: float = 0.4) -> int:
    """Nudge clip end points (in place) so cuts land on music beats.

    Each cut is moved by at most `tolerance` seconds, never past the source video's
    limits and never below the minimum clip length. Returns how many cuts moved.
    """
    from app.config import settings

    clips, transitions = plan["clips"], plan["transitions"]
    moved = 0
    pos = 0.0                                     # timeline position where the current clip starts
    for i, clip in enumerate(clips[:-1]):
        dur = effective_duration(clip)
        name = transitions[i] if i < len(transitions) else "cut"
        td = tr.transition_duration(name, dur, effective_duration(clips[i + 1]))
        join = pos + dur - td / 2                 # centre of the cut or transition
        beat = _nearest(beats, join)
        if beat is not None and 0.01 < abs(beat - join) <= tolerance:
            speed = 1.0 if clip.get("effect") == "speed_ramp" else float(clip["speed"])   # a ramp ends at normal speed
            new_end = float(clip["end"]) + (beat - join) * speed
            limit = float(sources[clip["source"]]["duration_seconds"])
            length = new_end - float(clip["start"])
            if new_end <= limit and settings.min_clip_seconds <= length <= settings.max_clip_seconds:
                clip["end"] = round(new_end, 3)
                dur = effective_duration(clip)
                moved += 1
        pos += dur - td
    return moved
