"""Plug-in point for FUTURE semantic gameplay-event detectors.

The first version deliberately has none registered: scene cuts, motion and
audio peaks cannot tell a fight from a car chase. When you later add a real
detector (for example a small image classifier or a kill-feed OCR), register
it here and its events will automatically appear in the gameplay analysis,
clearly labelled as "semantic_event" and boosting the excitement score.

A detector is any object with:
    name: str
    detect(video_path: str, record: dict) -> list[dict]
and each returned event must contain: start (s), end (s), label (str),
and may contain: confidence (0..1).
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

_DETECTORS: List[Any] = []


def register_detector(detector: Any) -> None:
    if not hasattr(detector, "name") or not callable(getattr(detector, "detect", None)):
        raise ValueError("A detector needs a `name` attribute and a `detect(video_path, record)` method")
    _DETECTORS.append(detector)


def clear_detectors() -> None:
    _DETECTORS.clear()


def registered_names() -> List[str]:
    return [d.name for d in _DETECTORS]


def run_detectors(video_path: str, record: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Run every registered detector. Returns (events, error_messages)."""
    events: List[Dict[str, Any]] = []
    errors: List[str] = []
    for det in _DETECTORS:
        try:
            for e in det.detect(video_path, record):
                start, end = float(e["start"]), float(e["end"])
                if end <= start:
                    continue
                events.append({
                    "kind": "semantic_event",
                    "detector": det.name,
                    "label": str(e.get("label", "event"))[:60],
                    "start": round(start, 2),
                    "end": round(end, 2),
                    "confidence": float(e.get("confidence", 0.5)),
                })
        except Exception as exc:  # one broken detector must never break analysis
            errors.append(f"{det.name}: {exc}")
    return events, errors
