"""Thread node: groups items that cover the same story into chronological threads (V3 slice 1, see
docs/scoping.md §10). Same pattern as the verifier (backend/agents/verifier.py): a bounded agentic
loop, and a search tool the LLM decides for itself whether to call before concluding.

Two deliberate differences from the verifier:

- No per-category filter: out_of_scope never reaches analyzed_items (backend/agents/analyst.py
  discards it before they are built), so every item that gets this far is already eligible to be
  attached to a story — VERIFIER_CATEGORIES covered only 2 of the 6 categories because V2
  cross-checking specifically targets legal risk, a restriction with no purpose here.
- No exclusion of the items of the current run: the verifier's corroboration requires an independent
  confirmation over time (backend/memory/store.py, docstring of search_related), whereas two sources
  covering the same event on the same day are on the contrary the clearest case of "same story".
"""

import uuid

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from backend.config import MAX_THREAD_ESCALATIONS_PER_RUN, MAX_THREAD_STEPS_PER_ITEM, THREAD_GATE_MIN_SCORE
from backend.guardrails import BudgetExceeded, check_and_increment_llm_call
from backend.logging_setup import get_logger
from backend.memory.store import analyzed_window, record_analyzed, search_thread_candidates
from backend.state import AnalyzedItem, VigieState

log = get_logger("thread")

MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """You are a defence/geopolitics intelligence analyst. You are given an item that has
already been classified and summarised. Your task: determine whether it covers the same story as an
item already analysed — same parties, same operation, same contract — not merely the same general
theme or the same country.

Use the find_thread_candidates tool to look for already analysed items that might be about the same
story (companies, countries, type of contract/movement mentioned in the summary). You may call it
several times with different queries if the first returns nothing useful, but do not persist if the
results are plainly unrelated.

Once your search is done (or if you judge that no further search would help), conclude with
same_story_as: the exact link of one of the candidates returned by the tool if one of them clearly
covers the same story, or null otherwise. A shared theme or country is not enough."""


class _ThreadDecision(BaseModel):
    same_story_as: str | None = Field(
        description="Exact link of the candidate that covers the same story, or null if none matches"
    )


def _make_thread_tool(current_link: str):
    @tool
    def find_thread_candidates(query: str) -> str:
        """Searches the history of already analysed items (up to 7 days, including the current run)
        for those that might cover the same story. `query`: relevant keywords (company names,
        countries, type of contract, and so on)."""
        results = search_thread_candidates(query, exclude_link=current_link, limit=5)
        if not results:
            return "No matching item found in the history."
        return "\n".join(
            f"- [{r['date']}] {r['country']}/{r['category']}: {r['title_en']} "
            f"(source: {r['source']}, link: {r['link']})"
            for r in results
        )

    return find_thread_candidates


def _thread_item(item: AnalyzedItem) -> str | None:
    """Agentic loop bounded by MAX_THREAD_STEPS_PER_ITEM, same structure as verifier._verify_item.
    Returns the link of the candidate judged to be the same story, or None."""
    search_tool = _make_thread_tool(item["link"])
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

    for _ in range(MAX_THREAD_STEPS_PER_ITEM):
        check_and_increment_llm_call("thread")
        response = llm.invoke(messages)
        if not response.tool_calls:
            break
        messages.append(response)
        for call in response.tool_calls:
            result = search_tool.invoke(call["args"])
            messages.append(ToolMessage(content=result, tool_call_id=call["id"]))

    check_and_increment_llm_call("thread")
    concluder = ChatAnthropic(model=MODEL, temperature=0).with_structured_output(_ThreadDecision)
    messages.append(HumanMessage(content="Conclude now with same_story_as."))
    conclusion = concluder.invoke(messages)
    return conclusion.same_story_as


