"""Phase 2 tests (reference style profile). Run:  python -m pytest -q"""
import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import settings

HAS_FFMPEG = bool(shutil.which(settings.ffmpeg_path) and shutil.which(settings.ffprobe_path))
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg/ffprobe not installed")


@pytest.fixture(scope="module")
def click_video(tmp_path_factory) -> Path:
    """9 s, 3 colour shots (cuts at 3 s and 6 s) + a click every 0.5 s (120 BPM)."""
    out = tmp_path_factory.mktemp("media") / "clicks.mp4"
    cmd = [
        settings.ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=red:s=640x360:r=30:d=3",
        "-f", "lavfi", "-i", "color=c=blue:s=640x360:r=30:d=3",
        "-f", "lavfi", "-i", "color=c=green:s=640x360:r=30:d=3",
        "-f", "lavfi", "-i", "aevalsrc='if(lt(mod(t,0.5),0.02),0.8*sin(2*PI*1000*t),0)':s=16000:d=9",
        "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
        "-map", "[v]", "-map", "3:a", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def _record(path: Path, cuts, audio=True):
    edges = [0.0] + list(cuts) + [9.0]
    scenes = [
        {"index": i, "start": edges[i], "end": edges[i + 1], "duration": round(edges[i + 1] - edges[i], 3)}
        for i in range(len(edges) - 1)
    ]
    return {
        "id": "abcdef123456",
        "original_name": path.name,
        "path": str(path),
        "metadata": {
            "duration_seconds": 9.0,
            "video": {"width": 640, "height": 360, "fps": 30.0, "aspect_ratio": "16:9", "orientation": "landscape"},
            "audio": {"codec": "aac"} if audio else None,
        },
        "scenes": {"settings": {}, "scenes": scenes},
    }


@needs_ffmpeg
def test_audio_onsets_and_tempo(click_video):
    from app.analyzers.audio_analyzer import analyze_audio

    summary, onsets = analyze_audio(click_video, True, 300)
    assert summary["analyzed"] is True
    assert 14 <= summary["onset_count"] <= 20  # about 17-18 clicks in 9 s
    assert len(onsets) == summary["onset_count"]
    bpm = summary["estimated_bpm"]
    assert abs(bpm - 120) < 6 or abs(bpm - 60) < 4  # 120 BPM, or its half-tempo


@needs_ffmpeg
def test_audio_missing_is_handled(click_video):
    from app.analyzers.audio_analyzer import analyze_audio

    summary, onsets = analyze_audio(click_video, False, 300)
    assert summary == {"present": False} and len(onsets) == 0


@needs_ffmpeg
def test_frame_analysis_basic(click_video):
    from app.analyzers.motion_analyzer import analyze_frames

    r = analyze_frames(click_video, 640, 360, 30.0, 9.0, 300)
    assert r["analysis_resolution"] == "160x90"
    assert 8.5 <= r["analyzed_seconds"] <= 9.5
    for key in ("color", "motion", "transitions", "slow_motion"):
        assert key in r
    assert r["slow_motion"]["likely_used"] is False


@needs_ffmpeg
def test_profile_structure_and_json(click_video):
    import json
    from app.agents.reference_agent import build_reference_profile

    p = build_reference_profile(_record(click_video, [3.0, 6.0]))
    json.dumps(p)  # must be serialisable
    assert p["pacing"]["scene_count"] == 3
    assert p["pacing"]["average_scene_duration"] == 3.0
    assert p["format"]["orientation"] == "landscape"
    assert p["audio"]["analyzed"] is True
    assert p["style_tags"] and p["summary"] and p["limitations"]
    assert p["planner_hints"]["clip_length_seconds"]["target"] == 3.0


@needs_ffmpeg
def test_cut_audio_sync_detects_on_and_off_beat(click_video):
    from app.agents.reference_agent import build_reference_profile

    on = build_reference_profile(_record(click_video, [1.5, 3.0, 4.5, 6.0, 7.5]))
    off = build_reference_profile(_record(click_video, [1.25, 2.75, 4.25, 5.75, 7.25]))
    assert on["rhythm"]["cuts_synced_to_audio"] is True
    assert off["rhythm"]["cuts_synced_to_audio"] is False


@needs_ffmpeg
def test_truncation_flagged(click_video):
    from app.agents.reference_agent import build_reference_profile

    p = build_reference_profile(_record(click_video, [3.0, 6.0], audio=False), max_seconds=5)
    assert p["source"]["truncated"] is True
    assert p["audio"] == {"present": False}
    assert p["rhythm"]["available"] is False


@needs_ffmpeg
def test_profile_requires_scene_detection(click_video):
    from app.agents.reference_agent import ReferenceAnalysisError, build_reference_profile

    rec = _record(click_video, [3.0, 6.0])
    rec["scenes"] = None
    with pytest.raises(ReferenceAnalysisError):
        build_reference_profile(rec)


# ----------------------------------------------------------------- API flow
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


@needs_ffmpeg
def test_reference_api_flow(client, click_video):
    r = client.post("/videos/register", json={"path": str(click_video), "role": "reference"})
    assert r.status_code == 200, r.text
    vid = r.json()["id"]

    r = client.post(f"/reference/{vid}/analyze", params={"name": "Test style"})
    assert r.status_code == 200, r.text
    profile = r.json()
    assert profile["name"] == "Test style"
    assert profile["pacing"]["scene_count"] == 3

    # Saved and reusable
    assert client.get("/reference/profiles").json()["count"] == 1
    assert client.get(f"/reference/profiles/{vid}").json()["id"] == vid
    assert (settings.reference_profiles_dir / f"{vid}.json").is_file()

    # Second call returns the saved profile (same timestamp) unless force=true
    again = client.post(f"/reference/{vid}/analyze").json()
    assert again["created_at"] == profile["created_at"]

    assert client.delete(f"/reference/profiles/{vid}").status_code == 200
    assert client.get(f"/reference/profiles/{vid}").status_code == 404


def test_reference_api_unknown_video(client):
    assert client.post("/reference/aaaaaaaaaaaa/analyze").status_code == 404
    assert client.get("/reference/profiles/aaaaaaaaaaaa").status_code == 404
