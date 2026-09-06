"""Metrics over the annotated pairs: threading quality, and threshold calibration (§7, §10 V3).

Usage: python -m backend.eval.score_pairs

Two distinct readings, not to be confused:

- **Threading precision** — of the pairs the model actually grouped, what share really is about the
  same story. That is the acceptance criterion of §10 V3 slice 1, and it is a precision figure alone:
  recall (the stories the model did not bring together) is not measurable on this sample, which only
  contains what it did bring together. Say so, rather than letting a high precision read as "threading
  works".
- **Threshold calibration** — among candidate pairs, at what IDF score the rate of true matches
  collapses. The sample being stratified by band (not drawn uniformly), the rates are reweighted by
  the real population of each band: without that, the high bands, deliberately over-sampled, would
  swamp the measurement.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

PAIRS_FILE = Path(__file__).parent / "pairs.json"

# Same encoding fix as score.py: the Windows console runs cp1252.
sys.stdout.reconfigure(encoding="utf-8")

# Below this number of annotated pairs in a band, the rate is displayed but flagged: at two or three
# pairs, a single judgement flips it from 0 to 1. Hiding it would suggest the band was not evaluated,
# when the problem is the volume.
MIN_SUPPORT = 5

THRESHOLDS = (10, 15, 20, 25, 30, 40)


def _rate(yes: int, total: int) -> str:
    return f"{100 * yes / total:5.1f}%" if total else "    — "


def _print_threading(rows: list[dict]) -> None:
    threads = [r for r in rows if r["kind"] == "thread" and r["same_story"] is not None]
    if not threads:
        print("No intra-thread pair annotated — V3 slice 1 acceptance criterion not measured.\n")
        return

    yes = sum(1 for r in threads if r["same_story"] is True)
    no = sum(1 for r in threads if r["same_story"] is False)
    unsure = sum(1 for r in threads if r["same_story"] == "unsure")

    print("=== V3 slice 1 acceptance criterion — threading precision ===")
    print(f"  intra-thread pairs annotated: {len(threads)}")
    print(f"  same story: {yes}   different stories: {no}   unsure: {unsure}")
    print(f"  precision: {_rate(yes, yes + no)}")
    print("  The 'unsure' verdicts leave the denominator, and are never counted as successes.")
    print("  Precision alone: recall is not measurable here — a story the model did not bring")
    print("  together produces no pair to annotate.\n")

    faulty = [r for r in threads if r["same_story"] is not True]
    if faulty:
        print("  Disputed pairs, by thread:")
        for r in faulty:
            verdict = "unsure" if r["same_story"] == "unsure" else "different stories"
            print(f"    [{r['id']}] thread {r['thread_id'][:8]} — {verdict}")
            print(f"        A: {r['a']['title_en'][:78]}")
            print(f"        B: {r['b']['title_en'][:78]}")
        print()


def _print_calibration(rows: list[dict]) -> None:
    gate = [r for r in rows if r["kind"] == "gate" and r["same_story"] is not None]
    if not gate:
        print("No gate pair annotated — threshold cannot be calibrated.\n")
        return

    by_band: dict[str, list[dict]] = defaultdict(list)
    for row in gate:
        by_band[row["band"]].append(row)

    def band_low(label: str) -> float:
        return float(label.split("-")[0])

    print("=== Escalation threshold calibration — rate of true matches per band ===")
    print(f"  {'band':>10} {'annotated':>10} {'same story':>12} {'rate':>8} {'population':>11}")
    stats = {}
    for label in sorted(by_band, key=band_low):
        bucket = by_band[label]
        yes = sum(1 for r in bucket if r["same_story"] is True)
        decided = sum(1 for r in bucket if r["same_story"] is not True and r["same_story"] != "unsure") + yes
        population = bucket[0]["band_population"]
        flag = " *" if decided < MIN_SUPPORT else ""
        print(f"  {label:>10} {len(bucket):>10} {yes:>12} {_rate(yes, decided):>8} {population:>11}{flag}")
        stats[label] = (yes, decided, population)
    print(f"  (* fewer than {MIN_SUPPORT} decided pairs in the band — rate inconclusive)\n")

    print("=== Effect of a threshold, extrapolated to the real population of the bands ===")
    print("  The rate measured per band is applied to its population: the sample is stratified, so a")
    print("  raw count would over-weight the high bands, drawn at a higher rate.")
    print(f"\n  {'thresh.':>8} {'pairs escalated':>17} {'estimated true matches':>24} {'estimated precision':>21}")
    for threshold in THRESHOLDS:
        kept = [(label, s) for label, s in stats.items() if band_low(label) >= threshold]
        population = sum(s[2] for _, s in kept)
        estimated = sum(s[2] * (s[0] / s[1]) for _, s in kept if s[1])
        precision = f"{100 * estimated / population:5.1f}%" if population else "    — "
        print(f"  {'>= ' + str(threshold):>8} {population:>17} {estimated:>24.0f} {precision:>21}")
    print()


def main() -> None:
    if not PAIRS_FILE.exists():
        print("No sample. Run this first: python -m backend.eval.build_pairs")
        return

    rows = json.loads(PAIRS_FILE.read_text(encoding="utf-8"))
    annotated = [r for r in rows if r["same_story"] is not None]

    if not annotated:
        print("No annotated pair. Run this first: python -m backend.eval.annotate_pairs")
        return
    if len(annotated) < len(rows):
        print(f"Warning: {len(rows) - len(annotated)} pairs not annotated, ignored in the computation.\n")

    _print_threading(rows)
    _print_calibration(rows)


if __name__ == "__main__":
    main()
