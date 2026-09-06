"""Entry point of the Cloud Run Job that executes the daily run.

The pipeline is a ~10-minute batch job, not a request: triggering it over HTTP would mean holding the
connection open for its whole duration, under the service timeout *and* under the scheduler's
(30 min at most on the Cloud Scheduler side). A Job has no request timeout, and the Cloud Run service
stays dedicated to what it does quickly: serving the digest already produced, through GET /events.

Same image as the service, different command — not two builds to keep in sync.
"""

import os
import sys

from backend.graph import run_pipeline
from backend.logging_setup import configure_logging, get_logger

log = get_logger("job")

# Variables through which LangChain turns on sending traces to LangSmith. Both names coexist (the old
# one and the one introduced by the LangSmith rename) and are read independently: neutralising only
# one leaves tracing active through the other.
_TRACING_VARS = ("LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING")


def _disable_tracing_unless_opted_in() -> bool:
    """Turns tracing off on the Job, unless explicitly requested through `VIGIE_JOB_TRACING=true`.

    Measured on 2026-08-30: the LangSmith service became unreachable **during** a run and the pipeline
    stalled for several minutes on its timeouts. The LangSmith client waits 60 s on read per send
    (`timeout_ms` defaults to `(10_000, 60_000)`) and that value is not settable through an
    environment variable in the pinned version — bounding it would mean building the client ourselves,
    and therefore maintaining tracing code inside the run's execution path.

    The Job is the unattended path, and the one with the least margin: 880 s measured against a 900 s
    target, whose Cloud Run timeout we are raising separately. An observatory that can stop what it
    observes has no place there by default. Tracing keeps all its value in development, where someone
    is watching the screen — hence inverting the default here only, and not in `.env`: `uvicorn` and
    the eval scripts keep tracing normally.

    Returns True if tracing was left on.
    """
    if os.getenv("VIGIE_JOB_TRACING", "").strip().lower() in {"1", "true", "yes"}:
        log.info("LangSmith tracing left on for the Job, on explicit request")
        return True
    disabled = [var for var in _TRACING_VARS if os.environ.pop(var, None) is not None]
    if disabled:
        log.info("LangSmith tracing turned off for the Job", extra={"variables": disabled})
    return False


def main() -> int:
    """Exit code 0 if the run went through, 1 if it failed.

    **A truncated run exits 0**, and that is the decision that matters here: Cloud Run Jobs retries a
    task that exits with an error, yet a truncated run has reached the daily call cap (§6). Retrying
    it would produce nothing — the budget is spent, deduplication has already marked the submitted
    items — but would bury the work that was paid for under a pile of failed attempts. Truncation is a
    partial success: it shows up as a WARNING in the log and as `truncated` in the structured fields,
    not in the exit code.
    """
    configure_logging()
    _disable_tracing_unless_opted_in()
    try:
        result = run_pipeline()
    except Exception:
        # run_pipeline already logs the exception with its duration; here we only translate the
        # failure into an exit code, the only signal Cloud Run Jobs knows how to read.
        log.error("daily run failed, exiting with an error")
        return 1

    log.info(
        "daily run finished",
        extra={"items": len(result["analyzed_items"]), "truncated": result["truncated"]},
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
