"""Builds a sample to measure classification precision (see docs/scoping.md §7).

Usage: python -m backend.eval.build_sample [--per-source N]
Then : python -m backend.eval.annotate
Then : python -m backend.eval.score

Sizing: the cost is one LLM call per item kept, and it adds to that of the daily run (~148 calls, see
scripts/daily_run.py) against the same daily cap. The script therefore refuses to start a sample it
could not finish, stating the `--per-source` that fits in the remaining budget: better to choose the
sample size deliberately than to suffer it. A smaller sample widens the margin of error on a KPI whose
margin is already wide (§7).
"""

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from backend.agents.analyst import _clean_text, classify_item
from backend.agents.collector import collect
from backend.guardrails import BudgetExceeded, remaining_calls_today

SAMPLE_FILE = Path(__file__).parent / "sample.json"


def _archive_existing() -> None:
    """Sets aside an already annotated sample before replacing it.

    `sample.json` is not versioned: overwriting it would irrecoverably destroy the annotation work
    that underpins the measured precision, and the input of the boundary retests that replay the
    prompt over the disputed items. A measurement cannot be replayed once its sample is gone.
    """
    if not SAMPLE_FILE.exists():
        return
    rows = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))
    annotated = sum(1 for r in rows if r.get("category_gold"))
    if not annotated:
        return
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    archive = SAMPLE_FILE.with_name(f"sample-{stamp}.json")
    archive.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Existing sample ({annotated} annotated items) archived to {archive.name}.\n")


def main(per_source: int) -> None:
    raw = collect({})["raw_items"]

    by_source: dict[str, list] = defaultdict(list)
    for item in raw:
        by_source[item["source"]].append(item)

    selected = [item for items in by_source.values() for item in items[:per_source]]
    print(f"Sample: {len(selected)} items ({per_source} max per source, {len(by_source)} sources)")

    remaining = remaining_calls_today()
    print(f"Budget: {remaining} calls left, {len(selected)} needed.")
    if len(selected) > remaining:
        fits = remaining // max(len(by_source), 1)
        if fits < 1:
            print(
                f"Insufficient budget — sample not built. Fewer than one call per source is left "
                f"({remaining} for {len(by_source)} sources): no stratified sample can be built "
                "today, wait for tomorrow's cap."
            )
        else:
            print(
                f"Insufficient budget — sample not built. Rerun with --per-source {fits} "
                f"(~{fits * len(by_source)} items), or wait for tomorrow's cap."
            )
        return

    rows = []
    try:
        for item in selected:
            try:
                result = classify_item(item)
            except (ValidationError, ValueError):
                # Same handling as the analyze node (backend/agents/analyst.py): the model can return a
                # category outside the enumeration — classify_item attempts a repair
                # (_normalize_category) then raises ValidationError or ValueError if it fails. The item
                # is discarded as unclassifiable. Letting it propagate would lose the whole sample
                # already paid for — which is exactly what happened here before this fix.
                print(f"  [--] {item['source']} — unvalidatable response, discarded — {item['title'][:60]}")
                continue
            rows.append(
                {
                    "id": len(rows),
                    "source": item["source"],
                    "title": item["title"],
                    "text_excerpt": _clean_text(item["raw_text"])[:500],
                    "link": item["link"],
                    "category_system": result.category,
                    "citation": result.citation,
                    "category_gold": None,
                }
            )
            print(f"  [{len(rows) - 1}] {item['source']} — {result.category} — {item['title'][:70]}")
    except BudgetExceeded:
        # Same rule as in the pipeline (docs/scoping.md §8): a cap truncates the work, it does not
        # destroy it. The items already classified cost their call and remain annotatable.
        print(f"\nCap reached after {len(rows)} items: sample truncated, not lost.")

    if not rows:
        print("No item classified — nothing to write.")
        return

    # Archiving here and not before the loop: a run that fails part-way must not leave an orphan
    # archive behind, since it has written nothing to replace.
    _archive_existing()
    SAMPLE_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWritten to {SAMPLE_FILE} ({len(rows)} items).")
    print("Next step (in an interactive terminal): python -m backend.eval.annotate")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-source", type=int, default=6)
    args = parser.parse_args()
    main(args.per_source)
