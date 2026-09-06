"""FastAPI application: exposes the digest produced by the pipeline (README architecture).

/run triggers the full pipeline (~10 min); /events serves a sliding window over the analysed history,
recomputing nothing. Manual triggering in V1 (POST /run called by hand), replaced by
Cloud Scheduler -> Cloud Run job in production.

The digest is deliberately not the result of the last run: deduplication discards, before the LLM
call, everything already seen in the last 7 days, so a second run on the same day returns only a
handful of new items. Serving that raw result would erase the displayed history on every collection
(see backend/memory/store.py).
"""

import secrets
import time

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.config import ALLOWED_ORIGINS, DIGEST_WINDOW_DAYS, RUN_TOKEN
from backend.graph import run_pipeline
from backend.logging_setup import configure_logging, get_logger
from backend.memory.store import RELATED_ITEMS_WINDOW_DAYS, last_run_at, load_digest

configure_logging()
log = get_logger("api")

app = FastAPI(title="VIGIE-01 API")

# Restricted to the declared origins (backend/config.py, ALLOWED_ORIGINS) since the deployment was
# prepared. The V1 "*" avoided a configuration step at startup; it also allowed any page to read the
# digest from a visitor's browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _authorize_run(token: str) -> None:
    """Closes POST /run behind a shared token. Two distinct refusals, deliberately:

    503 when no token is configured — the service is running but the most expensive endpoint of the
    system has no guard, and opening it "in the meantime" is exactly what the budget cap forbids.
    Same logic as MAX_STEPS_PER_RUN / MAX_LLM_CALLS_PER_DAY, which fail the import rather than take a
    default value; here the failure is carried by the endpoint and not by startup, so that
    GET /events keeps serving the digest already produced.

    401 when a token is configured but the caller does not have the right one.

    compare_digest and not "==": the naive comparison stops at the first differing byte, which lets
    the token be guessed byte by byte by measuring the response time.
    """
    if not RUN_TOKEN:
        log.error("POST /run called with no RUN_TOKEN configured: endpoint closed")
        raise HTTPException(
            status_code=503,
            detail="RUN_TOKEN is not configured: POST /run is closed. Set RUN_TOKEN to enable it.",
        )
    if not secrets.compare_digest(token, RUN_TOKEN):
        log.warning("POST /run refused: invalid token")
        raise HTTPException(status_code=401, detail="Invalid token.")


@app.post("/run")
def run(x_run_token: str = Header(default="", alias="X-Run-Token")) -> dict:
    _authorize_run(x_run_token)

    # The budget cap (guardrail §8) no longer propagates up to here: it truncates the run inside the
    # nodes that call the model, which return what they have already produced and paid for. A
    # truncated run is therefore a partial success — 200 with truncated=True — and not a 429:
    # answering with an error would make the client ignore a digest that was in fact enriched, which
    # is what happened before this fix (the front does not reload the digest on error).
    # Start, end, duration and truncation are logged here and not only returned in the response body:
    # Cloud Scheduler does not read that body. Without these lines, a truncated run in production is
    # indistinguishable from a complete one, and a duration that drifts (401 s on 2026-08-20, 620 s on
    # 2026-08-22) only shows up when it exceeds the service timeout.
    started = time.monotonic()
    log.info("POST /run accepted")
    result = run_pipeline()
    duration = round(time.monotonic() - started, 1)
    if result["truncated"]:
        # A truncation is not an error: it is a partial success, and the two must be distinguishable
        # in an alert (WARNING against ERROR), not merged into one failure total.
        log.warning("run truncated by a cap", extra={"duration_s": duration, "items": len(result["analyzed_items"])})
    log.info(
        "POST /run finished",
        extra={"duration_s": duration, "items": len(result["analyzed_items"]), "truncated": result["truncated"]},
    )
    return {"item_count": len(result["analyzed_items"]), "truncated": result["truncated"]}


@app.get("/events")
def events(
    days: int = Query(
        DIGEST_WINDOW_DAYS,
        ge=1,
        le=RELATED_ITEMS_WINDOW_DAYS,
        description="Depth of the digest in days, bounded by the retention of the analysed history.",
    ),
) -> dict:
    items = load_digest(days)
    # 404 means "the pipeline has never run", not "nothing in this period": a narrow window over a
    # non-empty history must stay a navigable empty digest, with the period selector available to
    # widen it.
    if not items and not load_digest(RELATED_ITEMS_WINDOW_DAYS):
        raise HTTPException(status_code=404, detail="No digest generated. Call POST /run first.")
    return {
        "generated_at": last_run_at(items),
        "window_days": days,
        "max_window_days": RELATED_ITEMS_WINDOW_DAYS,
        "items": items,
    }
