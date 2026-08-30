from datetime import date, timedelta

import backend.memory.store as store


def _item(link: str) -> dict:
    return {
        "source": "s",
        "theme": "t",
        "lang": "fr",
        "title": "titre",
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
    """Le marquage appartient au nœud analyze, pas au dédoublonnage : un run interrompu entre les
    deux laissait des items réputés vus sans avoir jamais été analysés — donc écartés de toutes les
    collectes suivantes. Constaté en réel sur 12 items."""
    store.deduplicate({"raw_items": [_item("a")], "analyzed_items": []})  # run interrompu ensuite

    retry = store.deduplicate({"raw_items": [_item("a")], "analyzed_items": []})

    assert [i["link"] for i in retry["raw_items"]] == ["a"]


def test_deduplicate_also_collapses_duplicates_inside_one_run():
    """Deux flux peuvent republier le même lien dans la même collecte : le doublon doit tomber
    avant l'appel LLM, pas seulement d'un run à l'autre."""
    result = store.deduplicate({"raw_items": [_item("a"), _item("a")], "analyzed_items": []})

    assert [i["link"] for i in result["raw_items"]] == ["a"]


def test_items_dropped_by_the_analyst_are_still_marked_as_seen():
    """Un item écarté en hors_perimetre a déjà coûté son appel LLM : il doit être filtré sans frais
    aux collectes suivantes, pas resoumis chaque jour."""
    submitted = store.deduplicate({"raw_items": [_item("a")], "analyzed_items": []})["raw_items"]
    store.mark_analyzed_as_seen(submitted)  # aucun item retenu, tous écartés par analyze()

    assert store.deduplicate({"raw_items": [_item("a")], "analyzed_items": []})["raw_items"] == []


def test_seen_links_outside_the_dedup_window_are_purged(persistence):
    stale = (date.today() - timedelta(days=store.DEDUP_WINDOW_DAYS + 1)).isoformat()
    persistence.mark_seen({"stale-link": stale, "fresh-link": date.today().isoformat()})

    store.deduplicate({"raw_items": [], "analyzed_items": []})

    assert set(persistence.seen_links("0000-01-01")) == {"fresh-link"}


def _analyzed_item(link: str, title_fr: str, summary: str, category: str = "contrat_armement") -> dict:
    return {
        "source": "s",
        "lang": "fr",
        "country": "FR",
        "state_affiliated": False,
        "title": "t",
        "title_fr": title_fr,
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
            _analyzed_item("a", "Rafale vendu à la Grèce", "Contrat Dassault confirmé"),
            _analyzed_item("b", "Sous-marins nucléaires australiens", "Accord AUKUS"),
        ]
    )

    results = store.search_related("Rafale Grèce Dassault", exclude_links={"c"})

    assert [r["title_fr"] for r in results] == ["Rafale vendu à la Grèce"]


def test_search_related_excludes_every_link_of_the_current_run():
    """Un item ne se corrobore ni lui-même ni via un autre item du même lot : deux dépêches
    arrivées dans la même collecte ne sont pas une confirmation indépendante dans le temps."""
    store.record_analyzed(
        [
            _analyzed_item("a", "Rafale vendu à la Grèce", "Contrat Dassault confirmé"),
            _analyzed_item("b", "Rafale : la Grèce signe", "Dassault confirme le contrat"),
        ]
    )

    assert store.search_related("Rafale Grèce Dassault", exclude_links={"a", "b"}) == []


def test_search_related_prunes_entries_older_than_window(persistence):
    old_date = (date.today() - timedelta(days=store.RELATED_ITEMS_WINDOW_DAYS + 1)).isoformat()
    persistence.put_analyzed(
        [{**_analyzed_item("a", "Rafale vendu à la Grèce", "Contrat Dassault confirmé"), "date": old_date}]
    )

    assert store.search_related("Rafale Grèce Dassault", exclude_links={"z"}) == []


