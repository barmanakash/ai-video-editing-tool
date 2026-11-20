"""Phase 5-6 tests: editing engine, renderer, quality checks, render jobs and API.

Run:  python -m pytest -q tests/test_phase5_6.py

* Unit tests need nothing but Python.
* Render tests need FFmpeg on PATH (they are skipped otherwise) and use tiny generated videos.
* API tests need fastapi + scenedetect (the normal project install).
"""
import shutil
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest

from app.config import settings
from app.engine import audio_engine, effects_engine, transition_engine, video_cutter
from app.engine.plan_schema import effective_duration, validate_plan

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="FFmpeg / FFprobe not installed")


# =========================================================== unit: filters
def test_atempo_chain_covers_the_whole_speed_range():
    assert audio_engine.atempo_chain(1.0) == []
    assert audio_engine.atempo_chain(0.5) == ["atempo=0.5"]
    assert audio_engine.atempo_chain(0.25) == ["atempo=0.5", "atempo=0.5"]
    assert audio_engine.atempo_chain(4.0) == ["atempo=2.0", "atempo=2.0"]
    assert audio_engine.atempo_chain(1.5) == ["atempo=1.5"]
    for s in (0.25, 0.3, 0.7, 1.3, 2.5, 4.0):          # every instance stays inside FFmpeg's 0.5-2.0 limit
        for part in audio_engine.atempo_chain(s):
            assert 0.5 <= float(part.split("=")[1]) <= 2.0


def test_video_chain_contains_only_expected_filters():
    base = dict(fps=30, speed=0.5, width=854, height=480, fit="crop", color={}, frames=60)
    plain = effects_engine.video_chain(effect="slow_motion", **base)
    assert plain.startswith("setpts=(PTS-STARTPTS)/0.5,fps=30,scale=854:480")
    assert "eq=" not in plain and "zoom" not in plain and "trim=end_frame=60" in plain

    zoomed = effects_engine.video_chain(effect="zoom_in", zoom_offset=1.0, zoom_total=4.0, **base)
    assert "eval=frame" in zoomed and "t+1)/4" in zoomed

    graded = effects_engine.video_chain(effect="none", **{**base, "color": {"brightness": 0.1, "contrast": 1.2, "saturation": 1.0}})
    assert "eq=brightness=0.1:contrast=1.2:saturation=1" in graded

    padded = effects_engine.video_chain(effect="none", **{**base, "fit": "pad"})
    assert "pad=854:480" in padded and "crop=" not in padded


def test_output_resolutions():
    assert effects_engine.target_resolution("youtube", "full") == (1920, 1080)
    assert effects_engine.target_resolution("instagram", "full") == (1080, 1920)
    assert effects_engine.target_resolution("youtube", "test")[0] > effects_engine.target_resolution("youtube", "test")[1]
    assert effects_engine.target_resolution("instagram", "test")[0] < effects_engine.target_resolution("instagram", "test")[1]
    with pytest.raises(ValueError):
        effects_engine.target_resolution("tiktok", "full")


def test_final_audio_filter_has_music_fades_and_limiter():
    no_music = audio_engine.final_audio_filter(30, 0.8, 0.7, use_music=False)
    assert "[1:a]" not in no_music and "volume=0.8" in no_music and no_music.endswith("[aout]")
    with_music = audio_engine.final_audio_filter(30, 0.4, 0.7, use_music=True)
    assert "amix=inputs=2:duration=first" in with_music and "afade=t=out:st=28.5" in with_music and "alimiter" in with_music


# ======================================================= unit: transitions
def test_transition_durations_are_capped_and_frame_aligned():
    effs = [6.0, 6.0, 0.6, 6.0]
    d, notes = transition_engine.plan_transition_durations(effs, ["crossfade", "fadeblack", "cut"], 0.4, 30)
    assert d[0] == pytest.approx(0.4) and d[2] == 0.0 and notes == []
    assert all(abs(x * 30 - round(x * 30)) < 1e-6 for x in d)          # whole frames
    # a join next to a 0.6 s clip may use at most 40 % of it (0.24 s)
    assert d[1] == pytest.approx(0.2333, abs=0.01)
    # too-short clips turn the transition into a cut and say so
    d2, notes2 = transition_engine.plan_transition_durations([0.5, 0.5], ["crossfade"], 0.4, 30)
    assert d2 == [0.0] and notes2 and "became a cut" in notes2[0]


