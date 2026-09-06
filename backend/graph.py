"""Assembles the pipeline as a LangGraph StateGraph: collect → deduplicate → analyze → verify →
thread (README §architecture).

deduplicate sits before analyze, not after (see backend/memory/store.py): filtering out items
already seen before the LLM call rather than after avoids paying for a call to re-analyse an item
that has already been processed.

verify (backend/agents/verifier.py) is the first slice of docs/scoping.md §10 V2: cross-checking and
a confidence score for items in sensitive categories (VERIFIER_CATEGORIES), with its own agentic
loop bounded inside the node.

thread (backend/agents/threader.py) is the first slice of docs/scoping.md §10 V3: grouping into
chronological stories, placed after verify so that its history window already sees the items of the
current run (verify has written them), with its own bounded agentic loop as well.
"""

import time

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from backend.agents.analyst import analyze, reset_submission_tally, submissions_by_source
from backend.agents.collector import collect
from backend.agents.threader import thread_events
from backend.agents.verifier import verify
from backend.config import MAX_STEPS_PER_RUN
from backend.guardrails import calls_by_node, reset_call_tally
from backend.logging_setup import configure_logging, get_logger
from backend.memory.store import deduplicate
from backend.state import VigieState

log = get_logger("run")


def build_graph() -> CompiledStateGraph:
    builder = StateGraph(VigieState)
    builder.add_node("collect", collect)
    builder.add_node("analyze", analyze)
    builder.add_node("deduplicate", deduplicate)
    builder.add_node("verify", verify)
    builder.add_node("thread", thread_events)

    builder.add_edge(START, "collect")
    builder.add_edge("collect", "deduplicate")
    builder.add_edge("deduplicate", "analyze")
    builder.add_edge("analyze", "verify")
    builder.add_edge("verify", "thread")
    builder.add_edge("thread", END)

    return builder.compile()


def run_pipeline() -> VigieState:
    """Raises langgraph.errors.GraphRecursionError if MAX_STEPS_PER_RUN is exceeded
    (guardrail §8 "runaway agent loop", non-negotiable — see docs/scoping.md).
    """
    # Idempotent: a run launched by the API finds logging already installed, a run launched from the
    # command line (scripts/, python -c) installs it here.
    configure_logging()
    # The per-node tally is a measurement of the run, not of the day: resetting it here, the single
    # entry point of a run, keeps two runs served by the same process (the API does not restart
    # between two POST /run) from accumulating their splits. No effect on the daily cap, which is
    # persistent and must emphatically not be reset by a run.
    reset_call_tally()
    # Same scope and same reason as the call tally above: what `analyze` submitted belongs to *this*
    # run, not to the day (see backend/agents/analyst.py).
    reset_submission_tally()
    graph = build_graph()
    started = time.monotonic()
    log.info("run started")
    try:
        result = graph.invoke(
            {"raw_items": [], "analyzed_items": [], "truncated": False},
            config={"recursion_limit": MAX_STEPS_PER_RUN},
        )
    except Exception:
        # Logged then re-raised: under Cloud Scheduler the exception is visible nowhere else — the
        # body of the HTTP response is not read by the scheduler.
        log.exception("run interrupted by an error", extra={"duration_s": round(time.monotonic() - started, 1)})
        raise

    # Both operational measurements used to be emitted by scripts/daily_run.py alone, which is an
    # operator tool and does not ship to production (Cloud Scheduler replaces it). Emitting them here
    # is what makes them available in the cloud, where they are the only way to know how the 200
    # calls of the day were split.
    log.info(
        "run finished",
        extra={
            "duration_s": round(time.monotonic() - started, 1),
            "items": len(result["analyzed_items"]),
            "truncated": result["truncated"],
            "llm_calls_by_node": calls_by_node(),
            "llm_calls_total": sum(calls_by_node().values()),
            "analyze_by_source": submissions_by_source(),
        },
    )
    return result
