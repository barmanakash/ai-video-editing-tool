"""Phase 3 tests (gameplay highlight candidates). Run:  python -m pytest -q tests/test_phase3.py"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import settings

HAS_FFMPEG = bool(shutil.which(settings.ffmpeg_path) and shutil.which(settings.ffprobe_path))
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg/ffprobe not installed")


def _make_action_video(out: Path, audio: bool = True) -> Path:
    """20 s clip: calm 0-8 s, noisy + loud 'action' 8-12 s, calm 12-20 s."""
    cmd = [
        settings.ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=0x303840:s=320x180:r=30:d=8",
        "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=4,noise=alls=60:allf=t",
        "-f", "lavfi", "-i", "color=c=0x303840:s=320x180:r=30:d=8",
    ]
    if audio:
        cmd += ["-f", "lavfi", "-i",
                "aevalsrc='if(between(t,8,12),0.8*sin(2*PI*220*t)*sin(2*PI*9*t),0.01*sin(2*PI*220*t))':s=16000:d=20"]
    cmd += ["-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]", "-map", "[v]"]
    if audio:
        cmd += ["-map", "3:a", "-c:a", "aac"]
    cmd += ["-pix_fmt", "yuv420p", "-shortest", str(out)]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


@pytest.fixture(scope="module")
def action_video(tmp_path_factory) -> Path:
    return _make_action_video(tmp_path_factory.mktemp("media") / "action.mp4")


@pytest.fixture(scope="module")
def silent_video(tmp_path_factory) -> Path:
    return _make_action_video(tmp_path_factory.mktemp("media") / "silent.mp4", audio=False)


def _record(path: Path, audio=True):
    return {
        "id": "abcdef123456",
        "original_name": path.name,
        "path": str(path),
        "metadata": {
            "duration_seconds": 20.0,
            "video": {"width": 320, "height": 180, "fps": 30.0, "aspect_ratio": "16:9", "orientation": "landscape"},
            "audio": {"codec": "aac"} if audio else None,
        },
        "scenes": {"scenes": [
            {"index": 0, "start": 0.0, "end": 8.0, "duration": 8.0},
            {"index": 1, "start": 8.0, "end": 12.0, "duration": 4.0},
            {"index": 2, "start": 12.0, "end": 20.0, "duration": 8.0},
        ]},
    }


@needs_ffmpeg
def test_highlight_lands_on_the_action(action_video):
    from app.agents.gameplay_agent import analyze_gameplay

    result = analyze_gameplay(_record(action_video))
    json.dumps(result)  # must be serialisable
    hl = result["estimated_highlights"]
    assert hl, "expected at least one estimated highlight"
    best = max(hl, key=lambda h: h["score"])
    assert 7.0 <= best["peak_time"] <= 13.5, best

    for h in hl:  # honest labelling + sane windows
        assert h["kind"] == "estimated_highlight"
        assert h["confidence"] == "estimate"
        assert 0.0 <= h["start"] < h["end"] <= 20.0
        assert h["reasons"]
    # Peaks are separated
    peaks = sorted(h["peak_time"] for h in hl)
    assert all(b - a >= 6 for a, b in zip(peaks, peaks[1:]))


@needs_ffmpeg
def test_detected_facts_are_separate_from_estimates(action_video):
    from app.agents.gameplay_agent import analyze_gameplay

    r = analyze_gameplay(_record(action_video))
    assert r["detected"]["scene_cuts"] == [8.0, 12.0]
    assert r["detected"]["scene_cuts_available"] is True
    assert any(7 <= m["time"] <= 13 for m in r["detected"]["loud_moments"])
    assert r["semantic_events"] == [] and r["semantic_detectors_registered"] == []
    assert any("do NOT mean a fight" in s for s in r["limitations"])
    assert r["analysis_settings"]["audio_used"] is True


@needs_ffmpeg
def test_works_without_audio(silent_video):
    from app.agents.gameplay_agent import analyze_gameplay

    r = analyze_gameplay(_record(silent_video, audio=False))
    assert r["analysis_settings"]["audio_used"] is False
    assert r["detected"]["loud_moments"] == []
    assert r["estimated_highlights"]
    best = max(r["estimated_highlights"], key=lambda h: h["score"])
    assert 7.0 <= best["peak_time"] <= 13.5


@needs_ffmpeg
def test_truncation_is_flagged(action_video):
    from app.agents.gameplay_agent import analyze_gameplay

    r = analyze_gameplay(_record(action_video), max_seconds=10)
    assert r["source"]["truncated"] is True
    assert r["source"]["analyzed_seconds"] == 10.0
    assert any("first 10" in s for s in r["limitations"])
    assert all(h["end"] <= 10.0 for h in r["estimated_highlights"])


@needs_ffmpeg
def test_semantic_detector_plugin_is_labelled_and_boosts(action_video):
    from app.agents.gameplay_agent import analyze_gameplay
    from app.analyzers import event_detectors as ed

    class Fake:
        name = "fake_fight"

        def detect(self, video_path, record):
            return [{"start": 2.0, "end": 4.0, "label": "fight", "confidence": 1.0}]

    class Broken:
        name = "broken"

        def detect(self, video_path, record):
            raise RuntimeError("boom")

    ed.register_detector(Fake())
    ed.register_detector(Broken())
    try:
        r = analyze_gameplay(_record(action_video))
    finally:
        ed.clear_detectors()
    assert r["semantic_events"][0]["kind"] == "semantic_event"
    assert r["semantic_events"][0]["label"] == "fight"
    assert any("broken" in e for e in r["detector_errors"])  # one bad detector never breaks analysis
    assert r["estimated_highlights"]


def test_missing_file_is_reported(tmp_path):
    from app.agents.gameplay_agent import GameplayAnalysisError, analyze_gameplay

    with pytest.raises(GameplayAnalysisError):
        analyze_gameplay(_record(tmp_path / "gone.mp4"))


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
def test_gameplay_api_flow(client, action_video):
    r = client.post("/videos/register", json={"path": str(action_video), "role": "gameplay"})
    assert r.status_code == 200, r.text
    vid = r.json()["id"]

    r = client.post(f"/gameplay/{vid}/analyze", params={"top_k": 3})
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["estimated_highlights"] and len(first["estimated_highlights"]) <= 3
    assert first["detected"]["scene_cuts_available"] is True  # scene detection ran automatically

    assert client.get("/gameplay/analyses").json()["count"] == 1
    assert client.get(f"/gameplay/{vid}/highlights").json()["video_id"] == vid
    assert (settings.analysis_dir / vid / "gameplay.json").is_file()

    # cached unless force
    assert client.post(f"/gameplay/{vid}/analyze").json()["created_at"] == first["created_at"]
    assert client.post(f"/gameplay/{vid}/analyze", params={"force": True}).status_code == 200


def test_gameplay_api_unknown_video(client):
    assert client.post("/gameplay/aaaaaaaaaaaa/analyze").status_code == 404
    assert client.get("/gameplay/aaaaaaaaaaaa/highlights").status_code == 404
