"""Memory node: short-term deduplication (README architecture, docs/scoping.md §10 V1) and the
history of analysed items — which serves both the verifier agent's cross-checking (§10 V2, see
backend/agents/verifier.py) and the digest served by the API.

A single history for both uses, deliberately. The previous version kept two: this history on one
side, and a `.digest.json` file rewritten on every run on the other. That second file only held the
items of the current run — yet deduplication discards, before the LLM call, everything already seen
in the last 7 days. As a result, a second run on the same day produced only a handful of new items
and overwrote the previous digest, which was lost to the display even though the items were still
present here. The digest is therefore now a sliding window over this history (`load_digest`), not a
snapshot of the last run.

Storage (local files in dev, Firestore in production) sits behind backend/memory/persistence.py.
"""

import math
import re
from collections import Counter
from datetime import UTC, date, datetime, timedelta

from backend.logging_setup import get_logger
from backend.state import AnalyzedItem, RawItem, VigieState

from .persistence import get_persistence

DEDUP_WINDOW_DAYS = 7

# Aligned with DEDUP_WINDOW_DAYS since 2026-08-20: the cross-checking window used to be longer
# (30 days) to give the verifier more history, but keeping records beyond seven days costs storage
# with no measured benefit — the accumulation campaign that could have justified it ends that day.
# It also bounds the maximum consultable depth of the digest (see backend/api/main.py) and the
# choices of the front selector (frontend/src/App.tsx, WINDOW_CHOICES).
RELATED_ITEMS_WINDOW_DAYS = 7

log = get_logger("deduplicate")


