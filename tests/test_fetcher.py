"""Tests du nœud de récupération du texte intégral (backend/agents/fetcher.py).

Le transport HTTP est systématiquement substitué : la suite ne doit joindre aucun site réel, au
même titre que le LLM et les flux RSS y sont mockés. La validation contre données réelles est faite
séparément, par sonde (cf. docs/cadrage.md §11).
"""

import pytest

from backend import config
from backend.agents import analyst, fetcher


def _raw_item(raw_text: str, source: str = "s", link: str = "https://example.test/a") -> dict:
    return {
        "source": source,
        "theme": "contrats",
        "lang": "en",
        "country": "US",
        "state_affiliated": False,
        "title": "titre",
        "link": link,
        "published": "",
        "raw_text": raw_text,
    }


class _FakeResponse:
    def __init__(self, text: str = "", status_code: int = 200):
        self.text = text
        self.status_code = status_code


def _page(body: str) -> str:
    """HTML minimal que trafilatura sait réduire au corps de l'article."""
    return f"<html><body><article><p>{body}</p></article></body></html>"


# --- ancrage -----------------------------------------------------------------------------------


def test_anchor_overlap_none_when_teaser_too_short_to_anchor():
    # Cas réel : le teaser de Federal Register est vide, celui d'un item CGTN fait 37 caractères.
    # Sans ancre, on ne peut pas vérifier que l'extraction porte bien cet article.
    assert fetcher._anchor_overlap("", "texte quelconque de la page") is None
    assert fetcher._anchor_overlap("Xi visit", "texte quelconque de la page") is None


def test_anchor_overlap_full_when_extract_contains_teaser():
    teaser = "Le ministre annonce une commande de blindés supplémentaires"
    assert fetcher._anchor_overlap(teaser, f"{teaser} pour l'armée de terre.") == 1.0


def test_anchor_overlap_low_when_extract_is_site_chrome():
    # Le cas Federal Register/CGTN s'il avait un teaser : mentions légales au lieu de l'article.
    teaser = "Le ministre annonce une commande de blindés supplémentaires"
    chrome = "This site displays a prototype of a Web 2.0 version of the daily Federal Register."
    assert fetcher._anchor_overlap(teaser, chrome) == 0.0


# --- récupération unitaire ---------------------------------------------------------------------


def test_fetch_full_article_returns_extracted_body(monkeypatch):
    monkeypatch.setattr(
        fetcher.requests,
        "get",
        lambda *a, **k: _FakeResponse(_page("Un corps d'article assez long pour être extrait.")),
    )
    assert "corps d'article" in fetcher.fetch_full_article("https://example.test/a")


def test_fetch_full_article_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(fetcher.requests, "get", lambda *a, **k: _FakeResponse("", status_code=403))
    with pytest.raises(fetcher.ArticleUnavailable, match="403"):
        fetcher.fetch_full_article("https://example.test/a")


def test_fetch_full_article_raises_on_network_error(monkeypatch):
    def boom(*a, **k):
        raise fetcher.requests.ConnectionError("coupure")

    monkeypatch.setattr(fetcher.requests, "get", boom)
    with pytest.raises(fetcher.ArticleUnavailable):
        fetcher.fetch_full_article("https://example.test/a")


def test_fetch_full_article_raises_when_extraction_is_empty(monkeypatch):
    monkeypatch.setattr(fetcher.requests, "get", lambda *a, **k: _FakeResponse("<html><body></body></html>"))
    with pytest.raises(fetcher.ArticleUnavailable, match="vide"):
        fetcher.fetch_full_article("https://example.test/a")


# --- enrichissement du lot ---------------------------------------------------------------------


