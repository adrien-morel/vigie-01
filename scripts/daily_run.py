"""Daily launch of the pipeline during the history accumulation campaign.

**Intent.** The arbitration on extending the verifier (docs/scoping.md §10, V2) and the first slice of
V3 (event threads) both depend on a question we cannot yet settle: how many items really have a
neighbour about the same story? The measurement was attempted on 3 days of history
(`python -m backend.eval.candidates`) and concluded the base was too thin — 2 to 4 real matches over
102 items, too few to calibrate or validate a threshold. Two dispatches about the same story 48 h
apart are rare by construction. A fortnight of continuous history was therefore needed before
replaying the measurement and deciding.

This script is the tool of that campaign: one launch a day, by hand, until the base is sufficient. It
is not meant to outlive the campaign — in production, triggering goes through Cloud Scheduler ->
Cloud Run (see backend/api/main.py).

**Closure (2026-08-20).** The campaign stops at five launches and seven days of continuous history
(2026-08-14 -> 2026-08-20, 261 items), short of the fifteen-day base targeted above — an explicit
decision to move on to evaluation, retention having been brought down the same day to 7 days
(`RELATED_ITEMS_WINDOW_DAYS`, see backend/memory/store.py) to limit storage cost. The sliding history
can therefore no longer exceed that depth: the fifteen-day base is now unreachable by construction,
not merely postponed.

**The measurement was taken nonetheless, over seven days.** Replayed on 2026-08-20 over the 261 items
(`python -m backend.eval.candidates`), it gives a signal the 102 items of three days did not: at an
IDF-weighted threshold of >= 40, 8 items out of 261 (3.1%) would be escalated, and reading the best
pairs by hand finds a majority of genuine story matches where the previous measurement found only 2
to 4 across the whole sample. The "base too thin" conclusion therefore no longer holds at this size —
but a threshold is not set by eyeballing eight pairs. Calibration proper goes through
`backend/eval/build_pairs.py`, which freezes a sample of pairs stratified by score band: that is what
now carries the decision, and it had to be built that day precisely because the 7-day purge erases the
measured corpus.

The script remains usable for a one-off launch, but is no longer steered towards the original target.

**Why a log, and why it cannot be deduced from the analysed history.** A day with no new item
(everything discarded by deduplication) and a day when the launch was forgotten leave exactly the same
trace in `.analyzed_history.json`: none. The first is a measurement — the feed published nothing new
in the perimeter — the second is a hole. Conflating them would distort the reading of the campaign at
decision time: a history that is sparse because the corpus is poor does not call for the same
conclusion as a history that is sparse because the operator skipped four days. The log therefore
records *every launch*, including those that produce nothing and those that fail.

**Collection window and unrecoverable holes.** `COLLECTION_LOOKBACK_HOURS` (96 h since 2026-08-17;
48 h originally, raised once the cost was covered by a per-source cap rather than by time — see
backend/config.py) bounds what a collection can catch up on. A skipped day is therefore recovered by
the next launch; consecutive skipped days beyond that window permanently lose the items published in
the uncovered interval. The script measures the gap since the last logged launch and flags it — the
information is only useful at the moment it is observed, and it must stay attached to the run in the
log.

**Why the log does not go through backend/memory/persistence.py.** The project invariant (CLAUDE.md)
is that all *business state* surviving a run goes through the persistence layer. This log is not
business state: it does not describe the product but the way it is operated, it is read by no pipeline
node, it does not ship to production, and it must stay readable even when persistence is precisely
what failed. A deliberately local file, outside the abstraction.

Usage:
    python -m scripts.daily_run              # the daily launch
    python -m scripts.daily_run --dry-run    # campaign status, without running the pipeline
"""

import argparse
import json
import sys
import time
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from backend.agents.analyst import submissions_by_source
from backend.agents.collector import source_freshness
from backend.config import (
    COLLECTION_LOOKBACK_HOURS,
    MAX_ITEMS_PER_SOURCE_PER_RUN,
    MAX_LLM_CALLS_PER_DAY,
    SOURCES,
)
from backend.graph import run_pipeline
from backend.guardrails import calls_by_node, remaining_calls_today
from backend.memory.persistence import get_persistence
from backend.memory.store import RELATED_ITEMS_WINDOW_DAYS

# JSONL rather than JSON: a launch only has to append a line, without re-reading or rewriting the
# file — a crash mid-write cannot corrupt the launches already logged.
LOG_FILE = Path(__file__).resolve().parent / ".run_log.jsonl"


def _s(count: int) -> str:
    """Plural marker for the operational output."""
    return "s" if count > 1 else ""


