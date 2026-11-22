"""Phase 7B tests: export presets (1080p/1440p/4K), HEVC, fps, quality levels, Intel QSV with CPU fallback.

Run:  python -m pytest -q tests/test_phase7b.py
(The render tests need FFmpeg and are skipped when it is missing. 4K tests use very short clips.)
"""
import json
import shutil
import subprocess

import pytest

from app.config import settings
from app.engine import encoders
from app.engine.plan_schema import PlanValidationError, validate_plan

HAS_FFMPEG = bool(shutil.which(settings.ffmpeg_path) and shutil.which(settings.ffprobe_path))
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg/ffprobe not installed")
FF = "ffmpeg"


def _sources(path="x/a.mp4", w=1280, h=720, fps=30.0):
    return {"aaaaaaaaaaaa": {"duration_seconds": 10.0, "has_audio": True, "path": str(path), "name": "a.mp4",
                             "width": w, "height": h, "fps": fps}}


def _plan(**output):
    return {"clips": [{"source": "aaaaaaaaaaaa", "start": 1, "end": 2.5}], "output": output}


# ------------------------------------------------------------------- sizes
def test_all_resolutions_and_both_orientations():
    assert encoders.output_size("youtube", "full") == (1920, 1080)
    assert encoders.output_size("youtube", "1440p") == (2560, 1440)
    assert encoders.output_size("youtube", "4k") == (3840, 2160)
    assert encoders.output_size("instagram", "4k") == (2160, 3840)
    assert encoders.output_size("instagram", "full") == (1080, 1920)
    assert encoders.output_size("instagram", "test") == (480, 854)
    with pytest.raises(ValueError):
        encoders.output_size("youtube", "8k")
    from app.engine import renderer

    assert renderer.OUTPUT_SIZES[("youtube", "full")] == (1920, 1080)          # old import path still works
    with pytest.raises(renderer.RenderError):
        renderer.output_size("tiktok", "full")


# ------------------------------------------------------------------- schema
def test_schema_accepts_new_output_settings_and_defaults_old_plans():
    p = validate_plan(_plan(quality="4k", fps=60, codec="hevc", encoder="qsv", quality_level="high"), _sources())
    assert p["output"] == {"format": "youtube", "quality": "4k", "fit": "crop", "fps": 60,
                           "codec": "hevc", "encoder": "qsv", "quality_level": "high"}
    old = validate_plan(_plan(format="instagram", quality="full"), _sources())["output"]
    assert (old["codec"], old["encoder"], old["quality_level"]) == ("h264", "auto", "standard")
    for bad in ({"quality": "8k"}, {"codec": "av1"}, {"encoder": "nvenc"}, {"quality_level": "ultra"}, {"fps": 120}):
        with pytest.raises(PlanValidationError):
            validate_plan(_plan(**bad), _sources())


# ---------------------------------------------------------- encoder choice
@pytest.fixture()
def fake_ffmpeg(monkeypatch):
    """Control which encoders exist and which really work, without needing real hardware."""
    state = {"listed": {"libx264", "libx265", "h264_qsv", "hevc_qsv"}, "usable": set()}
    monkeypatch.setattr(encoders, "encoder_listed", lambda ff, name: name in state["listed"])
    monkeypatch.setattr(encoders, "probe_encoder", lambda ff, name: name in state["usable"])
    return state


def test_preview_is_always_fast_cpu_h264(fake_ffmpeg):
    fake_ffmpeg["usable"] |= {"h264_qsv", "hevc_qsv"}
    c = encoders.choose_encoder("ffmpeg", "hevc", "qsv", "test", "high")
    assert c.name == "libx264" and not c.hardware and "ultrafast" in c.args
    assert any("preview" in n for n in c.notes)


def test_auto_uses_quick_sync_for_4k_only_when_it_really_works(fake_ffmpeg):
    c = encoders.choose_encoder("ffmpeg", "h264", "auto", "4k", "standard")
    assert c.name == "libx264" and any("4K on the CPU" in n for n in c.notes)       # listed but not usable
    fake_ffmpeg["usable"].add("h264_qsv")
    c = encoders.choose_encoder("ffmpeg", "h264", "auto", "4k", "standard")
    assert c.name == "h264_qsv" and c.hardware and "-global_quality" in c.args
    c = encoders.choose_encoder("ffmpeg", "h264", "auto", "full", "standard")      # 1080p stays on the CPU
    assert c.name == "libx264" and not c.hardware


