"""Phase 7A tests: speed ramps, beat/cut punch effects, grading presets, titles.

Run:  python -m pytest -q tests/test_phase7a.py
(The render tests need FFmpeg and are skipped when it is missing.)
"""
import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import settings
from app.engine import effects_engine, speed_ramp, text_overlay
from app.engine.plan_schema import PlanValidationError, effective_duration, validate_plan

HAS_FFMPEG = bool(shutil.which(settings.ffmpeg_path) and shutil.which(settings.ffprobe_path))
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg/ffprobe not installed")


def _sources(path="x/a.mp4", has_audio=True):
    return {"aaaaaaaaaaaa": {"duration_seconds": 40.0, "has_audio": has_audio, "path": str(path), "name": "a.mp4"}}


def _plan(clips, **extra):
    n = len(clips)
    return {"clips": clips, "transitions": extra.pop("transitions", ["cut"] * (n - 1)), **extra}


RAMP = {"source": "aaaaaaaaaaaa", "start": 10.0, "end": 18.0, "speed": 0.4, "effect": "speed_ramp", "peak": 14.0}


# --------------------------------------------------------------- speed ramp
def test_ramp_pieces_are_contiguous_and_slowest_at_the_peak():
    pieces = speed_ramp.segments(RAMP)
    assert len(pieces) == 5
    assert pieces[0][0] == 10.0 and pieces[-1][1] == 18.0
    for (a1, b1, _), (a2, b2, _) in zip(pieces, pieces[1:]):
        assert b1 == pytest.approx(a2, abs=0.002)           # no gaps, no overlap
    assert [p[2] for p in pieces] == [1.0, 0.7, 0.4, 0.7, 1.0]
    slow = pieces[2]
    assert slow[0] <= 14.0 <= slow[1]                         # the slowest piece contains the peak


def test_ramp_is_longer_than_normal_but_shorter_than_constant_slow_motion():
    d = effective_duration(RAMP)
    assert 8.0 < d < 8.0 / 0.4
    assert d == pytest.approx(sum((b - a) / s for a, b, s in speed_ramp.segments(RAMP)))


def test_ramp_near_the_clip_edge_stays_inside_the_clip():
    for peak in (10.0, 10.2, 17.9, 18.0, None):
        clip = {**RAMP, "peak": peak}
        pieces = speed_ramp.segments(clip)
        assert pieces[0][0] >= 10.0 and pieces[-1][1] <= 18.0 + 1e-6
        assert all(b > a for a, b, _ in pieces)


def test_tiny_clip_ramp_still_works():
    clip = {**RAMP, "start": 5.0, "end": 5.6, "peak": 5.3}
    assert speed_ramp.segments(clip)
    assert effective_duration(clip) > 0.6


# ------------------------------------------------------------------- schema
def test_schema_accepts_ramp_with_defaults_and_clamps_peak():
    p = validate_plan(_plan([{"source": "aaaaaaaaaaaa", "start": 10, "end": 18, "effect": "speed_ramp"}]), _sources())
    c = p["clips"][0]
    assert c["speed"] == 0.4 and c["peak"] == 14.0
    p = validate_plan(_plan([{**RAMP, "peak": 3.0}]), _sources())
    assert p["clips"][0]["peak"] == 10.0                       # clamped into the clip
    assert p["total_duration_estimate"] == pytest.approx(effective_duration(p["clips"][0]), abs=0.01)


def test_schema_rejects_bad_ramp_and_unknown_look_settings():
    bad = [
        _plan([{**RAMP, "speed": 1.0}]),
        _plan([RAMP], color={"preset": "$(evil)"}),
        _plan([RAMP], fx={"punch": "always"}),
        _plan([RAMP], titles=[{"text": "x", "position": "diagonal"}]),
        _plan([RAMP], titles=[{"text": ":::'''%%%"}]),           # nothing printable left
        _plan([RAMP], titles=[{"text": "t"}] * 7),
    ]
    for p in bad:
        with pytest.raises(PlanValidationError):
            validate_plan(p, _sources())


def test_titles_are_sanitised():
    p = validate_plan(_plan([RAMP], titles=[{"text": "EPIC: it's 100% 'wild' \\ <b>fights</b>; rm -rf /"}]), _sources())
    text = p["titles"][0]["text"]
    for ch in ":'%\\<>;":
        assert ch not in text
    assert "EPIC" in text and len(text) <= 60


