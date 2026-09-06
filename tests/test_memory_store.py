from datetime import date, timedelta

import backend.memory.store as store


def _item(link: str) -> dict:
    return {
        "source": "s",
        "theme": "t",
        "lang": "fr",
        "title": "title",
        "link": link,
        "published": "",
        "raw_text": "",
    }


def test_deduplicate_filters_items_already_submitted_to_the_analyst():
    first = store.deduplicate({"raw_items": [_item("a"), _item("b")], "analyzed_items": []})
    assert [i["link"] for i in first["raw_items"]] == ["a", "b"]
    store.mark_analyzed_as_seen(first["raw_items"])

    second = store.deduplicate({"raw_items": [_item("a"), _item("c")], "analyzed_items": []})
    assert [i["link"] for i in second["raw_items"]] == ["c"]


def test_items_stay_collectable_until_they_have_actually_been_analyzed():
    """Marking belongs to the analyze node, not to deduplication: a run interrupted between the two
    left items deemed seen without ever having been analysed — and therefore discarded from every
    subsequent collection. Observed for real on 12 items."""
    store.deduplicate({"raw_items": [_item("a")], "analyzed_items": []})  # run interrupted afterwards

    retry = store.deduplicate({"raw_items": [_item("a")], "analyzed_items": []})

    assert [i["link"] for i in retry["raw_items"]] == ["a"]


def test_deduplicate_also_collapses_duplicates_inside_one_run():
    """Two feeds can republish the same link in the same collection: the duplicate must fall before
    the LLM call, not only from one run to the next."""
    result = store.deduplicate({"raw_items": [_item("a"), _item("a")], "analyzed_items": []})

    assert [i["link"] for i in result["raw_items"]] == ["a"]


def test_items_dropped_by_the_analyst_are_still_marked_as_seen():
    """An item discarded as out_of_scope has already cost its LLM call: it must be filtered free of
    charge on subsequent collections, not resubmitted every day."""
    submitted = store.deduplicate({"raw_items": [_item("a")], "analyzed_items": []})["raw_items"]
    store.mark_analyzed_as_seen(submitted)  # no item kept, all discarded by analyze()

    assert store.deduplicate({"raw_items": [_item("a")], "analyzed_items": []})["raw_items"] == []


def test_seen_links_outside_the_dedup_window_are_purged(persistence):
    stale = (date.today() - timedelta(days=store.DEDUP_WINDOW_DAYS + 1)).isoformat()
    persistence.mark_seen({"stale-link": stale, "fresh-link": date.today().isoformat()})

    store.deduplicate({"raw_items": [], "analyzed_items": []})

    assert set(persistence.seen_links("0000-01-01")) == {"fresh-link"}


def _analyzed_item(link: str, title_en: str, summary: str, category: str = "arms_contract") -> dict:
    return {
        "source": "s",
        "lang": "fr",
        "country": "FR",
        "state_affiliated": False,
        "title": "t",
        "title_en": title_en,
        "link": link,
        "published": "",
        "category": category,
        "summary": summary,
        "citation": "c",
        "location": "",
        "model_confidence": None,
        "corroborated": None,
    }


def test_search_related_finds_items_sharing_keywords():
    store.record_analyzed(
        [
            _analyzed_item("a", "Rafale sold to Greece", "Dassault contract confirmed"),
            _analyzed_item("b", "Australian nuclear submarines", "AUKUS agreement"),
        ]
    )

    results = store.search_related("Rafale Greece Dassault", exclude_links={"c"})

    assert [r["title_en"] for r in results] == ["Rafale sold to Greece"]


def test_search_related_excludes_every_link_of_the_current_run():
    """An item corroborates neither itself nor through another item of the same batch: two dispatches
    arriving in the same collection are not an independent confirmation over time."""
    store.record_analyzed(
        [
            _analyzed_item("a", "Rafale sold to Greece", "Dassault contract confirmed"),
            _analyzed_item("b", "Rafale: Greece signs", "Dassault confirms the contract"),
        ]
    )

    assert store.search_related("Rafale Greece Dassault", exclude_links={"a", "b"}) == []


def test_search_related_prunes_entries_older_than_window(persistence):
    old_date = (date.today() - timedelta(days=store.RELATED_ITEMS_WINDOW_DAYS + 1)).isoformat()
    persistence.put_analyzed(
        [{**_analyzed_item("a", "Rafale sold to Greece", "Dassault contract confirmed"), "date": old_date}]
    )

    assert store.search_related("Rafale Greece Dassault", exclude_links={"z"}) == []