def thread_events(state: VigieState) -> VigieState:
    """LangGraph node: attaches each item to a thread_id shared with the items of the same story.

    Filter before escalation: an item is only escalated to the LLM if its best candidate in the
    history reaches THREAD_GATE_MIN_SCORE (IDF-weighted overlap score, see store._overlap_score);
    otherwise it stays thread_id=None with no call. Capped on top of that at
    MAX_THREAD_ESCALATIONS_PER_RUN per run, like the verifier.

    This threshold replaces the free "at least one candidate" filter used until 2026-08-20: measured
    over 199 real items, that filter was cleared by 100% of items, including after IDF weighting of
    the score — the query being the whole title and summary, it almost always shares a token with at
    least one record in the window, so it bounded nothing. THREAD_GATE_MIN_SCORE was calibrated on
    the sample of 65 hand-annotated pairs (backend/eval/pairs.json, backend/eval/score_pairs.py):
    >= 20 retains an estimated 62.0% of true matches, against 20.2% at >= 10 (the old filter, in
    practice). That threshold only applies when IDF weighting is active (window >= 3 items, see
    store.search_thread_candidates) — below that, the score is a raw count on an unrelated scale, and
    the filter falls back to "at least one candidate" so as not to make the canonical thread case
    ineligible (two sources from the same run, history still empty).

    The gate's result is written on every item (has_thread_candidate), escalated or not, and doubled
    by thread_checked, which says whether the model actually concluded. Two are needed where the
    verifier makes do with has_antecedent_candidate, because a threader escalation does not always
    produce an attachment: the model can look and conclude that no candidate covers the same story,
    which is a measurement, not a silence. Without these two fields, a null thread_id conflated three
    states — measured on the 2026-08-21 run, where 17 items cleared the gate for 3 attached, the
    other 14 being indistinguishable on screen from items with no story.

    The history window is loaded once (verify() has already written the items of the current run
    before this node runs, so they are already in it) and kept up to date in memory as the loop goes:
    an item processed early in the run can therefore be found, with its freshly assigned thread_id, by
    an item processed later in the same run. When the candidate found does not have a thread_id yet, a
    new identifier is created and attached to both — the older record is rewritten in full
    (put_analyzed replaces by link, no partial patch, see backend/memory/persistence.py). Merging two
    already distinct threads is not handled in v1.
    """
    window = analyzed_window()

    escalated = 0
    budget_exhausted = False
    touched_links: set[str] = set()
    gate: dict[str, bool] = {}
    checked: dict[str, bool] = {}

    for item in state["analyzed_items"]:
        probe = search_thread_candidates(
            f"{item['title_en']} {item['summary']}",
            exclude_link=item["link"],
            limit=1,
            min_score=THREAD_GATE_MIN_SCORE,
        )
        gate[item["link"]] = bool(probe)
        checked[item["link"]] = False
        escalatable = not budget_exhausted and bool(probe) and escalated < MAX_THREAD_ESCALATIONS_PER_RUN
        if not escalatable:
            continue

        escalated += 1
        try:
            winner_link = _thread_item(item)
        except BudgetExceeded:
            # Escalated but never concluded: `checked` stays False, otherwise the display would read
            # this item as examined and storyless, when in fact nothing was judged.
            budget_exhausted = True
            continue
        checked[item["link"]] = True

        if not winner_link or winner_link == item["link"] or winner_link not in window:
            # A link absent from the window queried, or an item referencing itself: a model
            # hallucination rather than an attachment fabricated on an unverified basis.
            continue

        winner = window[winner_link]
        # window may not carry the current item yet: verify() always writes it there in production
        # before this node runs, but nothing must break if a caller (a unit test, say) has not —
        # fall back on the item itself.
        mine = window.setdefault(item["link"], item)
        thread_id = winner.get("thread_id") or mine.get("thread_id") or str(uuid.uuid4())

        if mine.get("thread_id") != thread_id:
            window[item["link"]] = {**mine, "thread_id": thread_id}
            touched_links.add(item["link"])
        if winner.get("thread_id") != thread_id:
            window[winner_link] = {**winner, "thread_id": thread_id}
            touched_links.add(winner_link)

    # Rebuilt from the original items (strict AnalyzedItem shape), not from window: window's records
    # carry persistence fields (date, first_seen) that have no place in the graph state, only
    # thread_id should come back up.
    updated_items = [
        {
            **item,
            "thread_id": window.get(item["link"], item).get("thread_id"),
            "has_thread_candidate": gate[item["link"]],
            "thread_checked": checked[item["link"]],
        }
        for item in state["analyzed_items"]
    ]
    # The whole batch is rewritten, not only the touched links: the two state fields above apply to
    # unattached items as much as to the others, and the digest is read from the history
    # (store.load_digest), never from the graph state. One extra write per item per run, of the same
    # order as the verifier's two passes — that is the price of the display. Touched links outside the
    # batch (a historical antecedent receiving the shared thread_id) are added to it: those are not in
    # `updated_items`.
    batch_links = {item["link"] for item in state["analyzed_items"]}
    record_analyzed(updated_items + [window[link] for link in touched_links if link not in batch_links])

    # The four states the front distinguishes (no candidate / examined / attached / not searched) are
    # logged with the same boundaries: without that, a cloud run would not say whether thin threading
    # comes from the history or from the cap, which is exactly the distinction the V3 slice cost two
    # days to make visible on screen.
    eligible = sum(1 for i in updated_items if i["has_thread_candidate"])
    if budget_exhausted:
        log.warning("thread grouping truncated by the daily cap", extra={"escalations": escalated})
    if escalated >= MAX_THREAD_ESCALATIONS_PER_RUN:
        log.warning(
            "run escalation cap reached",
            extra={"cap": MAX_THREAD_ESCALATIONS_PER_RUN, "eligible": eligible},
        )
    log.info(
        "thread grouping finished",
        extra={
            "items": len(updated_items),
            "eligible": eligible,
            "escalations": escalated,
            "attached": sum(1 for i in updated_items if i["thread_id"]),
            "examined_unattached": sum(1 for i in updated_items if i["thread_checked"] and not i["thread_id"]),
            "not_searched": sum(1 for i in updated_items if i["has_thread_candidate"] and not i["thread_checked"]),
            "budget_exhausted": budget_exhausted,
        },
    )
    return {"analyzed_items": updated_items, "truncated": state.get("truncated", False) or budget_exhausted}
