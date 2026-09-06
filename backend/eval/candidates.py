"""Measures the density of cross-check candidates in the analysed history, with no LLM call at all.

The question this script answers: how many items have, in the history, at least one neighbour dealing
with the same story? That is the figure that arbitrates extending the verifier (docs/scoping.md §10,
V2) — either raise the caps to score every item, or restrict escalation to the items that really have
a candidate, or accept partial coverage. Escalating an item the history has nothing to say about costs
1 to 3 calls to produce a non-answer.

The overlap is computed with the product's real function (`store._tokenize`), not with a copy: a
measurement that drifted from the implementation it measures would be worthless. Three variants are
compared, from the most naive to the most weighted, plus a gate on the structured fields already
extracted and verified verbatim.

The history is read through the persistence layer, not through direct file access: the measurement
therefore works identically on the local backend and on Firestore.

Usage: python -m backend.eval.candidates [--pairs N] [--days N]
"""

import argparse
import math
import re
from collections import Counter
from datetime import date, timedelta

from backend.memory.persistence import get_persistence

# A deliberate import of a private name: the point is to measure the real behaviour of
# search_related(), not that of a reimplementation that would drift at the first change to store.py.
from backend.memory.store import RELATED_ITEMS_WINDOW_DAYS, _tokenize

# English/French stop words: they pass the real tokenizer's `len > 2` filter and create overlap
# between two items that have nothing in common. A deliberately short list — it exists to quantify the
# share of lexical noise, not to constitute a linguistic reference.
STOPWORDS = frozenset(
    """the and for with that this has have was were from its his her they their not but all new said
    les des une dans pour avec sur par que qui sont est aux cette ces son ses leur leurs plus mais pas
    non aussi entre vers sous lors selon apres avant depuis dont ete etre avoir fait faire deux trois
    ans annee annonce declare ont""".split()
)


def _item_tokens(record: dict) -> set[str]:
    """Tokens of a candidate item, exactly as search_related() computes them."""
    return _tokenize(record.get("title_en", "")) | _tokenize(record.get("summary", ""))


def _distinctive(tokens: set[str]) -> set[str]:
    return {t for t in tokens if t not in STOPWORDS and not t.isdigit()}


def _norm(value: str) -> str:
    return re.sub(r"\W+", "", (value or "").lower())


def weighted_pairs(history: list[dict]) -> tuple[dict[str, float], list[tuple[float, int, int, set[str]]]]:
    """The window's IDF, and pairs of distinct dates sharing at least one token.

    Extracted from `main()` so it can also serve `backend/eval/build_pairs.py`: the annotated sample
    must be about exactly the score measured here, and two implementations of the same computation
    would diverge at the first correction — the same reason that already makes this module import
    `_tokenize` rather than rewrite it.

    Scale caveat, to keep in mind before comparing a figure produced here with one produced by the
    pipeline: this function calibrates in `log(n / (1 + df))` where `store._overlap_score` applies
    `log(n / df)`. Rescoring the same pairs on the two scales moves some of them across a band
    boundary — which is exactly what corrected the 64.7% published on 2026-08-20 to 62.0%.
    """
    n = len(history)
    raw = [_item_tokens(r) for r in history]

    # IDF computed over the history itself: a token present everywhere weighs ~0, a rare token weighs
    # the most. The hypothesis under test: the identity of a story lies in its rare tokens.
    df: Counter = Counter()
    for tokens in raw:
        df.update(tokens)
    idf = {tok: math.log(n / (1 + c)) for tok, c in df.items()}

    pairs: list[tuple[float, int, int, set[str]]] = []
    for i in range(n):
        for j in range(i + 1, n):
            # A proxy for `exclude_links`: the current run's batch is never visible to cross-checking.
            if history[i].get("date") == history[j].get("date"):
                continue
            shared = raw[i] & raw[j]
            if not shared:
                continue
            pairs.append((sum(idf[t] for t in shared), i, j, shared))
    return idf, pairs


