from backend.agents import analyst


def _raw_item(raw_text: str, country: str = "US") -> dict:
    return {
        "source": "s",
        "lang": "en",
        "country": country,
        "state_affiliated": False,
        "title": "title",
        "link": "l",
        "published": "",
        "raw_text": raw_text,
    }


class _FakeAnalysis:
    def __init__(
        self,
        category,
        citation,
        location="",
        location_country="",
        actor="",
        actor_country="",
        domestic=False,
        title_en="Title",
        summary="Summary",
    ):
        self.category = category
        self.citation = citation
        self.location = location
        self.location_country = location_country
        self.actor = actor
        self.actor_country = actor_country
        self.domestic = domestic
        self.title_en = title_en
        self.summary = summary


def test_clean_text_strips_html_and_unescapes_entities():
    assert analyst._clean_text("<p>Rafale &amp; export</p>") == "Rafale & export"


def test_extract_verified_true_for_verbatim_substring():
    assert analyst._extract_verified("Rafale export deal", "The Rafale export deal was signed today.")


def test_extract_verified_false_when_not_in_source():
    assert not analyst._extract_verified("Rafale export deal", "No mention of that aircraft here.")


def test_extract_verified_false_for_empty_extract():
    assert not analyst._extract_verified("", "Some source text.")


def test_analyze_drops_out_of_scope(monkeypatch):
    monkeypatch.setattr(analyst, "classify_item", lambda item: _FakeAnalysis("out_of_scope", ""))

    result = analyst.analyze({"raw_items": [_raw_item("some text")], "analyzed_items": []})

    assert result["analyzed_items"] == []


def test_analyze_rejects_items_without_verified_citation(monkeypatch):
    monkeypatch.setattr(
        analyst,
        "classify_item",
        lambda item: _FakeAnalysis("arms_contract", "this citation is not in the source"),
    )

    result = analyst.analyze({"raw_items": [_raw_item("Actual source text.")], "analyzed_items": []})

    assert result["analyzed_items"] == []


def test_analyze_keeps_items_with_verified_citation(monkeypatch):
    monkeypatch.setattr(
        analyst,
        "classify_item",
        lambda item: _FakeAnalysis("arms_contract", "source text about a contract"),
    )

    result = analyst.analyze({"raw_items": [_raw_item("Actual source text about a contract.")], "analyzed_items": []})

    assert len(result["analyzed_items"]) == 1
    assert result["analyzed_items"][0]["category"] == "arms_contract"


def test_analyze_skips_an_unparsable_classification_without_losing_the_rest_of_the_run(monkeypatch):
    """Observed on a real run: the model returned a Spanish-inflected category on a Spanish-language
    source. The validation error propagated up to the graph and lost every item already analysed — a
    cost out of all proportion to that of one failed item."""
    from pydantic import ValidationError

    def _classify(item):
        if item["link"] == "bad":
            raise ValidationError.from_exception_data("_Analysis", [])
        return _FakeAnalysis("arms_contract", "source text about a contract")

    monkeypatch.setattr(analyst, "classify_item", _classify)

    good, bad = _raw_item("Actual source text about a contract."), _raw_item("Another text")
    bad["link"] = "bad"

    result = analyst.analyze({"raw_items": [bad, good], "analyzed_items": []})

    assert [i["link"] for i in result["analyzed_items"]] == ["l"]


def test_analyze_truncates_the_run_when_the_budget_falls_instead_of_losing_what_it_paid_for(monkeypatch):
    """Point 29 of the log: when the cap fell during analyze, the exception propagated to the graph
    and verify was never reached — so neither was record_analyzed. The items already analysed were
    marked seen by the `finally` and recorded nowhere: paid for, lost."""
    from backend.guardrails import BudgetExceeded

    def _classify(item):
        if item["link"] != "l":
            raise BudgetExceeded("cap reached")
        return _FakeAnalysis("arms_contract", "source text about a contract")

    monkeypatch.setattr(analyst, "classify_item", _classify)

    done = _raw_item("Actual source text about a contract.")
    unpaid, later = _raw_item("Another text"), _raw_item("Yet another text")
    unpaid["link"], later["link"] = "unpaid", "later"

    result = analyst.analyze({"raw_items": [done, unpaid, later], "analyzed_items": []})

    assert [i["link"] for i in result["analyzed_items"]] == ["l"]
    assert result["truncated"] is True


