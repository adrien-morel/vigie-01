"""Verifier node: cross-checking and a confidence score (first slice of docs/scoping.md §10 V2 — see
backend/memory/store.py for the cross-checking history). Unlike analyze(), this node has a genuine
bounded agentic loop: the LLM decides for itself whether to look for extra context before concluding.

What bounds the cost changed on 2026-08-20: it is no longer the category of the item but the
existence of a candidate antecedent in the history (VERIFIER_GATE_MIN_SCORE). The whole MECE
perimeter is now eligible, and an item whose window holds nothing close enough is not escalated — it
would produce a non-answer paid for with 2 to 3 calls.
"""

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from backend.config import (
    MAX_VERIFIER_ESCALATIONS_PER_RUN,
    MAX_VERIFIER_STEPS_PER_ITEM,
    VERIFIER_CATEGORIES,
    VERIFIER_GATE_MIN_SCORE,
)
from backend.guardrails import BudgetExceeded, check_and_increment_llm_call
from backend.logging_setup import get_logger
from backend.memory.store import has_antecedent, record_analyzed, search_related
from backend.state import AnalyzedItem, VigieState

log = get_logger("verify")

MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """You are a defence/geopolitics intelligence verifier. You are given an item that
has already been classified and summarised. Your task: assess its reliability by looking for earlier
items that corroborate this story.

Use the search_related_items tool to look for items already analysed on the same subject (companies,
countries, type of contract/movement mentioned in the summary). You may call it several times with
different queries if the first returns nothing useful, but do not persist if the results are
plainly unrelated.

Once your search is done (or if you judge that no further search would help), conclude with a
confidence score (0 to 1) and a corroborated boolean:
- corroborated=True if at least one earlier item clearly deals with the same story (same contract,
  same movement, same parties) — not merely the same general theme.
- The confidence score reflects your overall confidence in the summary, not only the corroboration:
  an uncorroborated item whose citation is clear and unambiguous can have a decent score
  (0.6-0.7, say); an item corroborated by several independent sources deserves a high score (0.85+);
  an isolated item with a summary that leaves room for interpretation deserves a lower one."""


class _VerifierResult(BaseModel):
    # The stored field and the schema property now carry the same name. They were deliberately kept
    # apart for a while: `with_structured_output` sends this schema to the model, properties
    # included, so renaming it is a prompt change and has to be retested, whereas renaming the stored
    # field changes nothing the model sees. Unified on 2026-09-06, in the same pass that rewrote this
    # prompt in English — that pass had to be retested end to end anyway, so the rename rides along
    # with it rather than costing a retest of its own.
    model_confidence: float = Field(description="Overall confidence score, between 0 and 1")
    corroborated: bool = Field(description="At least one earlier item clearly deals with the same story")


def _make_search_tool(exclude_links: set[str]):
    @tool
    def search_related_items(query: str) -> str:
        """Searches the history of already analysed items (up to 7 days) for those that could
        corroborate or add context to the story at hand. `query`: relevant keywords (company names,
        countries, type of contract, and so on)."""
        results = search_related(query, exclude_links=exclude_links, limit=5)
        if not results:
            return "No matching item found in the history."
        return "\n".join(
            f"- [{r['date']}] {r['country']}/{r['category']}: {r['title_en']} (source: {r['source']})" for r in results
        )

    return search_related_items


def _verify_item(item: AnalyzedItem, exclude_links: set[str]) -> tuple[float, bool]:
    """Agentic loop bounded by MAX_VERIFIER_STEPS_PER_ITEM. Every LLM call (tool decision or
    conclusion) goes through check_and_increment_llm_call() — the existing daily cap
    (MAX_LLM_CALLS_PER_DAY) therefore absorbs this node too, with no separate guardrail."""
    search_tool = _make_search_tool(exclude_links)
    llm = ChatAnthropic(model=MODEL, temperature=0).bind_tools([search_tool])

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"Category: {item['category']}\n"
                f"Summary: {item['summary']}\n"
                f"Citation: {item['citation']}\n"
                f"Country/place: {item['location']}"
            )
        ),
    ]

    for _ in range(MAX_VERIFIER_STEPS_PER_ITEM):
        check_and_increment_llm_call("verify")
        response = llm.invoke(messages)
        if not response.tool_calls:
            break
        messages.append(response)
        for call in response.tool_calls:
            result = search_tool.invoke(call["args"])
            messages.append(ToolMessage(content=result, tool_call_id=call["id"]))

    check_and_increment_llm_call("verify")
    concluder = ChatAnthropic(model=MODEL, temperature=0).with_structured_output(_VerifierResult)
    messages.append(HumanMessage(content="Conclude now with your confidence score and corroborated."))
    conclusion = concluder.invoke(messages)
    return conclusion.model_confidence, conclusion.corroborated


