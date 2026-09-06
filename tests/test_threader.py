from backend.agents import threader
from backend.memory import store


def _analyzed_item(
    link: str,
    title_en: str = "translated title",
    summary: str = "summary",
    category: str = "military_movement",
) -> dict:
    return {
        "source": "s",
        "lang": "en",
        "country": "US",
        "state_affiliated": False,
        "title": "title",
        "title_en": title_en,
        "link": link,
        "published": "",
        "category": category,
        "summary": summary,
        "citation": "original citation",
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
    """Same pattern as tests/test_verifier.py: .bind_tools() replays tool_responses then answers with
    no tool, .with_structured_output() always returns `conclusion`."""

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
    """Free filter (docs/scoping.md §10): with no keyword-overlap candidate at all, no LLM call goes
    out — not merely a thread_id left at None."""
    counter = [0]
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(), invoke_counter=counter)

    item = _analyzed_item("a", title_en="Isolated subject", summary="Nothing to match in the history")
    result = threader.thread_events({"raw_items": [], "analyzed_items": [item]})

    assert result["analyzed_items"][0]["thread_id"] is None
    assert counter[0] == 0


def test_thread_skips_escalation_below_the_gate_score_once_idf_is_active(monkeypatch):
    """THREAD_GATE_MIN_SCORE (backend/config.py, set on 2026-08-20 from backend/eval/pairs.json) is
    applied at the gate, not merely "at least one candidate": in a window of >= 3 items where the only
    candidate shares a measurable IDF score but well below the threshold, no LLM call goes out."""
    counter = [0]
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(), invoke_counter=counter)
    store.record_analyzed(
        [
            _analyzed_item("c", title_en="Rafale sold to Greece", summary="Dassault confirms the sale"),
            _analyzed_item("filler-1", title_en="Australian nuclear submarines", summary="AUKUS agreement signed"),
            _analyzed_item("filler-2", title_en="Bayraktar drones in Ukraine", summary="Delivery confirmed by Kyiv"),
        ]
    )

    item = _analyzed_item("a", title_en="Rafale Greece", summary="contract")
    result = threader.thread_events({"raw_items": [], "analyzed_items": [item]})

    assert result["analyzed_items"][0]["thread_id"] is None
    assert counter[0] == 0


def test_thread_assigns_a_shared_thread_id_to_a_matching_historical_item(monkeypatch):
    store.record_analyzed(
        [_analyzed_item("c", title_en="Rafale sold to Greece", summary="Dassault delivers Rafale jets")]
    )
    tool_call = _FakeToolCallResponse(
        [{"name": "find_thread_candidates", "args": {"query": "Rafale Greece"}, "id": "c1"}]
    )
    _patch_llm(monkeypatch, tool_responses=[tool_call], conclusion=_FakeConclusion(same_story_as="c"))

    item = _analyzed_item("a", title_en="Rafale sold to Greece", summary="Dassault contract confirmed")
    result = threader.thread_events({"raw_items": [], "analyzed_items": [item]})

    assert result["analyzed_items"][0]["thread_id"] is not None
    # The older record is rewritten too, not only the new one (put_analyzed replaces by link, no
    # partial patch — see backend/memory/persistence.py).
    by_link = {r["link"]: r for r in store.load_digest(1)}
    assert by_link["c"]["thread_id"] == result["analyzed_items"][0]["thread_id"]


def test_thread_lets_two_items_of_the_same_run_share_a_thread(monkeypatch):
    """Unlike the verifier, thread must not exclude the items of the current run: two sources covering
    the same event on the same day are the clearest case of "same story", whereas corroboration on the
    contrary requires an independent confirmation over time."""
    items = [
        _analyzed_item("a", title_en="Rafale sold to Greece", summary="Dassault confirms the sale"),
        _analyzed_item("b", title_en="Rafale sold to Greece", summary="Athens confirms the purchase"),
    ]
    store.record_analyzed(items)  # verify() would already have written these before thread runs

    tool_call = _FakeToolCallResponse(
        [{"name": "find_thread_candidates", "args": {"query": "Rafale Greece"}, "id": "c1"}]
    )
    _patch_llm(monkeypatch, tool_responses=[tool_call], conclusion=_FakeConclusion(same_story_as="a"))

    result = threader.thread_events({"raw_items": [], "analyzed_items": items})

    by_link = {i["link"]: i for i in result["analyzed_items"]}
    assert by_link["a"]["thread_id"] is not None
    assert by_link["a"]["thread_id"] == by_link["b"]["thread_id"]