def test_analyze_leaves_the_unbilled_item_collectable_when_the_budget_falls(monkeypatch):
    """The cap is checked *before* the call: the item it falls on cost nothing. Marking it "seen"
    would discard it from every subsequent collection without it ever having been analysed — the loss
    of point 28, reintroduced through the budget path."""
    import backend.memory.store as store
    from backend.guardrails import BudgetExceeded

    def _classify(item):
        if item["link"] != "l":
            raise BudgetExceeded("cap reached")
        return _FakeAnalysis("arms_contract", "source text about a contract")

    monkeypatch.setattr(analyst, "classify_item", _classify)

    done = _raw_item("Actual source text about a contract.")
    unpaid, later = _raw_item("Another text"), _raw_item("Yet another text")
    unpaid["link"], later["link"] = "unpaid", "later"

    analyst.analyze({"raw_items": [done, unpaid, later], "analyzed_items": []})

    # Replayed on the next collection: only the item actually submitted to the model is discarded.
    still_collectable = store.deduplicate({"raw_items": [done, unpaid, later], "analyzed_items": []})
    assert [i["link"] for i in still_collectable["raw_items"]] == ["unpaid", "later"]


def test_analyze_blanks_unverified_location_instead_of_trusting_it(monkeypatch):
    monkeypatch.setattr(
        analyst,
        "classify_item",
        lambda item: _FakeAnalysis(
            "arms_contract",
            "source text about a contract",
            location="Nowhereland",
            location_country="Nowhereland",
        ),
    )

    result = analyst.analyze({"raw_items": [_raw_item("Actual source text about a contract.")], "analyzed_items": []})

    assert result["analyzed_items"][0]["location"] == ""
    # The inferred country cannot be verified verbatim: its only anchor is the place it is inferred
    # from. Place rejected, country rejected — otherwise an unverified place would come back and put
    # the item on the map through a field the guardrail does not cover.
    assert result["analyzed_items"][0]["location_country"] == ""


def test_analyze_keeps_deduced_country_when_location_is_verified(monkeypatch):
    monkeypatch.setattr(
        analyst,
        "classify_item",
        lambda item: _FakeAnalysis(
            "arms_contract",
            "source text about a contract",
            location="Darwin",
            location_country="Australia",
        ),
    )

    result = analyst.analyze(
        {"raw_items": [_raw_item("Source text about a contract signed in Darwin.")], "analyzed_items": []}
    )

    assert result["analyzed_items"][0]["location"] == "Darwin"
    assert result["analyzed_items"][0]["location_country"] == "Australia"


def test_analyze_presumes_domestic_only_when_no_location_was_extracted(monkeypatch):
    monkeypatch.setattr(
        analyst,
        "classify_item",
        lambda item: _FakeAnalysis("arms_contract", "source text about a contract", domestic=True),
    )

    result = analyst.analyze({"raw_items": [_raw_item("Actual source text about a contract.")], "analyzed_items": []})

    assert result["analyzed_items"][0]["location"] == ""
    assert result["analyzed_items"][0]["domestic_to_source"] is True


def test_analyze_ignores_domestic_when_a_location_was_extracted(monkeypatch):
    # An extracted place is an answer: the outlet's country must not substitute itself for it, even
    # if the event is also domestic. The fallback is a last resort, not a competitor.
    monkeypatch.setattr(
        analyst,
        "classify_item",
        lambda item: _FakeAnalysis("arms_contract", "source text about a contract", location="Darwin", domestic=True),
    )

    result = analyst.analyze(
        {"raw_items": [_raw_item("Source text about a contract signed in Darwin.")], "analyzed_items": []}
    )

    assert result["analyzed_items"][0]["domestic_to_source"] is False


def test_normalize_category_repairs_the_near_misses_the_vocabulary_invites():
    # The real production case was a Spanish inflection of the identifiers, seen on Infodefensa. The
    # identifiers are English since 2026-09-06, and the near-misses that vocabulary invites are the
    # British spelling — which the prompt's own prose uses — and plurals.
    assert analyst._normalize_category("defence_diplomacy") == "defense_diplomacy"
    assert analyst._normalize_category("industrial_programme") == "industrial_program"
    assert analyst._normalize_category("arms_contracts") == "arms_contract"


def test_normalize_category_leaves_unrelated_strings_untouched():
    # No false positive: a string that resembles no category is left unchanged, so that Pydantic
    # validation rejects it normally rather than flipping it at random. The Spanish inflection that
    # motivated this net against the French identifiers is now one of those strings — too far from
    # the English vocabulary to be repaired, and correctly left alone rather than guessed at.
    assert analyst._normalize_category("cybersecurity_") == "cybersecurity_"
    assert analyst._normalize_category("diplomacia_defensa") == "diplomacia_defensa"


