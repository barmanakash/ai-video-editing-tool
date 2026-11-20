"""AI Editing Planner (Phase 4).

Qwen 2.5 3B (via Ollama) proposes an editing plan as JSON. Python then:

  1. parses it,
  2. repairs small, common mistakes (clamps times, fixes speed/effect pairs),
  3. FORCES the output format, music path and volumes from the user's request,
     so the model can never choose file paths or anything outside the schema,
  4. validates it with the strict schema (app/engine/plan_schema.py),
  5. retries once with the error message, and finally
  6. falls back to a deterministic planner if the model is unusable.

The LLM never sees or produces shell commands or FFmpeg arguments.
Long video ids are replaced by short aliases (v1, v2, ...) in the prompt because
a 3B model copies short ids far more reliably.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.config import settings
from app.engine.plan_schema import (
    ALLOWED_EFFECTS,
    ALLOWED_TRANSITIONS,
    SPEED_MAX,
    SPEED_MIN,
    TRANSITION_ALIASES,
    PlanValidationError,
    effective_duration,
    validate_plan,
)
from app.services.ollama_service import OllamaError, chat_json

MAX_HIGHLIGHTS_PER_VIDEO = 6
MAX_HIGHLIGHTS_TOTAL = 14
MAX_OVERSHOOT = 1.3          # drop trailing clips if the plan is >30% longer than the target

SYSTEM_PROMPT = """You are a video edit planner for gaming videos. Reply with ONE JSON object and nothing else.
Choose clips only from the listed videos. Times are seconds in the source video. Prefer the listed highlight_ranges (they are estimates from motion and audio, not confirmed events).
Schema:
{"style":"short label","clips":[{"source":"v1","start":12.5,"end":20.0,"speed":1.0,"effect":"none"}],"transitions":["cut","crossfade"],"color":{"brightness":0.0,"contrast":1.0,"saturation":1.0}}
Rules:
- effect is one of: none, slow_motion, speed_up, zoom_in.
- slow_motion needs speed below 1 (for example 0.5). speed_up needs speed above 1 (for example 1.5).
- transitions has exactly one entry between each pair of clips (number of clips minus 1). Allowed: cut, crossfade, fadeblack, fadewhite, slideleft.
- The final length is the sum of (end-start)/speed. Make it close to target_duration_seconds.
- Follow reference_style hints when present (clip length, transitions, slow motion, zoom).
- Use slow_motion only for the strongest moment. Never repeat a clip.
- Output only the JSON object. No file paths, no commands, no explanations."""


@dataclass
class PlannerContext:
    instructions: str
    sources: Dict[str, Dict[str, Any]]       # video_id -> {duration_seconds, has_audio, path, name}
    analyses: Dict[str, Dict[str, Any]]      # video_id -> gameplay analysis (may be empty)
    profile: Optional[Dict[str, Any]]        # reference style profile or None
    output: Dict[str, Any]                   # {"format", "quality", "fit"}
    target_duration: float
    audio: Dict[str, Any]                    # {"use_uploaded_music", "music_path", "music_volume", ...}
    aliases: Dict[str, str] = field(default_factory=dict)   # "v1" -> video id

    def __post_init__(self) -> None:
        if not self.aliases:
            self.aliases = {f"v{i}": vid for i, vid in enumerate(self.sources, start=1)}


# ----------------------------------------------------------------- helpers
def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    if isinstance(value, bool):
        return default
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def candidates(ctx: PlannerContext) -> List[Dict[str, Any]]:
    """Flat, score-sorted list of estimated highlights across all videos."""
    out: List[Dict[str, Any]] = []
    for vid, src in ctx.sources.items():
        dur = float(src["duration_seconds"])
        items = sorted((ctx.analyses.get(vid) or {}).get("estimated_highlights", []), key=lambda h: -float(h.get("score", 0)))
        for h in items[:MAX_HIGHLIGHTS_PER_VIDEO]:
            start, end = _clamp(float(h["start"]), 0.0, dur), _clamp(float(h["end"]), 0.0, dur)
            if end - start < settings.min_clip_seconds:
                continue
            out.append({
                "video": vid,
                "start": round(start, 2),
                "end": round(end, 2),
                "peak": round(_clamp(float(h.get("peak_time", (start + end) / 2)), start, end), 2),
                "score": round(float(h.get("score", 0.0)), 3),
                "reasons": list(h.get("reasons", []))[:3],
            })
    out.sort(key=lambda c: -c["score"])
    return out[:MAX_HIGHLIGHTS_TOTAL]


def build_user_prompt(ctx: PlannerContext, feedback: Optional[str] = None) -> str:
    cands = candidates(ctx)
    videos = []
    for alias, vid in ctx.aliases.items():
        src = ctx.sources[vid]
        videos.append({
            "id": alias,
            "file": src.get("name"),
            "duration": round(float(src["duration_seconds"]), 1),
            "highlight_ranges": [
                {"start": c["start"], "end": c["end"], "peak": c["peak"], "score": c["score"], "why": c["reasons"]}
                for c in cands if c["video"] == vid
            ],
        })
    data: Dict[str, Any] = {
        "instructions": ctx.instructions,
        "target_duration_seconds": ctx.target_duration,
        "output_format": ctx.output.get("format"),
        "videos": videos,
    }
    if ctx.profile:
        hints = ctx.profile.get("planner_hints") or {}
        slim = {k: hints[k] for k in ("clip_length_seconds", "transition_mix", "use_slow_motion",
                                      "use_zoom_punch_ins", "prefer_cuts_on_audio_onsets") if k in hints}
        data["reference_style"] = {
            "summary": ctx.profile.get("summary"),
            "tags": (ctx.profile.get("style_tags") or [])[:10],
            "hints": slim,
        }
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    if feedback:
        text += "\n\nYour previous answer was rejected: " + feedback + "\nReturn a corrected JSON object."
    return text


def parse_json_object(text: str) -> Dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.M).strip()
    try:
        obj = json.loads(cleaned)
    except ValueError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("no JSON object found in the reply")
        try:
            obj = json.loads(cleaned[start:end + 1])
        except ValueError as exc:
            raise ValueError(f"invalid JSON: {exc}")
    if not isinstance(obj, dict):
        raise ValueError("the top-level JSON value must be an object")
    return obj


# ------------------------------------------------------------------ repair
def _resolve_source(raw: Any, ctx: PlannerContext) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    key = raw.strip()
    if key.lower() in ctx.aliases:
        return ctx.aliases[key.lower()]
    if key in ctx.sources:
        return key
    named = [vid for vid, s in ctx.sources.items() if s.get("name") == key]
    return named[0] if len(named) == 1 else None


def repair_plan(raw: Dict[str, Any], ctx: PlannerContext) -> Tuple[Dict[str, Any], List[str]]:
    """Fix the small mistakes small models make. Returns (partial_plan, notes)."""
    notes: List[str] = []
    clips: List[Dict[str, Any]] = []
    seen = set()
    raw_clips = raw.get("clips") if isinstance(raw.get("clips"), list) else []
    if not raw_clips:
        notes.append("model returned no clips")

    for i, c in enumerate(raw_clips[: settings.max_plan_clips], start=1):
        tag = f"clip {i}"
        if not isinstance(c, dict):
            notes.append(f"{tag} dropped: not an object")
            continue
        vid = _resolve_source(c.get("source"), ctx)
        if vid is None:
            notes.append(f"{tag} dropped: unknown source '{c.get('source')}'")
            continue
        dur = float(ctx.sources[vid]["duration_seconds"])
        start, end = _num(c.get("start")), _num(c.get("end"))
        if start is None or end is None:
            notes.append(f"{tag} dropped: missing start or end")
            continue
        if start > end:
            start, end = end, start
            notes.append(f"{tag}: start and end were swapped")
        start, end = _clamp(start, 0.0, dur), _clamp(end, 0.0, dur)
        if end - start < settings.min_clip_seconds:
            notes.append(f"{tag} dropped: shorter than {settings.min_clip_seconds}s after clamping")
            continue
        if end - start > settings.max_clip_seconds:
            end = start + settings.max_clip_seconds
            notes.append(f"{tag}: shortened to {settings.max_clip_seconds:.0f}s")

        speed = _num(c.get("speed"), 1.0)
        if not (SPEED_MIN <= speed <= SPEED_MAX):
            speed = _clamp(speed, SPEED_MIN, SPEED_MAX)
            notes.append(f"{tag}: speed clamped to {speed}")
        effect = c.get("effect", "none")
        if effect not in ALLOWED_EFFECTS:
            notes.append(f"{tag}: unknown effect '{effect}' replaced with none")
            effect = "none"
        if effect == "slow_motion" and speed >= 1.0:
            speed = 0.5
            notes.append(f"{tag}: slow_motion speed set to 0.5")
        elif effect == "speed_up" and speed <= 1.0:
            speed = 1.5
            notes.append(f"{tag}: speed_up speed set to 1.5")
        elif effect == "none" and speed < 1.0:
            effect = "slow_motion"
        elif effect == "none" and speed > 1.0:
            effect = "speed_up"

        key = (vid, round(start, 1), round(end, 1))
        if key in seen:
            notes.append(f"{tag} dropped: duplicate of an earlier clip")
            continue
        seen.add(key)
        clips.append({"source": vid, "start": round(start, 3), "end": round(end, 3),
                      "speed": round(speed, 3), "effect": effect})

    # Keep the plan near the requested length.
    total = sum(effective_duration(c) for c in clips)
    while len(clips) > 1 and total > ctx.target_duration * MAX_OVERSHOOT:
        total -= effective_duration(clips.pop())
        notes.append("last clip dropped to stay near the target duration")

    # Exactly one transition per join.
    joins = max(len(clips) - 1, 0)
    raw_tr = raw.get("transitions") if isinstance(raw.get("transitions"), list) else []
    transitions: List[str] = []
    for t in raw_tr[:joins]:
        name = TRANSITION_ALIASES.get(t, t) if isinstance(t, str) else None
        transitions.append(name if name in ALLOWED_TRANSITIONS else "cut")
    if len(transitions) != joins or len(raw_tr) != joins:
        notes.append(f"transitions adjusted to {joins} entries")
    transitions += ["cut"] * (joins - len(transitions))

    co = raw.get("color") if isinstance(raw.get("color"), dict) else {}
    color = {
        "brightness": _clamp(_num(co.get("brightness"), 0.0), -0.3, 0.3),
        "contrast": _clamp(_num(co.get("contrast"), 1.0), 0.5, 2.0),
        "saturation": _clamp(_num(co.get("saturation"), 1.0), 0.5, 2.0),
    }
    style = raw.get("style") if isinstance(raw.get("style"), str) else "custom"
    return {"style": style, "clips": clips, "transitions": transitions, "color": color}, notes


def assemble(ctx: PlannerContext, part: Dict[str, Any]) -> Dict[str, Any]:
    """Merge the model's creative choices with the user's fixed choices."""
    return {
        "project_type": "gaming_video",
        "style": part.get("style") or "custom",
        "target_duration": ctx.target_duration,
        "output": dict(ctx.output),
        "clips": part["clips"],
        "transitions": part["transitions"],
        "audio": dict(ctx.audio),
        "color": part.get("color") or {},
    }


# ---------------------------------------------------------------- fallback
def heuristic_plan(ctx: PlannerContext) -> Tuple[Dict[str, Any], List[str]]:
    """Deterministic planner used when the LLM is unavailable or keeps failing."""
    notes: List[str] = []
    hints = (ctx.profile or {}).get("planner_hints") or {}
    text = ctx.instructions.lower()
    target = ctx.target_duration
    cl = hints.get("clip_length_seconds") or {}
    clip_len = _clamp(float(cl.get("target", 3.0)) * 1.5, 2.0, 8.0)

    cands = candidates(ctx)
    if not cands:
        notes.append("no highlight analysis available: sampled the middle of each video")
        for vid, src in ctx.sources.items():
            dur = float(src["duration_seconds"])
            length = min(6.0, dur)
            mid = max(0.0, (dur - length) / 2)
            cands.append({"video": vid, "start": mid, "end": mid + length, "peak": mid + length / 2, "score": 0.0, "reasons": []})

    use_slow = bool(hints.get("use_slow_motion")) or "slow" in text
    use_zoom = bool(hints.get("use_zoom_punch_ins")) or "zoom" in text

    def window(c: Dict[str, Any], length: float) -> Tuple[float, float]:
        length = min(length, c["end"] - c["start"])
        s = _clamp(c["peak"] - 0.4 * length, c["start"], c["end"] - length)
        return round(s, 3), round(s + length, 3)

    chosen: List[Dict[str, Any]] = []
    total = 0.0
    rest = list(cands)
    if use_slow and rest:
        best = rest.pop(0)
        s, e = window(best, 2.5)
        if e - s >= settings.min_clip_seconds:
            clip = {"source": best["video"], "start": s, "end": e, "speed": 0.5, "effect": "slow_motion", "score": best["score"]}
            chosen.append(clip)
            total += effective_duration(clip)
    for c in rest:
        if total >= target:
            break
        s, e = window(c, clip_len)
        if e - s < settings.min_clip_seconds:
            continue
        # trim the last clip if it would overshoot by more than a second
        over = total + (e - s) - target
        if over > 1.0 and (e - s) - over >= 1.0:
            e = round(e - over, 3)
        clip = {"source": c["video"], "start": s, "end": e, "speed": 1.0, "effect": "none", "score": c["score"]}
        chosen.append(clip)
        total += effective_duration(clip)
    if use_zoom:
        for clip in chosen:
            if clip["effect"] == "none":
                clip["effect"] = "zoom_in"
                break

    chosen.sort(key=lambda c: c["score"])          # build up to the strongest moment
    clips = [{k: v for k, v in c.items() if k != "score"} for c in chosen][: settings.max_plan_clips]

    mix = hints.get("transition_mix") or {}
    default_tr = "cut"
    if "smooth" in text or "fade" in text or float(mix.get("fade", 0)) > 0.3:
        default_tr = "crossfade"
    elif float(mix.get("flash", 0)) > 0.3:
        default_tr = "fadewhite"
    transitions = []
    for i in range(len(clips) - 1):
        into_slow = clips[i + 1]["effect"] == "slow_motion"
        transitions.append("crossfade" if into_slow and default_tr == "cut" else default_tr)

    style = "fast_paced_action" if (cl.get("target", 3.0) or 3.0) < 3.0 else "gameplay_highlights"
    notes.append("deterministic fallback planner used")
    return {"style": style, "clips": clips, "transitions": transitions, "color": {}}, notes


# ------------------------------------------------------------------- main
LlmFn = Callable[[str, str], str]


def generate_plan(ctx: PlannerContext, use_llm: bool = True, llm: Optional[LlmFn] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return (validated_plan, planner_meta). Always returns a valid plan or raises PlanValidationError."""
    llm = llm or chat_json
    warnings: List[str] = []
    attempts = 0

    if use_llm:
        feedback: Optional[str] = None
        for _ in range(2):
            attempts += 1
            try:
                reply = llm(SYSTEM_PROMPT, build_user_prompt(ctx, feedback))
            except OllamaError as exc:
                warnings.append(f"Ollama unavailable: {exc}")
                break
            try:
                raw = parse_json_object(reply)
            except ValueError as exc:
                feedback = f"it was not valid JSON ({exc})"
                warnings.append(f"attempt {attempts}: {feedback}")
                continue
            part, notes = repair_plan(raw, ctx)
            try:
                plan = validate_plan(assemble(ctx, part), ctx.sources)
            except PlanValidationError as exc:
                feedback = "; ".join(exc.errors[:6])
                warnings.append(f"attempt {attempts}: plan rejected: {feedback}")
                continue
            return plan, {
                "mode": "llm" if not notes else "llm_repaired",
                "model": settings.ollama_model,
                "attempts": attempts,
                "warnings": warnings + notes,
            }

    part, notes = heuristic_plan(ctx)
    plan = validate_plan(assemble(ctx, part), ctx.sources)
    return plan, {
        "mode": "fallback",
        "model": settings.ollama_model if use_llm else None,
        "attempts": attempts,
        "warnings": warnings + notes,
    }
