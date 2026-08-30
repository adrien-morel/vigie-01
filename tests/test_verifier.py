from backend.agents import verifier
from backend.memory import store


def _analyzed_item(category: str, link: str = "l") -> dict:
    return {
        "source": "s",
        "lang": "en",
        "country": "US",
        "state_affiliated": False,
        "title": "titre",
        "title_fr": "titre fr",
        "link": link,
        "published": "",
        "category": category,
        "summary": "résumé original",
        "citation": "citation originale",
        "location": "",
        "model_confidence": None,
        "corroborated": None,
    }


class _FakeToolCallResponse:
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls


class _FakeNoToolResponse:
    tool_calls = []


class _FakeConclusion:
    def __init__(self, confidence_score=0.7, corroborated=False):
        # Le double du schéma `_VerifierResult`, qui garde volontairement l'ancien nom : c'est lui
        # que remplit le modèle. Le renommage ne porte que sur le champ écrit dans l'item.
        self.confidence_score = confidence_score
        self.corroborated = corroborated


def _fake_chat_anthropic(tool_responses, conclusion, invoke_counter=None):
    """Fabrique un ChatAnthropic factice : .bind_tools() rejoue tool_responses puis répond sans
    outil, .with_structured_output() retourne toujours `conclusion`."""

    class _LoopLLM:
        def __init__(self):
            self._remaining = list(tool_responses)

        def invoke(self, messages):
            if invoke_counter is not None:
                invoke_counter[0] += 1
            if self._remaining:
                return self._remaining.pop(0)
            return _FakeNoToolResponse()

    class _Concluder:
        def invoke(self, messages):
            return conclusion

    class _FakeChatAnthropic:
        def __init__(self, model, temperature):
            pass

        def bind_tools(self, tools):
            return _LoopLLM()

        def with_structured_output(self, schema):
            return _Concluder()

    return _FakeChatAnthropic


def _patch_llm(monkeypatch, tool_responses=(), conclusion=None, invoke_counter=None):
    monkeypatch.setattr(verifier, "check_and_increment_llm_call", lambda node=None: None)
    monkeypatch.setattr(
        verifier,
        "ChatAnthropic",
        _fake_chat_anthropic(tool_responses, conclusion or _FakeConclusion(), invoke_counter),
    )


def _open_the_gate(monkeypatch) -> None:
    """Ouvre le portillon d'escalade, pour les tests qui portent sur autre chose que lui.

    Deux gestes, pas un. Un antécédent dans l'historique d'abord : depuis le 2026-08-20 un historique
    vide rend tout le lot inéligible — le comportement voulu (rien à recouper, donc rien à payer),
    mais pas ce que mesurent les tests d'escalade. Le seuil ramené à 0 ensuite, parce que fabriquer
    un chevauchement pondéré IDF au-dessus de 20 demanderait une dizaine de tokens rares partagés
    dans chaque test ; le seuil réel est éprouvé à part, dans
    test_verify_skips_an_item_the_history_has_nothing_close_to.

    Le remplissage au vocabulaire distinct n'est pas décoratif : sans lui, tous les tokens de la
    fenêtre seraient présents dans tous ses enregistrements, donc de poids IDF nul
    (log(total / df) = 0), et le portillon resterait fermé même à seuil 0.
    """
    monkeypatch.setattr(verifier, "VERIFIER_GATE_MIN_SCORE", 0.0)
    store.record_analyzed(
        [
            _analyzed_item("contrat_armement", "ante"),
            {
                **_analyzed_item("contrat_armement", "ante-filler"),
                "title_fr": "Sujet sans rapport",
                "summary": "Aucun mot commun",
            },
        ]
    )