def test_search_thread_candidates_filters_below_min_score_once_idf_is_active():
    """THREAD_GATE_MIN_SCORE (backend/config.py) ne peut discriminer qu'une fois la pondération IDF
    active (fenêtre >= 3 items, cf. _overlap_score) : construit une fenêtre de 3 items où le score
    du candidat cible est mesurable, puis vérifie que min_score l'inclut ou l'exclut selon sa valeur."""
    store.record_analyzed(
        [
            _analyzed_item("target", "Rafale vendu à la Grèce", "Dassault confirme la vente"),
            _analyzed_item("filler-1", "Sous-marins nucléaires australiens", "Accord AUKUS signé"),
            _analyzed_item("filler-2", "Drones Bayraktar en Ukraine", "Livraison confirmée par Kyiv"),
        ]
    )

    below = store.search_thread_candidates("Rafale Grèce", exclude_link="query", min_score=100.0)
    above = store.search_thread_candidates("Rafale Grèce", exclude_link="query", min_score=0.1)

    assert below == []
    assert [c["link"] for c in above] == ["target"]
    assert above[0]["score"] > 0


def test_search_thread_candidates_ignores_min_score_under_a_degenerate_window():
    """Sous 3 items, le score retombe sur un compte brut de tokens partagés (cf. _overlap_score) —
    une échelle différente sur laquelle min_score n'a pas de sens : le seuil est donc ignoré plutôt
    que d'exclure le cas canonique du thread (deux sources du même run, historique encore vide)."""
    store.record_analyzed([_analyzed_item("target", "Rafale vendu à la Grèce", "Dassault confirme la vente")])

    results = store.search_thread_candidates("Rafale Grèce", exclude_link="query", min_score=1000.0)

    assert [c["link"] for c in results] == ["target"]


def test_has_antecedent_applies_min_score_once_idf_is_active():
    """Portillon d'escalade du vérificateur (VERIFIER_GATE_MIN_SCORE) : même mécanique que celle du
    threader, mais sur tout un lot et une seule lecture d'historique."""
    store.record_analyzed(
        [
            _analyzed_item("target", "Rafale vendu à la Grèce", "Dassault confirme la vente"),
            _analyzed_item("filler-1", "Sous-marins nucléaires australiens", "Accord AUKUS signé"),
            _analyzed_item("filler-2", "Drones Bayraktar en Ukraine", "Livraison confirmée par Kyiv"),
        ]
    )
    queries = {"item": "Rafale Grèce"}

    assert store.has_antecedent(queries, exclude_links=set(), min_score=0.1) == {"item": True}
    assert store.has_antecedent(queries, exclude_links=set(), min_score=100.0) == {"item": False}


def test_has_antecedent_ignores_min_score_under_a_degenerate_window():
    """Sous 3 items le score retombe sur un compte brut de tokens (cf. _overlap_score) : un seuil
    mesuré en pondéré n'y a pas de sens, et le portillon retombe sur « au moins un candidat »."""
    store.record_analyzed([_analyzed_item("target", "Rafale vendu à la Grèce", "Dassault confirme la vente")])

    assert store.has_antecedent({"item": "Rafale Grèce"}, exclude_links=set(), min_score=1000.0) == {"item": True}


def test_has_antecedent_never_counts_an_item_of_the_current_batch():
    """Un antécédent est une confirmation indépendante dans le temps : deux reprises simultanées de
    la même dépêche ne s'en tiennent pas lieu, d'où exclude_links sur tout le lot (cf. search_related)."""
    store.record_analyzed(
        [
            _analyzed_item("a", "Rafale vendu à la Grèce", "Dassault confirme la vente"),
            _analyzed_item("b", "Rafale vendu à la Grèce", "Dassault confirme la vente"),
        ]
    )

    gate = store.has_antecedent({"a": "Rafale Grèce", "b": "Rafale Grèce"}, exclude_links={"a", "b"}, min_score=0.0)

    assert gate == {"a": False, "b": False}


