from backend.agents import analyst


def _raw_item(raw_text: str, country: str = "US") -> dict:
    return {
        "source": "s",
        "lang": "en",
        "country": country,
        "state_affiliated": False,
        "title": "titre",
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
        title_fr="Titre",
        summary="Résumé",
    ):
        self.category = category
        self.citation = citation
        self.location = location
        self.location_country = location_country
        self.actor = actor
        self.actor_country = actor_country
        self.domestic = domestic
        self.title_fr = title_fr
        self.summary = summary


def test_clean_text_strips_html_and_unescapes_entities():
    assert analyst._clean_text("<p>Rafale &amp; export</p>") == "Rafale & export"


def test_extract_verified_true_for_verbatim_substring():
    assert analyst._extract_verified("Rafale export deal", "The Rafale export deal was signed today.")


def test_extract_verified_false_when_not_in_source():
    assert not analyst._extract_verified("Rafale export deal", "No mention of that aircraft here.")


def test_extract_verified_false_for_empty_extract():
    assert not analyst._extract_verified("", "Some source text.")


def test_analyze_drops_hors_perimetre(monkeypatch):
    monkeypatch.setattr(analyst, "classify_item", lambda item: _FakeAnalysis("hors_perimetre", ""))

    result = analyst.analyze({"raw_items": [_raw_item("some text")], "analyzed_items": []})

    assert result["analyzed_items"] == []


def test_analyze_rejects_items_without_verified_citation(monkeypatch):
    monkeypatch.setattr(
        analyst,
        "classify_item",
        lambda item: _FakeAnalysis("contrat_armement", "this citation is not in the source"),
    )

    result = analyst.analyze({"raw_items": [_raw_item("Actual source text.")], "analyzed_items": []})

    assert result["analyzed_items"] == []


def test_analyze_keeps_items_with_verified_citation(monkeypatch):
    monkeypatch.setattr(
        analyst,
        "classify_item",
        lambda item: _FakeAnalysis("contrat_armement", "source text about a contract"),
    )

    result = analyst.analyze({"raw_items": [_raw_item("Actual source text about a contract.")], "analyzed_items": []})

    assert len(result["analyzed_items"]) == 1
    assert result["analyzed_items"][0]["category"] == "contrat_armement"


def test_analyze_skips_an_unparsable_classification_without_losing_the_rest_of_the_run(monkeypatch):
    """Constaté en run réel : le modèle a renvoyé « diplomacia_defense » sur une source
    hispanophone. L'erreur de validation remontait jusqu'au graphe et faisait perdre tous les items
    déjà analysés — coût sans rapport avec celui d'un item raté."""
    from pydantic import ValidationError

    def _classify(item):
        if item["link"] == "bad":
            raise ValidationError.from_exception_data("_Analysis", [])
        return _FakeAnalysis("contrat_armement", "source text about a contract")

    monkeypatch.setattr(analyst, "classify_item", _classify)

    good, bad = _raw_item("Actual source text about a contract."), _raw_item("Autre texte")
    bad["link"] = "bad"

    result = analyst.analyze({"raw_items": [bad, good], "analyzed_items": []})

    assert [i["link"] for i in result["analyzed_items"]] == ["l"]


def test_analyze_truncates_the_run_when_the_budget_falls_instead_of_losing_what_it_paid_for(monkeypatch):
    """Point 29 du journal : quand le plafond tombait pendant analyze, l'exception remontait au
    graphe et verify n'était jamais atteint — donc record_analyzed non plus. Les items déjà
    analysés étaient marqués vus par le `finally` et enregistrés nulle part : payés, perdus."""
    from backend.guardrails import BudgetExceeded

    def _classify(item):
        if item["link"] != "l":
            raise BudgetExceeded("plafond atteint")
        return _FakeAnalysis("contrat_armement", "source text about a contract")

    monkeypatch.setattr(analyst, "classify_item", _classify)

    done = _raw_item("Actual source text about a contract.")
    unpaid, later = _raw_item("Autre texte"), _raw_item("Encore un texte")
    unpaid["link"], later["link"] = "unpaid", "later"

    result = analyst.analyze({"raw_items": [done, unpaid, later], "analyzed_items": []})

    assert [i["link"] for i in result["analyzed_items"]] == ["l"]
    assert result["truncated"] is True


