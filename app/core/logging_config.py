
import json
import logging

from datetime import datetime, timezone
from pathlib import Path

from app.core.request_context import request_id_ctx


class JSONFormatter(logging.Formatter):

    def format(self, record):

        log_data = {
            "timestamp": datetime.fromtimestamp(
                record.created,
                tz=timezone.utc
            ).isoformat(),

            "level": record.levelname,

            "service": "ecommerce-api",

            "logger": record.name,

            "request_id": request_id_ctx.get(),

            "message": record.getMessage()
        }

        # Include additional information when available
        for field in [
            "endpoint",
            "failure_type",
            "status_code"
        ]:
            if hasattr(record, field):
                log_data[field] = getattr(record, field)

        return json.dumps(log_data)


def setup_logging():

    log_directory = Path("logs")
    log_directory.mkdir(exist_ok=True)

    log_file = log_directory / "app.log"

    # File handler
    file_handler = logging.FileHandler(
        log_file,
        encoding="utf-8"
    )

    # Console handler
    console_handler = logging.StreamHandler()

    # Apply JSON formatting to both handlers
    formatter = JSONFormatter()

    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logging.basicConfig(
        level=logging.INFO,
        handlers=[
            file_handler,
            console_handler
        ],
        force=True
    )
