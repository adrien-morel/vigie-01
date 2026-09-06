"""Structured logging for the pipeline — a format Cloud Logging can work with.

One output line = one JSON object on stdout. Cloud Run captures stdout and parses it into
`jsonPayload`, on two conditions this module honours: the severity must be carried by the `severity`
field (and not `level`, which Cloud Logging ignores — everything would then surface as `DEFAULT`, and
an error would no longer be distinguishable from an informational line in an alert), and the JSON
must fit on a single line (an object spread over several lines is split into that many unreadable
entries).

Measurements are emitted as **structured fields**, never interpolated into the message: a truncated
run must be filterable by `jsonPayload.truncated=true`, not by grepping free text. That is the
difference between logging and decorative tracing — and the reason for the "check that the format is
usable by Cloud Logging" item in the production rollout plan.

No business state passes through here: this module writes to stdout, it persists nothing (see the
rule "all durable state goes through backend/memory/persistence.py").
"""

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any

# Name of the root shared by every log in the project. A dedicated logger rather than the root
# logger: uvicorn configures its own, and grafting onto it would mix the HTTP access format with the
# pipeline's.
ROOT = "vigie"

# LogRecord fields the standard library sets itself: everything else in __dict__ is, by construction,
# a field added by the caller through `extra=`.
_STANDARD = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            # Cloud Logging promotes these three keys out of the jsonPayload; the others stay inside
            # and are filterable through `jsonPayload.<key>`.
            "severity": record.levelname,
            "message": record.getMessage(),
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "logger": record.name,
        }
        payload.update({k: v for k, v in record.__dict__.items() if k not in _STANDARD})
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # default=str rather than a failure: a non-serialisable measurement must degrade the line,
        # not fail the run it is meant to document.
        return json.dumps(payload, ensure_ascii=False, default=str)


class _TextFormatter(logging.Formatter):
    """Human-readable fallback for local development — never used in production."""

    def format(self, record: logging.LogRecord) -> str:
        fields = {k: v for k, v in record.__dict__.items() if k not in _STANDARD}
        suffix = " " + " ".join(f"{k}={v}" for k, v in fields.items()) if fields else ""
        return f"{record.levelname:<8} {record.name:<16} {record.getMessage()}{suffix}"


def configure_logging() -> None:
    """Installs the handler on the project's root logger. Idempotent: called by run_pipeline() and
    when the API is imported, which may run in the same process."""
    logger = logging.getLogger(ROOT)
    if logger.handlers:
        return
    # On Windows, stdout falls back to the ANSI code page (cp1252) as soon as output is redirected: a
    # dispatch in Cyrillic or Korean inside a log field then makes the write fail with
    # UnicodeEncodeError — that is, logging would bring down the run it is meant to document. Same
    # trap as the explicit `encoding="utf-8"` required everywhere else in this repository.
    # `errors="replace"` degrades the character, never the line.
    if (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "") != "utf8":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    handler = logging.StreamHandler(sys.stdout)
    text_mode = os.getenv("VIGIE_LOG_FORMAT", "json").lower() == "text"
    handler.setFormatter(_TextFormatter() if text_mode else _JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(os.getenv("VIGIE_LOG_LEVEL", "INFO").upper())
    # Without this, every line would come out twice as soon as a caller (uvicorn, pytest) has
    # configured the stdlib root logger.
    logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Logger for a node or a module, under the shared root. `name` acts as a filter on the Cloud
    Logging side (`jsonPayload.logger`), so it carries the node's name, not the file's."""
    return logging.getLogger(f"{ROOT}.{name}")
