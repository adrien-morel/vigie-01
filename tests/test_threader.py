from backend.agents import threader
from backend.memory import store


def _analyzed_item(
    link: str,
    title_fr: str = "titre fr",
    summary: str = "résumé",
    category: str = "mouvement_militaire",
) -> dict:
    return {
        "source": "s",
        "lang": "en",
        "country": "US",
        "state_affiliated": False,
        "title": "titre",
        "title_fr": title_fr,
        "link": link,
        "published": "",
        "category": category,
        "summary": summary,
        "citation": "citation originale",
        "location": "",
        "model_confidence": None,
        "corroborated": None,
        "thread_id": None,
    }


class _FakeToolCallResponse:
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls


class _FakeNoToolResponse:
    tool_calls = []


class _FakeConclusion:
    def __init__(self, same_story_as=None):
        self.same_story_as = same_story_as


def _fake_chat_anthropic(tool_responses, conclusion, invoke_counter=None):
    """Même patron que tests/test_verifier.py : .bind_tools() rejoue tool_responses puis répond sans
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
    monkeypatch.setattr(threader, "check_and_increment_llm_call", lambda node=None: None)
    monkeypatch.setattr(
        threader,
        "ChatAnthropic",
        _fake_chat_anthropic(tool_responses, conclusion or _FakeConclusion(), invoke_counter),
    )


def test_thread_skips_escalation_without_a_free_candidate(monkeypatch):
    """Filtre gratuit (docs/cadrage.md §10) : sans aucun candidat au chevauchement de mots-clés,
    pas d'appel LLM du tout — pas seulement thread_id resté None."""
    counter = [0]
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(), invoke_counter=counter)

    item = _analyzed_item("a", title_fr="Sujet isolé", summary="Rien à rapprocher dans l'historique")
    result = threader.thread_events({"raw_items": [], "analyzed_items": [item]})

    assert result["analyzed_items"][0]["thread_id"] is None
    assert counter[0] == 0


def test_thread_skips_escalation_below_the_gate_score_once_idf_is_active(monkeypatch):
    """THREAD_GATE_MIN_SCORE (backend/config.py, posé le 2026-08-20 sur backend/eval/pairs.json) est
    appliqué au portillon, pas seulement « au moins un candidat » : dans une fenêtre >= 3 items où
    le seul candidat partage un score IDF mesurable mais loin sous le seuil, aucun appel LLM ne part."""
    counter = [0]
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(), invoke_counter=counter)
    store.record_analyzed(
        [
            _analyzed_item("c", title_fr="Rafale vendu à la Grèce", summary="Dassault confirme la vente"),
            _analyzed_item("filler-1", title_fr="Sous-marins nucléaires australiens", summary="Accord AUKUS signé"),
            _analyzed_item("filler-2", title_fr="Drones Bayraktar en Ukraine", summary="Livraison confirmée par Kyiv"),
        ]
    )

    item = _analyzed_item("a", title_fr="Rafale Grèce", summary="contrat")
    result = threader.thread_events({"raw_items": [], "analyzed_items": [item]})

    assert result["analyzed_items"][0]["thread_id"] is None
    assert counter[0] == 0


def test_thread_assigns_a_shared_thread_id_to_a_matching_historical_item(monkeypatch):
    store.record_analyzed(
        [_analyzed_item("c", title_fr="Rafale vendu à la Grèce", summary="Dassault livre des Rafale")]
    )
    tool_call = _FakeToolCallResponse(
        [{"name": "find_thread_candidates", "args": {"query": "Rafale Grèce"}, "id": "c1"}]
    )
    _patch_llm(monkeypatch, tool_responses=[tool_call], conclusion=_FakeConclusion(same_story_as="c"))

    item = _analyzed_item("a", title_fr="Rafale vendu à la Grèce", summary="Contrat Dassault confirmé")
    result = threader.thread_events({"raw_items": [], "analyzed_items": [item]})

    assert result["analyzed_items"][0]["thread_id"] is not None
    # L'ancien enregistrement est réécrit lui aussi, pas seulement le nouveau (put_analyzed remplace
    # par lien, pas de patch partiel — cf. backend/memory/persistence.py).
    by_link = {r["link"]: r for r in store.load_digest(1)}
    assert by_link["c"]["thread_id"] == result["analyzed_items"][0]["thread_id"]