def _cutoff(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


# Records written before the 2026-09-06 English pass carry the old field and category names. They
# are translated on read rather than migrated in the store, which empties itself through the
# retention window anyway.
#
# Removable once a purge has run on or after 2026-09-13 — and it is the purge that is the criterion,
# not the date: the two dated fallbacks removed on 2026-08-30 had been past their date for three days
# without having become safe, for want of a run to purge. Check that the oldest record in the store
# is more recent than 2026-09-06 before deleting this.
_LEGACY_CATEGORIES = {
    "contrat_armement": "arms_contract",
    "mouvement_militaire": "military_movement",
    "diplomatie_defense": "defense_diplomacy",
    "programme_industriel": "industrial_program",
    "hors_perimetre": "out_of_scope",
}


def _migrate_legacy(record: dict) -> dict:
    """Translates a record written before the English pass into the current vocabulary.

    Three renames ride together because they were shipped together: `confidence_score` became
    `model_confidence` on 2026-08-30, then `title_fr` became `title_en` and the six category
    identifiers became English on 2026-09-06. Reading is the only place that needs to know — the
    rest of the code sees the current names only.
    """
    needs_score = "model_confidence" not in record and "confidence_score" in record
    needs_title = "title_en" not in record and "title_fr" in record
    needs_category = record.get("category") in _LEGACY_CATEGORIES
    if not (needs_score or needs_title or needs_category):
        return record
    migrated = dict(record)
    if needs_score:
        migrated["model_confidence"] = migrated.pop("confidence_score")
    if needs_title:
        migrated["title_en"] = migrated.pop("title_fr")
    if needs_category:
        migrated["category"] = _LEGACY_CATEGORIES[migrated["category"]]
    return migrated


def _read_analyzed(days: int) -> list[dict]:
    """The single read path into the analysed history — every caller goes through it so that the
    legacy translation above applies once and only once."""
    return [_migrate_legacy(r) for r in get_persistence().analyzed_since(_cutoff(days))]


def deduplicate(state: VigieState) -> VigieState:
    """LangGraph node: removes raw_items already seen (key = link), before the analyst's LLM call.

    Placed between collect and analyze rather than after analyze: an item already seen must not only
    be excluded from the digest, it must not even be re-analysed — otherwise the LLM budget (§8) is
    consumed every day on items already processed the day before.
    """
    persistence = get_persistence()
    # Once per run, at the start of the pipeline: without an explicit purge, backends that filter on
    # read (Firestore) would keep data outside the retention window indefinitely.
    persistence.purge_before(_cutoff(DEDUP_WINDOW_DAYS), _cutoff(RELATED_ITEMS_WINDOW_DAYS))

    seen = persistence.seen_links(_cutoff(DEDUP_WINDOW_DAYS))

    new_items: list[RawItem] = []
    kept: set[str] = set()
    duplicates_in_batch = 0
    for item in state["raw_items"]:
        if item["link"] in kept:
            duplicates_in_batch += 1
            continue
        if item["link"] in seen:
            continue
        new_items.append(item)
        kept.add(item["link"])

    # The two causes of the gap are kept apart: "already seen on an earlier day" is deduplication
    # working normally, "twice in the same batch" flags two feeds republishing the same link — useful
    # to source composition, invisible if only a total is counted.
    log.info(
        "deduplication finished",
        extra={
            "received": len(state["raw_items"]),
            "kept": len(new_items),
            "discarded_already_seen": len(state["raw_items"]) - len(new_items) - duplicates_in_batch,
            "duplicates_in_batch": duplicates_in_batch,
            "links_in_memory": len(seen),
        },
    )

    # This node filters, it does not mark: it is mark_analyzed_as_seen(), called by the analyze node,
    # that records the links once the item has really been submitted to the model. Marking here lost
    # for good the items of a run interrupted between the two — they were deemed seen without ever
    # having been analysed, and therefore discarded from every subsequent collection. Observed for
    # real: an unvalidatable model response failed a run, and its 12 items stayed seen without
    # existing anywhere.
    return {"raw_items": new_items}


def mark_analyzed_as_seen(items: list[RawItem]) -> None:
    """Records the links submitted to the analyst in the deduplication memory.

    It covers every submitted item, not only those kept: an item discarded as `out_of_scope` or for
    want of a verifiable citation has already cost its LLM call, and must be discarded free of charge
    on subsequent collections.
    """
    if not items:
        return
    today = date.today().isoformat()
    get_persistence().mark_seen({item["link"]: today for item in items})


def record_analyzed(items: list[AnalyzedItem]) -> None:
    """Writes the analysed items of the current run into the history (cross-checking §10 V2 + digest).

    Called at the end of the verify node, once `model_confidence`/`corroborated` are filled in, then
    at the end of the thread node, once `thread_id`/`has_thread_candidate`/`thread_checked` are set:
    the history must hold the item as it will be displayed, not its pre-verification version — it is
    the history, not the graph state, that `load_digest` serves to the front. The invariant
    "cross-check search never sees the current run" is held by `exclude_links` on the verifier side,
    not by the write order.

    `first_seen` is preserved on rewrite: a re-analysed item must not grow younger, otherwise it would
    never leave the retention window. `thread_id` is preserved the same way, defensively: the thread
    node (V3 slice 1) always sets that field explicitly on the items it handles, but a future caller
    that did not must not erase an attachment already established.
    """
    if not items:
        return

    persistence = get_persistence()
    today = date.today().isoformat()
    now = datetime.now(UTC).isoformat()
    known = {r["link"]: r for r in _read_analyzed(RELATED_ITEMS_WINDOW_DAYS)}

    persistence.put_analyzed(
        [
            {
                **item,
                "date": known.get(item["link"], {}).get("date", today),
                "first_seen": known.get(item["link"], {}).get("first_seen", now),
                "thread_id": item.get("thread_id") or known.get(item["link"], {}).get("thread_id"),
            }
            for item in items
        ]
    )


# Fields without which the front cannot render an item card. Before the two stores were merged, the
# history only kept 7 fields per item (enough for cross-checking, not for display): those records
# stay searchable by the verifier but are kept out of the digest rather than served incomplete. They
# will leave the retention window on their own.
_DISPLAY_FIELDS = ("title", "citation", "location", "published", "lang")


def _is_displayable(record: dict) -> bool:
    return all(field in record for field in _DISPLAY_FIELDS)


def load_digest(days: int) -> list[dict]:
    """Analysed items of the last `days` days, most recent first.

    This is what GET /events serves. The items keep `date`/`first_seen`: the front needs them to date
    the entry into the digest, which is not the article's publication date.
    """
    records = [r for r in _read_analyzed(days) if _is_displayable(r)]
    records.sort(key=lambda r: (r.get("first_seen", ""), r.get("published", "")), reverse=True)
    return records


def last_run_at(records: list[dict]) -> str | None:
    """Timestamp of the most recent entry in the digest — hence of the last collection that produced
    something. Derived from the items rather than stored separately: a separate counter could drift
    from what is actually displayed."""
    stamps = [r["first_seen"] for r in records if r.get("first_seen")]
    return max(stamps) if stamps else None


def _tokenize(text: str) -> set[str]:
    return {tok for tok in re.findall(r"\w+", text.lower()) if len(tok) > 2}


def _record_tokens(record: dict) -> set[str]:
    return _tokenize(record.get("title_en", "")) | _tokenize(record.get("summary", ""))


def _document_frequencies(records: list[dict]) -> Counter[str]:
    """Number of items in the window containing each token.

    Computed over the whole window, including the items the caller will exclude from the ranking
    (current batch, the item itself): these are corpus statistics, and making them depend on the
    day's batch would make a word's weight vary from one run to the next.
    """
    df: Counter[str] = Counter()
    for record in records:
        df.update(_record_tokens(record))
    return df


def _overlap_score(query_tokens: set[str], record_tokens: set[str], df: Counter[str], total: int) -> float:
    """Keyword overlap weighted by how rare the word is in the history (IDF).

    The raw count that preceded it was dominated by stop words: measured over 199 real items, 88% of
    item pairs had a non-zero overlap, and 64% of the score was carried by tokens present in more than
    a fifth of the corpus. The order of the five candidates served to the model was therefore largely
    noise.

    log(total / df) rather than a stop-word list: the weight is derived from the corpus instead of
    being curated by hand, which also rules out the stop words *of the domain* ("defence", "drones",
    "according") that no generic list would cover, and introduces no threshold to calibrate.

    Scope measured at the time, exceeded since: the weighting corrected the *ranking* (a third of the
    candidates served to the model change, 328 evictions across 89 of the 199 items) without making
    the escalation gate of backend/agents/threader.py discriminating — the query being the item's
    whole title and summary, long enough to share a rare token with at least one of the 199 records
    whatever the weighting, that gate was still cleared by 100% of items. A corpus large enough to set
    a threshold was missing at the time (see backend/eval/candidates.py). It has since been measured
    and set: THREAD_GATE_MIN_SCORE in backend/config.py, applied by search_thread_candidates through
    its `min_score` parameter, calibrated on 2026-08-20 on the annotated sample
    backend/eval/pairs.json (see its history in backend/eval/score_pairs.py).

    Under three items the weighting is degenerate, and the bound is derived rather than set: a token
    shared by an item and a query taken from another item has `df >= 2`, so in a window of two items
    every shared token has `df == total` and zero weight — the weighting can then rank nothing. We
    fall back to the raw count, for want of a corpus on which to measure rarity. The gate therefore
    tightens as the history grows, which is the intended direction, and the canonical thread case (two
    sources from the same run on the same story, see tests/test_threader.py) stays covered while the
    history is still empty.
    """
    shared = query_tokens & record_tokens
    if total < 3:
        return float(len(shared))
    return sum(math.log(total / df[tok]) for tok in shared)


def search_related(query: str, exclude_links: set[str], limit: int = 5) -> list[dict]:
    """IDF-weighted keyword-overlap search in the history (§10 V2, backend/agents/verifier.py) — see
    `_overlap_score` for the measurement that motivated the weighting.

    No embeddings/vector store: consistent with the "local file storage as a documented placeholder
    before Firestore" convention that governed this module. IDF weighting derives from the corpus
    already loaded, where a top-k over embeddings would replace the threshold to calibrate with a `k`
    to calibrate, on a history that does not yet allow the question to be settled.

    `exclude_links` carries every link of the current run, not only that of the item being verified:
    an item must not be "corroborated" by another item of the same batch, which brings no independent
    confirmation over time.
    """
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    records = _read_analyzed(RELATED_ITEMS_WINDOW_DAYS)
    df = _document_frequencies(records)

    scored: list[tuple[float, dict]] = []
    for record in records:
        if record["link"] in exclude_links:
            continue
        score = _overlap_score(query_tokens, _record_tokens(record), df, len(records))
        if score > 0:
            scored.append((score, record))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        {
            "date": record["date"],
            "source": record["source"],
            "country": record.get("country", ""),
            "category": record["category"],
            "title_en": record["title_en"],
        }
        for _, record in scored[:limit]
    ]