def _clips():
    return [
        {"source": "a", "start": 2.0, "end": 7.0, "speed": 1.0, "effect": "none"},         # 5 s
        {"source": "b", "start": 3.0, "end": 6.0, "speed": 0.5, "effect": "slow_motion"},  # 6 s
        {"source": "a", "start": 10.0, "end": 14.0, "speed": 1.0, "effect": "zoom_in"},    # 4 s
    ]


SRC = {"a": {"path": "a.mp4", "has_audio": True, "duration_seconds": 20.0},
       "b": {"path": "b.mp4", "has_audio": False, "duration_seconds": 15.0}}


def test_pieces_add_up_to_clips_minus_transition_overlap():
    clips = _clips()
    joins = [0.4, 0.0]                      # crossfade then hard cut
    pieces = video_cutter.build_pieces(clips, SRC, joins, ["crossfade", "cut"], 30)
    total = sum(p.frames for p in pieces) / 30
    assert total == pytest.approx(5 + 6 + 4 - 0.4)
    assert [p.kind for p in pieces] == ["body", "transition", "body", "body"]
    trans = pieces[1]
    assert trans.frames == 12 and len(trans.slices) == 2
    a_side, b_side = trans.slices
    assert a_side.src_start == pytest.approx(2.0 + (5.0 - 0.4)) and a_side.src_len == pytest.approx(0.4)
    assert b_side.src_start == pytest.approx(3.0) and b_side.src_len == pytest.approx(0.4 * 0.5)   # slow motion: half the source
    # the body after the transition starts where the blend stopped
    assert pieces[2].slices[0].src_start == pytest.approx(3.0 + 0.4 * 0.5)
    # zoom continues smoothly across pieces
    assert pieces[3].slices[0].zoom_offset == 0.0 and pieces[3].slices[0].zoom_total == pytest.approx(4.0)


def test_pieces_without_transitions_are_one_body_per_clip():
    pieces = video_cutter.build_pieces(_clips(), SRC, [0.0, 0.0], ["cut", "cut"], 30)
    assert [p.kind for p in pieces] == ["body"] * 3
    assert sum(p.frames for p in pieces) == 15 * 30


# ============================================================ unit: snapping
def test_cuts_snap_to_nearby_onsets_only():
    clips = [
        {"source": "a", "start": 0.0, "end": 5.2, "speed": 1.0, "effect": "none"},
        {"source": "a", "start": 8.0, "end": 12.35, "speed": 1.0, "effect": "none"},
        {"source": "a", "start": 14.0, "end": 18.0, "speed": 1.0, "effect": "none"},
    ]
    onsets = [5.0, 9.6, 14.0]               # join 1 (5.2) is 0.2 s from 5.0; join 2 (9.35 after the first move) is 0.25 s from 9.6
    new, count = audio_engine.snap_cuts_to_onsets(clips, [0.0, 0.0], onsets, {"a": 30.0}, 0.3)
    assert count == 2
    assert new[0]["end"] == pytest.approx(5.0, abs=0.01)
    assert effective_duration(new[0]) + effective_duration(new[1]) == pytest.approx(9.6, abs=0.01)
    assert new[2] == clips[2]               # the last clip has no join
    far, count = audio_engine.snap_cuts_to_onsets(clips, [0.0, 0.0], [20.0], {"a": 30.0}, 0.3)
    assert count == 0 and far == clips
    short, count = audio_engine.snap_cuts_to_onsets(clips, [0.0, 0.0], [], {"a": 30.0}, 0.3)
    assert count == 0


def test_snapping_never_runs_past_the_end_of_the_source():
    clips = [{"source": "a", "start": 0.0, "end": 10.0, "speed": 1.0, "effect": "none"},
             {"source": "a", "start": 12.0, "end": 16.0, "speed": 1.0, "effect": "none"}]
    new, count = audio_engine.snap_cuts_to_onsets(clips, [0.0], [10.2], {"a": 10.0}, 0.3)
    assert count == 0 and new[0]["end"] == 10.0


