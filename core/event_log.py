"""
core/event_log.py — Lightweight operational event log.

Provides a simple ring-buffer of structured events, persisted as JSON lines.
Each event has the shape:
  {
    "ts":      "2024-01-02T10:11:12.345678",
    "area":    "auth" | "ota" | "network" | "bluetooth" | "audio" | "standby" | "rfid" | "jobs" | ...,
    "severity": "info" | "warning" | "error",
    "message": "human-readable message",
    "details": {...}   # optional extra data
  }

Design goals:
- No crash on missing / corrupt storage
- Bounded size (ring buffer: at most EVENT_LOG_MAX_ENTRIES entries)
- Thread-safe appends
- Fast reads (return a list in reverse-chronological order)
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any

# Maximum number of events kept in the log file (ring buffer)
EVENT_LOG_MAX_ENTRIES = 500

_lock = threading.Lock()
_log_file: str | None = None  # set by _init_log_file() on first use


def _init_log_file() -> str:
    """Return the path to the event log file, initialising it from config if needed."""
    global _log_file
    if _log_file is None:
        try:
            from config import EVENT_LOG_FILE
            _log_file = EVENT_LOG_FILE
        except Exception:
            import tempfile
            _log_file = os.path.join(tempfile.gettempdir(), "gufobox_events.jsonl")
    return _log_file


def _read_raw() -> list[dict]:
    """Read all stored events from disk. Returns [] on any error."""
    path = _init_log_file()
    events: list[dict] = []
    try:
        if not os.path.exists(path):
            return events
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass  # skip corrupt lines
    except Exception:
        pass
    return events


def _write_raw(events: list[dict]) -> None:
    """Write the event list to disk (overwrite). Silently ignores errors."""
    path = _init_log_file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception:
        pass


def log_event(
    area: str,
    severity: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    """
    Append a new event to the ring buffer.

    Args:
        area:     Subsystem originating the event (e.g. "ota", "auth", "network").
        severity: One of "info", "warning", "error".
        message:  Short human-readable description.
        details:  Optional dict with extra structured data.
    """
    severity = severity if severity in ("info", "warning", "error") else "info"
    event: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "area": str(area),
        "severity": severity,
        "message": str(message),
    }
    if details:
        event["details"] = details

    with _lock:
        events = _read_raw()
        events.append(event)
        # Trim to max size (keep most recent)
        if len(events) > EVENT_LOG_MAX_ENTRIES:
            events = events[-EVENT_LOG_MAX_ENTRIES:]
        _write_raw(events)


def get_events(limit: int = 100) -> list[dict]:
    """
    Return the most recent ``limit`` events in reverse-chronological order.

    Never raises; returns [] on any error.
    """
    with _lock:
        events = _read_raw()
    # Most recent first
    events = list(reversed(events))
    return events[:limit]


def clear_events() -> None:
    """Remove all stored events. Used mainly in tests."""
    with _lock:
        _write_raw([])