def test_record_analyzed_is_not_visible_to_search_before_it_is_called():
    assert store.search_related("Rafale Grèce Dassault", exclude_links={"z"}) == []


def test_digest_accumulates_across_runs_instead_of_being_replaced():
    """Le défaut corrigé : chaque run écrasait le digest, donc une seconde collecte dans la journée
    — dont le dédoublonnage a écarté presque tous les items — effaçait l'historique affiché."""
    store.record_analyzed([_analyzed_item("a", "Premier run", "résumé a")])
    store.record_analyzed([_analyzed_item("b", "Second run", "résumé b")])

    assert {i["link"] for i in store.load_digest(store.DEDUP_WINDOW_DAYS)} == {"a", "b"}


def test_digest_is_empty_for_a_window_that_predates_every_item(persistence):
    old_date = (date.today() - timedelta(days=10)).isoformat()
    persistence.put_analyzed([{**_analyzed_item("a", "Ancien", "résumé"), "date": old_date}])

    assert store.load_digest(3) == []
    assert [i["link"] for i in store.load_digest(30)] == ["a"]


def test_re_recording_an_item_updates_it_without_duplicating_or_rejuvenating_it(persistence):
    store.record_analyzed([_analyzed_item("a", "titre", "résumé")])
    first_seen = store.load_digest(1)[0]["first_seen"]

    scored = {**_analyzed_item("a", "titre", "résumé"), "model_confidence": 0.8, "corroborated": True}
    store.record_analyzed([scored])

    digest = store.load_digest(1)
    assert len(digest) == 1
    assert digest[0]["model_confidence"] == 0.8
    assert digest[0]["first_seen"] == first_seen


def test_digest_skips_records_that_predate_the_full_item_schema(persistence):
    """L'ancien historique ne gardait que 7 champs par item : exploitable pour le recoupement,
    pas pour l'affichage. Ces enregistrements sont écartés du digest, pas servis incomplets."""
    persistence.put_analyzed(
        [
            {
                "date": date.today().isoformat(),
                "link": "legacy",
                "source": "s",
                "country": "FR",
                "category": "contrat_armement",
                "title_fr": "Ancien format",
                "summary": "résumé",
            }
        ]
    )

    assert store.load_digest(7) == []
    assert [r["title_fr"] for r in store.search_related("Ancien format", exclude_links=set())] == ["Ancien format"]


def test_digest_reads_the_old_score_field_under_its_new_name(persistence):
    """`confidence_score` s'appelle `model_confidence` depuis le 2026-08-30. Les 45 enregistrements
    du run de ce jour-là portent l'ancien nom : le digest doit les servir sous le nouveau, sinon le
    front lit `undefined` et affiche « non vérifié » sur des items qui portent un score."""
    legacy = {**_analyzed_item("a", "titre", "résumé"), "confidence_score": 0.8, "corroborated": True}
    legacy.pop("model_confidence", None)
    persistence.put_analyzed([{**legacy, "date": date.today().isoformat(), "first_seen": "2026-08-30T00:00:00+00:00"}])

    record = store.load_digest(1)[0]

    assert record["model_confidence"] == 0.8
    assert "confidence_score" not in record


def test_digest_does_not_overwrite_a_new_score_with_an_old_one(persistence):
    """Contrôle du repli : un enregistrement qui porte déjà les deux noms — cas d'une réécriture
    partielle — garde la valeur neuve, jamais celle qu'on traduisait."""
    both = {
        **_analyzed_item("a", "titre", "résumé"),
        "model_confidence": 0.9,
        "confidence_score": 0.1,
        "corroborated": True,
    }
    persistence.put_analyzed([{**both, "date": date.today().isoformat(), "first_seen": "2026-08-30T00:00:00+00:00"}])

    assert store.load_digest(1)[0]["model_confidence"] == 0.9