def verify(state: VigieState) -> VigieState:
    """LangGraph node: adds model_confidence/corroborated to the items the gate retains, capped at
    MAX_VERIFIER_ESCALATIONS_PER_RUN per run. The others keep model_confidence/corroborated at None —
    no score fabricated without a real basis.

    The gate (store.has_antecedent, threshold VERIFIER_GATE_MIN_SCORE) is computed for the whole
    batch in a single history read, before the loop: an item is escalated only if the window holds an
    antecedent whose IDF-weighted overlap reaches the threshold. It replaces the per-category
    restriction that played that role until 2026-08-20 — which bounded the cost by refusing to look
    at four categories out of five, not by telling verifiable items from the rest.

    Its result is written on every item (has_antecedent_candidate), escalated or not. Without it, two
    very different silences would be indistinguishable on screen: "the history held nothing to
    cross-check", which is a measurement, and "the run cap or the budget cut in before", which is an
    absence of measurement.

    The history is written twice, and that is intended. First before the escalation: this node makes
    network calls, and a failure part-way must not lose items that have already been analysed and
    paid for. Then after, so that the history holds the items as they will be displayed, scores
    included — it also feeds the digest served by the API (see store.load_digest). The write is an
    upsert by link that preserves the first-seen date: the second pass updates, it does not
    duplicate.

    The invariant "search_related_items never sees the current run, only the history of previous
    runs" therefore does not rest on the write order but on `exclude_links`, which carries every link
    in the batch — two items of the same run do not corroborate each other.

    If the daily cap falls during escalation, verification stops there but the node runs to the end:
    the remaining items are kept as they are, `model_confidence`/`corroborated` at None, and the
    history is written as usual. An item that has been analysed and paid for must not be lost because
    its verification could not be funded.
    """
    current_links = {item["link"] for item in state["analyzed_items"]}
    record_analyzed(state["analyzed_items"])

    gate = has_antecedent(
        {item["link"]: f"{item['title_en']} {item['summary']}" for item in state["analyzed_items"]},
        exclude_links=current_links,
        min_score=VERIFIER_GATE_MIN_SCORE,
    )

    escalated = 0
    budget_exhausted = False
    updated_items: list[AnalyzedItem] = []
    for original in state["analyzed_items"]:
        item: AnalyzedItem = {**original, "has_antecedent_candidate": gate[original["link"]]}
        escalatable = (
            not budget_exhausted
            and item["category"] in VERIFIER_CATEGORIES
            and gate[item["link"]]
            and escalated < MAX_VERIFIER_ESCALATIONS_PER_RUN
        )
        if not escalatable:
            updated_items.append(item)
            continue

        escalated += 1
        try:
            model_confidence, corroborated = _verify_item(item, current_links)
        except BudgetExceeded:
            # Nothing left to fund: this item and every one after it stay unverified. That is exactly
            # the "outside the verifier's perimeter" state that None already carries, and that the
            # display renders as such — no fabricated score to fill the gap.
            budget_exhausted = True
            updated_items.append(item)
            continue
        updated_items.append({**item, "model_confidence": model_confidence, "corroborated": corroborated})

    record_analyzed(updated_items)

    # `eligible` counts the gate being cleared, `escalations` what the run cap let through: the gap
    # between the two is exactly the measurement lost, and that is what the production rollout plan
    # asks to make visible under Scheduler (today a truncation leaves no usable trace outside the body
    # of the HTTP response).
    eligible = sum(1 for i in updated_items if gate[i["link"]] and i["category"] in VERIFIER_CATEGORIES)
    if budget_exhausted:
        log.warning("verification truncated by the daily cap", extra={"escalations": escalated})
    if escalated >= MAX_VERIFIER_ESCALATIONS_PER_RUN:
        log.warning(
            "run escalation cap reached",
            extra={"cap": MAX_VERIFIER_ESCALATIONS_PER_RUN, "eligible": eligible},
        )
    log.info(
        "verification finished",
        extra={
            "items": len(updated_items),
            "eligible": eligible,
            "escalations": escalated,
            "with_antecedent": sum(1 for i in updated_items if i.get("corroborated")),
            "without_antecedent": sum(1 for i in updated_items if i.get("corroborated") is False),
            "budget_exhausted": budget_exhausted,
        },
    )
    return {"analyzed_items": updated_items, "truncated": state.get("truncated", False) or budget_exhausted}