def test_old_plans_still_validate_and_get_defaults():
    p = validate_plan(_plan([{"source": "aaaaaaaaaaaa", "start": 1, "end": 5}]), _sources())
    assert p["fx"] == {"punch": "off", "zoom_punch": True, "flash": False, "shake": False}
    assert p["titles"] == [] and p["color"]["preset"] == "none"


# ----------------------------------------------------------- filter building
def test_pulse_and_punch_filters():
    assert effects_engine.thin_times([1.0, 1.2, 1.7, 2.4], 0.55) == [1.0, 1.7, 2.4]
    expr = effects_engine.pulse_expr([1.0, 2.0])
    assert expr.count("exp(") == 2 and expr.startswith("(") and expr.endswith(")")
    assert effects_engine.punch_chain([], 1920, 1080, True, True, True) == []
    assert effects_engine.punch_chain([1.0], 1920, 1080, False, False, False) == []
    chain = ",".join(effects_engine.punch_chain([1.0, 2.0], 1280, 720, True, True, True))
    assert "eval=frame" in chain and "crop=1280:720" in chain and "brightness=" in chain
    for name in ("none", "clean", "vibrant", "cinematic"):
        assert isinstance(effects_engine.preset_filters(name), list)
    assert effects_engine.preset_filters("cinematic") and not effects_engine.preset_filters("none")


def test_graph_expands_ramp_into_pieces_without_extra_cuts_for_punch():
    from app.engine import renderer

    plan = validate_plan(_plan(
        [RAMP, {"source": "aaaaaaaaaaaa", "start": 20, "end": 24}],
        transitions=["crossfade"], fx={"punch": "cuts", "zoom_punch": True, "flash": True}, color={"preset": "cinematic"},
    ), _sources())
    pieces, trans, internal = renderer.expand_pieces(plan)
    assert len(pieces) == 6 and trans == ["cut"] * 4 + ["crossfade"]
    assert internal == [True] * 4 + [False]
    built = renderer.build_graph(plan, _sources(), 854, 480)
    assert built.input_args.count("-i") == 6
    import re
    punch_starts = set(re.findall(r"between\(t,([\d.]+),", built.graph))
    assert len(punch_starts) == 1                              # ONE punch time: the real cut, not the 4 invisible joins
    assert "vignette" in built.graph and "curves" in built.graph
    assert built.total == pytest.approx(plan["total_duration_estimate"] - 0.0, abs=0.6)   # crossfade overlap only


# -------------------------------------------------------------- real renders
def _ffmpeg(*args):
    subprocess.run([settings.ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error", *args], check=True)


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    video = d / "game.mp4"
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=40",
            "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=44100:duration=40",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video))
    music = d / "music.wav"                                     # a hit every half second
    _ffmpeg("-f", "lavfi", "-i", "aevalsrc='if(lt(mod(t,0.5),0.08),0.9*sin(2*PI*180*t),0.0)':s=44100:d=20", str(music))
    return {"video": video, "music": music}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "outputs_dir", tmp_path / "outputs")
    settings.ensure_dirs()
    text_overlay.drawtext_available.cache_clear()


def _render(plan, media, **kw):
    from app.agents import quality_agent
    from app.engine import renderer

    sources = {"aaaaaaaaaaaa": {"duration_seconds": 40.0, "has_audio": True, "path": str(media["video"]), "name": "game.mp4"}}
    plan = validate_plan(plan, sources)
    res = renderer.render(plan, sources, "p1" + "0" * 10)
    report = quality_agent.check_output(
        res["output_path"], {"width": res["width"], "height": res["height"],
                             "duration": res["expected_duration"], "has_audio": True})
    return plan, res, report


@needs_ffmpeg
def test_render_speed_ramp_has_expected_length(env, media):
    clip = {"source": "aaaaaaaaaaaa", "start": 10, "end": 18, "effect": "speed_ramp", "speed": 0.4, "peak": 14}
    plan, res, report = _render(_plan([clip]), media)
    assert report["passed"], report
    assert res["expected_duration"] == pytest.approx(effective_duration(plan["clips"][0]), abs=0.1)
    assert res["expected_duration"] > 9.0                        # longer than the 8 s of source


