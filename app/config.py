"""Central configuration for the local AI gaming video editor.

Everything is tuned for a low-resource machine (8 GB RAM, no dedicated GPU).
Any value can be overridden with an environment variable (GVE_*) without
editing code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    # --- Folders -----------------------------------------------------------
    data_dir: Path = BASE_DIR / "data"
    outputs_dir: Path = BASE_DIR / "outputs"

    # --- External tools ----------------------------------------------------
    ffmpeg_path: str = os.environ.get("GVE_FFMPEG", "ffmpeg")
    ffprobe_path: str = os.environ.get("GVE_FFPROBE", "ffprobe")
    # 127.0.0.1 instead of "localhost" avoids slow IPv6 lookups on Windows.
    ollama_url: str = os.environ.get("GVE_OLLAMA_URL", "http://127.0.0.1:11434")
    ollama_model: str = os.environ.get("GVE_OLLAMA_MODEL", "qwen2.5:3b")
    # A 3B model on CPU can be slow: allow up to 10 minutes per planning call.
    ollama_timeout: float = _env_float("GVE_OLLAMA_TIMEOUT", 600.0)
    ollama_num_ctx: int = _env_int("GVE_OLLAMA_NUM_CTX", 4096)
    ollama_num_predict: int = _env_int("GVE_OLLAMA_NUM_PREDICT", 700)
    # 0 = unload the model right after planning so RAM is free for rendering.
    ollama_keep_alive: str = os.environ.get("GVE_OLLAMA_KEEP_ALIVE", "0")

    # --- Ingestion limits --------------------------------------------------
    allowed_extensions: Tuple[str, ...] = (".mp4", ".mkv", ".mov", ".avi", ".webm")
    audio_extensions: Tuple[str, ...] = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")
    # Default 4 GB per uploaded file. Prefer /videos/register for big files:
    # it does NOT copy the file, which saves disk space.
    max_upload_bytes: int = _env_int("GVE_MAX_UPLOAD_MB", 4096) * 1024 * 1024

    # --- Thumbnails --------------------------------------------------------
    thumbnail_count: int = _env_int("GVE_THUMB_COUNT", 4)
    thumbnail_width: int = _env_int("GVE_THUMB_WIDTH", 320)

    # --- Scene detection (lightweight settings) ---------------------------
    scene_threshold: float = _env_float("GVE_SCENE_THRESHOLD", 27.0)
    # frame_skip=2 analyses every 3rd frame: ~3x faster, still catches hard cuts.
    scene_frame_skip: int = _env_int("GVE_SCENE_FRAME_SKIP", 2)
    scene_min_len_frames: int = _env_int("GVE_SCENE_MIN_LEN", 15)

    # --- Plan limits (validation) -----------------------------------------
    max_plan_clips: int = 40
    min_clip_seconds: float = 0.5
    max_clip_seconds: float = 30.0
    max_output_seconds: float = 900.0

    # --- Rendering ---------------------------------------------------------
    render_fps: int = _env_int("GVE_RENDER_FPS", 30)
    transition_seconds: float = _env_float("GVE_TRANSITION_SECONDS", 0.4)
    full_preset: str = os.environ.get("GVE_FULL_PRESET", "veryfast")
    full_crf: int = _env_int("GVE_FULL_CRF", 20)
    test_preset: str = "ultrafast"
    test_crf: int = 28
    min_free_disk_gb: float = 5.0          # health-check warning threshold
    min_free_render_gb: float = 1.5        # refuse to render below this
    # 0 = let FFmpeg choose. Set e.g. 2 to keep the PC responsive while rendering.
    render_threads: int = _env_int("GVE_RENDER_THREADS", 0)
    # Run FFmpeg at below-normal priority on Windows so the PC stays usable.
    render_low_priority: bool = os.environ.get("GVE_RENDER_LOW_PRIORITY", "1") != "0"
    keep_temp_files: bool = os.environ.get("GVE_KEEP_TEMP", "0") == "1"   # debugging only
    # Cuts are moved at most this many seconds to land on a music loudness jump.
    max_beat_shift: float = _env_float("GVE_MAX_BEAT_SHIFT", 0.3)
    zoom_end: float = _env_float("GVE_ZOOM_END", 1.15)   # zoom_in effect ends at 115 % scale
    music_fade_in: float = 0.5
    music_fade_out: float = 1.5

    # --- Derived paths -----------------------------------------------------
    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def analysis_dir(self) -> Path:
        return self.data_dir / "analysis"

    @property
    def thumbnails_dir(self) -> Path:
        return self.data_dir / "thumbnails"

    @property
    def reference_profiles_dir(self) -> Path:
        return self.data_dir / "reference_profiles"

    @property
    def plans_dir(self) -> Path:
        return self.data_dir / "plans"

    @property
    def music_dir(self) -> Path:
        return self.data_dir / "music"

    @property
    def temp_dir(self) -> Path:
        return self.data_dir / "temp"

    def ensure_dirs(self) -> None:
        for d in (
            self.uploads_dir,
            self.analysis_dir,
            self.thumbnails_dir,
            self.reference_profiles_dir,
            self.plans_dir,
            self.music_dir,
            self.temp_dir,
            self.outputs_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
