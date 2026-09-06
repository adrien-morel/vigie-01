"""Full-text retrieval for an article (docs/scoping.md §10, tier 1 tool).

Rationale — **and an attribution corrected by measuring it.** The 2026-08-30 breakdown charged this
module with 26 calls lost per run to `quote_unverified` (18% of the budget), on the assumption that
the RSS excerpt was too short to carry a verifiable citation. Measured on 2026-08-31 over a real
Opex360/ESUT batch, in paired arms: **that was the wrong object.** Of the 6 failures observed, 4 were
pure typography — curly against straight apostrophes — and are settled in `analyst._normalize`,
without a single HTTP request; the other 2 are genuine paraphrases, which nothing here can rescue.
That typographic folding alone took the batch's retention from 2/10 to 5/10, when enrichment adds only
one net item.

**The justification that holds is therefore classification, not the citation.** Points 38/39
(docs/scoping.md §7) showed two ESUT items **misclassified** because of a truncated teaser — a prompt
fix cannot compensate for an excerpt that does not contain the information to be classified. That is
the class of gain, and the only one, that the 2026-08-31 validation reproduced: the two favourable
flips in the batch are two `out_of_scope` items that became kept items once the whole article was
read. Over 10 paired items the balance is +2 gains, −1 regression: a signal pointing the expected way,
**but not a conclusive measurement** at that sample size — hence the `FETCH_FULL_ARTICLE` switch, and
not hard-wired behaviour.

This module consumes no LLM call: fetching an article is free, only submitting it to the model costs,
and that happens anyway.

Central invariant — **we add, we do not replace.** The full text is concatenated to the teaser rather
than substituted for it. Three consequences, all intended:

- The verifiable corpus only grows, so **a given citation that verifies today keeps verifying** after
  enrichment. A traceability guardrail that can be broken retroactively would be a bad trade.

  **What this invariant does not say**, and what was observed for real on 2026-08-31: it applies to a
  string of characters, not to the fate of the item. Faced with a longer text, the model **picks a
  different citation** — 1 item out of the 10 in the validation batch went from `kept` to
  `quote_unverified` even though its original citation still verified. The module therefore cannot
  promise the absence of regression at item level, and must not be presented as doing so.
- A failed fetch degrades an item, it does not lose it: we fall back exactly on the behaviour from
  before this module. Same rule as for an unreachable feed (fix of 2026-08-30) — the failure is local,
  named and logged, it does not bring down what surrounds it.
- An extraction that brings back the site's chrome (cookie banner, legal notices) adds noise but
  removes no information.
"""

import html
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests
import trafilatura

from backend.config import (
    FETCH_MAX_CHARS,
    FETCH_MAX_WORKERS,
    FETCH_SKIP_SOURCES,
    FETCH_TIMEOUT_S,
)
from backend.logging_setup import get_logger
from backend.state import RawItem

log = get_logger("fetch")

# Browser header. Measured on 2026-08-31 across the 18 sources: three feeds refuse a bare GET and
# answer 200 with this header — Breaking Defense (403), TASS (403), NK News (520). This is not a
# circumvention trick but the consequence of a missing `User-Agent`: the default `requests` client is
# filtered by CDNs. The articles remain public and are read exactly as published.
#
# The survey also corrects the scoping note that claimed "2 blocked sources, Defense.gov and Federal
# Register": Federal Register answers 200 with no particular header (its problem lies elsewhere, see
# `_anchor_overlap`), and three blocked sources had gone unnoticed.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
}

# Minimum teaser length, in tokens of at least 4 characters, for it to serve as an anchor. Below that,
# we cannot check that the extraction really brought back *this* article — so we abstain.
_MIN_ANCHOR_TOKENS = 5


class ArticleUnavailable(Exception):
    """The article could not be fetched or extracted. To be treated as a local degradation: the item
    stays analysable on its teaser, as before this module existed."""


def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"\w+", text.lower()) if len(w) >= 4]


def _anchor_overlap(teaser: str, text: str) -> float | None:
    """Share of the teaser's tokens found in the extracted text, or `None` if the teaser is too short
    to anchor anything.

    It measures what no HTTP status check tells you: did the extraction bring back *this* article, or
    the site's chrome? Two real cases in the 2026-08-31 survey of 49 articles — Federal Register
    returns 3,669 characters of legal notices ("This site displays a prototype of a Web 2.0 version of
    the daily Federal Register…") and CGTN returns a cookie banner followed by the navigation menu.
    Both have a teaser too short to anchor (0 and 37 characters), so **the anchorability rule alone
    rules them out** and no threshold is needed to catch them.

    That is why this score is **measured and logged, but decides nothing**. The only two negatives in
    the survey being caught by another rule, no positive/negative separation is left on which to
    calibrate a threshold: setting one by judgement would be arbitrariness dressed up as measurement,
    exactly what THREAD_GATE_MIN_SCORE avoided by staying a free filter until its annotated sample was
    available. Instrument first, cap later — the same order as for `has_antecedent_candidate`.

    Orders of magnitude from the survey, for a future calibration: 42 of the 44 anchorable items are at
    >= 0.67 and half at 1.00; the two lowest (0.20 and 0.42) are not chrome but short extractions,
    where the teaser carries a sentence the body of the article does not repeat.
    """
    anchor = _tokens(teaser)
    if len(anchor) < _MIN_ANCHOR_TOKENS:
        return None
    body = set(_tokens(text))
    return sum(1 for w in anchor if w in body) / len(anchor)


