from backend.agents import verifier
from backend.memory import store


def _analyzed_item(category: str, link: str = "l") -> dict:
    return {
        "source": "s",
        "lang": "en",
        "country": "US",
        "state_affiliated": False,
        "title": "title",
        "title_en": "translated title",
        "link": link,
        "published": "",
        "category": category,
        "summary": "original summary",
        "citation": "original citation",
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
    def __init__(self, model_confidence=0.7, corroborated=False):
        # The stand-in for the `_VerifierResult` schema, whose property the model fills. The schema
        # property and the stored field carry the same name since 2026-09-06, when the English pass
        # rewrote the prompt anyway and the rename could ride along with its retest.
        self.model_confidence = model_confidence
        self.corroborated = corroborated


def _fake_chat_anthropic(tool_responses, conclusion, invoke_counter=None):
    """Builds a fake ChatAnthropic: .bind_tools() replays tool_responses then answers with no tool,
    .with_structured_output() always returns `conclusion`."""

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
    """Opens the escalation gate, for the tests that are about something other than the gate itself.

    Two gestures, not one. An antecedent in the history first: since 2026-08-20 an empty history makes
    the whole batch ineligible — the intended behaviour (nothing to cross-check, so nothing to pay
    for), but not what the escalation tests measure. Then the threshold brought down to 0, because
    manufacturing an IDF-weighted overlap above 20 would take a dozen shared rare tokens in every
    test; the real threshold is exercised separately, in
    test_verify_skips_an_item_the_history_has_nothing_close_to.

    The filler with distinct vocabulary is not decorative: without it, every token in the window would
    be present in all of its records, hence of zero IDF weight (log(total / df) = 0), and the gate
    would stay shut even at threshold 0.
    """
    monkeypatch.setattr(verifier, "VERIFIER_GATE_MIN_SCORE", 0.0)
    store.record_analyzed(
        [
            _analyzed_item("arms_contract", "ante"),
            {
                **_analyzed_item("arms_contract", "ante-filler"),
                "title_en": "Unrelated subject",
                "summary": "No word in common",
            },
        ]
    )


def test_verify_escalates_every_category_of_the_perimeter(monkeypatch):
    """The category no longer bounds escalation since 2026-08-20: military_movement, outside the
    verifier's perimeter until then, is verified just like export_control as soon as the history holds
    a candidate antecedent. What bounds the cost is the gate."""
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(0.8, True))
    _open_the_gate(monkeypatch)

    items = [_analyzed_item("export_control", "a"), _analyzed_item("military_movement", "b")]
    result = verifier.verify({"raw_items": [], "analyzed_items": items})

    escalated = {i["link"]: i for i in result["analyzed_items"]}
    assert escalated["a"]["model_confidence"] == 0.8
    assert escalated["a"]["corroborated"] is True
    assert escalated["b"]["model_confidence"] == 0.8
    assert escalated["b"]["corroborated"] is True
    assert escalated["b"]["has_antecedent_candidate"] is True


def test_verify_skips_an_item_the_history_has_nothing_close_to(monkeypatch):
    """VERIFIER_GATE_MIN_SCORE is applied, not merely "at least one candidate": in a window of >= 3
    items where the only candidate shares a measurable IDF score but well below the threshold, no call
    goes out — and the item comes out marked as having no candidate antecedent, which distinguishes
    that silence from the silence of a cap being reached."""
    counter = [0]
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(), invoke_counter=counter)
    store.record_analyzed(
        [
            {**_analyzed_item("arms_contract", "c"), "title_en": "Rafale sold to Greece"},
            {**_analyzed_item("arms_contract", "filler-1"), "title_en": "Australian submarines"},
            {**_analyzed_item("arms_contract", "filler-2"), "title_en": "Bayraktar drones in Ukraine"},
        ]
    )

    item = {**_analyzed_item("arms_contract", "a"), "title_en": "Rafale Greece", "summary": "contract"}
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
    # The gate had retained b all the same: its silence comes from the cap, not from a mute history.
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

    assert counter[0] == 2  # capped, never the number of fake responses available (10)