def _read_log() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    entries = []
    for line in LOG_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def _append_log(entry: dict) -> None:
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _history_shape() -> tuple[int, dict[str, int]]:
    """Size and per-day distribution of the analysed history, inside the retention window.

    Read through the persistence layer, like backend/eval/candidates.py: the campaign must read back
    identically if storage moves to Firestore.
    """
    cutoff = (date.today() - timedelta(days=RELATED_ITEMS_WINDOW_DAYS)).isoformat()
    records = get_persistence().analyzed_since(cutoff)
    return len(records), dict(sorted(Counter(r.get("date", "?") for r in records).items()))


def _hours_since_last(entries: list[dict]) -> float | None:
    for entry in reversed(entries):
        started = entry.get("started_at")
        if started:
            return (datetime.now(UTC) - datetime.fromisoformat(started)).total_seconds() / 3600
    return None


def _print_campaign(entries: list[dict]) -> None:
    if not entries:
        print("\nCampaign: no launch logged yet.")
        return
    days = {e["started_at"][:10] for e in entries if e.get("started_at")}
    failed = sum(1 for e in entries if e.get("error"))
    truncated = sum(1 for e in entries if e.get("truncated"))
    holes = sum(1 for e in entries if e.get("lookback_exceeded"))
    first = min(days) if days else "?"
    print(
        f"\nCampaign since {first}: {len(entries)} launch{'es' if len(entries) > 1 else ''} "
        f"over {len(days)} distinct day{_s(len(days))} — "
        f"failures: {failed}, truncated by budget: {truncated}, "
        f"holes beyond {COLLECTION_LOOKBACK_HOURS} h: {holes}."
    )
    print(f"Log: {LOG_FILE}")