def test_enrich_items_appends_without_replacing_the_teaser(monkeypatch):
    """L'invariant central du module : on ajoute, on ne remplace pas."""
    teaser = "Le ministre annonce une commande de blindés supplémentaires livrables en 2027"
    monkeypatch.setattr(
        fetcher.requests,
        "get",
        lambda *a, **k: _FakeResponse(_page(f"{teaser}. Le contrat porte sur trente véhicules et un soutien associé.")),
    )
    item = _raw_item(teaser)
    tally = fetcher.enrich_items([item])

    assert tally.enriched == 1
    assert teaser in item["raw_text"], "le teaser d'origine doit survivre à l'enrichissement"
    assert "trente véhicules" in analyst._clean_text(item["raw_text"])


def test_citation_verifiable_before_enrichment_stays_verifiable_after(monkeypatch):
    """Conséquence de l'invariant, et la raison pour laquelle il est posé : le corpus vérifiable ne
    fait que croître, donc le garde-fou de traçabilité (§8) ne peut pas régresser."""
    teaser = "Le ministre annonce une commande de blindés supplémentaires livrables en 2027"
    citation = "une commande de blindés supplémentaires"
    item = _raw_item(teaser)
    assert analyst._extract_verified(citation, analyst._clean_text(item["raw_text"]))

    monkeypatch.setattr(
        fetcher.requests, "get", lambda *a, **k: _FakeResponse(_page("Un tout autre texte, plus long, sans rapport."))
    )
    fetcher.enrich_items([item])
    assert analyst._extract_verified(citation, analyst._clean_text(item["raw_text"]))


def test_enriched_text_survives_clean_text_round_trip(monkeypatch):
    """Le texte ajouté est échappé avant concaténation, parce que l'analyste repasse `raw_text` par
    `_clean_text` (retrait des balises puis `html.unescape`). Sans l'échappement, une esperluette ou
    un chevron du corps de l'article ressortirait transformé et casserait une citation verbatim."""
    teaser = "Le ministre annonce une commande de blindés supplémentaires livrables en 2027"
    body = "Accord signé entre Thales & Naval Group, marge < 5 % selon la source."
    monkeypatch.setattr(fetcher.requests, "get", lambda *a, **k: _FakeResponse(_page(f"{teaser}. {body}")))

    item = _raw_item(teaser)
    fetcher.enrich_items([item])
    assert body in analyst._clean_text(item["raw_text"])


def test_enrich_items_skips_configured_sources(monkeypatch):
    """Defense.gov répond 403 avec comme sans en-tête navigateur : renoncement documenté, pas
    découverte en production. Aucune requête ne doit partir pour ces sources."""

    def fail(*a, **k):
        raise AssertionError("aucune requête ne doit partir pour une source exclue")

    monkeypatch.setattr(fetcher.requests, "get", fail)
    source = next(iter(config.FETCH_SKIP_SOURCES))
    item = _raw_item("Un teaser de longueur tout à fait raisonnable pour ancrer", source=source)
    before = item["raw_text"]

    tally = fetcher.enrich_items([item])
    assert tally.skipped_source == 1
    assert item["raw_text"] == before


def test_enrich_items_abstains_when_teaser_is_not_anchorable(monkeypatch):
    """Le cas Federal Register : la page se récupère (200), mais l'extraction ramène les mentions
    légales du site et le teaser est trop court pour le détecter. On s'abstient."""
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
    """Un article injoignable dégrade l'item, il ne le perd pas — même règle qu'un flux injoignable."""
    monkeypatch.setattr(fetcher.requests, "get", lambda *a, **k: _FakeResponse("", status_code=500))
    item = _raw_item("Un teaser de longueur tout à fait raisonnable pour ancrer")
    before = item["raw_text"]

    tally = fetcher.enrich_items([item])
    assert tally.failed == 1
    assert item["raw_text"] == before


