"""Computes the classification metrics over the annotated sample (see docs/scoping.md §7).

Usage: python -m backend.eval.score

Overall precision alone is misleading on this sample: nearly half the reference items are
`out_of_scope`, so it mostly measures the perimeter gate and drowns three errors of very different
natures — letting an out-of-scope item through (which pollutes the digest), discarding an in-scope
item (a silent loss, invisible on screen), and filing an in-scope item under the wrong category
(visible and recoverable by the analyst). It is still displayed as such to stay comparable to the
figure tracked in the scoping document, but the three views that follow are the ones that say what to
fix.
"""

import json
import sys
from collections import Counter
from pathlib import Path

SAMPLE_FILE = Path(__file__).parent / "sample.json"

# Output forced to UTF-8: the Windows console runs cp1252, where ">=" glyphs and the matrix characters
# do not exist — the script used to crash after its first line. Same failure mode as the one already
# fixed on file reads and writes, but on stdout, which the `encoding="utf-8"` convention did not cover.
sys.stdout.reconfigure(encoding="utf-8")

OUT_OF_SCOPE = "out_of_scope"

# Short codes for the confusion matrix: full labels would make the columns unreadable at six
# categories.
SHORT = {
    "out_of_scope": "OS",
    "arms_contract": "AC",
    "export_control": "EC",
    "industrial_program": "IP",
    "military_movement": "MM",
    "defense_diplomacy": "DD",
}

# Below this number of reference items, a per-category precision or recall is reported with a warning:
# at one or two items, a single annotation judgement takes the F1 from 0 to 1. The figure is displayed
# anyway — hiding it would suggest the category was not evaluated, when the problem is the volume.
MIN_SUPPORT = 5


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def _print_scope_gate(annotated: list[dict]) -> None:
    """The perimeter seen as a binary "keep or not" decision, which is what the product actually
    commits to: an out-of-scope item filed under the wrong in-scope category is still an undue entry
    in the digest, whatever the category."""
    tp = sum(1 for r in annotated if r["category_system"] != OUT_OF_SCOPE and r["category_gold"] != OUT_OF_SCOPE)
    fp = sum(1 for r in annotated if r["category_system"] != OUT_OF_SCOPE and r["category_gold"] == OUT_OF_SCOPE)
    fn = sum(1 for r in annotated if r["category_system"] == OUT_OF_SCOPE and r["category_gold"] != OUT_OF_SCOPE)
    precision, recall, f1 = _prf(tp, fp, fn)

    print("Perimeter gate (kept for the digest vs discarded)")
    print(f"  precision: {precision:.0%}  — of what the system keeps, the share that is genuinely in scope")
    print(f"  recall   : {recall:.0%}  — of what is in scope, the share the system keeps")
    print(f"  F1       : {f1:.2f}")
    print(f"  {fp} out-of-scope item(s) wrongly kept, {fn} in-scope item(s) wrongly discarded.\n")


def _print_per_category(annotated: list[dict]) -> None:
    gold = Counter(r["category_gold"] for r in annotated)
    system = Counter(r["category_system"] for r in annotated)
    correct = Counter(r["category_gold"] for r in annotated if r["category_system"] == r["category_gold"])

    print(f"Per category ({'*'} = fewer than {MIN_SUPPORT} reference items, figure inconclusive)")
    print(f"  {'category':22} {'ref.':>5} {'prec.':>6} {'recall':>7} {'F1':>5}")
    for category in sorted(gold | system, key=lambda c: -gold[c]):
        tp = correct[category]
        precision, recall, f1 = _prf(tp, system[category] - tp, gold[category] - tp)
        flag = " *" if gold[category] < MIN_SUPPORT else ""
        print(f"  {category:22} {gold[category]:>5} {precision:>5.0%} {recall:>6.0%} {f1:>5.2f}{flag}")
    print()


def _print_confusion(annotated: list[dict]) -> None:
    """The full matrix rather than just a count of disagreements: it is the *direction* of the error
    that points to the prompt fix — confusing two in-scope categories with each other and letting
    out-of-scope material in are not corrected in the same place."""
    labels = sorted(SHORT, key=lambda c: c != OUT_OF_SCOPE)
    matrix = Counter((r["category_gold"], r["category_system"]) for r in annotated)

    print("Confusion matrix (rows = reference, columns = system)")
    print(f"  {'':6}" + "".join(f"{SHORT[c]:>5}" for c in labels))
    for row in labels:
        cells = "".join(f"{matrix[(row, col)] or '·':>5}" for col in labels)
        print(f"  {SHORT[row]:6}{cells}")
    print("  " + ", ".join(f"{SHORT[c]}={c}" for c in labels) + "\n")


def main() -> None:
    rows = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))
    annotated = [r for r in rows if r["category_gold"] is not None]

    if not annotated:
        print("No annotated item. Run this first: python -m backend.eval.annotate")
        return
    if len(annotated) < len(rows):
        print(f"Warning: {len(rows) - len(annotated)} items not annotated, ignored in the computation.\n")

    correct = sum(1 for r in annotated if r["category_system"] == r["category_gold"])
    precision = correct / len(annotated)

    print(f"Overall precision: {correct}/{len(annotated)} = {precision:.0%}")
    print(f"(scoping §7 target: >= 85% — sample of {len(annotated)} items, wide margin of error at that volume)")
    print("Accuracy across all categories, out_of_scope included — see the module header.\n")

    _print_scope_gate(annotated)
    _print_per_category(annotated)
    _print_confusion(annotated)

    disagreements = [r for r in annotated if r["category_system"] != r["category_gold"]]
    if disagreements:
        print("Disagreements (system -> actual):")
        for r in disagreements:
            print(f"  [{r['id']}] system={r['category_system']!r} actual={r['category_gold']!r} — {r['title'][:60]}")
    else:
        print("No disagreement on this sample.")


if __name__ == "__main__":
    main()
