"""Format contract of the log — Cloud Logging reads it, not a human.

These tests do not check "that we log" but that the output stays parsable and filterable: a log that
degrades into free text is only noticed at the first production incident, when you are looking for
why an overnight run returned three items.
"""

import json
import logging

from backend.logging_setup import ROOT, configure_logging, get_logger


def _emit(level: str, message: str, **fields) -> dict:
    """Formats one line with the real JSON formatter and returns the parsed object."""
    from backend.logging_setup import _JsonFormatter

    record = logging.LogRecord(f"{ROOT}.test", getattr(logging, level), "f.py", 1, message, None, None)
    record.__dict__.update(fields)
    return json.loads(_JsonFormatter().format(record))


def test_severity_is_the_field_cloud_logging_reads():
    """`level` is ignored by Cloud Logging: without `severity`, everything surfaces as DEFAULT and an
    error stops being distinguishable from an informational line in an alert."""
    payload = _emit("WARNING", "cap reached")

    assert payload["severity"] == "WARNING"
    assert payload["message"] == "cap reached"
    assert "level" not in payload


def test_measurements_are_structured_fields_not_interpolated_text():
    """A truncated run must be filterable by `jsonPayload.truncated=true`, not by grepping."""
    payload = _emit("INFO", "run finished", truncated=True, items=31, llm_calls_by_node={"analyze": 72})

    assert payload["truncated"] is True
    assert payload["items"] == 31
    assert payload["llm_calls_by_node"] == {"analyze": 72}


def test_one_record_is_one_line():
    """A JSON object spread over several lines is split into that many unreadable entries."""
    from backend.logging_setup import _JsonFormatter

    record = logging.LogRecord(f"{ROOT}.test", logging.INFO, "f.py", 1, "message\non two lines", None, None)

    assert "\n" not in _JsonFormatter().format(record)


def test_an_unserializable_field_degrades_the_line_instead_of_failing_the_run():
    """An unserialisable measurement must cost a less precise line, not the run it documents."""
    payload = _emit("INFO", "measurement", obj=object())

    assert payload["message"] == "measurement"
    assert isinstance(payload["obj"], str)


def test_configure_logging_is_idempotent():
    """Called by run_pipeline() and when the API is imported, which live in the same process: a
    second handler would double every line.

    The handlers are cleared then restored because pytest grafts its own onto this logger — it does so
    precisely because `propagate = False`, and their presence would make the test pass without proving
    anything (configure_logging would return on its first line)."""
    logger = logging.getLogger(ROOT)
    saved = logger.handlers[:]
    logger.handlers.clear()
    try:
        configure_logging()
        configure_logging()
        assert len(logger.handlers) == 1
    finally:
        logger.handlers[:] = saved

    assert get_logger("collect").name == f"{ROOT}.collect"