@needs_ffmpeg
def test_render_full_look_with_cuts_music_punches_grade_and_titles(env, media):
    clips = [
        {"source": "aaaaaaaaaaaa", "start": 2, "end": 6},
        {"source": "aaaaaaaaaaaa", "start": 10, "end": 16, "effect": "speed_ramp", "speed": 0.4},
        {"source": "aaaaaaaaaaaa", "start": 20, "end": 24, "effect": "zoom_in"},
    ]
    plan = _plan(clips, transitions=["crossfade", "cut"],
                 audio={"use_uploaded_music": True, "music_path": str(media["music"]), "music_volume": 0.8},
                 color={"preset": "cinematic", "contrast": 1.05},
                 fx={"punch": "beats", "zoom_punch": True, "flash": True, "shake": True},
                 titles=[{"text": "EPIC FIGHTS", "position": "center", "at": "start", "duration": 2},
                         {"text": "Thanks for watching", "position": "lower", "size": "small", "at": "end", "duration": 2}])
    plan, res, report = _render(plan, media)
    assert report["passed"], report
    assert res["snapped_cuts"] >= 0
    assert not any("titles skipped" in n for n in res["notes"]) or not text_overlay.drawtext_available()


@needs_ffmpeg
def test_render_vertical_pad_and_cut_punches_without_music(env, media):
    clips = [{"source": "aaaaaaaaaaaa", "start": 1, "end": 5}, {"source": "aaaaaaaaaaaa", "start": 8, "end": 12}]
    plan = _plan(clips, transitions=["fadewhite"], output={"format": "instagram", "fit": "pad"},
                 fx={"punch": "beats", "flash": True}, color={"preset": "vibrant"})
    plan, res, report = _render(plan, media)
    assert report["passed"], report
    assert (res["width"], res["height"]) == (480, 854)
    assert any("no music beats" in n for n in res["notes"])         # asked for beats, had no music: fell back to cuts


# ------------------------------------------------- look options from the API
def test_build_look_cleans_titles_and_picks_punch_mode():
    from app.api_plan import PlanRequest, _build_look

    req = PlanRequest(instructions="make a montage", gameplay_ids=["a"], title="EPIC: it's 100%", subtitle=":::'%",
                      end_text="Thanks!", grade="vibrant", music_path="C:/m.mp3", flash=True)
    look = _build_look(req)
    assert look["preset"] == "vibrant"
    assert look["fx"] == {"punch": "beats", "zoom_punch": True, "flash": True, "shake": False}   # auto + music = beats
    assert [(t["position"], t["at"]) for t in look["titles"]] == [("center", "start"), ("center", "end")]   # empty subtitle skipped
    for t in look["titles"]:
        assert not set(":'%") & set(t["text"])
    plain = _build_look(PlanRequest(instructions="make a montage", gameplay_ids=["a"]))
    assert plain["fx"]["punch"] == "cuts" and "preset" not in plain and plain["titles"] == []


def test_planner_applies_the_users_look_over_the_models():
    from app.agents.editing_agent import PlannerContext, generate_plan

    sources = {"aaaaaaaaaaaa": {"duration_seconds": 60.0, "has_audio": True, "path": "x", "name": "a.mp4"}}
    ctx = PlannerContext(
        instructions="montage", sources=sources, analyses={}, profile=None,
        output={"format": "youtube", "quality": "test", "fit": "crop"}, target_duration=10.0,
        audio={"use_uploaded_music": False, "music_path": None, "music_volume": 0.7},
        look={"preset": "vibrant", "fx": {"punch": "off"},
              "titles": [{"text": "HELLO", "position": "center", "size": "large", "at": "start", "duration": 2.5}]},
    )
    reply = '{"clips":[{"source":"v1","start":5,"end":12,"effect":"speed_ramp","speed":0.4,"peak":8}],"color":{"preset":"clean"}}'
    plan, meta = generate_plan(ctx, llm=lambda s, u: reply)
    assert plan["color"]["preset"] == "vibrant"                  # the user's choice beats the model's "clean"
    assert plan["fx"]["punch"] == "off" and plan["titles"][0]["text"] == "HELLO"
    assert plan["clips"][0]["effect"] == "speed_ramp" and plan["clips"][0]["peak"] == 8.0
