from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import backend.agents.collector as collector
from backend.config import Source


def _published(hours_ago: float) -> str:
    return format_datetime(datetime.now(UTC) - timedelta(hours=hours_ago))


def test_collect_caps_items_per_source_keeping_the_most_recent(monkeypatch):
    monkeypatch.setattr(
        collector, "SOURCES", [Source("Test Source", "http://example.com/rss", "fr", "contracts", "FR")]
    )
    monkeypatch.setattr(collector, "MAX_ITEMS_PER_SOURCE_PER_RUN", 2)

    class _FakeFeed:
        entries = [
            {"title": "Oldest", "link": "http://example.com/1", "published": _published(3)},
            {"title": "Newest", "link": "http://example.com/2", "published": _published(1)},
            {"title": "Middle", "link": "http://example.com/3", "published": _published(2)},
        ]

    monkeypatch.setattr(collector.feedparser, "parse", lambda url: _FakeFeed())

    result = collector.collect({"raw_items": [], "analyzed_items": []})

    assert [item["title"] for item in result["raw_items"]] == ["Newest", "Middle"]


def test_collect_respects_a_source_specific_cap_override(monkeypatch):
    monkeypatch.setattr(
        collector,
        "SOURCES",
        [Source("Test Source", "http://example.com/rss", "fr", "contracts", "FR", max_per_run=1)],
    )
    monkeypatch.setattr(collector, "MAX_ITEMS_PER_SOURCE_PER_RUN", 12)

    class _FakeFeed:
        entries = [
            {"title": "One", "link": "http://example.com/1", "published": _published(2)},
            {"title": "Two", "link": "http://example.com/2", "published": _published(1)},
        ]

    monkeypatch.setattr(collector.feedparser, "parse", lambda url: _FakeFeed())

    result = collector.collect({"raw_items": [], "analyzed_items": []})

    assert len(result["raw_items"]) == 1
    assert result["raw_items"][0]["title"] == "Two"


def test_collect_parses_entries_from_configured_sources(monkeypatch):
    monkeypatch.setattr(
        collector, "SOURCES", [Source("Test Source", "http://example.com/rss", "fr", "contracts", "FR")]
    )

    class _FakeFeed:
        entries = [
            {
                "title": "Title 1",
                "link": "http://example.com/1",
                "published": "2026-01-01",
                "summary": "<p>Summary 1</p>",
            }
        ]

    monkeypatch.setattr(collector.feedparser, "parse", lambda url: _FakeFeed())

    result = collector.collect({"raw_items": [], "analyzed_items": []})

    assert len(result["raw_items"]) == 1
    item = result["raw_items"][0]
    assert item["source"] == "Test Source"
    assert item["theme"] == "contracts"
    assert item["country"] == "FR"
    assert item["state_affiliated"] is False
    assert item["link"] == "http://example.com/1"
    assert item["raw_text"] == "<p>Summary 1</p>"


def test_collect_returns_no_items_when_feed_is_empty(monkeypatch):
    monkeypatch.setattr(
        collector, "SOURCES", [Source("Test Source", "http://example.com/rss", "fr", "contracts", "FR")]
    )

    class _EmptyFeed:
        entries = []

    monkeypatch.setattr(collector.feedparser, "parse", lambda url: _EmptyFeed())

    result = collector.collect({"raw_items": [], "analyzed_items": []})

    assert result["raw_items"] == []


def test_source_freshness_flags_a_source_with_no_recent_item(monkeypatch):
    # A feed that parses without error but no longer publishes anything recent (real case: OFAC, dead
    # for ~1 year) must come out as silent, not as active — that is the whole point of the measurement.
    monkeypatch.setattr(
        collector,
        "SOURCES",
        [
            Source("Alive", "http://example.com/a", "fr", "contracts", "FR"),
            Source("Dead", "http://example.com/b", "fr", "contracts", "FR"),
        ],
    )

    def _fake_parse(url):
        class _Feed:
            entries = (
                [{"title": "T", "link": "l", "published": _published(1)}]
                if url == "http://example.com/a"
                else [{"title": "Old", "link": "l2", "published": _published(9999)}]
            )

        return _Feed()

    monkeypatch.setattr(collector.feedparser, "parse", _fake_parse)

    result = collector.source_freshness()

    assert result == {"Alive": 1, "Dead": 0}


