
import json

from pathlib import Path


# Locate the project root dynamically
PROJECT_ROOT = Path(__file__).resolve().parents[2]

LOG_FILE = PROJECT_ROOT / "logs" / "app.log"


def read_error_events(limit: int = 20):

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

            if event.get("level") == "ERROR":
                error_events.append(event)

    return error_events[-limit:]