def test_thread_lets_two_items_of_the_same_run_share_a_thread(monkeypatch):
    """Contrairement au vérificateur, thread ne doit pas exclure les items du run en cours : deux
    sources qui couvrent le même événement le même jour sont le cas le plus net de « même dossier »,
    alors que la corroboration exige au contraire une confirmation indépendante dans le temps."""
    items = [
        _analyzed_item("a", title_fr="Rafale vendu à la Grèce", summary="Dassault confirme la vente"),
        _analyzed_item("b", title_fr="Rafale vendu à la Grèce", summary="Athènes officialise l'achat"),
    ]
    store.record_analyzed(items)  # verify() aurait déjà écrit ces items avant que thread s'exécute

    tool_call = _FakeToolCallResponse(
        [{"name": "find_thread_candidates", "args": {"query": "Rafale Grèce"}, "id": "c1"}]
    )
    _patch_llm(monkeypatch, tool_responses=[tool_call], conclusion=_FakeConclusion(same_story_as="a"))

    result = threader.thread_events({"raw_items": [], "analyzed_items": items})

    by_link = {i["link"]: i for i in result["analyzed_items"]}
    assert by_link["a"]["thread_id"] is not None
    assert by_link["a"]["thread_id"] == by_link["b"]["thread_id"]


def test_thread_respects_max_escalations_per_run(monkeypatch):
    monkeypatch.setattr(threader, "MAX_THREAD_ESCALATIONS_PER_RUN", 1)
    store.record_analyzed(
        [_analyzed_item("c", title_fr="Rafale vendu à la Grèce", summary="Dassault livre des Rafale")]
    )
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(same_story_as="c"))

    items = [
        _analyzed_item("a", title_fr="Rafale vendu à la Grèce", summary="Contrat Dassault confirmé"),
        _analyzed_item("b", title_fr="Rafale vendu à la Grèce", summary="Livraison Dassault annoncée"),
    ]
    result = threader.thread_events({"raw_items": [], "analyzed_items": items})

    by_link = {i["link"]: i for i in result["analyzed_items"]}
    assert by_link["a"]["thread_id"] is not None
    assert by_link["b"]["thread_id"] is None


def test_thread_stops_tool_loop_at_max_steps(monkeypatch):
    monkeypatch.setattr(threader, "MAX_THREAD_STEPS_PER_ITEM", 2)
    store.record_analyzed(
        [_analyzed_item("c", title_fr="Rafale vendu à la Grèce", summary="Dassault livre des Rafale")]
    )

    always_tool = [
        _FakeToolCallResponse([{"name": "find_thread_candidates", "args": {"query": "x"}, "id": "c1"}])
        for _ in range(10)
    ]
    counter = [0]
    _patch_llm(monkeypatch, tool_responses=always_tool, conclusion=_FakeConclusion(), invoke_counter=counter)

    item = _analyzed_item("a", title_fr="Rafale vendu à la Grèce", summary="Contrat Dassault confirmé")
    threader.thread_events({"raw_items": [], "analyzed_items": [item]})

    assert counter[0] == 2  # plafonné, jamais le nombre de réponses factices disponibles (10)


def test_thread_truncates_without_losing_the_items_already_analyzed(monkeypatch):
    store.record_analyzed(
        [_analyzed_item("c", title_fr="Rafale vendu à la Grèce", summary="Dassault livre des Rafale")]
    )
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(same_story_as="c"))

    calls = [0]

    def _budget(node=None):
        # Laisse passer le premier item (boucle d'outil + conclusion), coupe pendant le second.
        calls[0] += 1
        if calls[0] > 2:
            raise threader.BudgetExceeded("plafond atteint")

    monkeypatch.setattr(threader, "check_and_increment_llm_call", _budget)

    items = [
        _analyzed_item("a", title_fr="Rafale vendu à la Grèce", summary="Contrat Dassault confirmé"),
        _analyzed_item("b", title_fr="Rafale vendu à la Grèce", summary="Livraison Dassault annoncée"),
    ]
    result = threader.thread_events({"raw_items": [], "analyzed_items": items})

    by_link = {i["link"]: i for i in result["analyzed_items"]}
    assert by_link["a"]["thread_id"] is not None
    assert by_link["b"]["thread_id"] is None
    assert result["truncated"] is True
    assert len(result["analyzed_items"]) == 2


