"""Phase 1 tests. Run:  pytest -q

Tests that need FFmpeg are skipped automatically if it is not installed.
"""
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings

HAS_FFMPEG = bool(shutil.which(settings.ffmpeg_path) and shutil.which(settings.ffprobe_path))
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg/ffprobe not installed")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "outputs_dir", tmp_path / "outputs")
    settings.ensure_dirs()
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def sample_video(tmp_path) -> Path:
    """9 s, 320x240, three solid-colour shots => 2 hard cuts => 3 scenes."""
    out = tmp_path / "sample.mp4"
    cmd = [
        settings.ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=red:s=320x240:r=24:d=3",
        "-f", "lavfi", "-i", "color=c=blue:s=320x240:r=24:d=3",
        "-f", "lavfi", "-i", "color=c=green:s=320x240:r=24:d=3",
        "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
        "-map", "[v]", "-pix_fmt", "yuv420p", str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def test_health_returns_expected_keys(client):
    data = client.get("/health").json()
    for key in ("ok", "python", "ffmpeg", "ffprobe", "ollama", "disk", "issues"):
        assert key in data


def test_register_rejects_missing_file(client, tmp_path):
    r = client.post("/videos/register", json={"path": str(tmp_path / "nope.mp4"), "role": "gameplay"})
    assert r.status_code == 400


def test_register_rejects_bad_extension(client, tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("hello")
    r = client.post("/videos/register", json={"path": str(f), "role": "gameplay"})
    assert r.status_code == 400


def test_register_rejects_bad_role(client, tmp_path):
    f = tmp_path / "x.mp4"
    f.write_bytes(b"123")
    r = client.post("/videos/register", json={"path": str(f), "role": "hacker"})
    assert r.status_code == 400


def test_upload_rejects_bad_extension(client):
    r = client.post("/videos/upload", files={"file": ("virus.exe", b"abc")}, data={"role": "gameplay"})
    assert r.status_code == 400


def test_unknown_video_id_is_404(client):
    assert client.get("/videos/aaaaaaaaaaaa").status_code == 404
    assert client.get("/videos/not-a-valid-id").status_code == 404


@needs_ffmpeg
def test_register_rejects_corrupt_video(client, tmp_path):
    fake = tmp_path / "fake.mp4"
    fake.write_text("this is not a video")
    r = client.post("/videos/register", json={"path": str(fake), "role": "gameplay"})
    assert r.status_code == 422


@needs_ffmpeg
def test_register_full_flow(client, sample_video):
    r = client.post("/videos/register", json={"path": str(sample_video), "role": "gameplay"})
    assert r.status_code == 200, r.text
    rec = r.json()
    vid = rec["id"]

    meta = rec["metadata"]
    assert meta["video"]["width"] == 320 and meta["video"]["height"] == 240
    assert meta["video"]["aspect_ratio"] == "4:3"
    assert meta["audio"] is None
    assert 8.5 < meta["duration_seconds"] < 9.5
    assert rec["source"] == "local"

    assert len(rec["thumbnail_urls"]) == settings.thumbnail_count
    assert client.get(rec["thumbnail_urls"][0]).status_code == 200

    s = client.post(f"/videos/{vid}/scenes", params={"frame_skip": 0}).json()
    assert s["scenes"]["scene_count"] == 3

    assert client.get("/videos").json()["count"] == 1

    # Deleting a registered video must NOT delete the user's original file.
    assert client.delete(f"/videos/{vid}").status_code == 200
    assert sample_video.exists()
    assert client.get(f"/videos/{vid}").status_code == 404


@needs_ffmpeg
def test_upload_flow_and_cleanup(client, sample_video):
    with open(sample_video, "rb") as fh:
        r = client.post("/videos/upload", files={"file": ("clip.mp4", fh, "video/mp4")}, data={"role": "reference"})
    assert r.status_code == 200, r.text
    rec = r.json()
    copied = Path(rec["path"])
    assert copied.exists() and rec["source"] == "upload" and rec["role"] == "reference"

    client.delete(f"/videos/{rec['id']}")
    assert not copied.exists()  # our copy is removed
    assert sample_video.exists()  # the original is untouched
