"""Replays the `thread` node alone over already analysed items, without going through the full chain.

**Rationale.** The LLM budget is a single global counter (backend/guardrails.py) and `thread` is the
last node of the graph: when the daily cap falls, it is the one that absorbs the whole shortfall.
Experienced on 2026-08-21, the first run to reach 200 calls — 17 items cleared the threader's gate,
only 3 were attached, the other 14 never having been submitted to the model. Relaunching the whole
pipeline to catch them up is the wrong tool: deduplication discards items already seen, so collection
does not bring them back, and a full run costs the entire budget. This script picks the batch up where
it was cut, for the cost of threading alone (62 calls for 36 items on 2026-08-21, against 200 for a
full run).

**What it is not.** An operator tool, like scripts/daily_run.py: imported by no node, absent from
production (where an untruncated run makes this catch-up unnecessary), and with no state of its own —
it writes to the history through the same `record_analyzed` as the node does in production, never
directly. Nor does it replay the analysis: the items must already carry category/summary/citation/
location, and therefore have been through `analyze` and `verify`.

**Why it skips items already instrumented.** Re-escalating an item whose `has_thread_candidate` is
already written would pay for calls to rewrite correct fields. The history window stays whole on the
threader side: an item skipped here remains a candidate for the others to attach to.

Usage:
    python -m scripts.replay_thread                # the day's items not yet instrumented
    python -m scripts.replay_thread --dry-run      # gate probe only, no LLM call
    python -m scripts.replay_thread --day 2026-08-21 --all
"""

import argparse
import json
from datetime import date

from backend.agents.threader import thread_events
from backend.config import (
    MAX_THREAD_ESCALATIONS_PER_RUN,
    MAX_THREAD_STEPS_PER_ITEM,
    THREAD_GATE_MIN_SCORE,
)
from backend.guardrails import remaining_calls_today
from backend.memory.store import analyzed_window, search_thread_candidates


def items_for(day: str, skip_instrumented: bool = True) -> list[dict]:
    """The analysed items of a given day, minus those a run has already instrumented."""
    batch = [r for r in analyzed_window().values() if (r.get("date") or "")[:10] == day]
    if skip_instrumented:
        batch = [r for r in batch if "has_thread_candidate" not in r]
    return batch


def main(day: str, dry_run: bool, include_all: bool) -> int:
    batch = items_for(day, skip_instrumented=not include_all)
    print(f"Day {day}: {len(batch)} item(s) to process.")
    print(f"Budget: {remaining_calls_today()} call(s) left today.")
    if not batch:
        print("Nothing to replay — every item of the day already carries the threader's instrumentation.")
        return 0

    # The same probe as the node, at the same threshold: what the gate will retain, spending nothing.
    eligible = [
        item
        for item in batch
        if search_thread_candidates(
            f"{item['title_en']} {item['summary']}",
            exclude_link=item["link"],
            limit=1,
            min_score=THREAD_GATE_MIN_SCORE,
        )
    ]
    escalations = min(len(eligible), MAX_THREAD_ESCALATIONS_PER_RUN)
    print(f"Gate (>= {THREAD_GATE_MIN_SCORE}) cleared by {len(eligible)}/{len(batch)} item(s).")
    print(f"Escalations: {escalations} (cap {MAX_THREAD_ESCALATIONS_PER_RUN}).")
    print(f"Cost: {escalations * 2} call(s) at best, {escalations * (MAX_THREAD_STEPS_PER_ITEM + 1)} at worst.")

    if dry_run:
        print("\n--dry-run: node not executed, no LLM call.")
        return 0

    if escalations * 2 > remaining_calls_today():
        # The node would know how to stop (BudgetExceeded is caught and leaves thread_checked at
        # False), but a replay that knows in advance it will be truncated is pointless: it would have
        # to be rerun.
        print("\nBudget too low even for the escalation floor: replay not launched.")
        return 1

    result = thread_events({"raw_items": [], "analyzed_items": batch, "truncated": False})
    out = result["analyzed_items"]

    threads: dict[str, list[str]] = {}
    for item in out:
        if item.get("thread_id"):
            threads.setdefault(item["thread_id"], []).append(item["title_en"])

    print("\n-- result --")
    print(f"Gate cleared: {sum(1 for i in out if i.get('has_thread_candidate'))}")
    print(f"Examined by the model: {sum(1 for i in out if i.get('thread_checked'))}")
    print(f"Attached: {sum(1 for i in out if i.get('thread_id'))}/{len(out)}")
    print(f"Truncated: {result['truncated']} — budget left: {remaining_calls_today()}")
    print(json.dumps(threads, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--day", default=date.today().isoformat(), help="target day (default: today)")
    parser.add_argument("--dry-run", action="store_true", help="gate probe only, no LLM call")
    parser.add_argument("--all", action="store_true", help="include items already instrumented")
    args = parser.parse_args()
    raise SystemExit(main(args.day, args.dry_run, args.all))