def test_analyze_leaves_the_unbilled_item_collectable_when_the_budget_falls(monkeypatch):
    """Le plafond est vérifié *avant* l'appel : l'item sur lequel il tombe n'a rien coûté. Le
    marquer « vu » l'écarterait de toutes les collectes suivantes sans qu'il ait jamais été
    analysé — la perte du point 28, réintroduite par le chemin du budget."""
    import backend.memory.store as store
    from backend.guardrails import BudgetExceeded

    def _classify(item):
        if item["link"] != "l":
            raise BudgetExceeded("plafond atteint")
        return _FakeAnalysis("contrat_armement", "source text about a contract")

    monkeypatch.setattr(analyst, "classify_item", _classify)

    done = _raw_item("Actual source text about a contract.")
    unpaid, later = _raw_item("Autre texte"), _raw_item("Encore un texte")
    unpaid["link"], later["link"] = "unpaid", "later"

    analyst.analyze({"raw_items": [done, unpaid, later], "analyzed_items": []})

    # Rejoué à la collecte suivante : seul l'item réellement soumis au modèle est écarté.
    still_collectable = store.deduplicate({"raw_items": [done, unpaid, later], "analyzed_items": []})
    assert [i["link"] for i in still_collectable["raw_items"]] == ["unpaid", "later"]


def test_analyze_blanks_unverified_location_instead_of_trusting_it(monkeypatch):
    monkeypatch.setattr(
        analyst,
        "classify_item",
        lambda item: _FakeAnalysis(
            "contrat_armement",
            "source text about a contract",
            location="Nowhereland",
            location_country="Nowhereland",
        ),
    )

    result = analyst.analyze({"raw_items": [_raw_item("Actual source text about a contract.")], "analyzed_items": []})

    assert result["analyzed_items"][0]["location"] == ""
    # Le pays déduit n'est pas vérifiable verbatim : son seul ancrage est le lieu dont il est
    # déduit. Lieu rejeté, pays rejeté — sinon un lieu non vérifié reviendrait placer l'item
    # sur la carte par un champ que le garde-fou ne couvre pas.
    assert result["analyzed_items"][0]["location_country"] == ""