def test_collect_survives_a_feed_that_raises_instead_of_returning(monkeypatch):
    # Real case of 2026-08-30: feedparser only intercepts `urllib.error.URLError`, so a
    # `RemoteDisconnected` on a redirect propagated all the way up and brought `collect()` down — and,
    # in an unattended Job, the whole day before the first article was analysed.
    monkeypatch.setattr(
        collector,
        "SOURCES",
        [
            Source("Healthy", "http://example.com/a", "fr", "contracts", "FR"),
            Source("Flaky", "http://example.com/b", "fr", "contracts", "FR"),
        ],
    )

    def _fake_parse(url):
        if url == "http://example.com/b":
            raise ConnectionResetError("Remote end closed connection without response")

        class _Feed:
            entries = [{"title": "T", "link": "http://example.com/1", "published": _published(1)}]

        return _Feed()

    monkeypatch.setattr(collector.feedparser, "parse", _fake_parse)

    result = collector.collect({"raw_items": [], "analyzed_items": []})

    assert [item["title"] for item in result["raw_items"]] == ["T"]


def test_collect_treats_an_unreadable_feed_as_unavailable_not_silent(monkeypatch):
    # feedparser swallows `URLError` and returns an empty result flagged `bozo`. With no distinction,
    # a feed out of service would count as silent: a network outage would read as a dead feed.
    monkeypatch.setattr(collector, "SOURCES", [Source("HS", "http://example.com/b", "fr", "contracts", "FR")])

    class _BozoFeed:
        entries = []
        bozo = True
        bozo_exception = OSError("domain name not found")

    monkeypatch.setattr(collector.feedparser, "parse", lambda url: _BozoFeed())

    records = []
    monkeypatch.setattr(collector.log, "error", lambda msg, extra=None: records.append(extra))
    monkeypatch.setattr(collector.log, "warning", lambda msg, extra=None: records.append(("SILENT", extra)))

    result = collector.collect({"raw_items": [], "analyzed_items": []})

    assert result["raw_items"] == []
    assert records == [
        {
            "unavailable_sources": {"HS": "domain name not found"},
            "window_h": collector.COLLECTION_LOOKBACK_HOURS,
        }
    ]


def test_a_malformed_but_parseable_feed_is_not_treated_as_unavailable(monkeypatch):
    # Control on the criterion: plenty of valid feeds are `bozo` and still return their entries. It is
    # `bozo` *and* zero entries that signs the failure, not `bozo` alone.
    monkeypatch.setattr(collector, "SOURCES", [Source("Wobbly", "http://example.com/a", "fr", "contracts", "FR")])

    class _BozoButUsable:
        entries = [{"title": "T", "link": "http://example.com/1", "published": _published(1)}]
        bozo = True
        bozo_exception = ValueError("unescaped character")

    monkeypatch.setattr(collector.feedparser, "parse", lambda url: _BozoButUsable())

    result = collector.collect({"raw_items": [], "analyzed_items": []})

    assert [item["title"] for item in result["raw_items"]] == ["T"]


def test_source_freshness_reports_none_for_an_unreachable_feed(monkeypatch):
    # `None` and not 0: the coverage KPI must not invent the measurement that is missing.
    monkeypatch.setattr(
        collector,
        "SOURCES",
        [
            Source("Alive", "http://example.com/a", "fr", "contracts", "FR"),
            Source("Unreachable", "http://example.com/b", "fr", "contracts", "FR"),
        ],
    )

    def _fake_parse(url):
        if url == "http://example.com/b":
            raise TimeoutError("timed out")

        class _Feed:
            entries = [{"title": "T", "link": "l", "published": _published(1)}]

        return _Feed()

    monkeypatch.setattr(collector.feedparser, "parse", _fake_parse)

    assert collector.source_freshness() == {"Alive": 1, "Unreachable": None}
