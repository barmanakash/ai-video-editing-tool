"""Renderer: executes a VALIDATED plan with FFmpeg in a single encode pass.

Design for an 8 GB machine:
  * every clip is a separate seeked input, so only the used seconds are decoded;
  * all clips, transitions, music and colour go through ONE filter graph, so there are
    no intermediate video files and the video is encoded exactly once;
  * the render runs at below-normal priority on Windows so the PC stays usable;
  * temporary files (log, optional graph script, partial output) are removed afterwards.

The plan is data. This module builds the FFmpeg argument list itself from validated
numbers; nothing from the LLM is ever passed to FFmpeg as text.
"""
from __future__ import annotations

import copy
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.config import settings
from app.engine import (audio_engine, effects_engine, encoders, speed_ramp, text_overlay, transition_engine,
                        video_cutter)
from app.engine.plan_schema import effective_duration

# Kept for compatibility: every (format, quality) pair and its size. See encoders.LANDSCAPE_SIZES.
OUTPUT_SIZES = {(fmt, q): encoders.output_size(fmt, q)
                for fmt in ("youtube", "instagram") for q in encoders.LANDSCAPE_SIZES}
INLINE_GRAPH_LIMIT = 8000       # longer graphs go through a script file (Windows command lines are limited)


class RenderError(RuntimeError):
    pass


class RenderCancelled(RuntimeError):
    pass


@dataclass
class GraphBuild:
    input_args: List[str]
    graph: str
    total: float
    has_audio: bool = True
    notes: List[str] = field(default_factory=list)


def output_size(fmt: str, quality: str) -> tuple:
    try:
        return encoders.output_size(fmt, quality)
    except ValueError:
        raise RenderError(f"Unsupported output: format={fmt!r}, quality={quality!r}")


def expand_pieces(plan: Dict[str, Any]) -> tuple:
    """Split speed-ramp clips into constant-speed pieces of the same source.

    Returns (pieces, transitions, internal) where transitions[k] joins piece k to piece k+1
    and internal[k] is True for the invisible joins inside a ramp (never a real cut).
    """
    pieces: List[Dict[str, Any]] = []
    trans: List[str] = []
    internal: List[bool] = []
    for i, clip in enumerate(plan["clips"]):
        if clip.get("effect") == "speed_ramp":
            parts = [{"source": clip["source"], "start": a, "end": b, "speed": s, "effect": "none"}
                     for a, b, s in speed_ramp.segments(clip)]
        else:
            parts = [clip]
        for k, piece in enumerate(parts):
            if pieces:
                if k > 0:
                    trans.append("cut")
                    internal.append(True)
                else:
                    tr = plan["transitions"]
                    trans.append(tr[i - 1] if i - 1 < len(tr) else "cut")
                    internal.append(False)
            pieces.append(piece)
    return pieces, trans, internal


def _punch_times(fx: Dict[str, Any], cut_times: List[float], beats: Optional[List[float]],
                 total: float) -> tuple:
    """Timeline times for zoom/flash/shake punches: real cuts, or strong spaced-out music beats."""
    mode = fx.get("punch", "off")
    if mode == "off":
        return [], []
    notes: List[str] = []
    times = list(cut_times)
    if mode == "beats":
        if beats:
            times = effects_engine.thin_times(list(beats), 0.55)
        else:
            notes.append("punch effects: no music beats available, used the cuts instead")
    times = [t for t in times if 0.2 < t < total - 0.1][: effects_engine.MAX_PUNCHES]
    return times, notes


