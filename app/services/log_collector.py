
import json

from pathlib import Path


# Locate the project root dynamically
PROJECT_ROOT = Path(__file__).resolve().parents[2]

LOG_FILE = PROJECT_ROOT / "logs" / "app.log"
MAX_ERROR_EVENTS = 100


def read_error_events(limit: int = 20):
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise TypeError("limit must be an integer")

    if limit < 0:
        raise ValueError("limit must not be negative")

    if limit > MAX_ERROR_EVENTS:
        raise ValueError(f"limit must not exceed {MAX_ERROR_EVENTS}")

    if limit == 0:
        return []

    if not LOG_FILE.exists():
        return []

    error_events = []

    with LOG_FILE.open("r", encoding="utf-8") as file:
        for line in file:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                # Skip old-format or malformed log entries
                continue

            if isinstance(event, dict) and event.get("level") == "ERROR":
                error_events.append(event)

    return error_events[-limit:]
