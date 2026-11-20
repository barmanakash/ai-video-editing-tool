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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.config import settings
from app.engine import audio_engine, effects_engine, transition_engine, video_cutter
from app.engine.plan_schema import effective_duration

OUTPUT_SIZES = {
    ("youtube", "full"): (1920, 1080),
    ("youtube", "test"): (854, 480),
    ("instagram", "full"): (1080, 1920),
    ("instagram", "test"): (480, 854),
}
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


def output_size(fmt: str, quality: str) -> tuple:
    try:
        return OUTPUT_SIZES[(fmt, quality)]
    except KeyError:
        raise RenderError(f"Unsupported output: format={fmt!r}, quality={quality!r}")


def build_graph(plan: Dict[str, Any], sources: Dict[str, Dict[str, Any]], width: int, height: int) -> GraphBuild:
    """Pure function: plan -> FFmpeg inputs + filter graph (easy to unit-test without FFmpeg)."""
    out = plan["output"]
    fps, fit = int(out["fps"]), out["fit"]
    clips, trans, audio = plan["clips"], plan["transitions"], plan["audio"]

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
    for j in range(1, len(clips)):
        name = trans[j - 1] if j - 1 < len(trans) else "cut"
        td = transition_engine.transition_duration(name, durs[j - 1], durs[j])
        new_lines, cur_v, cur_a, cur_len = transition_engine.join_streams(
            j, cur_v, cur_a, cur_len, durs[j], name, td, fps)
        lines += new_lines

    total = cur_len
    grade = effects_engine.color_filter(plan.get("color"))
    lines.append(f"{cur_v}{grade or 'null'},format=yuv420p[vout]")

    if audio.get("use_uploaded_music") and audio.get("music_path"):
        idx = len(clips)
        input_args += ["-stream_loop", "-1", "-i", str(audio["music_path"])]
        lines.append(audio_engine.music_chain(idx, total, float(audio["music_volume"])))
        lines.append(f"{cur_a}[m]amix=inputs=2:duration=first:normalize=0:dropout_transition=0[amix]")
        cur_a = "[amix]"
    fade = f"afade=t=out:st={max(total - 1.0, 0):.3f}:d=1.000," if total > 3 else ""
    lines.append(f"{cur_a}{fade}alimiter=limit=0.95[aout]")
    return GraphBuild(input_args=input_args, graph=";\n".join(lines), total=total)


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
    return 0x08000000 | 0x00004000          # CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS


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
    if audio.get("use_uploaded_music") and audio.get("music_path") and audio.get("sync_cuts_to_music", True) and len(plan["clips"]) > 1:
        try:
            snapped = audio_engine.snap_clips_to_beats(plan, sources, audio_engine.music_beats(audio["music_path"]))
        except Exception as exc:                              # beat sync is a bonus, never fatal
            notes.append(f"beat sync skipped: {exc}")

    built = build_graph(plan, sources, width, height)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    final = settings.outputs_dir / f"{_slug(plan.get('style'))}_{plan_id}_{out['format']}_{stamp}.mp4"
    tmp = settings.temp_dir
    part, log, script = tmp / f"{plan_id}.render.part", tmp / f"{plan_id}.render.log", tmp / f"{plan_id}.render.ffgraph"

    preset, crf = ((settings.test_preset, settings.test_crf) if out["quality"] == "test"
                   else (settings.full_preset, settings.full_crf))
    head = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-v", "error", "-progress", "pipe:1", "-nostats"] + built.input_args
    tail = ["-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart", "-t", f"{built.total:.3f}", "-f", "mp4", str(part)]

    if len(built.graph) <= INLINE_GRAPH_LIMIT:
        flavours = ["inline"]
    else:
        major = _ffmpeg_major(ffmpeg)
        flavours = ["new", "old"] if (major is None or major >= 7) else ["old", "new"]

    try:
        rc = 1
        for n, flavour in enumerate(flavours):
            rc = _run(head, _graph_args(built.graph, script, flavour), tail, built.total, log, progress_cb, cancel)
            if rc == 0:
                break
            text = log.read_text(errors="replace") if log.exists() else ""
            if n < len(flavours) - 1 and re.search(r"Unrecognized option|Option not found", text):
                continue                                       # try the other script option name
            break
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