def build_graph(plan: Dict[str, Any], sources: Dict[str, Dict[str, Any]], width: int, height: int,
                beats: Optional[List[float]] = None) -> GraphBuild:
    """Pure function: plan -> FFmpeg inputs + filter graph (easy to unit-test without FFmpeg)."""
    out = plan["output"]
    fps, fit = int(out["fps"]), out["fit"]
    audio = plan["audio"]
    clips, trans, internal = expand_pieces(plan)

    input_args: List[str] = []
    lines: List[str] = []
    durs: List[float] = []
    for i, clip in enumerate(clips):
        src = sources[clip["source"]]
        input_args += video_cutter.input_args(clip, src["path"])
        d = effective_duration(clip)
        durs.append(d)
        chain = effects_engine.video_chain(clip, width, height, fit, fps, d)
        lines.append(f"[{i}:v]" + ",".join(chain) + f"[v{i}]")
        lines.append(audio_engine.clip_audio_chain(i, clip, d, bool(src.get("has_audio")),
                                                   float(audio["game_audio_volume"])))

    cur_v, cur_a, cur_len = "[v0]", "[a0]", durs[0]
    cut_times: List[float] = []
    for j in range(1, len(clips)):
        name = trans[j - 1]
        td = transition_engine.transition_duration(name, durs[j - 1], durs[j])
        if not internal[j - 1]:
            cut_times.append(cur_len - td / 2)                 # centre of the real cut or transition
        new_lines, cur_v, cur_a, cur_len = transition_engine.join_streams(
            j, cur_v, cur_a, cur_len, durs[j], name, td, fps)
        lines += new_lines

    total = cur_len
    fx = plan.get("fx") or {}
    color = plan.get("color") or {}
    punch_times, notes = _punch_times(fx, cut_times, beats, total)
    post = effects_engine.punch_chain(punch_times, width, height, bool(fx.get("zoom_punch", True)),
                                      bool(fx.get("flash", False)), bool(fx.get("shake", False)))
    post += effects_engine.preset_filters(color.get("preset"))
    grade = effects_engine.color_filter(color)
    if grade:
        post.append(grade)
    title_filters, title_notes = text_overlay.build_filters(plan.get("titles"), total, width, height)
    post += title_filters
    notes += title_notes
    post.append("format=yuv420p")
    lines.append(f"{cur_v}" + ",".join(post) + "[vout]")

    if audio.get("use_uploaded_music") and audio.get("music_path"):
        idx = len(clips)
        input_args += ["-stream_loop", "-1", "-i", str(audio["music_path"])]
        lines.append(audio_engine.music_chain(idx, total, float(audio["music_volume"])))
        lines.append(f"{cur_a}[m]amix=inputs=2:duration=first:normalize=0:dropout_transition=0[amix]")
        cur_a = "[amix]"
    fade = f"afade=t=out:st={max(total - 1.0, 0):.3f}:d=1.000," if total > 3 else ""
    lines.append(f"{cur_a}{fade}alimiter=limit=0.95[aout]")
    return GraphBuild(input_args=input_args, graph=";\n".join(lines), total=total, notes=notes)


# ------------------------------------------------------------------ running
def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")[:30] or "edit"


def _ffmpeg_major(ffmpeg: str) -> Optional[int]:
    try:
        r = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, timeout=15)
        m = re.search(r"ffmpeg version n?(\d+)\.", r.stdout)
        return int(m.group(1)) if m else None
    except (OSError, subprocess.SubprocessError):
        return None


def _creationflags() -> int:
    if os.name != "nt":
        return 0
    flags = 0x08000000                       # CREATE_NO_WINDOW
    if settings.render_low_priority:
        flags |= 0x00004000                  # BELOW_NORMAL_PRIORITY_CLASS: keep the PC responsive
    return flags


def _graph_args(graph: str, script: Path, flavour: str) -> List[str]:
    if flavour == "inline":
        return ["-filter_complex", graph]
    script.write_text(graph, encoding="utf-8")
    return ["-/filter_complex", str(script)] if flavour == "new" else ["-filter_complex_script", str(script)]


def _run(cmd_head: List[str], graph_args: List[str], tail: List[str], total: float, log: Path,
         progress_cb: Optional[Callable[[float], None]], cancel: Any) -> int:
    cmd = cmd_head + graph_args + tail
    with open(log, "wb") as logf:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=logf, stdin=subprocess.DEVNULL,
                                text=True, creationflags=_creationflags())
        try:
            for line in proc.stdout:                       # -progress lines arrive about twice a second
                if cancel is not None and cancel.is_set():
                    proc.kill()
                    proc.wait()
                    raise RenderCancelled("Render cancelled")
                m = re.match(r"out_time_(?:us|ms)=(\d+)", line.strip())
                if m and progress_cb and total > 0:
                    progress_cb(min(99.0, int(m.group(1)) / 1_000_000 / total * 100))
            return proc.wait()
        except BaseException:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            raise


