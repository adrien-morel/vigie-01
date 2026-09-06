"""Shared state schema for the LangGraph pipeline (VigieState, see README)."""

from typing import Literal, TypedDict

# MECE in-scope categories (see docs/scoping.md §4) plus out_of_scope for items coming from the
# source feeds that fall outside the restricted perimeter (general tech news, cyber, and so on).
Category = Literal[
    "export_control",
    "arms_contract",
    "military_movement",
    "defense_diplomacy",
    "industrial_program",
    "out_of_scope",
]


class RawItem(TypedDict):
    source: str
    theme: str
    lang: str
    country: str  # country code of the source (see backend/config.py), not of the article
    state_affiliated: bool  # state media or tied to an official service (see backend/config.py)
    title: str
    link: str
    published: str  # ISO 8601 when the feed provides it, empty string otherwise
    raw_text: str


class AnalyzedItem(TypedDict):
    source: str
    lang: str
    country: str
    state_affiliated: bool
    title: str  # original title, in the language of the source
    title_en: str  # translated title, so the digest reads in English whatever the source
    link: str
    published: str
    category: Category
    summary: str
    citation: str  # verified excerpt of the source text, original language (guardrail §8: verbatim is not translatable)
    location: str  # verified country/place, metadata for the V2 map (§4); does not filter collection
    # Country inferred from the location above, English name. The only field that cannot be verified
    # verbatim (the country of a city is not in the text): empty as soon as location is, and validated
    # against the map's reference list at display time, where it is marked as inferred, not as quoted.
    location_country: str
    # Protagonist of the event, verified verbatim like location. Distinct from the place: an article
    # can name its actor without naming an attachable theatre ("Houthis attack eight Saudi oil
    # tankers" — the Red Sea and the Gulf of Aden belong to no country).
    actor: str
    # Country inferred from the actor above, English name. Same status as location_country — an
    # inference that cannot be verified verbatim, empty as soon as `actor` is, validated against the
    # map's reference list at display time — but one notch weaker: it attaches the item to the country
    # of whoever acts, not to the country where the facts take place. Marked as such on screen, never
    # merged into the inferred level.
    actor_country: str
    # True only if no location was extracted AND the model judges, from the content, that the event
    # takes place in the country of the source (the `country` field above). A presumed attachment,
    # weaker than location_country: distinguished as such on screen.
    domestic_to_source: bool
    # Filled in by the verifier in V2 (see docs/scoping.md §10); absent in V1.
    # `model_confidence` and not `confidence_score`: this is the model's self-assessment, not a
    # calibrated probability. Measured on 2026-08-20 over twenty items, it behaves like a function of
    # `corroborated` (0.65 for twelve of them) rather than like a judgement of its own — all the more
    # reason for the name not to promise what it does not deliver.
    model_confidence: float | None
    corroborated: bool | None
    # The verifier's escalation gate: did the history hold a candidate antecedent at verification
    # time (see VERIFIER_GATE_MIN_SCORE)? It separates two `model_confidence` nulls that nothing
    # distinguished until then: False = a measurement (nothing to cross-check in the window),
    # True = a silence (the run cap or the budget ran out before reaching it). Absent from records
    # written before 2026-08-20, where the per-category restriction played that role.
    has_antecedent_candidate: bool | None
    # Filled in by the thread node in V3 slice 1 (see docs/scoping.md §10); None as long as no other
    # item of the same story has been found — never filled in with a fabricated value.
    thread_id: str | None
    # The two fields that make a null thread_id readable, exactly as has_antecedent_candidate does
    # for a null model_confidence. Without them, `thread_id: None` carries three states that nothing
    # separates: "the history held no candidate story", which is a measurement; "the model looked and
    # brought nothing together", which is a stronger one still; and "the run cap or the budget cut in
    # before reaching it", which is an absence of measurement. Observed on the 2026-08-21 run:
    # 17 eligible items, 3 attached, and the other 14 indistinguishable on screen from items with no
    # story — so the display was saying something false.
    #
    # Threader escalation gate (THREAD_GATE_MIN_SCORE): did the history hold a candidate above the
    # threshold? Written on every item, escalated or not — the probe costs no call.
    has_thread_candidate: bool | None
    # Did the model reach a conclusion on this item? False covers both "never submitted" (gate not
    # cleared, run cap reached, budget already exhausted) and "submitted but interrupted by
    # BudgetExceeded before the conclusion": in either case nothing was judged. A boolean distinct
    # from the gate because, unlike the verifier, a threader escalation does not always produce a
    # result — the model can legitimately conclude that no candidate covers the same story.
    thread_checked: bool | None


class VigieState(TypedDict):
    raw_items: list[RawItem]
    analyzed_items: list[AnalyzedItem]
    # True if the daily LLM call cap (backend/guardrails.py) stopped the run before the end of the
    # batch. The run remains a partial success: the items already analysed are kept and served, and
    # this flag tells the caller that the batch was not processed in full — without it, a truncated
    # collection would be indistinguishable from a complete collection thin on novelty.
    truncated: bool
