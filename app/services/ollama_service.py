"""Minimal Ollama client.

Phase 1 only checks that Ollama is running and that the required model is
already installed. It NEVER pulls or downloads a model. Text generation is
added in Phase 4.

Uses only the standard library (no extra dependency).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List

from app.config import settings

# Bypass any system proxy: Ollama is always local.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class OllamaError(RuntimeError):
    pass


def list_models(timeout: float = 3.0) -> List[str]:
    """Return the names of locally installed Ollama models."""
    url = f"{settings.ollama_url.rstrip('/')}/api/tags"
    try:
        with _opener.open(urllib.request.Request(url), timeout=timeout) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        raise OllamaError(str(exc)) from exc
    return [m.get("name", "") for m in data.get("models", [])]


def chat_json(system: str, user: str, timeout: float | None = None) -> str:
    """Ask the local model for a JSON reply and return the raw text.

    Uses Ollama's JSON mode and a low temperature. Only the already-installed
    model is used; nothing is ever pulled.
    """
    payload = {
        "model": settings.ollama_model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {
            "temperature": 0.2,
            "num_ctx": settings.ollama_num_ctx,
            "num_predict": settings.ollama_num_predict,
        },
        "keep_alive": int(settings.ollama_keep_alive) if settings.ollama_keep_alive.lstrip("-").isdigit() else settings.ollama_keep_alive,
    }
    req = urllib.request.Request(
        f"{settings.ollama_url.rstrip('/')}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _opener.open(req, timeout=timeout or settings.ollama_timeout) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        raise OllamaError(f"Ollama request failed: {exc}") from exc
    content = (data.get("message") or {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise OllamaError("Ollama returned an empty reply")
    return content


def check_ollama() -> Dict[str, Any]:
    """Report whether Ollama is reachable and the required model is installed."""
    wanted = settings.ollama_model
    result: Dict[str, Any] = {
        "url": settings.ollama_url,
        "required_model": wanted,
        "reachable": False,
        "model_available": False,
        "installed_models": [],
        "error": None,
    }
    try:
        models = list_models()
    except OllamaError as exc:
        result["error"] = f"Ollama not reachable: {exc}"
        return result

    result["reachable"] = True
    result["installed_models"] = models
    result["model_available"] = any(m == wanted or m.startswith(wanted + "-") for m in models)
    if not result["model_available"]:
        result["error"] = (
            f"Model '{wanted}' not found. Installed: {models or 'none'}. "
            "No model will be downloaded automatically."
        )
    return result
