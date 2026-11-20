"""File handling: validation, streaming uploads, and JSON records.

Design notes (low-RAM machine):
- Uploads are streamed to disk in 1 MB chunks, never read fully into memory.
- Local files can be *registered in place* (no copy) to save disk space.
- Records are small JSON files written atomically.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Tuple

from app.config import settings

VIDEO_ID_RE = re.compile(r"^[a-f0-9]{12}$")
VALID_ROLES = ("gameplay", "reference")
CHUNK_SIZE = 1024 * 1024  # 1 MB


class FileValidationError(ValueError):
    pass


class FileTooLargeError(FileValidationError):
    pass


class RecordNotFoundError(KeyError):
    pass


# ---------------------------------------------------------------- validation
def new_video_id() -> str:
    return uuid.uuid4().hex[:12]


def validate_video_id(video_id: str) -> str:
    # Strict pattern also blocks path traversal like "../x".
    if not VIDEO_ID_RE.match(video_id or ""):
        raise RecordNotFoundError(video_id)
    return video_id


def validate_role(role: str) -> str:
    role = (role or "").strip().lower()
    if role not in VALID_ROLES:
        raise FileValidationError(f"role must be one of {VALID_ROLES}")
    return role


def validate_extension(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext not in settings.allowed_extensions:
        raise FileValidationError(
            f"Unsupported file type '{ext or 'none'}'. Allowed: {', '.join(settings.allowed_extensions)}"
        )
    return ext


def resolve_local_video(path_str: str) -> Path:
    """Validate a path on the user's disk (quotes from Explorer 'Copy as path' are stripped)."""
    cleaned = (path_str or "").strip().strip('"').strip("'")
    if not cleaned:
        raise FileValidationError("path is empty")
    path = Path(cleaned).expanduser()
    try:
        path = path.resolve()
    except OSError as exc:
        raise FileValidationError(f"Invalid path: {exc}") from exc
    if not path.is_file():
        raise FileValidationError(f"File not found: {path}")
    validate_extension(path.name)
    if path.stat().st_size == 0:
        raise FileValidationError("File is empty")
    return path


# ------------------------------------------------------------------- upload
def save_upload(fileobj: BinaryIO, filename: str, video_id: str) -> Tuple[Path, int]:
    """Stream an upload to data/uploads. Returns (final_path, size_bytes)."""
    ext = validate_extension(filename)
    settings.ensure_dirs()
    final = settings.uploads_dir / f"{video_id}{ext}"
    tmp = settings.temp_dir / f"{video_id}.part"
    written = 0
    try:
        with open(tmp, "wb") as out:
            while True:
                chunk = fileobj.read(CHUNK_SIZE)
                if not chunk:
                    break
                written += len(chunk)
                if written > settings.max_upload_bytes:
                    raise FileTooLargeError(
                        f"File exceeds {settings.max_upload_bytes // (1024 * 1024)} MB. "
                        "Use /videos/register with a local path instead."
                    )
                out.write(chunk)
        if written == 0:
            raise FileValidationError("Uploaded file is empty")
        os.replace(tmp, final)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return final, written


# ------------------------------------------------------------------ records
def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _record_path(video_id: str) -> Path:
    return settings.analysis_dir / validate_video_id(video_id) / "video.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_record(record: Dict[str, Any]) -> None:
    atomic_write_json(_record_path(record["id"]), record)


def load_record(video_id: str) -> Dict[str, Any]:
    path = _record_path(video_id)
    if not path.is_file():
        raise RecordNotFoundError(video_id)
    return json.loads(path.read_text(encoding="utf-8"))


def list_records() -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if not settings.analysis_dir.is_dir():
        return records
    for entry in settings.analysis_dir.iterdir():
        f = entry / "video.json"
        if entry.is_dir() and f.is_file():
            try:
                records.append(json.loads(f.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    return sorted(records, key=lambda r: r.get("created_at", ""))


def delete_record(video_id: str) -> None:
    """Delete analysis + thumbnails. Deletes the video file ONLY if we copied it (upload).

    Files registered from the user's own folders are never deleted.
    """
    record = load_record(video_id)
    if record.get("source") == "upload":
        Path(record["path"]).unlink(missing_ok=True)
    shutil.rmtree(settings.analysis_dir / video_id, ignore_errors=True)
    shutil.rmtree(settings.thumbnails_dir / video_id, ignore_errors=True)


def thumbnail_dir(video_id: str) -> Path:
    return settings.thumbnails_dir / validate_video_id(video_id)
