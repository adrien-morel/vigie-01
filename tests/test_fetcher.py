"""Tests for the full-text fetching node (backend/agents/fetcher.py).

The HTTP transport is substituted throughout: the suite must reach no real site, just as the LLM and
the RSS feeds are mocked in it. Validation against real data is done separately, by probe (see
docs/scoping.md §11).
"""

import pytest

from backend import config
from backend.agents import analyst, fetcher


def _raw_item(raw_text: str, source: str = "s", link: str = "https://example.test/a") -> dict:
    return {
        "source": source,
        "theme": "contracts",
        "lang": "en",
        "country": "US",
        "state_affiliated": False,
        "title": "title",
        "link": link,
        "published": "",
        "raw_text": raw_text,
    }


class _FakeResponse:
    def __init__(self, text: str = "", status_code: int = 200):
        self.text = text
        self.status_code = status_code


def _page(body: str) -> str:
    """Minimal HTML that trafilatura knows how to reduce to the body of the article."""
    return f"<html><body><article><p>{body}</p></article></body></html>"


# --- anchoring ------------------------------------------------------------------------------------


def test_anchor_overlap_none_when_teaser_too_short_to_anchor():
    # Real case: the Federal Register teaser is empty, a CGTN item's is 37 characters long. With no
    # anchor, we cannot check that the extraction really covers this article.
    assert fetcher._anchor_overlap("", "some arbitrary text from the page") is None
    assert fetcher._anchor_overlap("Xi visit", "some arbitrary text from the page") is None


def test_anchor_overlap_full_when_extract_contains_teaser():
    teaser = "The minister announces an order for additional armoured vehicles"
    assert fetcher._anchor_overlap(teaser, f"{teaser} for the land forces.") == 1.0


def test_anchor_overlap_low_when_extract_is_site_chrome():
    # The Federal Register/CGTN case if it had a teaser: legal notices instead of the article.
    teaser = "The minister announces an order for additional armoured vehicles"
    chrome = "This site displays a prototype of a Web 2.0 version of the daily Federal Register."
    assert fetcher._anchor_overlap(teaser, chrome) == 0.0


# --- single fetch ---------------------------------------------------------------------------------


def test_fetch_full_article_returns_extracted_body(monkeypatch):
    monkeypatch.setattr(
        fetcher.requests,
        "get",
        lambda *a, **k: _FakeResponse(_page("An article body long enough to be extracted.")),
    )
    assert "article body" in fetcher.fetch_full_article("https://example.test/a")


def test_fetch_full_article_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(fetcher.requests, "get", lambda *a, **k: _FakeResponse("", status_code=403))
    with pytest.raises(fetcher.ArticleUnavailable, match="403"):
        fetcher.fetch_full_article("https://example.test/a")


def test_fetch_full_article_raises_on_network_error(monkeypatch):
    def boom(*a, **k):
        raise fetcher.requests.ConnectionError("dropped")

    monkeypatch.setattr(fetcher.requests, "get", boom)
    with pytest.raises(fetcher.ArticleUnavailable):
        fetcher.fetch_full_article("https://example.test/a")


def test_fetch_full_article_raises_when_extraction_is_empty(monkeypatch):
    monkeypatch.setattr(fetcher.requests, "get", lambda *a, **k: _FakeResponse("<html><body></body></html>"))
    with pytest.raises(fetcher.ArticleUnavailable, match="empty"):
        fetcher.fetch_full_article("https://example.test/a")


# --- batch enrichment -----------------------------------------------------------------------------


def test_enrich_items_appends_without_replacing_the_teaser(monkeypatch):
    """The central invariant of the module: we add, we do not replace."""
    teaser = "The minister announces an order for additional armoured vehicles deliverable in 2027"
    monkeypatch.setattr(
        fetcher.requests,
        "get",
        lambda *a, **k: _FakeResponse(_page(f"{teaser}. The contract covers thirty vehicles and associated support.")),
    )
    item = _raw_item(teaser)
    tally = fetcher.enrich_items([item])

    assert tally.enriched == 1
    assert teaser in item["raw_text"], "the original teaser must survive enrichment"
    assert "thirty vehicles" in analyst._clean_text(item["raw_text"])


def test_citation_verifiable_before_enrichment_stays_verifiable_after(monkeypatch):
    """A consequence of the invariant, and the reason it is set: the verifiable corpus only grows, so
    the traceability guardrail (§8) cannot regress."""
    teaser = "The minister announces an order for additional armoured vehicles deliverable in 2027"
    citation = "an order for additional armoured vehicles"
    item = _raw_item(teaser)
    assert analyst._extract_verified(citation, analyst._clean_text(item["raw_text"]))

    monkeypatch.setattr(
        fetcher.requests, "get", lambda *a, **k: _FakeResponse(_page("A completely different, longer, unrelated text."))
    )
    fetcher.enrich_items([item])
    assert analyst._extract_verified(citation, analyst._clean_text(item["raw_text"]))


def test_enriched_text_survives_clean_text_round_trip(monkeypatch):
    """The added text is escaped before concatenation, because the analyst puts `raw_text` back
    through `_clean_text` (tag removal then `html.unescape`). Without the escaping, an ampersand or an
    angle bracket from the body of the article would come out transformed and would break a verbatim
    citation."""
    teaser = "The minister announces an order for additional armoured vehicles deliverable in 2027"
    body = "Agreement signed between Thales & Naval Group, margin < 5 % according to the source."
    monkeypatch.setattr(fetcher.requests, "get", lambda *a, **k: _FakeResponse(_page(f"{teaser}. {body}")))

    item = _raw_item(teaser)
    fetcher.enrich_items([item])
    assert body in analyst._clean_text(item["raw_text"])


