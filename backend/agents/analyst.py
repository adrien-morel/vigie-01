"""Analyst node: classification plus a traceable summary (see docs/scoping.md §2 and §8)."""

import difflib
import html
import re
import unicodedata
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import get_args

from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel, Field, ValidationError

from backend import config
from backend.agents.fetcher import enrich_items
from backend.guardrails import BudgetExceeded, check_and_increment_llm_call
from backend.logging_setup import get_logger
from backend.memory.store import mark_analyzed_as_seen
from backend.state import AnalyzedItem, Category, RawItem, VigieState

log = get_logger("analyze")

MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """You are a defence/geopolitics intelligence analyst. For the article provided:
1. Classify it into one of the categories: export_control, arms_contract, military_movement,
   defense_diplomacy, industrial_program, or out_of_scope if the article falls into none of these
   categories (general technology news, cybersecurity, financial analysis, and so on).
   Filtering is thematic only — the geographic location of the article plays no part in this choice.
   These six identifiers are a closed vocabulary, written exactly as above: never translate them,
   never inflect them into the language of the article — even for an article in Spanish, German,
   Italian or French, answer `defense_diplomacy` and not `diplomacia_defensa` or any other variant.
   Boundary clarifications:
   - Merger, acquisition or equity stake in the defence industry: classify as industrial_program if
     the article is about the transaction itself (parties, amount, strategic stake); as
     export_control only if the article explicitly deals with a licence, sanction or embargo; as
     out_of_scope if the article centres on market analysis (share price, market reaction) rather
     than on the transaction.
   - Opinion pieces, op-eds or forward-looking analysis that do not report a dated, verifiable fact
     or event: classify as out_of_scope even if the theme matches the perimeter. An article that
     reports a dated fact and then adds analysis stays in; a mere statement of position does not.
   - defense_diplomacy vs military_movement: what separates them is not the form of the act reported
     but its content. An accomplished operational fact or an established state of affairs (a force
     is deployed, a strait is closed or under control, a strike has taken place, an airspace is
     closed) belongs to military_movement — including, and especially, when it is reported through a
     statement or an official communiqué: the statement is then merely the source that establishes
     the fact, it is not the subject of the article. Classify as defense_diplomacy only if what is
     declared is an intention, a threat, a claimed capability, a posture, a position of principle
     (what a state will do, might do, or deems unacceptable) or defence cooperation between states —
     as well as commentary on a deployment, as opposed to the deployment itself. A commander stating
     that a strait is closed and under his control reports an accomplished fact (military_movement);
     the same commander threatening to close it states an intention (defense_diplomacy). A joint
     military exercise or training already under way (troops deployed, manoeuvres in progress)
     belongs to military_movement even if the text describes it in the vocabulary of cooperation or
     interoperability (strengthening interoperability, deepening cooperation): that vocabulary
     characterises the nature of the exercise under way, it is not an announcement of cooperation
     distinct from the accomplished fact it accompanies. Only switch to defense_diplomacy if no
     concrete exercise is yet under way at the date of the article — an agreement, a partnership or
     an intention to cooperate in future, with no manoeuvre in progress.
   - defense_diplomacy vs out_of_scope: a statement or official communiqué attributed to a named
     official WHO IS IN POST (or officially mandated), on cooperation, alliances or defence/security
     posture between states, is a dated fact (not an op-ed) — do not classify it as out_of_scope on
     the sole ground that no contract or movement is described. Conversely, a state visit, a
     protocol message or general diplomatic pressure (human rights, the domestic politics of a third
     country) with no explicit defence/security content stays out_of_scope even if the two countries
     otherwise have a defence relationship. Remarks by a former official — a retired general officer,
     a former minister — commit no state: classify them as out_of_scope, a statement of position, not
     as defense_diplomacy, however prominent the voice.
   - export_control is defined by the legal instrument, not by the economic effect: licence,
     sanction, embargo. A customs duty, a tariff barrier or a general trade policy measure is not one
     of these, even when aimed at components with military uses — classify as out_of_scope, unless
     the measure takes the form of a licence, a sanction or an embargo.
   - Aerospace, space and civil technologies: they enter the perimeter only if the article explicitly
     ties them to a defence application, a defence customer, or industrial cooperation involving a
     defence group. Avionics developed with the subsidiary of a defence group belongs to
     industrial_program; a commercial satellite launch by a private company, with no stated defence
     link, stays out_of_scope. The criterion is the defence link written in the article, not the
     presumed dual-use nature of the technology.
   - industrial_program vs the other three categories: what defines industrial_program is the stage
     of building a capability — development, study or consultation ahead of a purchase, force
     structure target, industrial cooperation between programmes, overhaul or modernisation of
     existing equipment — whoever carries it (an armed service, a ministry, two states jointly).
     Classify from the subject of the article — a capability under construction — never from the
     visible actor: a request for information ahead of a purchase issued by a navy stays
     industrial_program, not military_movement, and industrial cooperation between two states stays
     industrial_program, not defense_diplomacy.
     Distinction with arms_contract, to be settled in this order. First: does the article report a
     commercial or budgetary act? award or notification of a contract, order placed, framework
     agreement concluded, a government's acquisition decision, or the money behind it — funds voted,
     requested from parliament or released, a supplementary appropriation, down payments made to
     secure delivery timelines. If so, the category is arms_contract, including when the article
     justifies that act by delivery timelines, a programme schedule or a capability to be built: the
     stated motive does not move the category, the act reported is what fixes it. Only if that first
     test fails: everything to do with manufacture and the life of the capability — development,
     construction, launch or roll-out, delivery, entry into service, qualification trials,
     modernisation, through-life support — belongs to industrial_program, including when the military
     customer is named and the article uses the vocabulary of ordering. A manufacturer delivering a
     first example to an armed service reports a programme milestone (industrial_program); the same
     manufacturer winning the contract reports a transaction (arms_contract). What precedes the
     transaction — request for information, consultation, preliminary study — stays
     industrial_program. Distinction with military_movement: the operational use of an already
     existing capability (deployment, exercise, strike) is not its construction. Distinction with
     defense_diplomacy: as soon as a named programme, piece of equipment or joint force is under
     construction, the category is industrial_program even if the article reports the announcement
     through an official statement — a multinational force under construction (a joint task force,
     say) belongs to industrial_program, not defense_diplomacy, as long as it is being built.
2. Translate the title into English (title_en), faithfully, even if the original title is already in
   English.
3. Write a factual summary in English, 2-3 sentences maximum, with no interpretation or speculation.
4. Provide a citation: a VERBATIM excerpt of the source text, in its original language (an exact
   copy-paste, never translated) that supports the summary. If no excerpt clearly supports the
   summary, categorise as out_of_scope and leave the citation empty.
5. Provide location: the THEATRE of the event — the country, sea or region where the facts take
   place — extracted VERBATIM from the title or the source text. This is not the country of the
   actor: "Iran plante Angriffe auf Militärziele in Europa" has "Europa" as its theatre, Iran being
   the actor (question 7). Prefer the country name when it is written as such.
   Leave empty if no place is explicitly named — never infer a place that is not written in black
   and white, and do not turn a demonym into a country name ("Ukrainian" does not license "Ukraine"
   if the word "Ukraine" appears nowhere).
   An INFLECTED form of the country name, on the other hand, is still the country name, and must be
   extracted as written: the German "Dänemarks Verteidigung" gives location = "Dänemarks", the
   Russian "Германии" gives "Германии". That is the country's own word, declined by grammar — not a
   demonym, which instead designates the inhabitants or the origin ("dänische", "Ukrainian").
6. Provide location_country: the sovereign country in which the place of location sits, in ENGLISH
   and in its common form ("Australia", "Ukraine", "United States of America").
   Unlike the previous fields this is NOT an excerpt of the text: it is the only inference allowed,
   and it serves only to place the item on a map by country. "Darwin" gives "Australia", "Kharkiv"
   gives "Ukraine". Leave empty in these four cases:
   - location is empty (nothing to attach);
   - the place belongs to no country: high seas, international strait, space, a transnational region
     ("Sahel", "Balkans"), an organisation or a military unit;
   - the place spans several countries with no single one dominant;
   - the sovereignty of the place is contested or would be disputed between states.
   An empty field is always preferable to an arbitrated attachment.
7. Provide actor: the main PROTAGONIST of the event — the state, government, armed force, armed
   group, manufacturer or political leader that acts — extracted VERBATIM from the title or the
   source text. "Houthis attack eight Saudi oil tankers" gives "Houthis"; "Iran plante Angriffe"
   gives "Iran". Unlike location, a demonym is accepted here if it designates the actor ("Iranian
   control" gives "Iranian"), since it is the actor that is being asked for, not a place. Leave empty
   if the article names no protagonist, or if the protagonist is the international organisation
   itself (UN, NATO, EU).
8. Provide actor_country: the sovereign country the actor attaches to, in ENGLISH and in its common
   form. Like location_country, this is an INFERENCE, not an excerpt: "Houthis" gives "Yemen",
   "Trump" gives "United States of America", "Iranian" gives "Iran", "Airbus Helicopters" gives
   "France". This field serves only to place on the map an item whose theatre cannot be attached.
   Leave empty in these three cases:
   - actor is empty;
   - the actor is multinational or has no country: NATO, UN, EU, African Union, a coalition;
   - the actor attaches to several countries with no single one dominant (consortium, joint venture).
   An empty field is always preferable to an arbitrated attachment.
9. Provide domestic: does the event reported take place in the country of the source, given at the
   top of the message? Answer from the content of the article, never from the origin of the outlet
   alone: covering abroad is the most frequent case, and an outlet reporting an event that occurred
   in a third country must give false even if the article is written from its own country.
   true corresponds to domestic news: an institution, administration, industry or armed forces of the
   source's country acting on its own territory. When in doubt, false.
   This field does not exempt you from filling in the previous four: answer all of them."""