def test_thread_preserves_a_truncation_already_flagged_upstream(monkeypatch):
    _patch_llm(monkeypatch, conclusion=_FakeConclusion())

    item = _analyzed_item("a", title_fr="Sujet isolé", summary="Rien à rapprocher")
    result = threader.thread_events({"raw_items": [], "analyzed_items": [item], "truncated": True})

    assert result["truncated"] is True


def test_thread_never_touches_summary_or_citation(monkeypatch):
    store.record_analyzed(
        [_analyzed_item("c", title_fr="Rafale vendu à la Grèce", summary="Dassault livre des Rafale")]
    )
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(same_story_as="c"))

    item = _analyzed_item("a", title_fr="Rafale vendu à la Grèce", summary="Contrat Dassault confirmé")
    result = threader.thread_events({"raw_items": [], "analyzed_items": [item]})

    assert result["analyzed_items"][0]["summary"] == "Contrat Dassault confirmé"
    assert result["analyzed_items"][0]["citation"] == "citation originale"


def test_thread_ignores_a_hallucinated_link_not_in_the_search_window(monkeypatch):
    store.record_analyzed(
        [_analyzed_item("c", title_fr="Rafale vendu à la Grèce", summary="Dassault livre des Rafale")]
    )
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(same_story_as="does-not-exist"))

    item = _analyzed_item("a", title_fr="Rafale vendu à la Grèce", summary="Contrat Dassault confirmé")
    result = threader.thread_events({"raw_items": [], "analyzed_items": [item]})

    assert result["analyzed_items"][0]["thread_id"] is None


def test_thread_records_the_gate_result_on_every_item(monkeypatch):
    """Le portillon est une mesure, et il est écrit même quand il refuse : sans has_thread_candidate,
    un thread_id nul ne dit pas si l'historique ne portait aucun dossier proche ou si le run a coupé
    avant d'y regarder (cf. la docstring de thread_events)."""
    _patch_llm(monkeypatch, conclusion=_FakeConclusion())

    item = _analyzed_item("a", title_fr="Sujet isolé", summary="Rien à rapprocher dans l'historique")
    result = threader.thread_events({"raw_items": [], "analyzed_items": [item]})

    assert result["analyzed_items"][0]["has_thread_candidate"] is False
    assert result["analyzed_items"][0]["thread_checked"] is False


def test_thread_marks_an_item_the_model_examined_without_finding_a_match(monkeypatch):
    """Escaladé, conclu « aucun dossier » : c'est le silence le plus fort des trois, et il ne doit
    pas se lire comme le plafond du run."""
    store.record_analyzed(
        [_analyzed_item("c", title_fr="Rafale vendu à la Grèce", summary="Dassault livre des Rafale")]
    )
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(same_story_as=None))

    item = _analyzed_item("a", title_fr="Rafale vendu à la Grèce", summary="Contrat Dassault confirmé")
    result = threader.thread_events({"raw_items": [], "analyzed_items": [item]})

    assert result["analyzed_items"][0]["thread_id"] is None
    assert result["analyzed_items"][0]["has_thread_candidate"] is True
    assert result["analyzed_items"][0]["thread_checked"] is True


def test_thread_separates_a_capped_item_from_one_without_candidates(monkeypatch):
    """Le défaut mesuré au run du 2026-08-21 : 17 items éligibles, 3 rattachés, et rien à l'écran
    pour distinguer les 14 autres d'items sans dossier."""
    monkeypatch.setattr(threader, "MAX_THREAD_ESCALATIONS_PER_RUN", 1)
    store.record_analyzed(
        [_analyzed_item("c", title_fr="Rafale vendu à la Grèce", summary="Dassault livre des Rafale")]
    )
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(same_story_as="c"))

    items = [
        _analyzed_item("a", title_fr="Rafale vendu à la Grèce", summary="Contrat Dassault confirmé"),
        _analyzed_item("b", title_fr="Rafale vendu à la Grèce", summary="Livraison Dassault annoncée"),
    ]
    result = threader.thread_events({"raw_items": [], "analyzed_items": items})

    capped = {i["link"]: i for i in result["analyzed_items"]}["b"]
    assert capped["thread_id"] is None
    # Un candidat existait — l'absence de rattachement est une absence de mesure, pas une mesure.
    assert capped["has_thread_candidate"] is True
    assert capped["thread_checked"] is False


