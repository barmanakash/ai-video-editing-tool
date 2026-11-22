"""Editing-plan schema + strict validation.

The LLM (or a human) proposes a plan; only a plan that passes `validate_plan`
can be rendered. The validator returns a NEW normalised dict that contains
only known keys with whitelisted values, so nothing free-form (no shell text,
no FFmpeg arguments, no unknown paths) can ever reach the renderer.

Plan shape (all keys optional except `clips`):

{
  "project_type": "gaming_video",
  "style": "fast_paced_action",
  "target_duration": 30,
  "output": {"format": "youtube" | "instagram",
             "quality": "test" | "full" | "1440p" | "4k",     # test = 480p preview, full = 1080p
             "fit": "crop" | "pad", "fps": 30,
             "codec": "h264" | "hevc", "encoder": "auto" | "cpu" | "qsv",
             "quality_level": "fast" | "standard" | "high"},
  "clips": [
    {"source": "<video id or original file name>", "start": 12.5, "end": 24.0,
     "speed": 1.0, "effect": "none" | "slow_motion" | "speed_up" | "zoom_in" | "speed_ramp",
     "peak": 18.0}            # peak only for speed_ramp: speed = slowest point, peak = its source time
  ],
  "transitions": ["cut" | "crossfade" | "fadeblack" | "fadewhite" | "slideleft"],   # one per join
  "audio": {"use_uploaded_music": false, "music_path": null,
            "music_volume": 0.7, "game_audio_volume": 1.0, "sync_cuts_to_music": true},
  "color": {"preset": "none" | "clean" | "vibrant" | "cinematic",
            "brightness": 0.0, "contrast": 1.0, "saturation": 1.0},
  "fx": {"punch": "off" | "cuts" | "beats", "zoom_punch": true, "flash": false, "shake": false},
  "titles": [{"text": "EPIC FIGHTS", "position": "center" | "lower" | "top",
              "size": "large" | "medium" | "small", "at": "start" | "end" | "time",
              "start": 0.0, "duration": 2.5}]
}
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings
from app.engine import speed_ramp
from app.engine.effects_engine import GRADE_PRESETS
from app.engine.text_overlay import clean_text

PLAN_VERSION = 2
ALLOWED_EFFECTS = ("none", "slow_motion", "speed_up", "zoom_in", "speed_ramp")
ALLOWED_PUNCH = ("off", "cuts", "beats")
TITLE_POSITIONS = ("center", "lower", "top")
TITLE_SIZES = ("large", "medium", "small")
TITLE_ANCHORS = ("start", "end", "time")
MAX_TITLES = 6
ALLOWED_TRANSITIONS = ("cut", "crossfade", "fadeblack", "fadewhite", "slideleft")
ALLOWED_FORMATS = ("youtube", "instagram")
ALLOWED_QUALITY = ("test", "full", "1440p", "4k")        # test = fast 480p preview, full = 1080p
ALLOWED_CODEC = ("h264", "hevc")
ALLOWED_ENCODER = ("auto", "cpu", "qsv")                    # qsv = Intel hardware encoder (falls back to cpu)
ALLOWED_LEVEL = ("fast", "standard", "high")                # speed vs file quality
ALLOWED_FIT = ("crop", "pad")
TRANSITION_ALIASES = {"fade": "crossfade", "dissolve": "crossfade", "flash": "fadewhite", "none": "cut"}
SPEED_MIN, SPEED_MAX = 0.25, 4.0
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class PlanValidationError(ValueError):
    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def effective_duration(clip: Dict[str, Any]) -> float:
    """Seconds the clip occupies in the final video (slow motion makes it longer)."""
    if clip.get("effect") == "speed_ramp":
        return speed_ramp.duration(clip)
    return (float(clip["end"]) - float(clip["start"])) / float(clip["speed"])


def _num(value: Any, label: str, errors: List[str], lo: float, hi: float, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        errors.append(f"{label} must be a number")
        return default
    if not (lo <= value <= hi):
        errors.append(f"{label} must be between {lo} and {hi} (got {value})")
        return default
    return float(value)


def _resolve_source(raw: Any, sources: Dict[str, Dict[str, Any]]) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    if raw in sources:
        return raw
    matches = [vid for vid, s in sources.items() if s.get("name") == raw]
    return matches[0] if len(matches) == 1 else None


def validate_plan(plan: Any, sources: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Return a normalised plan or raise PlanValidationError listing every problem.

    `sources` maps video_id -> {"duration_seconds", "has_audio", "path", "name"}.
    """
    errors: List[str] = []
    if not isinstance(plan, dict):
        raise PlanValidationError(["plan must be a JSON object"])

    # ---- header ---------------------------------------------------------
    project_type = plan.get("project_type", "gaming_video")
    if project_type != "gaming_video":
        errors.append("project_type must be 'gaming_video'")
    style = plan.get("style", "custom")
    style = _CONTROL.sub("", style).strip()[:60] if isinstance(style, str) else "custom"

    target = _num(plan.get("target_duration"), "target_duration", errors, 3, settings.max_output_seconds)

    # ---- output ---------------------------------------------------------
    out_in = plan.get("output") or {}
    if not isinstance(out_in, dict):
        errors.append("output must be an object")
        out_in = {}
    fmt = out_in.get("format", "youtube")
    quality = out_in.get("quality", "test")
    fit = out_in.get("fit", "crop")
    if fmt not in ALLOWED_FORMATS:
        errors.append(f"output.format must be one of {ALLOWED_FORMATS}")
    if quality not in ALLOWED_QUALITY:
        errors.append(f"output.quality must be one of {ALLOWED_QUALITY}")
    if fit not in ALLOWED_FIT:
        errors.append(f"output.fit must be one of {ALLOWED_FIT}")
    fps = _num(out_in.get("fps"), "output.fps", errors, 24, 60, default=float(settings.render_fps))
    codec = out_in.get("codec", "h264")
    encoder = out_in.get("encoder", "auto")
    level = out_in.get("quality_level", "standard")
    if codec not in ALLOWED_CODEC:
        errors.append(f"output.codec must be one of {ALLOWED_CODEC}")
        codec = "h264"
    if encoder not in ALLOWED_ENCODER:
        errors.append(f"output.encoder must be one of {ALLOWED_ENCODER}")
        encoder = "auto"
    if level not in ALLOWED_LEVEL:
        errors.append(f"output.quality_level must be one of {ALLOWED_LEVEL}")
        level = "standard"

    # ---- clips ----------------------------------------------------------
    clips_in = plan.get("clips")
    clips: List[Dict[str, Any]] = []
    if not isinstance(clips_in, list) or not clips_in:
        errors.append("clips must be a non-empty list")
        clips_in = []
    if len(clips_in) > settings.max_plan_clips:
        errors.append(f"at most {settings.max_plan_clips} clips are allowed")
        clips_in = clips_in[: settings.max_plan_clips]

    total = 0.0
    for i, c in enumerate(clips_in):
        tag = f"clips[{i}]"
        if not isinstance(c, dict):
            errors.append(f"{tag} must be an object")
            continue
        vid = _resolve_source(c.get("source"), sources)
        if vid is None:
            errors.append(f"{tag}.source '{c.get('source')}' is not a known gameplay video (use its id or unique file name)")
            continue
        dur = float(sources[vid]["duration_seconds"])
        start = _num(c.get("start"), f"{tag}.start", errors, 0, dur)
        end = _num(c.get("end"), f"{tag}.end", errors, 0, dur + 0.05)
        effect = c.get("effect", "none")
        if effect not in ALLOWED_EFFECTS:
            errors.append(f"{tag}.effect must be one of {ALLOWED_EFFECTS}")
            effect = "none"
        speed = _num(c.get("speed"), f"{tag}.speed", errors, SPEED_MIN, SPEED_MAX,
                     default=0.4 if effect == "speed_ramp" else 1.0)
        peak = _num(c.get("peak"), f"{tag}.peak", errors, 0, dur)
        if start is None or end is None:
            if c.get("start") is None or c.get("end") is None:
                errors.append(f"{tag} needs both start and end")
            continue
        end = min(end, dur)
        length = end - start
        if length < settings.min_clip_seconds:
            errors.append(f"{tag} is too short ({length:.2f}s, minimum {settings.min_clip_seconds}s)")
            continue
        if length > settings.max_clip_seconds:
            errors.append(f"{tag} is too long ({length:.1f}s, maximum {settings.max_clip_seconds}s)")
            continue
        if effect == "slow_motion" and speed >= 1.0:
            errors.append(f"{tag}: slow_motion needs speed below 1.0")
        if effect == "speed_up" and speed <= 1.0:
            errors.append(f"{tag}: speed_up needs speed above 1.0")
        if effect == "speed_ramp" and speed >= 1.0:
            errors.append(f"{tag}: speed_ramp needs speed (the slowest point of the ramp) below 1.0")
        clip = {"source": vid, "start": round(start, 3), "end": round(end, 3), "speed": round(speed, 3), "effect": effect}
        if effect == "speed_ramp":
            clip["peak"] = round(min(max(peak if peak is not None else (start + end) / 2, start), end), 3)
        total += effective_duration(clip)
        clips.append(clip)

    if total > settings.max_output_seconds:
        errors.append(f"total video length {total:.0f}s exceeds the {settings.max_output_seconds:.0f}s limit")

    # ---- transitions (one per join) --------------------------------------
    trans_in = plan.get("transitions")
    joins = max(len(clips_in) - 1, 0)
    transitions: List[str] = []
    if trans_in is None or trans_in == []:
        transitions = ["cut"] * joins
    elif not isinstance(trans_in, list):
        errors.append("transitions must be a list")
    else:
        if len(trans_in) != joins:
            errors.append(f"transitions needs exactly {joins} entries (one between each pair of clips), got {len(trans_in)}")
        for j, t in enumerate(trans_in[:joins]):
            name = TRANSITION_ALIASES.get(t, t) if isinstance(t, str) else None
            if name not in ALLOWED_TRANSITIONS:
                errors.append(f"transitions[{j}] must be one of {ALLOWED_TRANSITIONS}")
                name = "cut"
            transitions.append(name)

    # ---- audio ----------------------------------------------------------
    au = plan.get("audio") or {}
    if not isinstance(au, dict):
        errors.append("audio must be an object")
        au = {}
    use_music = bool(au.get("use_uploaded_music", False))
    music_path: Optional[str] = None
    if use_music:
        raw = au.get("music_path")
        if not isinstance(raw, str) or not raw.strip():
            errors.append("audio.music_path is required when use_uploaded_music is true")
        else:
            p = Path(raw.strip().strip('"')).expanduser()
            if not p.is_file():
                errors.append(f"audio.music_path not found: {p}")
            elif p.suffix.lower() not in settings.audio_extensions:
                errors.append(f"audio.music_path must be one of {settings.audio_extensions}")
            else:
                music_path = str(p.resolve())
    music_volume = _num(au.get("music_volume"), "audio.music_volume", errors, 0, 1.5, default=0.7)
    game_volume = _num(au.get("game_audio_volume"), "audio.game_audio_volume", errors, 0, 2.0,
                       default=0.4 if use_music else 1.0)
    sync_cuts = bool(au.get("sync_cuts_to_music", True))

    # ---- colour ---------------------------------------------------------
    co = plan.get("color") or {}
    if not isinstance(co, dict):
        errors.append("color must be an object")
        co = {}
    brightness = _num(co.get("brightness"), "color.brightness", errors, -0.3, 0.3, default=0.0)
    contrast = _num(co.get("contrast"), "color.contrast", errors, 0.5, 2.0, default=1.0)
    saturation = _num(co.get("saturation"), "color.saturation", errors, 0.5, 2.0, default=1.0)
    preset = co.get("preset", "none")
    if preset not in GRADE_PRESETS:
        errors.append(f"color.preset must be one of {tuple(GRADE_PRESETS)}")
        preset = "none"

    # ---- beat / cut punch effects -----------------------------------------
    fx_in = plan.get("fx") or {}
    if not isinstance(fx_in, dict):
        errors.append("fx must be an object")
        fx_in = {}
    punch = fx_in.get("punch", "off")
    if punch not in ALLOWED_PUNCH:
        errors.append(f"fx.punch must be one of {ALLOWED_PUNCH}")
        punch = "off"
    fx = {
        "punch": punch,
        "zoom_punch": bool(fx_in.get("zoom_punch", True)),
        "flash": bool(fx_in.get("flash", False)),
        "shake": bool(fx_in.get("shake", False)),
    }

    # ---- titles ---------------------------------------------------------
    titles_in = plan.get("titles") or []
    titles: List[Dict[str, Any]] = []
    if not isinstance(titles_in, list):
        errors.append("titles must be a list")
        titles_in = []
    if len(titles_in) > MAX_TITLES:
        errors.append(f"at most {MAX_TITLES} titles are allowed")
        titles_in = titles_in[:MAX_TITLES]
    for k, t in enumerate(titles_in):
        tag = f"titles[{k}]"
        if not isinstance(t, dict):
            errors.append(f"{tag} must be an object")
            continue
        text = clean_text(t.get("text"))
        if not text:
            errors.append(f"{tag}.text is empty (letters, digits, spaces and . , ! ? & ( ) + - # @ / are allowed)")
            continue
        pos, size, at = t.get("position", "center"), t.get("size", "large"), t.get("at", "start")
        if pos not in TITLE_POSITIONS:
            errors.append(f"{tag}.position must be one of {TITLE_POSITIONS}")
            pos = "center"
        if size not in TITLE_SIZES:
            errors.append(f"{tag}.size must be one of {TITLE_SIZES}")
            size = "large"
        if at not in TITLE_ANCHORS:
            errors.append(f"{tag}.at must be one of {TITLE_ANCHORS}")
            at = "start"
        t_dur = _num(t.get("duration"), f"{tag}.duration", errors, 0.5, 10.0, default=2.5)
        t_start = _num(t.get("start"), f"{tag}.start", errors, 0.0, settings.max_output_seconds, default=0.0)
        titles.append({"text": text, "position": pos, "size": size, "at": at, "start": t_start, "duration": t_dur})

    if errors:
        raise PlanValidationError(errors)

    return {
        "plan_version": PLAN_VERSION,
        "project_type": "gaming_video",
        "style": style or "custom",
        "target_duration": target,
        "output": {"format": fmt, "quality": quality, "fit": fit, "fps": int(fps),
                   "codec": codec, "encoder": encoder, "quality_level": level},
        "clips": clips,
        "transitions": transitions,
        "audio": {
            "use_uploaded_music": use_music and music_path is not None,
            "music_path": music_path,
            "music_volume": music_volume,
            "game_audio_volume": game_volume,
            "sync_cuts_to_music": sync_cuts,
        },
        "color": {"preset": preset, "brightness": brightness, "contrast": contrast, "saturation": saturation},
        "fx": fx,
        "titles": titles,
        "total_duration_estimate": round(total, 2),
    }