def fetch_full_article(url: str, timeout: float | None = None) -> str:
    """Text of the article at `url`, extracted from the HTML. Raises `ArticleUnavailable` on any
    failure.

    `trafilatura` rather than a regex extraction: it is built to strip boilerplate, where cutting on
    tags produces exactly the false negatives found by the anchor probe of 2026-08-22 (typography and
    inline insertions breaking the string being searched for).
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout or FETCH_TIMEOUT_S, allow_redirects=True)
    except requests.RequestException as exc:
        raise ArticleUnavailable(f"network: {type(exc).__name__}") from exc
    if response.status_code != 200:
        raise ArticleUnavailable(f"HTTP {response.status_code}")
    text = trafilatura.extract(response.text, include_comments=False, include_tables=False)
    if not text or not text.strip():
        raise ArticleUnavailable("empty extraction")
    return text.strip()


@dataclass
class FetchTally:
    """Outcome of each fetch attempt. Same status as `analyst.submissions_by_source()`: an
    operational measurement, in memory, outside persistence, reset on every run."""

    enriched: int = 0
    skipped_source: int = 0
    not_anchorable: int = 0
    no_gain: int = 0
    failed: int = 0
    chars_added: int = 0
    overlaps: list[float] = field(default_factory=list)

    def as_dict(self) -> dict[str, float | int]:
        summary: dict[str, float | int] = {
            "enriched": self.enriched,
            "skipped_source": self.skipped_source,
            "teaser_not_anchorable": self.not_anchorable,
            "no_gain": self.no_gain,
            "failures": self.failed,
            "chars_added": self.chars_added,
        }
        if self.overlaps:
            ordered = sorted(self.overlaps)
            summary["anchor_median"] = round(ordered[len(ordered) // 2], 3)
            summary["anchor_min"] = round(ordered[0], 3)
        return summary


def _enrich_one(item: RawItem) -> tuple[RawItem, str, float | None, str]:
    """Returns (item, text to add, anchor score, outcome). Empty text = item unchanged."""
    # A documented per-source waiver rather than a discovery in production. Measured on 2026-08-31:
    # Defense.gov answers 403 with or without a browser header (and now redirects to war.gov). Its
    # items are still collected and analysed on their teaser.
    if item["source"] in FETCH_SKIP_SOURCES:
        return item, "", None, "skipped_source"

    teaser = html.unescape(re.sub(r"<[^>]+>", " ", item["raw_text"])).strip()
    try:
        text = fetch_full_article(item["link"])
    except ArticleUnavailable as exc:
        log.warning(
            "article not fetched, falling back on the teaser",
            extra={"source": item["source"], "link": item["link"], "reason": str(exc)},
        )
        return item, "", None, "failure"

    overlap = _anchor_overlap(teaser, text)
    if overlap is None:
        # Teaser too short to check that the extraction really covers this article. That is the case
        # for Federal Register (empty teaser) and part of CGTN — precisely the two sources whose
        # extraction brings back the site's chrome. We abstain rather than add noise.
        return item, "", None, "teaser_not_anchorable"
    if len(text) <= len(teaser):
        # Nothing to gain: the extraction brings no more than what the model already has.
        return item, "", overlap, "no_gain"
    return item, text[:FETCH_MAX_CHARS], overlap, "enriched"


def enrich_items(items: list[RawItem]) -> FetchTally:
    """Completes each item's `raw_text` with the full text of the article, in place.

    Called from `analyze` and not from `collect`: at that point in the graph, the batch has already
    been through the per-source cap **and** deduplication, so we only fetch articles that will
    actually be submitted to the model.

    Concurrent out of necessity, not elegance: the 2026-08-30 run lasted 880 s against a 900 s target
    (docs/scoping.md §11), so a sequential fetch of ~110 articles at ~2.2 s of per-request latency
    would push the run out of its target on its own. Measured at 8 threads: 13.6 s for 49 articles.
    """
    tally = FetchTally()
    if not items:
        return tally

    with ThreadPoolExecutor(max_workers=FETCH_MAX_WORKERS) as pool:
        results = list(pool.map(_enrich_one, items))

    for item, text, overlap, outcome in results:
        if overlap is not None:
            tally.overlaps.append(overlap)
        if outcome == "enriched":
            # Escaped before concatenation: `raw_text` is feed HTML, and the analyst puts it back
            # through `_clean_text` (tag removal then `html.unescape`). Escaping here guarantees that
            # the added text goes through that cleaning identically — without it, an ampersand or an
            # angle bracket from the body of the article would come out transformed, and a verbatim
            # citation covering it would fail to verify.
            item["raw_text"] = f"{item['raw_text']}\n\n{html.escape(text)}"
            tally.enriched += 1
            tally.chars_added += len(text)
        elif outcome == "skipped_source":
            tally.skipped_source += 1
        elif outcome == "teaser_not_anchorable":
            tally.not_anchorable += 1
        elif outcome == "no_gain":
            tally.no_gain += 1
        else:
            tally.failed += 1

    log.info("full-text fetching finished", extra={"submitted": len(items), **tally.as_dict()})
    return tally