def test_classify_item_repairs_an_out_of_enum_category_from_the_raw_tool_call(monkeypatch):
    """The include_raw structure exposes the raw arguments of the tool call even when Pydantic
    validation fails — classify_item must use them to repair the category before giving up, rather
    than losing the item as it did before this fix."""

    class _FakeRaw:
        tool_calls = [
            {
                "args": {
                    "category": "defence_diplomacy",
                    "title_en": "Title",
                    "summary": "Summary",
                    "citation": "el hecho",
                    "location": "",
                    "location_country": "",
                    "domestic": False,
                }
            }
        ]

    class _FakeLLM:
        def invoke(self, messages):
            return {"raw": _FakeRaw(), "parsed": None, "parsing_error": None}

    monkeypatch.setattr(analyst, "_llm", _FakeLLM())
    monkeypatch.setattr(analyst, "check_and_increment_llm_call", lambda node=None: None)

    result = analyst.classify_item(
        {
            "source": "s",
            "lang": "es",
            "country": "ES",
            "state_affiliated": False,
            "title": "title",
            "link": "l",
            "published": "",
            "raw_text": "texto",
        }
    )

    assert result.category == "defense_diplomacy"


def test_analyze_refuses_domestic_presumption_for_international_sources(monkeypatch):
    # "INT" designates a multi-country or EU institutional source: it has no country of origin, so
    # there is nothing to presume.
    monkeypatch.setattr(
        analyst,
        "classify_item",
        lambda item: _FakeAnalysis("arms_contract", "source text about a contract", domestic=True),
    )

    result = analyst.analyze(
        {"raw_items": [_raw_item("Actual source text about a contract.", country="INT")], "analyzed_items": []}
    )

    assert result["analyzed_items"][0]["domestic_to_source"] is False


def test_analyze_blanks_unverified_actor_instead_of_trusting_it(monkeypatch):
    monkeypatch.setattr(
        analyst,
        "classify_item",
        lambda item: _FakeAnalysis(
            "military_movement",
            "source text about a strike",
            actor="Nobodyans",
            actor_country="Yemen",
        ),
    )

    result = analyst.analyze({"raw_items": [_raw_item("Actual source text about a strike.")], "analyzed_items": []})

    assert result["analyzed_items"][0]["actor"] == ""
    # Same reasoning as for the place: `actor_country` has no verbatim anchor of its own, its only
    # anchor is the actor it is inferred from. Actor rejected, country rejected — otherwise an invented
    # protagonist would put the item on the map through a field the guardrail does not cover.
    assert result["analyzed_items"][0]["actor_country"] == ""


def test_analyze_keeps_actor_country_when_the_actor_is_verified(monkeypatch):
    monkeypatch.setattr(
        analyst,
        "classify_item",
        lambda item: _FakeAnalysis(
            "military_movement",
            "Houthis attacked eight tankers",
            actor="Houthis",
            actor_country="Yemen",
        ),
    )

    result = analyst.analyze(
        {"raw_items": [_raw_item("Houthis attacked eight tankers in the Red Sea.")], "analyzed_items": []}
    )

    assert result["analyzed_items"][0]["actor"] == "Houthis"
    assert result["analyzed_items"][0]["actor_country"] == "Yemen"


def test_analyze_verifies_the_actor_against_the_title_as_well_as_the_body(monkeypatch):
    # The protagonist is most often named in the title, and RSS excerpts are truncated: checking
    # against the body alone would erase correct extractions, as measured for the place.
    monkeypatch.setattr(
        analyst,
        "classify_item",
        lambda item: _FakeAnalysis(
            "defense_diplomacy",
            "a plan was uncovered",
            actor="Iran",
            actor_country="Iran",
        ),
    )

    item = _raw_item("a plan was uncovered by intelligence services.")
    item["title"] = "Iran plante Angriffe auf Militärziele in Europa"

    result = analyst.analyze({"raw_items": [item], "analyzed_items": []})

    assert result["analyzed_items"][0]["actor"] == "Iran"
    assert result["analyzed_items"][0]["actor_country"] == "Iran"