def _report_thresholds(label: str, best: list[float], thresholds: tuple) -> None:
    total = len(best)
    print(f"--- {label} ---")
    for threshold in thresholds:
        k = sum(1 for b in best if b >= threshold)
        print(f"  threshold >= {threshold:5} : {k:4d}/{total} items escalated ({100 * k / total:5.1f}%)")
    print()


def main(pairs_to_show: int, days: int) -> None:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    history = get_persistence().analyzed_since(cutoff)
    n = len(history)
    if n < 2:
        print(f"History too short ({n} item(s)): nothing to measure.")
        return

    by_date = Counter(r.get("date", "?") for r in history)
    print(f"History: {n} items over {len(by_date)} days — {dict(sorted(by_date.items()))}\n")

    raw = [_item_tokens(r) for r in history]
    dist = [_distinctive(t) for t in raw]
    idf, weighted = weighted_pairs(history)

    best_raw = [0] * n
    best_dist = [0] * n
    best_idf = [0.0] * n
    for weight, i, j, shared in weighted:
        shared_dist = len(dist[i] & dist[j])
        for idx in (i, j):
            best_raw[idx] = max(best_raw[idx], len(shared))
            best_dist[idx] = max(best_dist[idx], shared_dist)
            best_idf[idx] = max(best_idf[idx], weight)

    _report_thresholds("raw overlap (real tokenizer)", best_raw, (1, 2, 3, 4, 5, 6, 8, 10))
    _report_thresholds("overlap, stop words removed", best_dist, (1, 2, 3, 4, 5, 6, 8, 10))
    _report_thresholds("IDF-weighted overlap", best_idf, (5, 10, 15, 20, 25, 30, 40))

    # Gate on the structured fields: `location` is extracted by the model then verified verbatim
    # against the source text (docs/scoping.md §8), so it is more reliable than a free-text token.
    located = sum(1 for r in history if _norm(r.get("location", "")))
    structured = [
        (i, j)
        for i in range(n)
        for j in range(i + 1, n)
        if history[i].get("date") != history[j].get("date")
        and _norm(history[i].get("location", ""))
        and _norm(history[i].get("location", "")) == _norm(history[j].get("location", ""))
        and history[i].get("category") == history[j].get("category")
    ]
    gated = {idx for pair in structured for idx in pair}
    print("--- structured gate (same `location` + same category) ---")
    print(f"  items with a non-empty `location`: {located}/{n} ({100 * located / n:.0f}%)")
    print(f"  pairs retained: {len(structured)}")
    print(f"  items escalated: {len(gated)}/{n} ({100 * len(gated) / n:.1f}%)\n")

    # Qualitative control — indispensable: an escalation rate is worthless if the candidates retained
    # are not real candidates. This is where you read whether the ranking surfaces story identity or
    # merely thematic similarity.
    if pairs_to_show:
        weighted.sort(key=lambda p: p[0], reverse=True)
        print(f"=== {pairs_to_show} best pairs (IDF weighting) — to be judged by hand ===\n")
        for weight, i, j, shared in weighted[:pairs_to_show]:
            a, b = history[i], history[j]
            rarest = sorted(shared, key=lambda t: -idf[t])[:6]
            print(f"[{weight:5.1f}] {a.get('category')} / {b.get('category')}")
            print(f"   A ({a.get('source')}, {a.get('date')}): {a.get('title_en', '')[:100]}")
            print(f"   B ({b.get('source')}, {b.get('date')}): {b.get('title_en', '')[:100]}")
            print(f"   rarest shared tokens: {rarest}")
            print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", type=int, default=12, help="pairs to display for manual judgement")
    parser.add_argument("--days", type=int, default=RELATED_ITEMS_WINDOW_DAYS, help="history window")
    args = parser.parse_args()
    main(args.pairs, args.days)