def has_antecedent(queries: dict[str, str], exclude_links: set[str], min_score: float) -> dict[str, bool]:
    """The verifier's escalation gate (backend/agents/verifier.py): for each item — key, the link;
    value, the query — says whether the history holds at least one antecedent whose overlap score
    reaches `min_score`.

    A whole batch rather than a probe per item: the window and its document frequencies are loaded
    once, where `search_related` re-reads the history on every call. The verifier having covered the
    whole perimeter since 2026-08-20, a probe per item would have multiplied history reads by the
    volume of the run (~110), on a Firestore backend whose read cost is already an open point of the
    deployment (docs/scoping.md §11).

    `exclude_links` carries the whole current batch, like `search_related`: an antecedent is an
    independent confirmation over time, not a simultaneous pickup of the same dispatch. An empty
    history therefore makes the whole batch ineligible — that is the intended behaviour, escalating an
    item the history has nothing to say about costs 2 to 3 calls to produce a non-answer.

    Same scale caveat as `search_thread_candidates`: under three items in the window, `_overlap_score`
    falls back to a raw token count, a scale on which a threshold measured with weighting means
    nothing — the gate then falls back to "at least one candidate".
    """
    records = _read_analyzed(RELATED_ITEMS_WINDOW_DAYS)
    df = _document_frequencies(records)
    total = len(records)
    floor = min_score if total >= 3 else 0.0
    candidates = [(_record_tokens(record), record["link"]) for record in records]

    gate: dict[str, bool] = {}
    for link, query in queries.items():
        query_tokens = _tokenize(query)
        found = False
        for record_tokens, candidate_link in candidates:
            if candidate_link in exclude_links:
                continue
            score = _overlap_score(query_tokens, record_tokens, df, total)
            if score > 0 and score >= floor:
                found = True
                break
        gate[link] = found
    return gate


