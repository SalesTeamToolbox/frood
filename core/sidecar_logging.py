"""Structured JSON logging for Frood sidecar mode.

When --sidecar is active, all log output is JSON lines (one JSON object per line)
suitable for log aggregation tools. ANSI escape codes are stripped per D-10.
"""

import json
import logging
import re
import sys
import time

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[mGKHF]")


class SidecarJsonFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects.

    Output format:
        {"timestamp": "2026-03-28T12:00:00Z", "level": "INFO", "logger": "agent42", "message": "..."}
    """

    def format(self, record: logging.LogRecord) -> str:
        message = _ANSI_ESCAPE.sub("", record.getMessage())
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_sidecar_logging() -> None:
    """Replace root logger handlers with a single JSON-emitting StreamHandler.

    Call this once at startup when --sidecar is active, BEFORE constructing Frood.
    Per pitfall 5 in RESEARCH.md: only install JSON formatter in sidecar mode to
    avoid breaking dashboard's human-readable log format.
    """
    root = logging.getLogger()
    # Remove all existing handlers
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    # Install JSON formatter on a fresh StreamHandler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(SidecarJsonFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)
