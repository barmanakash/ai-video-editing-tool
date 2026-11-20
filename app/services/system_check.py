"""Environment inspection: Python, FFmpeg, FFprobe, Ollama, model, disk space."""
from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Any, Dict, List

from app.config import BASE_DIR, settings
from app.services.ollama_service import check_ollama


def _tool_info(executable: str) -> Dict[str, Any]:
    path = shutil.which(executable)
    if not path:
        return {"found": False, "path": None, "version": None}
    version = None
    try:
        proc = subprocess.run(
            [path, "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        version = (proc.stdout or proc.stderr).splitlines()[0] if (proc.stdout or proc.stderr) else None
    except (OSError, subprocess.SubprocessError):
        pass
    return {"found": True, "path": path, "version": version}


def run_checks() -> Dict[str, Any]:
    issues: List[str] = []

    py_ok = sys.version_info >= (3, 10)
    python = {
        "version": sys.version.split()[0],
        "ok": py_ok,
    }
    if not py_ok:
        issues.append("Python 3.10 or newer is required.")

    ffmpeg = _tool_info(settings.ffmpeg_path)
    ffprobe = _tool_info(settings.ffprobe_path)
    if not ffmpeg["found"]:
        issues.append("FFmpeg not found. Install it (winget install Gyan.FFmpeg) and reopen PowerShell.")
    if not ffprobe["found"]:
        issues.append("FFprobe not found (it ships with FFmpeg).")

    ollama = check_ollama()
    if ollama["error"]:
        issues.append(ollama["error"])

    usage = shutil.disk_usage(BASE_DIR)
    free_gb = round(usage.free / 1024 ** 3, 1)
    disk = {"free_gb": free_gb, "ok": free_gb >= settings.min_free_disk_gb}
    if not disk["ok"]:
        issues.append(f"Only {free_gb} GB free; keep at least {settings.min_free_disk_gb} GB for renders.")

    return {
        "ok": not issues,
        "python": python,
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "ollama": ollama,
        "disk": disk,
        "issues": issues,
    }
