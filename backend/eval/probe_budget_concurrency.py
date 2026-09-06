"""Concurrency probe on the LLM budget reservation.

Rationale: `check_and_increment_llm_call` increments a shared daily counter, and its atomicity is a
property of the **storage**, not of the caller (`backend/memory/persistence.py`). The Firestore
backend implements it inside a transaction, but that transaction had never been exercised under real
concurrency — and it is the only guardrail in the project that can only be wrong in production. A unit
test with a simulated LLM does not reach it: there is nothing to serialise in a single process writing
a JSON file.

What the probe measures, and what it does not. It fires `--attempts` simultaneous reservations and
counts the acceptances. The verdict only holds if the number of remaining slots is **lower than the
number of attempts**: with a full budget, all of them succeed and the probe proves nothing. That was
the trap of 2026-09-05, where two runs of the full pipeline had produced only a single reservation —
deduplication had starved them before the race could happen.

Prefer running it across several Cloud Run tasks (`--tasks N`) rather than threads alone: threads in a
single process would not detect a lock taken on the client side, whereas the real scenario is indeed
two distinct containers.

**No model call is issued.** A reservation is a counter increment; the probe therefore consumes
*accounting* budget — at most `--attempts` units, reset at the change of day — but not a cent of API.

    python -m backend.eval.probe_budget_concurrency --yes [--attempts 10]
"""

import argparse
import concurrent.futures as futures
import os
from collections import Counter

from backend.guardrails import BudgetExceeded, check_and_increment_llm_call, remaining_calls_today
from backend.logging_setup import configure_logging, get_logger

log = get_logger("eval.probe_budget")


def _attempt(_: int) -> str:
    try:
        check_and_increment_llm_call("probe")
        return "accepted"
    except BudgetExceeded:
        return "refused"
    except Exception as exc:  # noqa: BLE001 — we want the name of the fault, not to handle it
        return f"error:{type(exc).__name__}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempts", type=int, default=10, help="simultaneous reservations per task")
    # Invocation guardrail: the probe consumes accounting budget, it must not be able to start from a
    # mistyped `-m`.
    parser.add_argument("--yes", action="store_true", help="confirms the budget consumption")
    args = parser.parse_args()

    configure_logging()

    if not args.yes:
        log.error("probe not confirmed, nothing was attempted", extra={"attempts": args.attempts})
        return 2

    task = os.getenv("CLOUD_RUN_TASK_INDEX", "local")
    before = remaining_calls_today()

    with futures.ThreadPoolExecutor(max_workers=args.attempts) as pool:
        outcomes = list(pool.map(_attempt, range(args.attempts)))

    tally = dict(Counter(outcomes))
    log.info(
        "concurrency probe finished",
        extra={
            "task": task,
            "attempts": args.attempts,
            "outcomes": tally,
            "remaining_before": before,
            "remaining_after": remaining_calls_today(),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