def test_verify_escalates_every_category_of_the_perimeter(monkeypatch):
    """La catégorie ne borne plus l'escalade depuis le 2026-08-20 : mouvement_militaire, hors du
    périmètre du vérificateur jusque-là, est vérifié comme export_control dès lors que l'historique
    porte un antécédent candidat. Ce qui borne le coût, c'est le portillon."""
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(0.8, True))
    _open_the_gate(monkeypatch)

    items = [_analyzed_item("export_control", "a"), _analyzed_item("mouvement_militaire", "b")]
    result = verifier.verify({"raw_items": [], "analyzed_items": items})

    escalated = {i["link"]: i for i in result["analyzed_items"]}
    assert escalated["a"]["model_confidence"] == 0.8
    assert escalated["a"]["corroborated"] is True
    assert escalated["b"]["model_confidence"] == 0.8
    assert escalated["b"]["corroborated"] is True
    assert escalated["b"]["has_antecedent_candidate"] is True


def test_verify_skips_an_item_the_history_has_nothing_close_to(monkeypatch):
    """VERIFIER_GATE_MIN_SCORE est appliqué, pas seulement « au moins un candidat » : dans une
    fenêtre >= 3 items où le seul candidat partage un score IDF mesurable mais loin sous le seuil,
    aucun appel ne part — et l'item ressort marqué comme n'ayant pas d'antécédent candidat, ce qui
    distingue ce silence-là de celui d'un plafond atteint."""
    counter = [0]
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(), invoke_counter=counter)
    store.record_analyzed(
        [
            {**_analyzed_item("contrat_armement", "c"), "title_fr": "Rafale vendu à la Grèce"},
            {**_analyzed_item("contrat_armement", "filler-1"), "title_fr": "Sous-marins australiens"},
            {**_analyzed_item("contrat_armement", "filler-2"), "title_fr": "Drones Bayraktar en Ukraine"},
        ]
    )

    item = {**_analyzed_item("contrat_armement", "a"), "title_fr": "Rafale Grèce", "summary": "contrat"}
    result = verifier.verify({"raw_items": [], "analyzed_items": [item]})

    assert result["analyzed_items"][0]["model_confidence"] is None
    assert result["analyzed_items"][0]["has_antecedent_candidate"] is False
    assert counter[0] == 0


def test_verify_respects_max_escalations_per_run(monkeypatch):
    monkeypatch.setattr(verifier, "MAX_VERIFIER_ESCALATIONS_PER_RUN", 1)
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(0.9, False))
    _open_the_gate(monkeypatch)

    items = [_analyzed_item("export_control", "a"), _analyzed_item("export_control", "b")]
    result = verifier.verify({"raw_items": [], "analyzed_items": items})

    escalated = {i["link"]: i for i in result["analyzed_items"]}
    assert escalated["a"]["model_confidence"] == 0.9
    assert escalated["b"]["model_confidence"] is None
    # Le portillon avait pourtant retenu b : son silence vient du plafond, pas d'un historique muet.
    assert escalated["b"]["has_antecedent_candidate"] is True


def test_verify_stops_tool_loop_at_max_steps(monkeypatch):
    monkeypatch.setattr(verifier, "MAX_VERIFIER_STEPS_PER_ITEM", 2)

    always_tool = [
        _FakeToolCallResponse([{"name": "search_related_items", "args": {"query": "x"}, "id": "c1"}]) for _ in range(10)
    ]
    counter = [0]
    _patch_llm(monkeypatch, tool_responses=always_tool, conclusion=_FakeConclusion(), invoke_counter=counter)
    _open_the_gate(monkeypatch)

    verifier.verify({"raw_items": [], "analyzed_items": [_analyzed_item("export_control", "a")]})

    assert counter[0] == 2  # plafonné, jamais le nombre de réponses factices disponibles (10)


def test_verify_never_touches_summary_or_citation(monkeypatch):
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(0.5, False))
    _open_the_gate(monkeypatch)

    item = _analyzed_item("contrat_armement", "a")
    result = verifier.verify({"raw_items": [], "analyzed_items": [item]})

    assert result["analyzed_items"][0]["summary"] == "résumé original"
    assert result["analyzed_items"][0]["citation"] == "citation originale"


