"""Logging configuration with secret-aware field redaction."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from subscription_gateway.config import LoggingSettings

SENSITIVE_MARKERS = ("TOKEN", "KEY", "SECRET", "PASSWORD")


def redact_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    """Mask values whose field name looks secret-bearing."""

    return {
        key: "***" if any(marker in key.upper() for marker in SENSITIVE_MARKERS) else value
        for key, value in values.items()
    }


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in (
            "request_id",
            "provider",
            "model",
            "session_id",
            "queue_delay_ms",
            "duration_ms",
            "status",
        ):
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        # None of the fields above is secret-bearing today. Redacting on the way
        # out is what keeps that true when the next one is added.
        return json.dumps(redact_mapping(payload), separators=(",", ":"), default=str)


def configure_logging(settings: LoggingSettings) -> None:
    handler = logging.StreamHandler()
    if settings.json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.level)