def render(plan: Dict[str, Any], sources: Dict[str, Dict[str, Any]], plan_id: str,
           progress_cb: Optional[Callable[[float], None]] = None, cancel: Any = None) -> Dict[str, Any]:
    """Render the plan to outputs/. Returns details for the quality checker."""
    started = time.time()
    ffmpeg = shutil.which(settings.ffmpeg_path)
    if not ffmpeg:
        raise RenderError("FFmpeg was not found. Install it and check GVE_FFMPEG / PATH.")
    settings.ensure_dirs()
    free_gb = shutil.disk_usage(settings.outputs_dir).free / 1024 ** 3
    if free_gb < settings.min_free_render_gb:
        raise RenderError(f"Only {free_gb:.1f} GB free; need at least {settings.min_free_render_gb} GB to render.")

    plan = copy.deepcopy(plan)
    out = plan["output"]
    width, height = output_size(out["format"], out["quality"])
    notes: List[str] = []
    snapped = 0
    audio = plan["audio"]
    fx = plan.get("fx") or {}
    can_snap = bool(audio.get("sync_cuts_to_music", True)) and len(plan["clips"]) > 1
    beats: List[float] = []
    if audio.get("use_uploaded_music") and audio.get("music_path") and (can_snap or fx.get("punch") == "beats"):
        try:
            beats = audio_engine.music_beats(audio["music_path"])
        except Exception as exc:                              # beat analysis is a bonus, never fatal
            notes.append(f"beat analysis skipped: {exc}")
    if beats and can_snap:
        snapped = audio_engine.snap_clips_to_beats(plan, sources, beats)

    built = build_graph(plan, sources, width, height, beats=beats)
    notes += built.notes
    stamp = time.strftime("%Y%m%d_%H%M%S")
    final = settings.outputs_dir / f"{_slug(plan.get('style'))}_{plan_id}_{out['format']}_{out['quality']}_{stamp}.mp4"
    tmp = settings.temp_dir
    part, log, script = tmp / f"{plan_id}.render.part", tmp / f"{plan_id}.render.log", tmp / f"{plan_id}.render.ffgraph"

    fps_out = int(out["fps"])
    codec, enc_pref, level = out.get("codec", "h264"), out.get("encoder", "auto"), out.get("quality_level", "standard")
    est_mb = encoders.estimate_size_mb(width, height, fps_out, built.total, codec, level)
    free_mb = shutil.disk_usage(settings.outputs_dir).free / 1024 ** 2
    if free_mb < est_mb * 1.3 + settings.min_free_render_gb * 1024:
        raise RenderError(f"Not enough free disk space: this export needs about {est_mb:.0f} MB, "
                          f"only {free_mb:.0f} MB are free (keeping {settings.min_free_render_gb} GB spare). "
                          "Free some space or choose a lower quality.")
    notes += encoders.upscale_notes(plan["clips"], sources, width, height, fps_out, out["fit"])
    choice = encoders.choose_encoder(ffmpeg, codec, enc_pref, out["quality"], level, fps_out)
    notes += choice.notes
    attempts = [choice]
    if choice.hardware:                                         # hardware failed? retry on the CPU
        attempts.append(encoders.cpu_fallback(choice, ffmpeg, codec, out["quality"], level))

    head = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-v", "error", "-progress", "pipe:1", "-nostats"] + built.input_args

    def make_tail(enc: encoders.EncoderChoice) -> List[str]:
        return ("-map [vout] -map [aout]".split() + enc.args +
                ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
                 "-t", f"{built.total:.3f}", "-f", "mp4", str(part)])

    if len(built.graph) <= INLINE_GRAPH_LIMIT:
        flavours = ["inline"]
    else:
        major = _ffmpeg_major(ffmpeg)
        flavours = ["new", "old"] if (major is None or major >= 7) else ["old", "new"]

    used = choice
    try:
        rc = 1
        for a, enc in enumerate(attempts):
            tail = make_tail(enc)
            for n, flavour in enumerate(flavours):
                rc = _run(head, _graph_args(built.graph, script, flavour), tail, built.total, log, progress_cb, cancel)
                if rc == 0:
                    break
                text = log.read_text(errors="replace") if log.exists() else ""
                if n < len(flavours) - 1 and re.search(r"Unrecognized option|Option not found", text):
                    continue                                       # try the other script option name
                break
            if rc == 0 and part.is_file() and part.stat().st_size > 0:
                used = enc
                break
            if a < len(attempts) - 1:
                notes.append(f"{enc.label} failed on this computer, so the CPU encoder was used instead")
                part.unlink(missing_ok=True)
        if rc != 0 or not part.is_file() or part.stat().st_size == 0:
            text = log.read_text(errors="replace") if log.exists() else ""
            raise RenderError(f"FFmpeg failed (exit {rc}): {text.strip()[-1500:] or 'no error output'}")
        os.replace(part, final)
    finally:
        for f in (part, log, script):
            f.unlink(missing_ok=True)

    if progress_cb:
        progress_cb(100.0)
    return {
        "output_path": str(final),
        "width": width,
        "height": height,
        "expected_duration": built.total,
        "has_audio": True,
        "snapped_cuts": snapped,
        "notes": notes,
        "encoder": used.label,
        "fps": fps_out,
        "size_mb": round(final.stat().st_size / 1024 ** 2, 2),
        "elapsed": round(time.time() - started, 1),
    }


def cleanup_stale_temp(max_age_hours: float = 24.0) -> int:
    """Delete leftover render temp files (e.g. after a crash). Returns how many were removed."""
    removed = 0
    cutoff = time.time() - max_age_hours * 3600
    for pattern in ("*.render.part", "*.render.log", "*.render.ffgraph"):
        for f in settings.temp_dir.glob(pattern):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
            except OSError:
                pass
    return removed
