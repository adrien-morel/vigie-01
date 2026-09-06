"""Freezes a sample of item pairs to be annotated by hand (see docs/scoping.md §7, §10 V3).

Two measurements were pending. They bear on the same question — do these two items deal with the same
story? — and are therefore answered on a single sample:

1. **V3 slice 1 acceptance criterion** (§10): "a thread only brings together items about the same
   story (same parties, same operation)". Every pair actually grouped by the model is included, with
   no sampling: they are few and they are exactly the ones the criterion judges. This is a measurement
   of threading precision, not of recall — a story the model failed to bring together does not appear
   here.
2. **Escalation threshold calibration** (§10, arbitration on extending the verifier): pairs are
   sampled by IDF score band, so that one can read at what score the rate of true matches collapses.
   Without annotation spread across the whole scale, a threshold would remain a judgement call — which
   is precisely what the accumulation campaign was meant to avoid. The 2026-08-18 measurement had
   established that the current gate (at least one shared token) lets 100% of items through: it
   filters nothing, and only `MAX_THREAD_ESCALATIONS_PER_RUN` bounds the cost.

**Why freeze the sample.** Since 2026-08-20, retention is 7 days (`RELATED_ITEMS_WINDOW_DAYS`): the
history this measurement bears on is purged continuously, the oldest day disappearing on every run. A
sample rebuilt later would not cover the same corpus and would not be comparable; rebuilt a week
later, it would find none of today's items. The file produced is therefore a self-contained copy — it
carries everything needed to annotate and score without re-reading the history, exactly as
`sample.json` does for classification precision.

No LLM call: the overlap score is deterministic, and the judgement is human.

Usage: python -m backend.eval.build_pairs [--per-band N] [--days N]
Then : python -m backend.eval.annotate_pairs
Then : python -m backend.eval.score_pairs
"""

import argparse
import json
import random
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from itertools import combinations
from pathlib import Path

from backend.memory.persistence import get_persistence
from backend.memory.store import RELATED_ITEMS_WINDOW_DAYS

from .candidates import weighted_pairs

PAIRS_FILE = Path(__file__).parent / "pairs.json"

# IDF score bands. Bounds taken from the `candidates.py` report so that the annotation reads against
# its escalation rates, and tightened between 15 and 30 where the report locates the tipping point
# (67% of items at 15, 12% at 30): that is where the threshold will be decided, so that is where
# signal is needed.
BANDS = ((0, 10), (10, 15), (15, 20), (20, 25), (25, 30), (30, 40), (40, float("inf")))

# Reproducible draw: the sample must be replayable identically to settle a disputed annotation. An
# unseeded random draw would make the measurement depend on the execution.
SEED = 20260820


def _side(record: dict) -> dict:
    """Self-contained copy of an item, one side of a pair — annotation must not re-read the history."""
    return {
        "title_en": record.get("title_en", ""),
        "summary": record.get("summary", ""),
        "source": record.get("source", ""),
        "date": record.get("date", ""),
        "category": record.get("category", ""),
        "country": record.get("country", ""),
        "link": record.get("link", ""),
    }


def _archive_existing() -> None:
    """Sets aside an already annotated sample before replacing it.

    Same rule as `build_sample.py`: the annotation work underpins the measurement, overwriting it
    would make it unreplayable. The reason is stronger here — the original history being purged within
    7 days, a lost sample could not be rebuilt, not even identically.
    """
    if not PAIRS_FILE.exists():
        return
    rows = json.loads(PAIRS_FILE.read_text(encoding="utf-8"))
    annotated = sum(1 for r in rows if r.get("same_story") is not None)
    if not annotated:
        return
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    archive = PAIRS_FILE.with_name(f"pairs-{stamp}.json")
    archive.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Existing sample ({annotated} annotated pairs) archived to {archive.name}.\n")