def test_search_thread_candidates_filters_below_min_score_once_idf_is_active():
    """THREAD_GATE_MIN_SCORE (backend/config.py) can only discriminate once IDF weighting is active
    (window >= 3 items, see _overlap_score): this builds a window of 3 items where the target
    candidate's score is measurable, then checks that min_score includes or excludes it accordingly."""
    store.record_analyzed(
        [
            _analyzed_item("target", "Rafale sold to Greece", "Dassault confirms the sale"),
            _analyzed_item("filler-1", "Australian nuclear submarines", "AUKUS agreement signed"),
            _analyzed_item("filler-2", "Bayraktar drones in Ukraine", "Delivery confirmed by Kyiv"),
        ]
    )

    below = store.search_thread_candidates("Rafale Greece", exclude_link="query", min_score=100.0)
    above = store.search_thread_candidates("Rafale Greece", exclude_link="query", min_score=0.1)

    assert below == []
    assert [c["link"] for c in above] == ["target"]
    assert above[0]["score"] > 0


def test_search_thread_candidates_ignores_min_score_under_a_degenerate_window():
    """Under 3 items, the score falls back to a raw count of shared tokens (see _overlap_score) — a
    different scale on which min_score means nothing: the threshold is therefore ignored rather than
    excluding the canonical thread case (two sources from the same run, history still empty)."""
    store.record_analyzed([_analyzed_item("target", "Rafale sold to Greece", "Dassault confirms the sale")])

    results = store.search_thread_candidates("Rafale Greece", exclude_link="query", min_score=1000.0)

    assert [c["link"] for c in results] == ["target"]


def test_has_antecedent_applies_min_score_once_idf_is_active():
    """The verifier's escalation gate (VERIFIER_GATE_MIN_SCORE): the same mechanics as the threader's,
    but over a whole batch and a single history read."""
    store.record_analyzed(
        [
            _analyzed_item("target", "Rafale sold to Greece", "Dassault confirms the sale"),
            _analyzed_item("filler-1", "Australian nuclear submarines", "AUKUS agreement signed"),
            _analyzed_item("filler-2", "Bayraktar drones in Ukraine", "Delivery confirmed by Kyiv"),
        ]
    )
    queries = {"item": "Rafale Greece"}

    assert store.has_antecedent(queries, exclude_links=set(), min_score=0.1) == {"item": True}
    assert store.has_antecedent(queries, exclude_links=set(), min_score=100.0) == {"item": False}


def test_has_antecedent_ignores_min_score_under_a_degenerate_window():
    """Under 3 items the score falls back to a raw token count (see _overlap_score): a threshold
    measured with weighting means nothing there, and the gate falls back to "at least one candidate"."""
    store.record_analyzed([_analyzed_item("target", "Rafale sold to Greece", "Dassault confirms the sale")])

    assert store.has_antecedent({"item": "Rafale Greece"}, exclude_links=set(), min_score=1000.0) == {"item": True}


def test_has_antecedent_never_counts_an_item_of_the_current_batch():
    """An antecedent is an independent confirmation over time: two simultaneous pickups of the same
    dispatch do not qualify, hence exclude_links over the whole batch (see search_related)."""
    store.record_analyzed(
        [
            _analyzed_item("a", "Rafale sold to Greece", "Dassault confirms the sale"),
            _analyzed_item("b", "Rafale sold to Greece", "Dassault confirms the sale"),
        ]
    )

    gate = store.has_antecedent({"a": "Rafale Greece", "b": "Rafale Greece"}, exclude_links={"a", "b"}, min_score=0.0)

    assert gate == {"a": False, "b": False}


def test_record_analyzed_is_not_visible_to_search_before_it_is_called():
    assert store.search_related("Rafale Greece Dassault", exclude_links={"z"}) == []


def test_digest_accumulates_across_runs_instead_of_being_replaced():
    """The defect that was fixed: every run overwrote the digest, so a second collection in the day —
    whose deduplication discarded nearly every item — erased the displayed history."""
    store.record_analyzed([_analyzed_item("a", "First run", "summary a")])
    store.record_analyzed([_analyzed_item("b", "Second run", "summary b")])

    assert {i["link"] for i in store.load_digest(store.DEDUP_WINDOW_DAYS)} == {"a", "b"}