class _Analysis(BaseModel):
    category: Category = Field(description="MECE perimeter category, or out_of_scope (thematic only)")
    title_en: str = Field(description="Title translated into English, faithful to the original title")
    summary: str = Field(description="Factual summary in English, 2-3 sentences maximum")
    citation: str = Field(description="Verbatim excerpt of the source text, original language, supporting the summary")
    location: str = Field(
        description="Verbatim excerpt naming the main country/place of the article; empty if not mentioned"
    )
    location_country: str = Field(
        description="Sovereign country of the location, common English name; empty if the place is in no country, "
        "is transnational, or is of contested sovereignty"
    )
    actor: str = Field(
        default="",
        description="Verbatim excerpt naming the main protagonist (state, force, armed group, manufacturer, "
        "official); empty if none is named or if the protagonist is an international organisation",
    )
    actor_country: str = Field(
        default="",
        description="Sovereign country of the actor, common English name; empty if the actor is multinational, "
        "has no country, or attaches to several countries with no single one dominant",
    )
    domestic: bool = Field(
        description="Does the event reported take place in the country of the source? false as soon as the article "
        "covers abroad, and when in doubt"
    )


def _clean_text(raw_html: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", raw_html)).strip()


# Typographic variants folded before the verbatim comparison. Measured on 2026-08-31 over the
# `quote_unverified` failures of a real Opex360/ESUT batch: **4 of the 6 failures are pure
# typography** — the model reproduces the content of the article faithfully but normalises its
# marks, rendering "d'adaptation" where the source writes "d’adaptation", and straight quotes where
# it uses guillemets. The other 2 are genuine paraphrases (longest common fragment: 7 and 12
# characters), which nothing here should rescue.
#
# This folding does not loosen the traceability guardrail (docs/scoping.md §8), it makes it
# applicable: a curly apostrophe and a straight apostrophe are the same sign, not the same byte. It
# is the same kind of normalisation as case and whitespace, folded here for a long time — and the
# check it leaves intact is the only one that matters, namely that the *words* of the citation are
# indeed the source's.
#
# A diagnosis not to lose again: the 2026-08-30 breakdown charged those 26 calls per run to the
# length of the RSS excerpts, and therefore to `fetch_full_article`. That was the wrong object — on
# full text, those same items still fail, and for this reason. Same pattern as the §4 incident: a
# disagreement about form read as a gap in substance.
_TYPOGRAPHY = str.maketrans(
    {
        "’": "'",  # curly apostrophe
        "‘": "'",
        "‛": "'",
        "′": "'",  # prime
        "“": '"',
        "”": '"',
        "„": '"',
        "«": '"',  # French guillemets
        "»": '"',
        "–": "-",  # en dash
        "—": "-",  # em dash
        "−": "-",  # minus sign
        "…": "...",
    }
)


def _normalize(text: str) -> str:
    # NFKC first: it folds non-breaking and thin spaces, ligatures and compatibility forms, which the
    # table below then does not have to enumerate.
    folded = unicodedata.normalize("NFKC", text).translate(_TYPOGRAPHY)
    return re.sub(r"\s+", " ", folded).strip().lower()


def _extract_verified(extract: str, source_text: str) -> bool:
    """Checks that an excerpt (citation or evidence zone) really is a verbatim of the source text."""
    return bool(extract.strip()) and _normalize(extract) in _normalize(source_text)


_llm = None

# English names for the country codes of backend/config.py, for the `domestic` question: "RU" reads
# badly, "Russia" does not. "INT" (multi-country / EU institutional source) has no country of origin
# and is handled separately — the question makes no sense for that case.
_SOURCE_COUNTRY_NAME: dict[str, str] = {
    "US": "the United States",
    "FR": "France",
    "RU": "Russia",
    "CN": "China",
    "DE": "Germany",
    "IT": "Italy",
    "GB": "the United Kingdom",
    "IL": "Israel",
    "ES": "Spain",
    "KR": "South Korea",
    "IR": "Iran",
    "KP": "North Korea",
}

_KNOWN_CATEGORIES: tuple[str, ...] = get_args(Category)


def _normalize_category(value: str) -> str:
    """Repairs a near-match on a category rather than accepting an unknown variant.

    Seen in real conditions on a Spanish-language source: the model answered `diplomacia_defense`,
    the Spanish inflection of the category identifier, despite the prompt's instruction (the
    identifiers are a closed vocabulary). A safety net, not a hard constraint: it only corrects when
    one candidate clearly dominates the other five categories, so that an item is never flipped from
    one genuine category to another by accident — calibrated on the six identifiers (no pair scores
    above 0.55 against each other), so the margin below cannot confuse two real categories, only
    rescue a language variant.
    """
    if value in _KNOWN_CATEGORIES:
        return value
    scored = sorted(
        ((difflib.SequenceMatcher(None, value, c).ratio(), c) for c in _KNOWN_CATEGORIES),
        reverse=True,
    )
    best_score, best = scored[0]
    runner_up_score = scored[1][0]
    if best_score >= 0.7 and best_score - runner_up_score >= 0.2:
        return best
    return value


def classify_item(item: RawItem) -> _Analysis:
    """Calls the LLM for one item, with no filtering. Reused by analyze() and by the eval scripts
    (backend/eval/)."""
    global _llm
    if _llm is None:
        _llm = ChatAnthropic(model=MODEL, temperature=0).with_structured_output(_Analysis, include_raw=True)

    clean_text = _clean_text(item["raw_text"])
    # The country of the source is given only for question 9 (`domestic`). It is placed at the top and
    # named as such so as not to contaminate the extraction of location, which must remain a verbatim
    # of the text: a Russian source covering Ukraine must not start producing "Russia".
    origin = _SOURCE_COUNTRY_NAME.get(item["country"], "an international or multi-country outlet")
    check_and_increment_llm_call("analyze")
    result = _llm.invoke(
        [
            ("system", SYSTEM_PROMPT),
            (
                "human",
                f"Country of the source (metadata, not part of the article, to be used only for "
                f"question 9): {origin}\n\nTitle: {item['title']}\n\nText: {clean_text}",
            ),
        ]
    )
    if result["parsed"] is not None:
        return result["parsed"]

    # Validation failure: before giving up (as it did before this fix), we try to repair the category
    # from the raw arguments of the tool call — the only class of validation failure met in real
    # conditions so far, see `_normalize_category`. A genuinely malformed item (missing required
    # field) fails exactly as before: `_Analysis(**args)` then raises the same ValidationError,
    # propagated to the caller with no special handling.
    tool_calls = getattr(result["raw"], "tool_calls", None) or []
    if tool_calls and isinstance(tool_calls[0].get("args"), dict):
        args = tool_calls[0]["args"]
        if isinstance(args.get("category"), str):
            args = {**args, "category": _normalize_category(args["category"])}
        return _Analysis(**args)

    raise result["parsing_error"] or ValueError("structured response with no usable tool_call")


# Outcome recorded for each item submitted to the model, by source. Same status as `calls_by_node` in
# backend/guardrails.py, and for the same reason: an operational measurement, in memory, outside the
# persistence layer, reset by run_pipeline().
#
# Rationale (docs/scoping.md §11): `analyze` pays one call per item submitted, before knowing whether
# the item will be kept — an item classified out_of_scope cost exactly the same call as an item that
# reaches the digest. Measured on the 2026-08-22 run: 72 calls for 31 items kept, that is 41 calls
# (21% of the day's budget) spent on discarded items. It is the single largest line of the daily
# budget, and it was invisible: discarded items are recorded nowhere — neither in the analysed
# history, which holds only the kept ones, nor in the campaign log, which counts only the items
# submitted per feed before capping. Without this breakdown, one cannot say whether those 41 calls
# come from a few generalist feeds or from the whole panel, and therefore cannot decide whether the
# spend is reducible at collection time or is the price of the sorting itself.
#
# The key is (source, outcome) and not the source alone: "how much was lost" without "why" does not
# distinguish an off-topic feed from a feed whose excerpts are too short to carry a verifiable
# citation — two problems with different remedies.
_submissions: Counter[tuple[str, str]] = Counter()


def submissions_by_source() -> dict[str, dict[str, int]]:
    """Outcome of the items submitted to the model during the current run, by source then by outcome."""
    by_source: dict[str, dict[str, int]] = {}
    for (source, outcome), count in _submissions.items():
        by_source.setdefault(source, {})[outcome] = count
    return {source: dict(sorted(outcomes.items())) for source, outcomes in sorted(by_source.items())}


def reset_submission_tally() -> None:
    """Call at the start of a run, like reset_call_tally()."""
    _submissions.clear()


@dataclass
class _Progress:
    """What the node actually submitted to the model, and whether it stopped before the end of the batch.

    Mutable and shared with the generator rather than returned at the end of the iteration: the caller
    must be able to read both pieces of information even if the iteration is interrupted part-way.
    """

    # The items whose fate is settled — kept or discarded. Written into the deduplication memory when
    # the node exits, including if the node fails part-way: what has been paid for must not be paid
    # for again, what has not been processed must stay collectable.
    submitted: list[RawItem] = field(default_factory=list)
    truncated: bool = False


def analyze(state: VigieState) -> VigieState:
    """LangGraph node: classifies and summarises every raw_item, rejects untraceable summaries."""
    analyzed_items: list[AnalyzedItem] = []
    progress = _Progress()

    # Full-text fetching before the first submission — free in LLM calls, and placed here rather than
    # in `collect` because by this point the batch has already been through the per-source cap and
    # deduplication: we only fetch articles that will actually be submitted.
    #
    # Wrapped: this module makes outbound requests to seventeen sites, and it must under no
    # circumstances be able to bring the analysis down. A global failure lets it degrade to the
    # behaviour from before it existed — the batch goes to the model on its teasers alone, as it did
    # the day before.
    # Read off the module rather than imported by value: the switch must stay hot-swappable (tests,
    # an operational run that wants to do without it) without re-importing the analyst.
    if config.FETCH_FULL_ARTICLE:
        try:
            enrich_items(state["raw_items"])
        except Exception:  # noqa: BLE001 — deliberate degradation, see above
            log.exception("full-text fetching abandoned, analysing teasers only")

    try:
        analyzed_items.extend(_analyze_items(state["raw_items"], progress))
    finally:
        mark_analyzed_as_seen(progress.submitted)

    # The breakdown goes into the node's log and not only into the end-of-run summary: it is the
    # heaviest spending line of the daily budget (41 of the 72 calls on 2026-08-22 went on discarded
    # items) and it must stay readable even if the run stops after this node.
    by_source = submissions_by_source()
    by_outcome: Counter[str] = Counter()
    for outcomes in by_source.values():
        by_outcome.update(outcomes)
    if progress.truncated:
        log.warning("analysis truncated by the daily cap", extra={"submitted": len(progress.submitted)})
    log.info(
        "analysis finished",
        extra={
            "received": len(state["raw_items"]),
            "submitted": len(progress.submitted),
            "kept": len(analyzed_items),
            "by_outcome": dict(sorted(by_outcome.items())),
            "by_source": by_source,
            "truncated": progress.truncated,
        },
    )
    return {"analyzed_items": analyzed_items, "truncated": progress.truncated}


def _analyze_items(raw_items: list[RawItem], progress: _Progress) -> Iterator[AnalyzedItem]:
    """Generator: `progress` fills up as it is consumed, so that the caller knows exactly what was
    submitted to the model even if the iteration is interrupted."""
    for item in raw_items:
        progress.submitted.append(item)
        try:
            result = classify_item(item)
        except BudgetExceeded:
            # The daily cap truncates the batch, it does not destroy work already paid for: we stop
            # iterating and hand back the items already analysed, which the caller will record
            # normally.
            #
            # This item, on the other hand, cost nothing: the cap is checked *before* the call
            # (backend/guardrails.py), which therefore never happened. Removing it from the submitted
            # list is what keeps it collectable tomorrow — leaving it there would mark it "seen"
            # without it ever having been analysed, exactly the loss `mark_analyzed_as_seen` was moved
            # here to avoid.
            progress.submitted.pop()
            progress.truncated = True
            # No outcome recorded either: the item was not submitted, it goes back to collection.
            return
        except (ValidationError, ValueError):
            # The model can return a category outside the enumeration — seen in real conditions on a
            # Spanish-language source ("diplomacia_defense" instead of the expected identifier).
            # `classify_item` already tries to repair that precise case (`_normalize_category`); this
            # `except` covers what is left after that repair — an unrecognised variant, a missing
            # required field, or the total absence of a tool_call that `classify_item` surfaces as a
            # `ValueError` for want of a parsing exception to propagate. A malformed item is handled
            # like an unclassifiable item: we discard it, as we do a summary with no verifiable
            # citation. Letting it propagate would lose the whole run, including the items already
            # analysed before it — a cost out of all proportion to that of one failed item.
            # The LLM call did take place: the budget (§8) is charged, here as everywhere else.
            _submissions[(item["source"], "invalid_response")] += 1
            log.warning(
                "unusable model response, item discarded",
                extra={"source": item["source"], "link": item["link"]},
            )
            continue
        clean_text = _clean_text(item["raw_text"])

        if result.category == "out_of_scope":
            _submissions[(item["source"], "out_of_scope")] += 1
            continue
        if not _extract_verified(result.citation, clean_text):
            # Traceability guardrail (docs/scoping.md §8): no verifiable citation, no summary.
            _submissions[(item["source"], "quote_unverified")] += 1
            continue

        # location is metadata for the map (docs/scoping.md §4): it does not filter collection (no
        # geographic restriction in V1), but it is subject to the same traceability guardrail as the
        # citation — no invented place, empty rather than unverifiable.
        #
        # The title is part of the verifiable text, unlike the citation which must support the summary
        # and therefore comes from the body. Measured on a real run: checking against the body alone
        # erased correct extractions, 10 of the 11 empty places having their country named in the
        # title and nowhere else (RSS excerpts are often truncated, see §11).
        location = result.location if _extract_verified(result.location, f"{item['title']} {clean_text}") else ""

        # location_country is the only LLM output exempt from the verbatim guardrail, because it is by
        # construction absent from the text: "Darwin" does not contain "Australia". Two counterweights
        # bound it. Here: no verified place, no country — otherwise a place rejected on the verbatim
        # check would come back through the back door and place the item on the map.
        # At display time: the front keeps that country only if it exists in the map's reference list,
        # and marks it as inferred (frontend/src/lib/geo.ts).
        location_country = result.location_country.strip() if location else ""

        # The actor follows exactly the same discipline as the place, one notch lower on the map.
        # Measured on the 2026-08-20 history: five unattached items did name their protagonist in the
        # title ("Houthis", "Iran", "Trump"). The theatre was either absent or unattachable (Red Sea,
        # Gulf of Aden, Strait of Hormuz) — refusing to place the item there is correct for a *place*,
        # but it was losing information the source names in black and white.
        #
        # The verbatim guardrail therefore applies to `actor` as it does to `location`: a protagonist
        # not found in the text is an invented protagonist, and is discarded rather than flagged. The
        # title enters the verifiable text for the same reason as above — that is where the
        # protagonist is named most often, RSS excerpts being truncated.
        actor = result.actor if _extract_verified(result.actor, f"{item['title']} {clean_text}") else ""

        # And `actor_country` is to `actor` what `location_country` is to `location`: the inference is
        # allowed only if the excerpt that carries it has been verified, otherwise an actor rejected on
        # the verbatim check would come back and place the item on the map through the back door.
        actor_country = result.actor_country.strip() if actor else ""

        # Last-resort fallback for items with no named place at all: the model judged, from the content
        # of the article, that the event takes place in the country of the source. Three bounds.
        #
        # It applies only when `location` is empty: if a place was extracted but is attachable to no
        # country ("Black Sea"), that is an answer, not a gap — replacing it with the outlet's country
        # would be a regression, not a fallback.
        #
        # It is refused to "INT" sources, which have no country of origin.
        #
        # And it stays weaker than `location_country`, which infers from a named place: here nothing is
        # named, only the content is judged. The display therefore marks it as "presumed" and not as
        # "inferred" (frontend/src/lib/geo.ts). The country of the source is never enough on its own:
        # without that judgement, a state outlet covering abroad would inflate its own country's
        # footprint, and the perimeter deliberately over-samples those (see §4).
        domestic_to_source = bool(result.domestic) and not location and item["country"] != "INT"

        # Recorded before the `yield` and not after: a consumer that stops iterating (the node stops on
        # BudgetExceeded) would never hand control back here, and the item would be counted as lost
        # when it was in fact produced.
        _submissions[(item["source"], "kept")] += 1

        yield AnalyzedItem(
            source=item["source"],
            lang=item["lang"],
            country=item["country"],
            state_affiliated=item["state_affiliated"],
            title=item["title"],
            title_en=result.title_en,
            link=item["link"],
            published=item["published"],
            category=result.category,
            summary=result.summary,
            citation=result.citation,
            location=location,
            location_country=location_country,
            actor=actor,
            actor_country=actor_country,
            domestic_to_source=domestic_to_source,
            model_confidence=None,
            corroborated=None,
            thread_id=None,
        )
