"""Exit-code semantics of the Cloud Run Job.

Cloud Run Jobs retries a task that exits with an error: the exit code, and it alone, decides whether
there will be a second attempt. These tests fix when there should be one.
"""

import os

from backend import job


def test_a_complete_run_exits_zero(monkeypatch):
    monkeypatch.setattr(job, "run_pipeline", lambda: {"analyzed_items": [1, 2], "truncated": False})

    assert job.main() == 0


def test_a_truncated_run_exits_zero_because_a_retry_would_produce_nothing(monkeypatch):
    """A truncated run has reached the daily call cap: retrying it would produce nothing (budget
    spent, submitted items already marked seen) and would bury the work paid for under failed
    attempts. Truncation is read in the log, not in the exit code."""
    monkeypatch.setattr(job, "run_pipeline", lambda: {"analyzed_items": [1], "truncated": True})

    assert job.main() == 0


def test_a_failed_run_exits_one(monkeypatch):
    def _boom():
        raise RuntimeError("unreachable feed")

    monkeypatch.setattr(job, "run_pipeline", _boom)

    assert job.main() == 1


def test_job_disables_langsmith_tracing_by_default(monkeypatch):
    """Tracing stalled a run for several minutes on 2026-08-30 by becoming unreachable. The Job is
    the unattended path: it does not trace, unless explicitly asked to."""
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("VIGIE_JOB_TRACING", raising=False)

    assert job._disable_tracing_unless_opted_in() is False
    assert "LANGCHAIN_TRACING_V2" not in os.environ
    assert "LANGSMITH_TRACING" not in os.environ


def test_job_keeps_tracing_when_explicitly_opted_in(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("VIGIE_JOB_TRACING", "true")

    assert job._disable_tracing_unless_opted_in() is True
    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
