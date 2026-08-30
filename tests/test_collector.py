from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import backend.agents.collector as collector
from backend.config import Source


def _published(hours_ago: float) -> str:
    return format_datetime(datetime.now(UTC) - timedelta(hours=hours_ago))


def test_collect_caps_items_per_source_keeping_the_most_recent(monkeypatch):
    monkeypatch.setattr(collector, "SOURCES", [Source("Test Source", "http://example.com/rss", "fr", "contrats", "FR")])
    monkeypatch.setattr(collector, "MAX_ITEMS_PER_SOURCE_PER_RUN", 2)

    class _FakeFeed:
        entries = [
            {"title": "Ancien", "link": "http://example.com/1", "published": _published(3)},
            {"title": "Récent", "link": "http://example.com/2", "published": _published(1)},
            {"title": "Milieu", "link": "http://example.com/3", "published": _published(2)},
        ]

    monkeypatch.setattr(collector.feedparser, "parse", lambda url: _FakeFeed())

    result = collector.collect({"raw_items": [], "analyzed_items": []})

    assert [item["title"] for item in result["raw_items"]] == ["Récent", "Milieu"]


def test_collect_respects_a_source_specific_cap_override(monkeypatch):
    monkeypatch.setattr(
        collector,
        "SOURCES",
        [Source("Test Source", "http://example.com/rss", "fr", "contrats", "FR", max_per_run=1)],
    )
    monkeypatch.setattr(collector, "MAX_ITEMS_PER_SOURCE_PER_RUN", 12)

    class _FakeFeed:
        entries = [
            {"title": "Un", "link": "http://example.com/1", "published": _published(2)},
            {"title": "Deux", "link": "http://example.com/2", "published": _published(1)},
        ]

    monkeypatch.setattr(collector.feedparser, "parse", lambda url: _FakeFeed())

    result = collector.collect({"raw_items": [], "analyzed_items": []})

    assert len(result["raw_items"]) == 1
    assert result["raw_items"][0]["title"] == "Deux"


def test_collect_parses_entries_from_configured_sources(monkeypatch):
    monkeypatch.setattr(collector, "SOURCES", [Source("Test Source", "http://example.com/rss", "fr", "contrats", "FR")])

    class _FakeFeed:
        entries = [
            {
                "title": "Titre 1",
                "link": "http://example.com/1",
                "published": "2026-01-01",
                "summary": "<p>Résumé 1</p>",
            }
        ]

    monkeypatch.setattr(collector.feedparser, "parse", lambda url: _FakeFeed())

    result = collector.collect({"raw_items": [], "analyzed_items": []})

    assert len(result["raw_items"]) == 1
    item = result["raw_items"][0]
    assert item["source"] == "Test Source"
    assert item["theme"] == "contrats"
    assert item["country"] == "FR"
    assert item["state_affiliated"] is False
    assert item["link"] == "http://example.com/1"
    assert item["raw_text"] == "<p>Résumé 1</p>"


def test_collect_returns_no_items_when_feed_is_empty(monkeypatch):
    monkeypatch.setattr(collector, "SOURCES", [Source("Test Source", "http://example.com/rss", "fr", "contrats", "FR")])

    class _EmptyFeed:
        entries = []

    monkeypatch.setattr(collector.feedparser, "parse", lambda url: _EmptyFeed())

    result = collector.collect({"raw_items": [], "analyzed_items": []})

    assert result["raw_items"] == []