def test_verify_records_the_scored_items_not_their_pre_verification_version(monkeypatch):
    """L'historique alimente aussi le digest servi par l'API : il doit porter l'item tel qu'il sera
    affiché. Enregistré avant l'escalade, il aurait figé model_confidence/corroborated à None."""
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(0.5, True))
    _open_the_gate(monkeypatch)

    verifier.verify({"raw_items": [], "analyzed_items": [_analyzed_item("contrat_armement", "a")]})

    recorded = {r["link"]: r for r in store.load_digest(1)}
    assert recorded["a"]["model_confidence"] == 0.5
    assert recorded["a"]["corroborated"] is True


def test_verify_truncates_escalation_without_losing_the_items_already_analyzed(monkeypatch):
    """Un item analysé et payé ne doit pas disparaître parce que sa vérification, elle, n'a pas pu
    être financée : le nœud va au bout du lot, laisse None sur les non vérifiés — l'état que la
    restitution rend déjà comme « hors périmètre du vérificateur » — et écrit l'historique."""
    from backend.guardrails import BudgetExceeded

    _patch_llm(monkeypatch, conclusion=_FakeConclusion(0.8, True))
    _open_the_gate(monkeypatch)

    calls = [0]

    def _budget(node=None):
        # Laisse passer le premier item (boucle d'outil + conclusion), coupe pendant le second.
        calls[0] += 1
        if calls[0] > 2:
            raise BudgetExceeded("plafond atteint")

    monkeypatch.setattr(verifier, "check_and_increment_llm_call", _budget)

    items = [_analyzed_item("export_control", "a"), _analyzed_item("export_control", "b")]
    result = verifier.verify({"raw_items": [], "analyzed_items": items})

    by_link = {i["link"]: i for i in result["analyzed_items"]}
    assert by_link["a"]["model_confidence"] == 0.8
    assert by_link["b"]["model_confidence"] is None
    assert result["truncated"] is True
    # Les deux items restent dans l'historique : c'est lui qui alimente le digest servi par l'API.
    assert {"a", "b"} <= {r["link"] for r in store.load_digest(1)}


def test_verify_preserves_a_truncation_already_flagged_by_analyze(monkeypatch):
    """Le drapeau traverse le graphe : verify écrit la même clé d'état et ne doit pas effacer une
    troncature survenue en amont, sans quoi l'API annoncerait un run complet."""
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(0.8, True))

    result = verifier.verify(
        {"raw_items": [], "analyzed_items": [_analyzed_item("mouvement_militaire", "a")], "truncated": True}
    )

    assert result["truncated"] is True


def test_verify_never_lets_two_items_of_the_same_run_corroborate_each_other(monkeypatch):
    """Le nœud écrivait l'historique avant d'escalader, en n'excluant ensuite que le lien de l'item
    courant : un item pouvait donc être « corroboré » par son voisin de lot, qui n'apporte aucune
    confirmation indépendante dans le temps."""
    seen_queries = []

    tool_call = _FakeToolCallResponse([{"name": "search_related_items", "args": {"query": "Rafale"}, "id": "c1"}])
    _patch_llm(monkeypatch, tool_responses=[tool_call], conclusion=_FakeConclusion(0.5, False))
    _open_the_gate(monkeypatch)

    items = [_analyzed_item("export_control", "a"), _analyzed_item("export_control", "b")]
    items[0]["summary"] = items[1]["summary"] = "Rafale vendu à la Grèce par Dassault"

    original = verifier.search_related

    def _spy(query, exclude_links, limit=5):
        seen_queries.append(set(exclude_links))
        return original(query, exclude_links=exclude_links, limit=limit)

    monkeypatch.setattr(verifier, "search_related", _spy)
    verifier.verify({"raw_items": [], "analyzed_items": items})

    assert seen_queries, "l'outil de recherche n'a pas été appelé"
    assert all(excluded == {"a", "b"} for excluded in seen_queries)
