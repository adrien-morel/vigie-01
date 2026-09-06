"""Daily LLM budget guardrail (see docs/scoping.md §6 and §8 — non-negotiable).

The counter is held by the persistence layer (backend/memory/persistence.py): a local file in dev,
Firestore in production. The reservation is delegated to the backend rather than done here as a
read-modify-write, because atomicity depends on the storage — with a local disk it is a given (a
single process), with several Cloud Run instances it requires a transaction. An in-memory or
file-based counter on Cloud Run would reset on every cold start, which would make this cap
circumventable by a simple restart.
"""

from collections import Counter
from datetime import UTC, date, datetime

from backend.config import MAX_LLM_CALLS_PER_DAY
from backend.logging_setup import get_logger
from backend.memory.persistence import get_persistence

log = get_logger("guardrails")


class BudgetExceeded(RuntimeError):
    pass


# Split of the current run's calls between nodes. Deliberately in memory and outside the persistence
# layer, unlike the cap counter: this is not a guardrail but an operational measurement. It therefore
# does not need the atomicity that `reserve_llm_call` demands, and putting it there would mean
# touching the Persistence interface and both its implementations — including FirestorePersistence,
# never validated against a real database. Reset by run_pipeline(), the single entry point of a run:
# without that, two runs in the same process (the API serves /run without restarting) would
# accumulate their tallies.
#
# Rationale (docs/scoping.md §11): the budget is a single global counter, so widening the perimeter
# of one node does not consume "extra" calls — it takes them away from the next node. Observed on
# 2026-08-21, where the extended verifier made the cap fall on `thread`, last in the chain.
# Arbitrating that split means measuring it; that is what this counter does.
_calls_by_node: Counter[str] = Counter()


def check_and_increment_llm_call(node: str = "unknown") -> None:
    """Call before every LLM call. Raises BudgetExceeded if the daily cap has been reached.

    The call does not take place when this exception is raised: it is triggered by the reservation
    being refused, upstream of the model. The item it falls on has therefore cost nothing and is
    still entirely to be processed — that is what lets the calling nodes hand it back to a later
    collection rather than mark it as seen (see backend/agents/analyst.py).
    """
    today = date.today().isoformat()
    if not get_persistence().reserve_llm_call(today, MAX_LLM_CALLS_PER_DAY):
        # Logged at the exact point of refusal, in addition to the exception: this is the only place
        # that knows *which* node was asking for the refused call, information lost as soon as the
        # exception propagates.
        log.warning(
            "call reservation refused, daily cap reached",
            extra={"node": node, "cap": MAX_LLM_CALLS_PER_DAY, "calls_by_node": dict(_calls_by_node)},
        )
        raise BudgetExceeded(
            f"Daily LLM call cap reached ({MAX_LLM_CALLS_PER_DAY}/day) "
            f"at {datetime.now(UTC).isoformat()}: call refused, run truncated "
            "(non-negotiable guardrail, see docs/scoping.md §6)."
        )
    # Incremented after the reservation, never before: a refused call cost nothing (see the docstring
    # above), charging it to a node would make it carry spending it never obtained.
    _calls_by_node[node] += 1


def remaining_calls_today() -> int:
    return MAX_LLM_CALLS_PER_DAY - get_persistence().calls_used(date.today().isoformat())


def calls_by_node() -> dict[str, int]:
    """Split of the current run's calls by node, in order of first spend."""
    return dict(_calls_by_node)


def reset_call_tally() -> None:
    """Call at the start of a run. Does not affect the daily cap, which is persistent."""
    _calls_by_node.clear()