def test_analyze_keeps_deduced_country_when_location_is_verified(monkeypatch):
    monkeypatch.setattr(
        analyst,
        "classify_item",
        lambda item: _FakeAnalysis(
            "contrat_armement",
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
        lambda item: _FakeAnalysis("contrat_armement", "source text about a contract", domestic=True),
    )

    result = analyst.analyze({"raw_items": [_raw_item("Actual source text about a contract.")], "analyzed_items": []})

    assert result["analyzed_items"][0]["location"] == ""
    assert result["analyzed_items"][0]["domestic_to_source"] is True


def test_analyze_ignores_domestic_when_a_location_was_extracted(monkeypatch):
    # Un lieu extrait est une réponse : le pays du média ne doit pas s'y substituer, même si
    # l'événement est aussi domestique. Le repli est un dernier recours, pas un concurrent.
    monkeypatch.setattr(
        analyst,
        "classify_item",
        lambda item: _FakeAnalysis(
            "contrat_armement", "source text about a contract", location="Darwin", domestic=True
        ),
    )

    result = analyst.analyze(
        {"raw_items": [_raw_item("Source text about a contract signed in Darwin.")], "analyzed_items": []}
    )

    assert result["analyzed_items"][0]["domestic_to_source"] is False


def test_normalize_category_repairs_the_spanish_inflection_seen_in_production():
    # Constaté en conditions réelles sur Infodefensa (source hispanophone) : le modèle a répondu
    # « diplomacia_defense » au lieu de « diplomatie_defense », malgré la consigne du prompt.
    assert analyst._normalize_category("diplomacia_defense") == "diplomatie_defense"


def test_normalize_category_leaves_unrelated_strings_untouched():
    # Pas de faux positif : une chaîne qui ne ressemble à aucune catégorie reste inchangée, pour que
    # la validation Pydantic la rejette normalement plutôt que de la faire basculer au hasard.
    assert analyst._normalize_category("cybersecurite") == "cybersecurite"


def test_classify_item_repairs_an_out_of_enum_category_from_the_raw_tool_call(monkeypatch):
    """La structure include_raw expose les arguments bruts de l'appel d'outil même quand la
    validation Pydantic échoue — classify_item doit s'en servir pour réparer la catégorie avant
    d'abandonner, plutôt que de perdre l'item comme avant ce correctif."""

    class _FakeRaw:
        tool_calls = [
            {
                "args": {
                    "category": "diplomacia_defense",
                    "title_fr": "Titre",
                    "summary": "Résumé",
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
            "title": "titre",
            "link": "l",
            "published": "",
            "raw_text": "texto",
        }
    )

    assert result.category == "diplomatie_defense"


def test_analyze_refuses_domestic_presumption_for_international_sources(monkeypatch):
    # "INT" désigne une source multi-pays ou institutionnelle UE : elle n'a pas de pays
    # d'origine, il n'y a donc rien à présumer.
    monkeypatch.setattr(
        analyst,
        "classify_item",
        lambda item: _FakeAnalysis("contrat_armement", "source text about a contract", domestic=True),
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
            "mouvement_militaire",
            "source text about a strike",
            actor="Nobodyans",
            actor_country="Yemen",
        ),
    )

    result = analyst.analyze({"raw_items": [_raw_item("Actual source text about a strike.")], "analyzed_items": []})

    assert result["analyzed_items"][0]["actor"] == ""
    # Même raisonnement que pour le lieu : `actor_country` n'a pas d'ancrage verbatim propre, son
    # seul ancrage est l'acteur dont il est déduit. Acteur rejeté, pays rejeté — sinon un
    # protagoniste inventé placerait l'item sur la carte par un champ non couvert par le garde-fou.
    assert result["analyzed_items"][0]["actor_country"] == ""


def test_analyze_keeps_actor_country_when_the_actor_is_verified(monkeypatch):
    monkeypatch.setattr(
        analyst,
        "classify_item",
        lambda item: _FakeAnalysis(
            "mouvement_militaire",
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
    # Le protagoniste est le plus souvent nommé dans le titre, et les extraits RSS sont tronqués :
    # vérifier contre le seul corps effacerait des extractions correctes, comme mesuré pour le lieu.
    monkeypatch.setattr(
        analyst,
        "classify_item",
        lambda item: _FakeAnalysis(
            "diplomatie_defense",
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
    # Le cas du détroit d'Ormuz : un lieu est bien nommé et vérifié, mais n'appartient à aucun pays,
    # donc `location_country` reste vide à dessein. L'acteur doit survivre à ce vide — c'est lui qui
    # portera le rattachement à l'affichage, sans quoi l'item disparaît de la carte.
    monkeypatch.setattr(
        analyst,
        "classify_item",
        lambda item: _FakeAnalysis(
            "diplomatie_defense",
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
    """Le nœud paie un appel par item soumis, retenu ou non. Sans cette ventilation, les appels
    dépensés sur des items écartés (21 % du budget au run du 2026-08-22) ne sont attribuables à
    aucun flux : les items écartés ne sont enregistrés nulle part ailleurs."""

    def _classify(item):
        if item["source"] == "hors_sujet":
            return _FakeAnalysis("hors_perimetre", "")
        if item["source"] == "teaser_court":
            return _FakeAnalysis("contrat_armement", "citation absente du texte")
        return _FakeAnalysis("contrat_armement", "source text about a contract")

    monkeypatch.setattr(analyst, "classify_item", _classify)

    kept = _raw_item("Actual source text about a contract.")
    dropped = _raw_item("Un texte sans rapport")
    unverifiable = _raw_item("Un extrait tronqué")
    dropped["source"], dropped["link"] = "hors_sujet", "d"
    unverifiable["source"], unverifiable["link"] = "teaser_court", "u"

    analyst.analyze({"raw_items": [kept, dropped, unverifiable], "analyzed_items": []})

    assert analyst.submissions_by_source() == {
        "hors_sujet": {"hors_perimetre": 1},
        "s": {"retenu": 1},
        "teaser_court": {"citation_non_verifiee": 1},
    }


def test_submission_tally_ignores_the_item_the_budget_refused(monkeypatch):
    """Pendant du test « collectable » ci-dessus : le plafond est vérifié avant l'appel, donc l'item
    sur lequel il tombe n'a rien coûté. L'inscrire comme perdu ferait porter à sa source une dépense
    qui n'a pas eu lieu — la même erreur d'imputation que le tally par nœud évite côté guardrails."""
    from backend.guardrails import BudgetExceeded

    def _classify(item):
        if item["link"] != "l":
            raise BudgetExceeded("plafond atteint")
        return _FakeAnalysis("contrat_armement", "source text about a contract")

    monkeypatch.setattr(analyst, "classify_item", _classify)

    done = _raw_item("Actual source text about a contract.")
    unpaid = _raw_item("Autre texte")
    unpaid["source"], unpaid["link"] = "affamee", "unpaid"

    analyst.analyze({"raw_items": [done, unpaid], "analyzed_items": []})

    assert analyst.submissions_by_source() == {"s": {"retenu": 1}}


# --- repli typographique de la comparaison verbatim (mesure du 2026-08-31) ---


def test_extract_verified_folds_curly_apostrophes():
    """4 des 6 échecs `citation_non_verifiee` d'un lot réel étaient de pure typographie : le modèle
    rend une apostrophe droite là où la source écrit une apostrophe courbe."""
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