# ======================================================= unit: quality agent
def test_quality_agent_reports_missing_and_tiny_files(tmp_path):
    from app.agents import quality_agent

    expected = {"width": 854, "height": 480, "duration": 5, "has_audio": True}
    report = quality_agent.check_output(tmp_path / "missing.mp4", expected)
    assert report["passed"] is False and "was not created" in report["summary"]
    tiny = tmp_path / "tiny.mp4"
    tiny.write_bytes(b"x" * 10)
    assert quality_agent.check_output(tiny, expected)["passed"] is False


# ================================================================ rendering
def make_video(path: Path, seconds: float = 8.0, audio: bool = True, kind: str = "testsrc2") -> Path:
    cmd = [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"{kind}=size=320x180:rate=30"]
    if audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100"]
    cmd += ["-t", str(seconds), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)
    return path


def make_music(path: Path, seconds: float = 4.0) -> Path:
    """A short track with a click every half second (so cut sync has something to find)."""
    expr = "0.9*sin(2*PI*180*t)*exp(-30*mod(t-0.13,0.5))*gte(t,0.13)"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d={seconds}",
                    "-c:a", "libmp3lame", str(path)], check=True)
    return path


def probe_streams(path):
    out = subprocess.run([FFPROBE, "-v", "error", "-count_frames", "-show_entries",
                          "stream=codec_type,nb_read_frames,duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.split()
    info = {}
    for line in out:
        kind, dur, frames = line.split(",")[:3]
        info[kind] = (float(dur) if dur not in ("N/A", "") else 0.0, int(frames) if frames.isdigit() else 0)
    return info


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "outputs_dir", tmp_path / "outputs")
    settings.ensure_dirs()
    sources = {
        "aaaaaaaaaaaa": {"path": str(make_video(tmp_path / "a.mp4", 8, True)), "has_audio": True,
                         "duration_seconds": 8.0, "name": "a.mp4"},
        "bbbbbbbbbbbb": {"path": str(make_video(tmp_path / "b.mp4", 8, False, "mandelbrot")), "has_audio": False,
                         "duration_seconds": 8.0, "name": "b.mp4"},
    }
    return tmp_path, sources


def _plan(sources, **over):
    base = {
        "clips": [
            {"source": "aaaaaaaaaaaa", "start": 1, "end": 4, "speed": 1.0, "effect": "none"},
            {"source": "bbbbbbbbbbbb", "start": 2, "end": 4, "speed": 0.5, "effect": "slow_motion"},
            {"source": "aaaaaaaaaaaa", "start": 4, "end": 7, "speed": 1.0, "effect": "zoom_in"},
        ],
        "transitions": ["cut", "cut"],
        "output": {"format": "youtube", "quality": "test"},
    }
    base.update(over)
    return validate_plan(base, sources)


def _check(res):
    from app.agents import quality_agent
    return quality_agent.check_output(res["output_path"], {
        "width": res["width"], "height": res["height"],
        "duration": res["expected_duration"], "has_audio": res["has_audio"]})


@needs_ffmpeg
def test_render_cuts_slow_motion_and_zoom(env):
    from app.engine import renderer

    tmp_path, sources = env
    progress = []
    res = renderer.render(_plan(sources), sources, "plan00000001", progress_cb=progress.append)
    assert (res["width"], res["height"]) == (854, 480)
    assert res["expected_duration"] == pytest.approx(3 + 4 + 3)           # slow motion doubles clip 2
    report = _check(res)
    assert report["passed"], report["summary"]
    streams = probe_streams(res["output_path"])
    assert streams["video"][1] == 300                                     # exactly 10 s at 30 fps
    assert abs(streams["audio"][0] - streams["video"][0]) < 0.05          # audio and video stay in sync
    assert progress == sorted(progress) and progress[-1] == 1.0
    assert not list(settings.temp_dir.iterdir()), "temporary files must be cleaned up"
    assert not list(settings.outputs_dir.glob("*.part"))


@needs_ffmpeg
def test_transitions_overlap_and_all_types_render(env):
    from app.engine import renderer

    tmp_path, sources = env
    clips = [
        {"source": "aaaaaaaaaaaa", "start": 0, "end": 3, "speed": 1.0, "effect": "none"},
        {"source": "bbbbbbbbbbbb", "start": 0, "end": 3, "speed": 1.0, "effect": "none"},
        {"source": "aaaaaaaaaaaa", "start": 3, "end": 6, "speed": 1.0, "effect": "none"},
        {"source": "bbbbbbbbbbbb", "start": 3, "end": 6, "speed": 2.0, "effect": "speed_up"},
    ]
    plan = _plan(sources, clips=clips, transitions=["crossfade", "fadeblack", "slideleft"])
    res = renderer.render(plan, sources, "plan00000002")
    d = settings.transition_seconds
    assert res["expected_duration"] == pytest.approx(3 + 3 + 3 + 1.5 - 3 * d, abs=0.05)
    assert res["pieces"] == 7                                             # 4 bodies + 3 blends
    report = _check(res)
    assert report["passed"], report["summary"]


@needs_ffmpeg
def test_instagram_pad_with_colour_grade(env):
    from app.engine import renderer

    tmp_path, sources = env
    plan = _plan(sources, transitions=["crossfade", "cut"],
                 output={"format": "instagram", "quality": "test", "fit": "pad"},
                 color={"brightness": 0.05, "contrast": 1.2, "saturation": 1.3})
    res = renderer.render(plan, sources, "plan00000003")
    assert (res["width"], res["height"]) == (480, 854)
    assert _check(res)["passed"]


@needs_ffmpeg
def test_music_is_mixed_looped_and_cuts_are_synced(env):
    from app.engine import renderer

    tmp_path, sources = env
    music = make_music(tmp_path / "beats.mp3", seconds=4.0)               # shorter than the video: must loop
    clips = [
        {"source": "aaaaaaaaaaaa", "start": 0, "end": 3.2, "speed": 1.0, "effect": "none"},
        {"source": "aaaaaaaaaaaa", "start": 4, "end": 7.3, "speed": 1.0, "effect": "none"},
        {"source": "bbbbbbbbbbbb", "start": 0, "end": 3.0, "speed": 1.0, "effect": "none"},
    ]
    plan = _plan(sources, clips=clips, transitions=["cut", "cut"],
                 audio={"use_uploaded_music": True, "music_path": str(music), "music_volume": 0.6})
    res = renderer.render(plan, sources, "plan00000004")
    assert res["snapped_cuts"] >= 1
    report = _check(res)
    assert report["passed"], report["summary"]
    assert abs(probe_streams(res["output_path"])["audio"][0] - res["expected_duration"]) < 0.1


@needs_ffmpeg
def test_video_without_any_audio_has_no_audio_track(env):
    from app.engine import renderer

    tmp_path, sources = env
    plan = _plan(sources, clips=[{"source": "bbbbbbbbbbbb", "start": 0, "end": 4, "speed": 1.0, "effect": "none"}],
                 transitions=[])
    res = renderer.render(plan, sources, "plan00000005")
    assert res["has_audio"] is False
    assert "audio" not in probe_streams(res["output_path"])
    assert _check(res)["passed"]


@needs_ffmpeg
def test_cancel_stops_ffmpeg_and_cleans_up(env):
    from app.engine import renderer

    tmp_path, sources = env
    cancel = threading.Event()
    plan = _plan(sources, output={"format": "youtube", "quality": "full"})   # 1080p: slow enough to cancel
    threading.Timer(0.7, cancel.set).start()
    with pytest.raises(renderer.RenderCancelled):
        renderer.render(plan, sources, "plan00000006", cancel=cancel)
    assert not list(settings.temp_dir.iterdir())
    assert not list(settings.outputs_dir.iterdir())


@needs_ffmpeg
def test_corrupt_source_gives_a_readable_error_and_no_leftovers(env):
    from app.engine import renderer

    tmp_path, sources = env
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"definitely not a video" * 50)
    sources["aaaaaaaaaaaa"]["path"] = str(bad)
    with pytest.raises(renderer.RenderError) as exc:
        renderer.render(_plan(sources), sources, "plan00000007")
    assert "FFmpeg failed" in str(exc.value) and "clip 1" in str(exc.value)
    assert not list(settings.temp_dir.iterdir())
    assert not list(settings.outputs_dir.iterdir())