def analyzed_window(days: int = RELATED_ITEMS_WINDOW_DAYS) -> dict[str, dict]:
    """History window indexed by link, for a caller that must resolve a link to its complete record
    (backend/agents/threader.py, for instance, to patch thread_id without starting from a partial
    record — put_analyzed replaces by link, no partial patch, see
    backend/memory/persistence.py)."""
    return {r["link"]: r for r in _read_analyzed(days)}


def search_thread_candidates(query: str, exclude_link: str, limit: int = 5, min_score: float = 0.0) -> list[dict]:
    """IDF-weighted keyword-overlap search for the thread node (V3 slice 1, see
    backend/agents/threader.py) — the same primitive as search_related, a separate function rather
    than an extra parameter so as to change nothing about the verifier's already tested behaviour.

    Two deliberate differences from search_related: `exclude_link` carries only the link of the
    current item, not the whole batch of the run (a thread does not require an independent
    confirmation over time as corroboration does — two sources covering the same event on the same day
    are the clearest case of "same story"); and the result includes `link`, `thread_id` and `score` so
    that the caller can attach a story to the historical record found and, for `score`, apply the
    escalation gate of backend/agents/threader.py.

    `min_score` filters on top of the `score > 0` already applied, but only when IDF weighting is
    active (window >= 3 items, see _overlap_score): below that corpus size the score falls back to a
    raw count of shared tokens, a scale on which a threshold measured on a weighted corpus (see
    THREAD_GATE_MIN_SCORE, calibrated on 2026-08-20 on backend/eval/pairs.json) means nothing —
    ignoring it then preserves the canonical thread case (two sources from the same run, history still
    empty, see tests/test_threader.py) rather than making it ineligible for want of a corpus.
    """
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    records = _read_analyzed(RELATED_ITEMS_WINDOW_DAYS)
    df = _document_frequencies(records)
    total = len(records)
    floor = min_score if total >= 3 else 0.0

    scored: list[tuple[float, dict]] = []
    for record in records:
        if record["link"] == exclude_link:
            continue
        score = _overlap_score(query_tokens, _record_tokens(record), df, total)
        if score > 0 and score >= floor:
            scored.append((score, record))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        {
            "link": record["link"],
            "thread_id": record.get("thread_id"),
            "date": record["date"],
            "source": record["source"],
            "country": record.get("country", ""),
            "category": record["category"],
            "title_en": record["title_en"],
            "score": score,
        }
        for score, record in scored[:limit]
    ]