def test_explicit_qsv_falls_back_with_a_note(fake_ffmpeg):
    c = encoders.choose_encoder("ffmpeg", "h264", "qsv", "full", "standard")
    assert c.name == "libx264" and any("Quick Sync" in n and "CPU" in n for n in c.notes)
    fake_ffmpeg["usable"].add("h264_qsv")
    assert encoders.choose_encoder("ffmpeg", "h264", "qsv", "full", "standard").hardware


def test_hevc_choices(fake_ffmpeg):
    c = encoders.choose_encoder("ffmpeg", "hevc", "cpu", "full", "standard")
    assert c.name == "libx265" and "hvc1" in c.args and "yuv420p" in c.args
    fake_ffmpeg["usable"].add("hevc_qsv")
    c = encoders.choose_encoder("ffmpeg", "hevc", "auto", "full", "standard")
    assert c.name == "hevc_qsv" and "hvc1" in c.args
    fake_ffmpeg["listed"] = {"libx264"}
    c = encoders.choose_encoder("ffmpeg", "hevc", "auto", "full", "standard")
    assert c.name == "libx264" and any("no HEVC encoder" in n for n in c.notes)


def test_quality_levels_change_the_crf_and_threads_are_respected(fake_ffmpeg, monkeypatch):
    def crf(level):
        a = encoders.choose_encoder("ffmpeg", "h264", "cpu", "full", level).args
        return int(a[a.index("-crf") + 1])

    assert crf("high") < crf("standard") < crf("fast")
    monkeypatch.setattr(settings, "render_threads", 2)
    a = encoders.choose_encoder("ffmpeg", "h264", "cpu", "full", "standard").args
    assert a[-2:] == ["-threads", "2"]


def test_size_estimate_and_honest_scaling_notes():
    small = encoders.estimate_size_mb(1920, 1080, 30, 60, "h264", "standard")
    assert encoders.estimate_size_mb(3840, 2160, 30, 60, "h264", "standard") > 3 * small
    assert encoders.estimate_size_mb(1920, 1080, 30, 60, "hevc", "standard") < small
    assert encoders.estimate_size_mb(1920, 1080, 60, 60, "h264", "standard") > small
    clips = [{"source": "aaaaaaaaaaaa"}]
    notes = encoders.upscale_notes(clips, _sources(w=1920, h=1080, fps=30), 3840, 2160, 60, "crop")
    assert any("scaled up about x2.00" in n for n in notes) and any("30 fps" in n and "60" in n for n in notes)
    assert encoders.upscale_notes(clips, _sources(w=3840, h=2160, fps=60), 3840, 2160, 60, "crop") == []
    assert encoders.upscale_notes(clips, _sources(w=1920, h=1080, fps=30), 480, 854, 30, "pad") == []