def test_thread_respects_max_escalations_per_run(monkeypatch):
    monkeypatch.setattr(threader, "MAX_THREAD_ESCALATIONS_PER_RUN", 1)
    store.record_analyzed(
        [_analyzed_item("c", title_en="Rafale sold to Greece", summary="Dassault delivers Rafale jets")]
    )
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(same_story_as="c"))

    items = [
        _analyzed_item("a", title_en="Rafale sold to Greece", summary="Dassault contract confirmed"),
        _analyzed_item("b", title_en="Rafale sold to Greece", summary="Dassault delivery announced"),
    ]
    result = threader.thread_events({"raw_items": [], "analyzed_items": items})

    by_link = {i["link"]: i for i in result["analyzed_items"]}
    assert by_link["a"]["thread_id"] is not None
    assert by_link["b"]["thread_id"] is None


def test_thread_stops_tool_loop_at_max_steps(monkeypatch):
    monkeypatch.setattr(threader, "MAX_THREAD_STEPS_PER_ITEM", 2)
    store.record_analyzed(
        [_analyzed_item("c", title_en="Rafale sold to Greece", summary="Dassault delivers Rafale jets")]
    )

    always_tool = [
        _FakeToolCallResponse([{"name": "find_thread_candidates", "args": {"query": "x"}, "id": "c1"}])
        for _ in range(10)
    ]
    counter = [0]
    _patch_llm(monkeypatch, tool_responses=always_tool, conclusion=_FakeConclusion(), invoke_counter=counter)

    item = _analyzed_item("a", title_en="Rafale sold to Greece", summary="Dassault contract confirmed")
    threader.thread_events({"raw_items": [], "analyzed_items": [item]})

    assert counter[0] == 2  # capped, never the number of fake responses available (10)


def test_thread_truncates_without_losing_the_items_already_analyzed(monkeypatch):
    store.record_analyzed(
        [_analyzed_item("c", title_en="Rafale sold to Greece", summary="Dassault delivers Rafale jets")]
    )
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(same_story_as="c"))

    calls = [0]

    def _budget(node=None):
        # Lets the first item through (tool loop + conclusion), cuts in during the second.
        calls[0] += 1
        if calls[0] > 2:
            raise threader.BudgetExceeded("cap reached")

    monkeypatch.setattr(threader, "check_and_increment_llm_call", _budget)

    items = [
        _analyzed_item("a", title_en="Rafale sold to Greece", summary="Dassault contract confirmed"),
        _analyzed_item("b", title_en="Rafale sold to Greece", summary="Dassault delivery announced"),
    ]
    result = threader.thread_events({"raw_items": [], "analyzed_items": items})

    by_link = {i["link"]: i for i in result["analyzed_items"]}
    assert by_link["a"]["thread_id"] is not None
    assert by_link["b"]["thread_id"] is None
    assert result["truncated"] is True
    assert len(result["analyzed_items"]) == 2


def test_thread_preserves_a_truncation_already_flagged_upstream(monkeypatch):
    _patch_llm(monkeypatch, conclusion=_FakeConclusion())

    item = _analyzed_item("a", title_en="Isolated subject", summary="Nothing to match")
    result = threader.thread_events({"raw_items": [], "analyzed_items": [item], "truncated": True})

    assert result["truncated"] is True


def test_thread_never_touches_summary_or_citation(monkeypatch):
    store.record_analyzed(
        [_analyzed_item("c", title_en="Rafale sold to Greece", summary="Dassault delivers Rafale jets")]
    )
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(same_story_as="c"))

    item = _analyzed_item("a", title_en="Rafale sold to Greece", summary="Dassault contract confirmed")
    result = threader.thread_events({"raw_items": [], "analyzed_items": [item]})

    assert result["analyzed_items"][0]["summary"] == "Dassault contract confirmed"
    assert result["analyzed_items"][0]["citation"] == "original citation"


def test_thread_ignores_a_hallucinated_link_not_in_the_search_window(monkeypatch):
    store.record_analyzed(
        [_analyzed_item("c", title_en="Rafale sold to Greece", summary="Dassault delivers Rafale jets")]
    )
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(same_story_as="does-not-exist"))

    item = _analyzed_item("a", title_en="Rafale sold to Greece", summary="Dassault contract confirmed")
    result = threader.thread_events({"raw_items": [], "analyzed_items": [item]})

    assert result["analyzed_items"][0]["thread_id"] is None


def test_thread_records_the_gate_result_on_every_item(monkeypatch):
    """The gate is a measurement, and it is written even when it refuses: without has_thread_candidate,
    a null thread_id does not say whether the history held no close story or whether the run cut in
    before looking (see the docstring of thread_events)."""
    _patch_llm(monkeypatch, conclusion=_FakeConclusion())

    item = _analyzed_item("a", title_en="Isolated subject", summary="Nothing to match in the history")
    result = threader.thread_events({"raw_items": [], "analyzed_items": [item]})

    assert result["analyzed_items"][0]["has_thread_candidate"] is False
    assert result["analyzed_items"][0]["thread_checked"] is False