def test_digest_is_empty_for_a_window_that_predates_every_item(persistence):
    old_date = (date.today() - timedelta(days=10)).isoformat()
    persistence.put_analyzed([{**_analyzed_item("a", "Old", "summary"), "date": old_date}])

    assert store.load_digest(3) == []
    assert [i["link"] for i in store.load_digest(30)] == ["a"]


def test_re_recording_an_item_updates_it_without_duplicating_or_rejuvenating_it(persistence):
    store.record_analyzed([_analyzed_item("a", "title", "summary")])
    first_seen = store.load_digest(1)[0]["first_seen"]

    scored = {**_analyzed_item("a", "title", "summary"), "model_confidence": 0.8, "corroborated": True}
    store.record_analyzed([scored])

    digest = store.load_digest(1)
    assert len(digest) == 1
    assert digest[0]["model_confidence"] == 0.8
    assert digest[0]["first_seen"] == first_seen


def test_digest_skips_records_that_predate_the_full_item_schema(persistence):
    """The old history only kept 7 fields per item: usable for cross-checking, not for display. Those
    records are kept out of the digest, not served incomplete."""
    persistence.put_analyzed(
        [
            {
                "date": date.today().isoformat(),
                "link": "legacy",
                "source": "s",
                "country": "FR",
                "category": "arms_contract",
                "title_en": "Old format",
                "summary": "summary",
            }
        ]
    )

    assert store.load_digest(7) == []
    assert [r["title_en"] for r in store.search_related("Old format", exclude_links=set())] == ["Old format"]


def test_digest_reads_the_old_score_field_under_its_new_name(persistence):
    """`confidence_score` has been called `model_confidence` since 2026-08-30. The 45 records of that
    day's run carry the old name: the digest must serve them under the new one, otherwise the front
    reads `undefined` and displays "not verified" on items that do carry a score."""
    legacy = {**_analyzed_item("a", "title", "summary"), "confidence_score": 0.8, "corroborated": True}
    legacy.pop("model_confidence", None)
    persistence.put_analyzed([{**legacy, "date": date.today().isoformat(), "first_seen": "2026-08-30T00:00:00+00:00"}])

    record = store.load_digest(1)[0]

    assert record["model_confidence"] == 0.8
    assert "confidence_score" not in record


def test_digest_does_not_overwrite_a_new_score_with_an_old_one(persistence):
    """Control on the fallback: a record that already carries both names — the case of a partial
    rewrite — keeps the new value, never the one being translated."""
    both = {
        **_analyzed_item("a", "title", "summary"),
        "model_confidence": 0.9,
        "confidence_score": 0.1,
        "corroborated": True,
    }
    persistence.put_analyzed([{**both, "date": date.today().isoformat(), "first_seen": "2026-08-30T00:00:00+00:00"}])

    assert store.load_digest(1)[0]["model_confidence"] == 0.9


def test_digest_reads_a_pre_english_record_under_the_current_vocabulary(persistence):
    """Records written before the 2026-09-06 English pass carry `title_fr` and the French category
    identifiers. Same rule as the score rename: translated on read rather than migrated in the store,
    which empties itself through the retention window. Without this, the front would show an unknown
    category — and its colour token, its filter and its label all key off that string."""
    legacy = _analyzed_item("a", "Rafale sold to Greece", "Dassault confirms the sale")
    legacy["title_fr"] = legacy.pop("title_en")
    legacy["category"] = "contrat_armement"
    persistence.put_analyzed([{**legacy, "date": date.today().isoformat(), "first_seen": "2026-09-05T00:00:00+00:00"}])

    record = store.load_digest(1)[0]

    assert record["title_en"] == "Rafale sold to Greece"
    assert record["category"] == "arms_contract"
    assert "title_fr" not in record


def test_the_legacy_translation_also_reaches_the_search_paths(persistence):
    """The migration sits on the single read path, not only in load_digest: a pre-English record must
    stay findable by the verifier and the threader, which tokenise `title_en`. Reading it only in the
    digest would leave those two blind to a whole week of history."""
    legacy = _analyzed_item("a", "Rafale sold to Greece", "Dassault confirms the sale")
    legacy["title_fr"] = legacy.pop("title_en")
    legacy["category"] = "contrat_armement"
    persistence.put_analyzed([{**legacy, "date": date.today().isoformat()}])

    results = store.search_related("Rafale Greece Dassault", exclude_links=set())

    assert [r["title_en"] for r in results] == ["Rafale sold to Greece"]
    assert results[0]["category"] == "arms_contract"