# --------------------------------------------------------------- real renders
def _ffmpeg(*args):
    subprocess.run([settings.ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error", *args], check=True)


def _probe(path):
    r = subprocess.run([settings.ffprobe_path, "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=codec_name,width,height,r_frame_rate:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    data = json.loads(r.stdout)
    num, den = data["streams"][0]["r_frame_rate"].split("/")
    return data["streams"][0]["codec_name"], data["streams"][0]["width"], data["streams"][0]["height"], \
        float(num) / float(den), float(data["format"]["duration"])


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("media7b")
    video = d / "game.mp4"
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=10", "-f", "lavfi", "-i", "sine=frequency=330:duration=10",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video))
    return video


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "outputs_dir", tmp_path / "outputs")
    settings.ensure_dirs()


def _render(media, **output):
    from app.agents import quality_agent
    from app.engine import renderer

    sources = _sources(media)
    plan = validate_plan(_plan(**output), sources)
    res = renderer.render(plan, sources, "p7" + "0" * 10)
    report = quality_agent.check_output(res["output_path"], {"width": res["width"], "height": res["height"],
                                                             "duration": res["expected_duration"], "has_audio": True})
    return res, report


@needs_ffmpeg
def test_render_4k_youtube_and_vertical(env, media):
    res, report = _render(media, quality="4k")
    assert report["passed"], report
    codec, w, h, _, _ = _probe(res["output_path"])
    assert (codec, w, h) == ("h264", 3840, 2160)
    assert any("scaled up" in n for n in res["notes"])                          # 1280x720 source -> honest warning
    assert "4k" in res["output_path"] and res["size_mb"] > 0
    res, report = _render(media, quality="4k", format="instagram")
    assert report["passed"], report
    assert _probe(res["output_path"])[1:3] == (2160, 3840)


@needs_ffmpeg
def test_render_hevc_1080p_60fps(env, media):
    res, report = _render(media, quality="full", codec="hevc", encoder="cpu", fps=60, quality_level="fast")
    assert report["passed"], report
    codec, w, h, fps, _ = _probe(res["output_path"])
    assert (codec, w, h, round(fps)) == ("hevc", 1920, 1080, 60)
    assert "HEVC" in res["encoder"]
    assert any("30 fps" in n for n in res["notes"])                              # 30 fps source -> 60 fps: honest note


@needs_ffmpeg
def test_requested_quick_sync_falls_back_to_cpu_when_unavailable(env, media):
    res, report = _render(media, quality="full", encoder="qsv")
    assert report["passed"], report
    assert "CPU" in res["encoder"] and _probe(res["output_path"])[0] == "h264"
    assert any("Quick Sync" in n for n in res["notes"])


@needs_ffmpeg
def test_hardware_failure_mid_render_retries_on_the_cpu(env, media, monkeypatch):
    """Simulate 'QSV passed the probe but fails for real': the renderer must retry on the CPU."""
    real = encoders.choose_encoder

    def pretend_hw(ffmpeg, codec, encoder, quality, level, fps=30):
        if encoder == "qsv":
            return encoders.EncoderChoice("h264_qsv", ["-c:v", "h264_qsv", "-global_quality", "23"], True,
                                          "H.264 (Intel QSV hardware)")
        return real(ffmpeg, codec, encoder, quality, level, fps)

    monkeypatch.setattr(encoders, "choose_encoder", pretend_hw)
    res, report = _render(media, quality="full", encoder="qsv")
    assert report["passed"], report
    assert res["encoder"] == "H.264 (CPU)"
    assert any("failed on this computer" in n for n in res["notes"])


@needs_ffmpeg
def test_render_refuses_when_the_export_cannot_fit_on_disk(env, media, monkeypatch):
    from app.engine import renderer

    monkeypatch.setattr(encoders, "estimate_size_mb", lambda *a, **k: 10 ** 9)
    sources = _sources(media)
    plan = validate_plan(_plan(quality="full"), sources)
    with pytest.raises(renderer.RenderError, match="free disk space"):
        renderer.render(plan, sources, "p7" + "1" * 10)
    assert not list(settings.temp_dir.glob("*.render.*"))                        # nothing left behind


# ----------------------------------------------------------------- API
@pytest.fixture()
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "outputs_dir", tmp_path / "outputs")
    settings.ensure_dirs()
    from app.main import app

    with TestClient(app) as c:
        yield c


@needs_ffmpeg
def test_export_options_and_estimate_endpoints(client):
    r = client.get("/export/options")
    assert r.status_code == 200, r.text
    data = r.json()
    ids = [q["id"] for q in data["qualities"]]
    assert ids == ["test", "full", "1440p", "4k"]
    four_k = next(q for q in data["qualities"] if q["id"] == "4k")
    assert four_k["youtube"] == "3840x2160" and four_k["instagram"] == "2160x3840"
    assert {c["id"] for c in data["codecs"]} == {"h264", "hevc"}
    assert "usable" in data["encoders"]["h264_qsv"] and isinstance(data["intel_quick_sync"]["h264"], bool)

    r = client.post("/export/estimate", json={"seconds": 60, "quality": "4k", "fps": 60, "codec": "hevc"})
    assert r.status_code == 200, r.text
    est = r.json()
    assert est["resolution"] == "3840x2160" and est["estimated_mb"] > 100 and "fits" in est
    assert client.post("/export/estimate", json={"seconds": 60, "quality": "8k"}).status_code == 422


def test_render_request_rejects_bad_export_values(client):
    for body in ({"fps": 120}, {"codec": "av1"}, {"encoder": "nvenc"}, {"quality_level": "ultra"}):
        assert client.post("/plans/aaaaaaaaaaaa/render", json=body).status_code == 422