def test_thread_marks_an_item_the_model_examined_without_finding_a_match(monkeypatch):
    """Escalated, concluded "no story": that is the strongest of the three silences, and it must not
    read as the run cap."""
    store.record_analyzed(
        [_analyzed_item("c", title_en="Rafale sold to Greece", summary="Dassault delivers Rafale jets")]
    )
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(same_story_as=None))

    item = _analyzed_item("a", title_en="Rafale sold to Greece", summary="Dassault contract confirmed")
    result = threader.thread_events({"raw_items": [], "analyzed_items": [item]})

    assert result["analyzed_items"][0]["thread_id"] is None
    assert result["analyzed_items"][0]["has_thread_candidate"] is True
    assert result["analyzed_items"][0]["thread_checked"] is True


def test_thread_separates_a_capped_item_from_one_without_candidates(monkeypatch):
    """The defect measured on the 2026-08-21 run: 17 eligible items, 3 attached, and nothing on screen
    to tell the other 14 apart from items with no story."""
    monkeypatch.setattr(threader, "MAX_THREAD_ESCALATIONS_PER_RUN", 1)
    store.record_analyzed(
        [_analyzed_item("c", title_en="Rafale sold to Greece", summary="Dassault delivers Rafale jets")]
    )
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(same_story_as="c"))

    items = [
        _analyzed_item("a", title_en="Rafale sold to Greece", summary="Dassault contract confirmed"),
        _analyzed_item("b", title_en="Rafale sold to Greece", summary="Dassault delivery announced"),
    ]
    result = threader.thread_events({"raw_items": [], "analyzed_items": items})

    capped = {i["link"]: i for i in result["analyzed_items"]}["b"]
    assert capped["thread_id"] is None
    # A candidate did exist — the absence of an attachment is an absence of measurement, not a
    # measurement.
    assert capped["has_thread_candidate"] is True
    assert capped["thread_checked"] is False


def test_thread_leaves_an_item_unchecked_when_the_budget_dies_before_its_conclusion(monkeypatch):
    """The item BudgetExceeded falls on was escalated but never judged: counting it as examined would
    make it look like an item the model looked at and set aside."""
    store.record_analyzed(
        [_analyzed_item("c", title_en="Rafale sold to Greece", summary="Dassault delivers Rafale jets")]
    )
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(same_story_as="c"))

    calls = [0]

    def _budget(node=None):
        calls[0] += 1
        if calls[0] > 2:
            raise threader.BudgetExceeded("cap reached")

    monkeypatch.setattr(threader, "check_and_increment_llm_call", _budget)

    items = [
        _analyzed_item("a", title_en="Rafale sold to Greece", summary="Dassault contract confirmed"),
        _analyzed_item("b", title_en="Rafale sold to Greece", summary="Dassault delivery announced"),
    ]
    result = threader.thread_events({"raw_items": [], "analyzed_items": items})

    by_link = {i["link"]: i for i in result["analyzed_items"]}
    assert by_link["a"]["thread_checked"] is True
    assert by_link["b"]["has_thread_candidate"] is True
    assert by_link["b"]["thread_checked"] is False


def test_thread_persists_the_silence_state_of_items_it_did_not_attach(monkeypatch):
    """The digest is read from the history, never from the graph state (store.load_digest): both
    fields must therefore be written for the whole batch, not only for the touched links."""
    _patch_llm(monkeypatch, conclusion=_FakeConclusion())

    item = _analyzed_item("a", title_en="Isolated subject", summary="Nothing to match in the history")
    threader.thread_events({"raw_items": [], "analyzed_items": [item]})

    stored = {r["link"]: r for r in store.load_digest(1)}["a"]
    assert stored["has_thread_candidate"] is False
    assert stored["thread_checked"] is False


def test_thread_charges_its_llm_calls_to_the_thread_node(monkeypatch):
    """Checks the wiring end to end, not just the signature: the real guardrail is left in place (only
    the model is simulated), so the attribution observed is the one a real run will produce. Without
    this test, a node could pass a wrong label without any assertion moving — and the split, which
    serves to arbitrate the budget (docs/scoping.md §11), would name the wrong culprit."""
    import backend.guardrails as guardrails

    monkeypatch.setattr(guardrails, "MAX_LLM_CALLS_PER_DAY", 50)
    monkeypatch.setattr(threader, "ChatAnthropic", _fake_chat_anthropic((), _FakeConclusion()))

    # Window < 3 items: IDF weighting is not active and the gate falls back to "at least one
    # candidate" (see store.search_thread_candidates). That is the canonical thread case, and the only
    # one that guarantees an escalation here — this test measures the attribution, not the threshold.
    store.record_analyzed([_analyzed_item("hist-1", title_en="Rafale sold to Greece", summary="Dassault confirms")])
    item = _analyzed_item("new", title_en="Rafale sold to Greece", summary="Dassault confirms")

    threader.thread_events({"raw_items": [], "analyzed_items": [item]})

    tally = guardrails.calls_by_node()
    assert set(tally) == {"thread"}, f"the thread node is charging elsewhere: {tally}"
    assert tally["thread"] > 0