def test_thread_leaves_an_item_unchecked_when_the_budget_dies_before_its_conclusion(monkeypatch):
    """L'item sur lequel BudgetExceeded tombe a été escaladé mais jamais jugé : le compter comme
    examiné le ferait passer pour un item que le modèle a regardé et écarté."""
    store.record_analyzed(
        [_analyzed_item("c", title_fr="Rafale vendu à la Grèce", summary="Dassault livre des Rafale")]
    )
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(same_story_as="c"))

    calls = [0]

    def _budget(node=None):
        calls[0] += 1
        if calls[0] > 2:
            raise threader.BudgetExceeded("plafond atteint")

    monkeypatch.setattr(threader, "check_and_increment_llm_call", _budget)

    items = [
        _analyzed_item("a", title_fr="Rafale vendu à la Grèce", summary="Contrat Dassault confirmé"),
        _analyzed_item("b", title_fr="Rafale vendu à la Grèce", summary="Livraison Dassault annoncée"),
    ]
    result = threader.thread_events({"raw_items": [], "analyzed_items": items})

    by_link = {i["link"]: i for i in result["analyzed_items"]}
    assert by_link["a"]["thread_checked"] is True
    assert by_link["b"]["has_thread_candidate"] is True
    assert by_link["b"]["thread_checked"] is False


def test_thread_persists_the_silence_state_of_items_it_did_not_attach(monkeypatch):
    """Le digest se lit depuis l'historique, jamais depuis l'état du graphe (store.load_digest) : les
    deux champs doivent donc être écrits pour tout le lot, pas seulement pour les liens touchés."""
    _patch_llm(monkeypatch, conclusion=_FakeConclusion())

    item = _analyzed_item("a", title_fr="Sujet isolé", summary="Rien à rapprocher dans l'historique")
    threader.thread_events({"raw_items": [], "analyzed_items": [item]})

    stored = {r["link"]: r for r in store.load_digest(1)}["a"]
    assert stored["has_thread_candidate"] is False
    assert stored["thread_checked"] is False


def test_thread_charges_its_llm_calls_to_the_thread_node(monkeypatch):
    """Vérifie le câblage de bout en bout, pas seulement la signature : le garde-fou réel est laissé
    en place (seul le modèle est simulé), donc l'imputation constatée est celle que produira un vrai
    run. Sans ce test, un nœud pourrait passer un mauvais label sans qu'aucune assertion ne bouge —
    et la répartition, qui sert à arbitrer le budget (docs/cadrage.md §11), désignerait le mauvais
    coupable."""
    import backend.guardrails as guardrails

    monkeypatch.setattr(guardrails, "MAX_LLM_CALLS_PER_DAY", 50)
    monkeypatch.setattr(threader, "ChatAnthropic", _fake_chat_anthropic((), _FakeConclusion()))

    # Fenêtre < 3 items : la pondération IDF n'est pas active et le portillon retombe sur « au moins
    # un candidat » (cf. store.search_thread_candidates). C'est le cas canonique du thread, et le
    # seul qui garantisse une escalade ici — ce test mesure l'imputation, pas le seuil.
    store.record_analyzed([_analyzed_item("hist-1", title_fr="Rafale vendu à la Grèce", summary="Dassault confirme")])
    item = _analyzed_item("new", title_fr="Rafale vendu à la Grèce", summary="Dassault confirme")

    threader.thread_events({"raw_items": [], "analyzed_items": [item]})

    tally = guardrails.calls_by_node()
    assert set(tally) == {"thread"}, f"le nœud thread impute ailleurs : {tally}"
    assert tally["thread"] > 0