def test_analyze_keeps_actor_country_independent_of_the_location_verdict(monkeypatch):
    # The Strait of Hormuz case: a place is indeed named and verified, but belongs to no country, so
    # `location_country` stays empty by design. The actor must survive that emptiness — it is what will
    # carry the attachment on screen, without which the item vanishes from the map.
    monkeypatch.setattr(
        analyst,
        "classify_item",
        lambda item: _FakeAnalysis(
            "defense_diplomacy",
            "the Strait of Hormuz has been and will always remain Iranian",
            location="Strait of Hormuz",
            location_country="",
            actor="Iranian",
            actor_country="Iran",
        ),
    )

    result = analyst.analyze(
        {
            "raw_items": [_raw_item("the Strait of Hormuz has been and will always remain Iranian, an adviser said.")],
            "analyzed_items": [],
        }
    )

    analyzed = result["analyzed_items"][0]
    assert analyzed["location"] == "Strait of Hormuz"
    assert analyzed["location_country"] == ""
    assert analyzed["actor_country"] == "Iran"


def test_submission_tally_attributes_each_outcome_to_its_source(monkeypatch):
    """The node pays one call per item submitted, kept or not. Without this breakdown, the calls spent
    on discarded items (21% of the budget on the 2026-08-22 run) are attributable to no feed: discarded
    items are recorded nowhere else."""

    def _classify(item):
        if item["source"] == "off_topic":
            return _FakeAnalysis("out_of_scope", "")
        if item["source"] == "short_teaser":
            return _FakeAnalysis("arms_contract", "a citation absent from the text")
        return _FakeAnalysis("arms_contract", "source text about a contract")

    monkeypatch.setattr(analyst, "classify_item", _classify)

    kept = _raw_item("Actual source text about a contract.")
    dropped = _raw_item("An unrelated text")
    unverifiable = _raw_item("A truncated excerpt")
    dropped["source"], dropped["link"] = "off_topic", "d"
    unverifiable["source"], unverifiable["link"] = "short_teaser", "u"

    analyst.analyze({"raw_items": [kept, dropped, unverifiable], "analyzed_items": []})

    assert analyst.submissions_by_source() == {
        "off_topic": {"out_of_scope": 1},
        "s": {"kept": 1},
        "short_teaser": {"quote_unverified": 1},
    }


def test_submission_tally_ignores_the_item_the_budget_refused(monkeypatch):
    """The counterpart of the "collectable" test above: the cap is checked before the call, so the item
    it falls on cost nothing. Recording it as lost would charge its source with spending that never
    happened — the same attribution error the per-node tally avoids on the guardrails side."""
    from backend.guardrails import BudgetExceeded

    def _classify(item):
        if item["link"] != "l":
            raise BudgetExceeded("cap reached")
        return _FakeAnalysis("arms_contract", "source text about a contract")

    monkeypatch.setattr(analyst, "classify_item", _classify)

    done = _raw_item("Actual source text about a contract.")
    unpaid = _raw_item("Another text")
    unpaid["source"], unpaid["link"] = "starved", "unpaid"

    analyst.analyze({"raw_items": [done, unpaid], "analyzed_items": []})

    assert analyst.submissions_by_source() == {"s": {"kept": 1}}


# --- typographic folding of the verbatim comparison (measurement of 2026-08-31) ---
#
# The source text stays French here on purpose: these are the real Opex360/ESUT strings the
# measurement was taken on, and the perimeter still carries French-language feeds. The citation is
# a verbatim of the source, so it is never translated — only the digest around it is in English.


def test_extract_verified_folds_curly_apostrophes():
    """4 of the 6 `quote_unverified` failures in a real batch were pure typography: the model renders a
    straight apostrophe where the source writes a curly one."""
    source = "DRAKAR facilite la mise en grappe rapide des véhicules d’adaptation réactif"
    assert analyst._extract_verified("des véhicules d'adaptation réactif", source)


def test_extract_verified_folds_guillemets_and_quotes():
    source = "la France est «ouverte» à une coopération avec la Suède"
    assert analyst._extract_verified('la France est "ouverte" à une coopération', source)


def test_extract_verified_folds_dashes_and_nonbreaking_spaces():
    source = "un contrat\u00a0— signé à Paris — porte sur trente véhicules"
    assert analyst._extract_verified("un contrat - signé à Paris - porte", source)


def test_extract_verified_still_rejects_a_paraphrase():
    """Le repli typographique ne doit pas rattraper une citation composée : c'est exactement ce que
    le garde-fou §8 existe pour refuser. Deux des six échecs mesurés étaient de ce type."""
    source = "Le nombre d’hélicoptères disponibles s’élève à trente-quatre appareils."
    assert not analyst._extract_verified("le ratio moyen d'un hélicoptère par département", source)