def test_one_failure_does_not_stop_the_batch(monkeypatch):
    """Même invariant que le correctif du 2026-08-30 sur les flux : l'échec est local à l'article."""
    teaser = "Le ministre annonce une commande de blindés supplémentaires livrables en 2027"

    def get(url, *a, **k):
        if "casse" in url:
            raise fetcher.requests.ConnectionError("coupure")
        return _FakeResponse(_page(f"{teaser}. Un complément d'article bien plus long que le teaser."))

    monkeypatch.setattr(fetcher.requests, "get", get)
    broken = _raw_item(teaser, link="https://example.test/casse")
    fine = _raw_item(teaser, link="https://example.test/ok")

    tally = fetcher.enrich_items([broken, fine])
    assert (tally.failed, tally.enriched) == (1, 1)


def test_enrich_items_caps_appended_length(monkeypatch):
    """Un article de la traîne (35 445 caractères au relevé, douze fois la médiane) ne doit pas
    partir entier au modèle."""
    teaser = "Le ministre annonce une commande de blindés supplémentaires livrables en 2027"
    monkeypatch.setattr(fetcher.requests, "get", lambda *a, **k: _FakeResponse(_page(f"{teaser}. " + "mot " * 20000)))
    monkeypatch.setattr(fetcher, "FETCH_MAX_CHARS", 500)

    item = _raw_item(teaser)
    tally = fetcher.enrich_items([item])
    assert tally.enriched == 1
    assert tally.chars_added == 500


def test_enrich_items_abstains_when_extract_adds_nothing(monkeypatch):
    """Extraction plus courte que le teaser : rien à gagner, on ne remplace pas."""
    teaser = "Le ministre annonce une commande de blindés supplémentaires livrables en 2027 " * 3
    monkeypatch.setattr(fetcher.requests, "get", lambda *a, **k: _FakeResponse(_page(f"{teaser[:80]}")))

    item = _raw_item(teaser)
    before = item["raw_text"]
    tally = fetcher.enrich_items([item])
    assert tally.no_gain == 1
    assert item["raw_text"] == before


def test_tally_reports_anchor_distribution_without_gating_on_it(monkeypatch):
    """Le score d'ancrage est mesuré et journalisé, mais ne décide de rien : aucune séparation
    positif/négatif ne permet encore de calibrer un seuil (cf. `_anchor_overlap`)."""
    teaser = "Le ministre annonce une commande de blindés supplémentaires livrables en 2027"
    monkeypatch.setattr(
        fetcher.requests,
        "get",
        lambda *a, **k: _FakeResponse(
            _page(
                "Texte entièrement disjoint du teaser, volontairement plus long que lui pour "
                "isoler l'effet de l'ancrage de celui du gain de longueur."
            )
        ),
    )
    item = _raw_item(teaser)
    tally = fetcher.enrich_items([item])

    assert tally.enriched == 1, "un ancrage faible n'écarte pas l'item — il est seulement mesuré"
    assert tally.overlaps == [0.0]
    assert "ancrage_median" in tally.as_dict()


# --- intégration au nœud analyze -----------------------------------------------------------------


def test_analyze_degrades_to_teasers_when_fetching_blows_up(monkeypatch):
    """La récupération ne doit en aucun cas faire tomber l'analyse : un échec global la ramène au
    comportement d'avant ce module."""
    monkeypatch.setattr(config, "FETCH_FULL_ARTICLE", True)

    def boom(_items):
        raise RuntimeError("pool en échec")

    monkeypatch.setattr(analyst, "enrich_items", boom)
    monkeypatch.setattr(analyst, "classify_item", lambda item: (_ for _ in ()).throw(ValueError("non classable")))

    result = analyst.analyze({"raw_items": [_raw_item("un texte")], "analyzed_items": []})
    assert result["analyzed_items"] == []


def test_analyze_skips_fetching_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "FETCH_FULL_ARTICLE", False)
    monkeypatch.setattr(
        analyst, "enrich_items", lambda _items: (_ for _ in ()).throw(AssertionError("ne doit pas être appelé"))
    )
    monkeypatch.setattr(analyst, "classify_item", lambda item: (_ for _ in ()).throw(ValueError("non classable")))

    analyst.analyze({"raw_items": [_raw_item("un texte")], "analyzed_items": []})