def _thread_rows(history: list[dict], weight_by_link: dict[frozenset, float]) -> list[dict]:
    """Every intra-thread pair, with no sampling.

    With no date filter, unlike the gate pairs: the threader does not hide the current batch (a
    deliberate divergence documented in CLAUDE.md), so two items from the same day can legitimately
    share a thread — excluding them would remove the most frequent case from the measurement.
    """
    by_thread: dict[str, list[dict]] = defaultdict(list)
    for record in history:
        if record.get("thread_id"):
            by_thread[record["thread_id"]].append(record)

    rows = []
    for thread_id, items in sorted(by_thread.items()):
        for a, b in combinations(sorted(items, key=lambda r: (r.get("date", ""), r.get("link", ""))), 2):
            key = frozenset((a.get("link", ""), b.get("link", "")))
            rows.append(
                {
                    "kind": "thread",
                    "thread_id": thread_id,
                    "thread_size": len(items),
                    # None (and not 0) when the pair is absent from the gate computation: same-date
                    # pairs do not appear there, and giving them 0 would make them look like pairs
                    # with no shared token at all, which is false.
                    "idf_weight": weight_by_link.get(key),
                    "shared_tokens": [],
                    "a": _side(a),
                    "b": _side(b),
                    "same_story": None,
                }
            )
    return rows


def _gate_rows(history: list[dict], pairs: list[tuple], per_band: int) -> list[dict]:
    """Pairs sampled by score band, to read where the threshold should fall."""
    by_band: dict[tuple, list[tuple]] = defaultdict(list)
    for pair in pairs:
        for band in BANDS:
            if band[0] <= pair[0] < band[1]:
                by_band[band].append(pair)
                break

    rng = random.Random(SEED)
    rows = []
    for band in BANDS:
        bucket = by_band.get(band, [])
        # High bands are often less populated than `per_band`: we take everything rather than leave an
        # annotation gap exactly where the threshold is decided.
        chosen = bucket if len(bucket) <= per_band else rng.sample(bucket, per_band)
        for weight, i, j, shared in sorted(chosen, key=lambda p: -p[0]):
            rows.append(
                {
                    "kind": "gate",
                    "band": f"{band[0]}-{'inf' if band[1] == float('inf') else band[1]}",
                    "band_population": len(bucket),
                    "idf_weight": round(weight, 2),
                    "shared_tokens": sorted(shared)[:12],
                    "a": _side(history[i]),
                    "b": _side(history[j]),
                    "same_story": None,
                }
            )
    return rows


def main(per_band: int, days: int) -> None:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    history = get_persistence().analyzed_since(cutoff)
    if len(history) < 2:
        print(f"History too short ({len(history)} item(s)): nothing to sample.")
        return

    _, pairs = weighted_pairs(history)
    weight_by_link = {
        frozenset((history[i].get("link", ""), history[j].get("link", ""))): weight for weight, i, j, _ in pairs
    }

    rows = _thread_rows(history, weight_by_link) + _gate_rows(history, pairs, per_band)
    for index, row in enumerate(rows):
        row["id"] = index

    threads = sum(1 for r in rows if r["kind"] == "thread")
    print(f"History: {len(history)} items, {len(pairs)} pairs of distinct dates.")
    print(f"Sample: {len(rows)} pairs — {threads} intra-thread, {len(rows) - threads} by score band.\n")
    for band in BANDS:
        label = f"{band[0]}-{'inf' if band[1] == float('inf') else band[1]}"
        chosen = sum(1 for r in rows if r.get("band") == label)
        population = next((r["band_population"] for r in rows if r.get("band") == label), 0)
        print(f"  band {label:>8}: {chosen:3d} annotated out of {population} pairs")

    _archive_existing()
    PAIRS_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWritten to {PAIRS_FILE} ({len(rows)} pairs).")
    print("Next step (interactive terminal): python -m backend.eval.annotate_pairs")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-band", type=int, default=8, help="pairs drawn per score band")
    parser.add_argument("--days", type=int, default=RELATED_ITEMS_WINDOW_DAYS, help="history window")
    args = parser.parse_args()
    main(args.per_band, args.days)