def test_verify_never_touches_summary_or_citation(monkeypatch):
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(0.5, False))
    _open_the_gate(monkeypatch)

    item = _analyzed_item("arms_contract", "a")
    result = verifier.verify({"raw_items": [], "analyzed_items": [item]})

    assert result["analyzed_items"][0]["summary"] == "original summary"
    assert result["analyzed_items"][0]["citation"] == "original citation"


def test_verify_records_the_scored_items_not_their_pre_verification_version(monkeypatch):
    """The history also feeds the digest served by the API: it must hold the item as it will be
    displayed. Recorded before the escalation, it would have frozen model_confidence/corroborated at
    None."""
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(0.5, True))
    _open_the_gate(monkeypatch)

    verifier.verify({"raw_items": [], "analyzed_items": [_analyzed_item("arms_contract", "a")]})

    recorded = {r["link"]: r for r in store.load_digest(1)}
    assert recorded["a"]["model_confidence"] == 0.5
    assert recorded["a"]["corroborated"] is True


def test_verify_truncates_escalation_without_losing_the_items_already_analyzed(monkeypatch):
    """An item that has been analysed and paid for must not disappear because its verification could
    not be funded: the node goes to the end of the batch, leaves None on the unverified ones — the
    state the display already renders as "outside the verifier's perimeter" — and writes the
    history."""
    from backend.guardrails import BudgetExceeded

    _patch_llm(monkeypatch, conclusion=_FakeConclusion(0.8, True))
    _open_the_gate(monkeypatch)

    calls = [0]

    def _budget(node=None):
        # Lets the first item through (tool loop + conclusion), cuts in during the second.
        calls[0] += 1
        if calls[0] > 2:
            raise BudgetExceeded("cap reached")

    monkeypatch.setattr(verifier, "check_and_increment_llm_call", _budget)

    items = [_analyzed_item("export_control", "a"), _analyzed_item("export_control", "b")]
    result = verifier.verify({"raw_items": [], "analyzed_items": items})

    by_link = {i["link"]: i for i in result["analyzed_items"]}
    assert by_link["a"]["model_confidence"] == 0.8
    assert by_link["b"]["model_confidence"] is None
    assert result["truncated"] is True
    # Both items stay in the history: it is the history that feeds the digest served by the API.
    assert {"a", "b"} <= {r["link"] for r in store.load_digest(1)}


def test_verify_preserves_a_truncation_already_flagged_by_analyze(monkeypatch):
    """The flag travels across the graph: verify writes the same state key and must not erase a
    truncation that happened upstream, otherwise the API would announce a complete run."""
    _patch_llm(monkeypatch, conclusion=_FakeConclusion(0.8, True))

    result = verifier.verify(
        {"raw_items": [], "analyzed_items": [_analyzed_item("military_movement", "a")], "truncated": True}
    )

    assert result["truncated"] is True


def test_verify_never_lets_two_items_of_the_same_run_corroborate_each_other(monkeypatch):
    """The node used to write the history before escalating, then exclude only the current item's
    link: an item could therefore be "corroborated" by its batch neighbour, which brings no
    independent confirmation over time."""
    seen_queries = []

    tool_call = _FakeToolCallResponse([{"name": "search_related_items", "args": {"query": "Rafale"}, "id": "c1"}])
    _patch_llm(monkeypatch, tool_responses=[tool_call], conclusion=_FakeConclusion(0.5, False))
    _open_the_gate(monkeypatch)

    items = [_analyzed_item("export_control", "a"), _analyzed_item("export_control", "b")]
    items[0]["summary"] = items[1]["summary"] = "Rafale sold to Greece by Dassault"

    original = verifier.search_related

    def _spy(query, exclude_links, limit=5):
        seen_queries.append(set(exclude_links))
        return original(query, exclude_links=exclude_links, limit=limit)

    monkeypatch.setattr(verifier, "search_related", _spy)
    verifier.verify({"raw_items": [], "analyzed_items": items})

    assert seen_queries, "the search tool was not called"
    assert all(excluded == {"a", "b"} for excluded in seen_queries)