@needs_ffmpeg
def test_missing_source_and_missing_music_are_reported_before_rendering(env):
    from app.engine import renderer

    tmp_path, sources = env
    plan = _plan(sources)
    Path(sources["bbbbbbbbbbbb"]["path"]).unlink()
    with pytest.raises(renderer.RenderError, match="no longer exists"):
        renderer.render(plan, sources, "plan00000008")


@needs_ffmpeg
def test_quality_agent_catches_damaged_and_wrong_videos(env):
    from app.agents import quality_agent
    from app.engine import renderer

    tmp_path, sources = env
    res = renderer.render(_plan(sources), sources, "plan00000009")
    good = Path(res["output_path"])
    expected = {"width": res["width"], "height": res["height"], "duration": res["expected_duration"], "has_audio": True}
    assert quality_agent.check_output(good, expected)["passed"]

    truncated = tmp_path / "truncated.mp4"
    truncated.write_bytes(good.read_bytes()[: good.stat().st_size // 3])
    assert quality_agent.check_output(truncated, expected)["passed"] is False

    wrong = quality_agent.check_output(good, {**expected, "width": 1920, "height": 1080, "duration": 99})
    assert wrong["passed"] is False
    assert "Expected 1920x1080" in wrong["summary"] and "plan expects 99.00s" in wrong["summary"]


# ================================================================ job service
def test_render_job_lifecycle_and_single_job_lock(monkeypatch):
    import app.agents as agents_pkg
    from app.services import render_jobs
    from app.services.locks import processing_lock

    release = threading.Event()

    def fake_render(plan_id, progress_cb=None, cancel=None):
        progress_cb(0.4)
        while not release.is_set():
            if cancel.is_set():
                from app.engine.renderer import RenderCancelled
                raise RenderCancelled("Rendering was cancelled")
            time.sleep(0.01)
        return {"status": "completed", "render": {}}

    fake = types.SimpleNamespace(render_plan=fake_render)
    monkeypatch.setitem(sys.modules, "app.agents.orchestrator", fake)
    monkeypatch.setattr(agents_pkg, "orchestrator", fake, raising=False)

    job = render_jobs.start("job1")
    with pytest.raises(render_jobs.JobBusyError):                       # one heavy job at a time
        render_jobs.start("job2")
    for _ in range(200):
        if job.progress >= 0.4:
            break
        time.sleep(0.01)
    assert job.state == "running" and job.to_dict()["progress_percent"] == 40.0
    assert render_jobs.is_active("job1")
    release.set()
    for _ in range(300):
        if not job.active:
            break
        time.sleep(0.01)
    assert job.state == "completed" and job.progress == 1.0
    assert not processing_lock.locked(), "the lock must be released when the job ends"

    release.clear()
    job = render_jobs.start("job3")
    assert render_jobs.cancel("job3") is True
    for _ in range(300):
        if not job.active:
            break
        time.sleep(0.01)
    assert job.state == "cancelled" and not processing_lock.locked()
    assert render_jobs.cancel("job3") is False                           # nothing left to cancel


def test_render_job_failure_is_reported_and_lock_released(monkeypatch):
    import app.agents as agents_pkg
    from app.services import render_jobs
    from app.services.locks import processing_lock

    def boom(plan_id, progress_cb=None, cancel=None):
        raise RuntimeError("FFmpeg failed while rendering clip 2")

    fake = types.SimpleNamespace(render_plan=boom)
    monkeypatch.setitem(sys.modules, "app.agents.orchestrator", fake)
    monkeypatch.setattr(agents_pkg, "orchestrator", fake, raising=False)
    job = render_jobs.start("job4")
    for _ in range(200):
        if not job.active:
            break
        time.sleep(0.01)
    assert job.state == "failed" and "clip 2" in job.error and not processing_lock.locked()


# ===================================================================== API
@pytest.fixture()
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("scenedetect")
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "outputs_dir", tmp_path / "outputs")
    settings.ensure_dirs()
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def real_videos(tmp_path):
    """Two real, tiny gameplay videos registered like /videos/register would."""
    from app.analyzers.video_analyzer import extract_metadata
    from app.services import analysis_service as an
    from app.services import file_service as fs

    ids = []
    for vid, name, audio in (("aaaaaaaaaaaa", "gameplay_01.mp4", True), ("bbbbbbbbbbbb", "gameplay_02.mp4", False)):
        path = make_video(tmp_path / name, 6, audio)
        fs.save_record({"id": vid, "role": "gameplay", "original_name": name, "path": str(path), "source": "local",
                        "created_at": fs.utc_now(), "thumbnails": [], "scenes": None, "metadata": extract_metadata(path)})
        an.save_gameplay({"video_id": vid, "source": {"original_name": name}, "created_at": fs.utc_now(),
                          "estimated_highlights": [{"id": "h1", "kind": "estimated_highlight", "start": 0.5, "end": 5.0,
                                                    "peak_time": 3.0, "score": 0.9, "reasons": ["motion"],
                                                    "confidence": "estimate"}]})
        ids.append(vid)
    return ids


def _wait_for(client, plan_id, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/plans/{plan_id}/render").json()
        job = status["job"]
        job_over = job is None or job["state"] not in ("queued", "running")
        if job_over and status["plan_status"] in ("completed", "failed", "failed_quality", "cancelled"):
            return status
        time.sleep(0.5)
    raise AssertionError("render did not finish in time")


@needs_ffmpeg
def test_api_render_flow(client, real_videos):
    r = client.post("/plans/generate", json={"instructions": "quick montage", "gameplay_ids": real_videos,
                                              "target_duration": 8, "quality": "test", "use_llm": False})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]

    # nothing rendered yet
    assert client.get(f"/plans/{pid}/output").status_code == 409
    assert client.post(f"/plans/{pid}/render/cancel").status_code == 409
    assert client.post("/plans/zzzzzzzzzzzz/render").status_code == 404

    r = client.post(f"/plans/{pid}/render")
    assert r.status_code == 202, r.text
    assert r.json()["state"] in ("queued", "running", "completed")
    status = _wait_for(client, pid)
    assert status["plan_status"] == "completed", status
    render = status["render"]
    assert render["quality_report"]["passed"] and render["resolution"] == "854x480"
    out = client.get(f"/plans/{pid}/output")
    assert out.status_code == 200 and out.content[4:8] == b"ftyp"

    # change the format at render time: 9:16 output
    r = client.post(f"/plans/{pid}/render", json={"format": "instagram"})
    assert r.status_code == 202, r.text
    status = _wait_for(client, pid)
    assert status["plan_status"] == "completed" and status["render"]["resolution"] == "480x854"

    # invalid overrides are rejected and nothing starts
    assert client.post(f"/plans/{pid}/render", json={"format": "tiktok"}).status_code == 422
    assert client.delete(f"/plans/{pid}?delete_output=true").status_code == 200
    assert not list(settings.outputs_dir.glob("*instagram*.mp4"))      # the deleted plan's file is gone


@needs_ffmpeg
def test_api_busy_server_returns_409(client, real_videos):
    from app.services.locks import processing_lock

    r = client.post("/plans/generate", json={"instructions": "quick montage", "gameplay_ids": real_videos,
                                              "target_duration": 8, "use_llm": False})
    pid = r.json()["id"]
    with processing_lock:                       # simulate another heavy job
        busy = client.post(f"/plans/{pid}/render")
    assert busy.status_code == 409 and "Another heavy job" in busy.json()["detail"]
    assert client.get(f"/plans/{pid}").json()["status"] == "draft"


def test_interrupted_renders_are_recovered_at_startup(client):
    from app.services import plan_service as plans

    plans.save_plan({"id": "cccccccccccc", "status": "rendering", "plan": {}, "render": None})
    assert plans.recover_interrupted() == 1
    rec = plans.load_plan("cccccccccccc")
    assert rec["status"] == "failed" and "interrupted" in rec["render"]["error"]