def main(dry_run: bool) -> int:
    entries = _read_log()
    gap_hours = _hours_since_last(entries)
    remaining_before = remaining_calls_today()
    history_before, by_date_before = _history_shape()

    print(f"Budget: {remaining_before}/{MAX_LLM_CALLS_PER_DAY} calls left today.")
    print(
        f"History: {history_before} item{_s(history_before)} "
        f"over {len(by_date_before)} day{_s(len(by_date_before))} — {by_date_before}"
    )

    # "Active" means "produced a recent item", not "the feed parses without error" — a dead feed
    # (OFAC, ~1 year with no new entry before being detected by this very check) went unnoticed by the
    # coverage KPI (docs/scoping.md §7) as long as the test was the latter. RSS reading only, no budget
    # cost.
    freshness = source_freshness()
    # Three states, not two: `None` flags an unreachable feed, and counting it as silent would make a
    # network outage look like a dead feed — exactly the reverse of the OFAC diagnosis.
    unavailable = sorted(name for name, count in freshness.items() if count is None)
    silent = sorted(name for name, count in freshness.items() if count == 0)
    active_count = len(SOURCES) - len(silent) - len(unavailable)
    print(f"Coverage: {active_count}/{len(SOURCES)} sources active within {COLLECTION_LOOKBACK_HOURS} h.")
    if silent:
        print(f"  Silent: {', '.join(silent)}")
    if unavailable:
        print(f"  Unreachable: {', '.join(unavailable)}")

    # The counterpart of the per-source cap, worth logging because it is invisible everywhere else:
    # `source_freshness()` measures the volume *before* capping, collection keeps only the most recent
    # ones, and nothing in the analysed history then distinguishes "the source published nothing" from
    # "we discarded its feed tail". Without this figure, the coverage KPI (§7) overstates what the
    # campaign actually saw, and the base of the coming evaluation is not interpretable — the same
    # rationale as the launch log itself.
    dropped = {
        source.name: freshness[source.name] - (source.max_per_run or MAX_ITEMS_PER_SOURCE_PER_RUN)
        for source in SOURCES
        if freshness[source.name] is not None
        and freshness[source.name] > (source.max_per_run or MAX_ITEMS_PER_SOURCE_PER_RUN)
    }
    if dropped:
        total = sum(dropped.values())
        detail = ", ".join(f"{name} (-{count})" for name, count in sorted(dropped.items(), key=lambda p: -p[1]))
        print(f"  Dropped by the per-source cap: {total} item{_s(total)} across {len(dropped)} feeds — {detail}")

    if gap_hours is None:
        print("No launch logged before: start of campaign.")
    else:
        print(f"Last launch {gap_hours:.1f} h ago.")
        if gap_hours > COLLECTION_LOOKBACK_HOURS:
            print(
                f"  /!\\ Beyond the collection window ({COLLECTION_LOOKBACK_HOURS} h): the items "
                "published in the uncovered interval are permanently lost. A hole to remember when "
                "reading the campaign back — the history alone will not show it."
            )

    # ~110 items/day at ~1 call each: below this threshold the run will be truncated. That is not an
    # error (the run stays a partial success, see docs/scoping.md §8) but it is worth knowing before,
    # not after.
    if remaining_before < 110:
        print("  Budget too low for a full batch: the run will probably be truncated.")

    if dry_run:
        print("\n--dry-run: pipeline not launched.")
        _print_campaign(entries)
        return 0

    started = datetime.now(UTC)
    clock = time.monotonic()
    analyzed, truncated, error = 0, False, None
    by_node: dict[str, int] = {}
    by_source: dict[str, dict[str, int]] = {}
    try:
        result = run_pipeline()
        analyzed = len(result["analyzed_items"])
        truncated = result["truncated"]
        # Read after the run, before any other call: this is the split of *this* run between nodes.
        # Without it, we know a global cap truncated the batch but not which node consumed what — so
        # arbitrating the split stayed impossible (docs/scoping.md §11).
        by_node = calls_by_node()
        # The counterpart of the previous one on the `analyze` side: the per-node split says *how much*
        # that node spent, this one says on *what*. Both are needed — an expensive `analyze` because
        # the batch is large and an expensive `analyze` because one feed fills the batch with off-topic
        # items do not call for the same budget arbitration.
        by_source = submissions_by_source()
    except Exception as exc:  # noqa: BLE001 — see below
        # Deliberately broad catch: an unlogged failure is precisely the hole this log exists to
        # avoid. The exception is recorded, then surfaced through the exit code.
        error = f"{type(exc).__name__}: {exc}"

    duration = time.monotonic() - clock
    remaining_after = remaining_calls_today()
    history_after, by_date_after = _history_shape()

    # The budget counter is daily: a run straddling midnight starts again from the full cap and the
    # difference stops meaning anything. Asserting nothing beats a wrong figure.
    consumed = remaining_before - remaining_after
    llm_calls = consumed if consumed >= 0 else None

    entry = {
        "started_at": started.isoformat(),
        "duration_s": round(duration, 1),
        "analyzed": analyzed,
        "truncated": truncated,
        "llm_calls": llm_calls,
        "llm_calls_by_node": by_node,
        "analyze_by_source": by_source,
        "history_before": history_before,
        "history_after": history_after,
        "history_by_date": by_date_after,
        "gap_hours": round(gap_hours, 1) if gap_hours is not None else None,
        "lookback_exceeded": gap_hours is not None and gap_hours > COLLECTION_LOOKBACK_HOURS,
        "sources_active": active_count,
        "sources_targeted": len(SOURCES),
        "sources_silent": silent,
        "sources_unavailable": unavailable,
        "error": error,
    }
    _append_log(entry)

    print()
    if error:
        print(f"FAILED after {duration:.0f} s: {error}")
    else:
        print(
            f"Run finished in {duration:.0f} s — {analyzed} item{_s(analyzed)} kept"
            f"{', run truncated by the budget' if truncated else ''}."
        )
    print(
        f"History: {history_before} -> {history_after} item{_s(history_after)} "
        f"over {len(by_date_after)} day{_s(len(by_date_after))}."
    )
    print(f"LLM calls consumed: {llm_calls if llm_calls is not None else 'undetermined (day changed)'}.")
    if by_node:
        # The per-node total can be lower than `llm_calls` if another process consumed budget during
        # the run: the two figures do not measure the same thing (this run vs. the day), and forcing
        # them to reconcile would hide precisely that case.
        detail = ", ".join(f"{node} {count}" for node, count in sorted(by_node.items(), key=lambda p: -p[1]))
        print(f"  Split by node: {detail} (total {sum(by_node.values())}).")
    if by_source:
        outcomes = Counter()
        for tally in by_source.values():
            outcomes.update(tally)
        submitted = sum(outcomes.values())
        wasted = submitted - outcomes.get("kept", 0)
        share = f"{100 * wasted / submitted:.0f}%" if submitted else "—"
        print(
            f"  Submitted to analysis: {submitted} item{_s(submitted)} for {outcomes.get('kept', 0)} "
            f"kept — {wasted} call{_s(wasted)} ({share}) on discarded items."
        )
        reasons = ", ".join(
            f"{name} {count}" for name, count in sorted(outcomes.items(), key=lambda p: -p[1]) if name != "kept"
        )
        if reasons:
            print(f"    Reasons: {reasons}")
        # The top five only: the full breakdown goes to the log, this line is here just to see at once
        # whether the discarded spend is concentrated or diffuse.
        worst = sorted(
            ((source, sum(t.values()) - t.get("kept", 0)) for source, t in by_source.items()),
            key=lambda p: -p[1],
        )[:5]
        detail = ", ".join(f"{source} (-{count})" for source, count in worst if count)
        if detail:
            print(f"    Largest contributors: {detail}")
    _print_campaign(entries + [entry])

    return 1 if error else 0


if __name__ == "__main__":
    # The default Windows console (cp1252) has no "—"; the operational output uses that kind of
    # character and there is no reason to impoverish it for that one terminal.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the campaign status and exit, without running the pipeline or consuming budget",
    )
    args = parser.parse_args()
    raise SystemExit(main(args.dry_run))