def test_enrich_items_skips_configured_sources(monkeypatch):
    """Defense.gov answers 403 with or without a browser header: a documented waiver, not a discovery
    in production. No request must go out for those sources."""

    def fail(*a, **k):
        raise AssertionError("no request must go out for an excluded source")

    monkeypatch.setattr(fetcher.requests, "get", fail)
    source = next(iter(config.FETCH_SKIP_SOURCES))
    item = _raw_item("A teaser of a perfectly reasonable length to anchor on", source=source)
    before = item["raw_text"]

    tally = fetcher.enrich_items([item])
    assert tally.skipped_source == 1
    assert item["raw_text"] == before


def test_enrich_items_abstains_when_teaser_is_not_anchorable(monkeypatch):
    """The Federal Register case: the page fetches (200), but the extraction brings back the site's
    legal notices and the teaser is too short to detect it. We abstain."""
    monkeypatch.setattr(
        fetcher.requests,
        "get",
        lambda *a, **k: _FakeResponse(_page("This site displays a prototype of the daily Federal Register edition.")),
    )
    item = _raw_item("")
    before = item["raw_text"]

    tally = fetcher.enrich_items([item])
    assert tally.not_anchorable == 1
    assert item["raw_text"] == before


def test_enrich_items_leaves_item_untouched_on_failure(monkeypatch):
    """An unreachable article degrades the item, it does not lose it — the same rule as an unreachable
    feed."""
    monkeypatch.setattr(fetcher.requests, "get", lambda *a, **k: _FakeResponse("", status_code=500))
    item = _raw_item("A teaser of a perfectly reasonable length to anchor on")
    before = item["raw_text"]

    tally = fetcher.enrich_items([item])
    assert tally.failed == 1
    assert item["raw_text"] == before


def test_one_failure_does_not_stop_the_batch(monkeypatch):
    """The same invariant as the 2026-08-30 fix on the feeds: the failure is local to the article."""
    teaser = "The minister announces an order for additional armoured vehicles deliverable in 2027"

    def get(url, *a, **k):
        if "broken" in url:
            raise fetcher.requests.ConnectionError("dropped")
        return _FakeResponse(_page(f"{teaser}. Some article continuation far longer than the teaser."))

    monkeypatch.setattr(fetcher.requests, "get", get)
    broken = _raw_item(teaser, link="https://example.test/broken")
    fine = _raw_item(teaser, link="https://example.test/ok")

    tally = fetcher.enrich_items([broken, fine])
    assert (tally.failed, tally.enriched) == (1, 1)


def test_enrich_items_caps_appended_length(monkeypatch):
    """An article from the tail (35,445 characters in the survey, twelve times the median) must not go
    to the model in full."""
    teaser = "The minister announces an order for additional armoured vehicles deliverable in 2027"
    monkeypatch.setattr(fetcher.requests, "get", lambda *a, **k: _FakeResponse(_page(f"{teaser}. " + "word " * 20000)))
    monkeypatch.setattr(fetcher, "FETCH_MAX_CHARS", 500)

    item = _raw_item(teaser)
    tally = fetcher.enrich_items([item])
    assert tally.enriched == 1
    assert tally.chars_added == 500


def test_enrich_items_abstains_when_extract_adds_nothing(monkeypatch):
    """An extraction shorter than the teaser: nothing to gain, we do not replace."""
    teaser = "The minister announces an order for additional armoured vehicles deliverable in 2027 " * 3
    monkeypatch.setattr(fetcher.requests, "get", lambda *a, **k: _FakeResponse(_page(f"{teaser[:80]}")))

    item = _raw_item(teaser)
    before = item["raw_text"]
    tally = fetcher.enrich_items([item])
    assert tally.no_gain == 1
    assert item["raw_text"] == before


def test_tally_reports_anchor_distribution_without_gating_on_it(monkeypatch):
    """The anchor score is measured and logged, but decides nothing: no positive/negative separation
    allows a threshold to be calibrated yet (see `_anchor_overlap`)."""
    teaser = "The minister announces an order for additional armoured vehicles deliverable in 2027"
    monkeypatch.setattr(
        fetcher.requests,
        "get",
        lambda *a, **k: _FakeResponse(
            _page(
                "Text entirely disjoint from the teaser, deliberately longer than it so as to "
                "isolate the effect of anchoring from that of the gain in length."
            )
        ),
    )
    item = _raw_item(teaser)
    tally = fetcher.enrich_items([item])

    assert tally.enriched == 1, "a weak anchor does not discard the item — it is only measured"
    assert tally.overlaps == [0.0]
    assert "anchor_median" in tally.as_dict()


# --- integration with the analyze node --------------------------------------------------------------


def test_analyze_degrades_to_teasers_when_fetching_blows_up(monkeypatch):
    """Fetching must under no circumstances bring the analysis down: a global failure returns it to
    the behaviour from before this module."""
    monkeypatch.setattr(config, "FETCH_FULL_ARTICLE", True)

    def boom(_items):
        raise RuntimeError("pool failed")

    monkeypatch.setattr(analyst, "enrich_items", boom)
    monkeypatch.setattr(analyst, "classify_item", lambda item: (_ for _ in ()).throw(ValueError("unclassifiable")))

    result = analyst.analyze({"raw_items": [_raw_item("some text")], "analyzed_items": []})
    assert result["analyzed_items"] == []


def test_analyze_skips_fetching_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "FETCH_FULL_ARTICLE", False)
    monkeypatch.setattr(
        analyst, "enrich_items", lambda _items: (_ for _ in ()).throw(AssertionError("must not be called"))
    )
    monkeypatch.setattr(analyst, "classify_item", lambda item: (_ for _ in ()).throw(ValueError("unclassifiable")))

    analyst.analyze({"raw_items": [_raw_item("some text")], "analyzed_items": []})