def test_source_freshness_flags_a_source_with_no_recent_item(monkeypatch):
    # Un flux qui se parse sans erreur mais ne publie plus rien de récent (cas réel : OFAC, mort
    # ~1 an) doit ressortir comme silencieux, pas comme actif — c'est tout l'intérêt de la mesure.
    monkeypatch.setattr(
        collector,
        "SOURCES",
        [
            Source("Vivante", "http://example.com/a", "fr", "contrats", "FR"),
            Source("Morte", "http://example.com/b", "fr", "contrats", "FR"),
        ],
    )

    def _fake_parse(url):
        class _Feed:
            entries = (
                [{"title": "T", "link": "l", "published": _published(1)}]
                if url == "http://example.com/a"
                else [{"title": "Vieux", "link": "l2", "published": _published(9999)}]
            )

        return _Feed()

    monkeypatch.setattr(collector.feedparser, "parse", _fake_parse)

    result = collector.source_freshness()

    assert result == {"Vivante": 1, "Morte": 0}


def test_collect_survives_a_feed_that_raises_instead_of_returning(monkeypatch):
    # Cas réel du 2026-08-30 : feedparser n'intercepte que `urllib.error.URLError`, donc un
    # `RemoteDisconnected` sur une redirection remontait jusqu'à faire tomber `collect()` — et,
    # dans un Job non surveillé, la journée entière avant le premier article analysé.
    monkeypatch.setattr(
        collector,
        "SOURCES",
        [
            Source("Saine", "http://example.com/a", "fr", "contrats", "FR"),
            Source("Capricieuse", "http://example.com/b", "fr", "contrats", "FR"),
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
    # feedparser avale `URLError` et rend un résultat vide marqué `bozo`. Sans distinction, un flux
    # hors service compterait comme muet : une panne réseau se lirait comme un flux mort.
    monkeypatch.setattr(collector, "SOURCES", [Source("HS", "http://example.com/b", "fr", "contrats", "FR")])

    class _BozoFeed:
        entries = []
        bozo = True
        bozo_exception = OSError("nom de domaine introuvable")

    monkeypatch.setattr(collector.feedparser, "parse", lambda url: _BozoFeed())

    records = []
    monkeypatch.setattr(collector.log, "error", lambda msg, extra=None: records.append(extra))
    monkeypatch.setattr(collector.log, "warning", lambda msg, extra=None: records.append(("MUETTE", extra)))

    result = collector.collect({"raw_items": [], "analyzed_items": []})

    assert result["raw_items"] == []
    assert records == [
        {
            "sources_indisponibles": {"HS": "nom de domaine introuvable"},
            "fenetre_h": collector.COLLECTION_LOOKBACK_HOURS,
        }
    ]


def test_a_malformed_but_parseable_feed_is_not_treated_as_unavailable(monkeypatch):
    # Contrôle du critère : beaucoup de flux valides sont `bozo` et rendent quand même leurs
    # entrées. C'est `bozo` *et* zéro entrée qui signe l'échec, pas `bozo` seul.
    monkeypatch.setattr(collector, "SOURCES", [Source("Bancale", "http://example.com/a", "fr", "contrats", "FR")])

    class _BozoButUsable:
        entries = [{"title": "T", "link": "http://example.com/1", "published": _published(1)}]
        bozo = True
        bozo_exception = ValueError("caractère non échappé")

    monkeypatch.setattr(collector.feedparser, "parse", lambda url: _BozoButUsable())

    result = collector.collect({"raw_items": [], "analyzed_items": []})

    assert [item["title"] for item in result["raw_items"]] == ["T"]


def test_source_freshness_reports_none_for_an_unreachable_feed(monkeypatch):
    # `None` et non 0 : le KPI de couverture ne doit pas inventer la mesure qui manque.
    monkeypatch.setattr(
        collector,
        "SOURCES",
        [
            Source("Vivante", "http://example.com/a", "fr", "contrats", "FR"),
            Source("Injoignable", "http://example.com/b", "fr", "contrats", "FR"),
        ],
    )

    def _fake_parse(url):
        if url == "http://example.com/b":
            raise TimeoutError("delai depasse")

        class _Feed:
            entries = [{"title": "T", "link": "l", "published": _published(1)}]

        return _Feed()

    monkeypatch.setattr(collector.feedparser, "parse", _fake_parse)

    assert collector.source_freshness() == {"Vivante": 1, "Injoignable": None}
