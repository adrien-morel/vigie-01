import pytest
from fastapi.testclient import TestClient

from backend.api import main as api_main

FAKE_ITEM = {
    "source": "s",
    "lang": "fr",
    "country": "FR",
    "state_affiliated": False,
    "title": "t",
    "title_fr": "t",
    "link": "l",
    "published": "",
    "category": "contrat_armement",
    "summary": "r",
    "citation": "c",
    "location": "",
    "confidence_score": None,
    "corroborated": None,
}


TOKEN = "jeton-de-test"


def _client() -> TestClient:
    return TestClient(api_main.app)


def _authorized(monkeypatch) -> dict:
    """POST /run est ferme par jeton partage (backend/config.RUN_TOKEN). Les tests qui declenchent
    un run posent le jeton plutot que de desactiver le controle : c'est le chemin reel de Cloud
    Scheduler, et desactiver le garde-fou dans les tests reviendrait a ne jamais le tester."""
    monkeypatch.setattr(api_main, "RUN_TOKEN", TOKEN)
    return {"X-Run-Token": TOKEN}


def test_health():
    assert _client().get("/health").json() == {"status": "ok"}


def test_events_404_when_the_pipeline_has_never_run():
    assert _client().get("/events").status_code == 404


def test_run_then_events_roundtrip(monkeypatch):
    from backend.memory import store

    def _fake_pipeline() -> dict:
        # Le vrai pipeline écrit l'historique dans son nœud verify ; /events le relit depuis là.
        store.record_analyzed([FAKE_ITEM])
        return {"analyzed_items": [FAKE_ITEM], "truncated": False}

    monkeypatch.setattr(api_main, "run_pipeline", _fake_pipeline)
    headers = _authorized(monkeypatch)

    run_res = _client().post("/run", headers=headers)
    assert run_res.status_code == 200
    assert run_res.json()["item_count"] == 1

    events_res = _client().get("/events")
    assert events_res.status_code == 200
    assert [i["link"] for i in events_res.json()["items"]] == ["l"]


def test_events_keeps_previous_items_when_a_later_run_brings_nothing_new(monkeypatch):
    """Le défaut d'origine : un run sans item neuf (tout dédoublonné) écrasait le digest précédent.
    Le digest étant désormais une fenêtre sur l'historique, il doit survivre à un run vide."""
    from backend.memory import store

    store.record_analyzed([FAKE_ITEM])
    monkeypatch.setattr(api_main, "run_pipeline", lambda: {"analyzed_items": [], "truncated": False})
    headers = _authorized(monkeypatch)

    client = _client()
    assert client.post("/run", headers=headers).json()["item_count"] == 0
    assert [i["link"] for i in client.get("/events").json()["items"]] == ["l"]


def test_events_window_is_bounded_by_history_retention():
    from backend.memory.store import RELATED_ITEMS_WINDOW_DAYS

    client = _client()
    assert client.get(f"/events?days={RELATED_ITEMS_WINDOW_DAYS + 1}").status_code == 422
    assert client.get("/events?days=0").status_code == 422


def test_events_reports_the_window_it_served():
    from backend.memory import store

    store.record_analyzed([FAKE_ITEM])

    body = _client().get("/events?days=3").json()

    assert body["window_days"] == 3
    assert body["generated_at"] is not None


def test_events_returns_an_empty_window_rather_than_404_when_history_exists():
    """404 veut dire « le pipeline n'a jamais tourné ». Une fenêtre trop étroite sur un historique
    non vide reste un digest navigable, sinon le sélecteur de période disparaîtrait de l'écran."""
    from datetime import date, timedelta

    from backend.memory import store
    from backend.memory.persistence import get_persistence

    # A day within retention (RELATED_ITEMS_WINDOW_DAYS) but outside the narrow queried window.
    old = (date.today() - timedelta(days=store.RELATED_ITEMS_WINDOW_DAYS - 1)).isoformat()
    get_persistence().put_analyzed([{**FAKE_ITEM, "date": old, "first_seen": old}])

    res = _client().get("/events?days=2")

    assert res.status_code == 200
    assert res.json()["items"] == []


def test_run_reports_a_truncated_run_as_a_partial_success_not_an_error(monkeypatch):
    """Le plafond de budget ne remonte plus en exception : les nœuds tronquent et rendent ce qu'ils
    ont produit. Répondre 429 ferait ignorer au front un digest réellement enrichi — il ne recharge
    pas sur erreur, ce qui masquait la mise à jour."""
    monkeypatch.setattr(api_main, "run_pipeline", lambda: {"analyzed_items": [FAKE_ITEM], "truncated": True})
    headers = _authorized(monkeypatch)

    res = _client().post("/run", headers=headers)

    assert res.status_code == 200
    assert res.json() == {"item_count": 1, "truncated": True}


def test_run_reports_a_complete_run_as_untruncated(monkeypatch):
    monkeypatch.setattr(api_main, "run_pipeline", lambda: {"analyzed_items": [FAKE_ITEM], "truncated": False})
    headers = _authorized(monkeypatch)

    assert _client().post("/run", headers=headers).json() == {"item_count": 1, "truncated": False}


def test_run_is_closed_when_no_token_is_configured(monkeypatch):
    """Sans jeton configure, l'endpoint le plus couteux du systeme est ferme et non ouvert : 503.
    Le service continue de servir le digest par GET /events, qui ne coute rien."""
    monkeypatch.setattr(api_main, "RUN_TOKEN", "")
    monkeypatch.setattr(api_main, "run_pipeline", lambda: pytest.fail("le pipeline ne doit pas demarrer"))

    assert _client().post("/run").status_code == 503


def test_run_rejects_a_missing_or_wrong_token(monkeypatch):
    monkeypatch.setattr(api_main, "RUN_TOKEN", TOKEN)
    monkeypatch.setattr(api_main, "run_pipeline", lambda: pytest.fail("le pipeline ne doit pas demarrer"))

    client = _client()
    assert client.post("/run").status_code == 401
    assert client.post("/run", headers={"X-Run-Token": "faux"}).status_code == 401


def test_cors_no_longer_answers_every_origin():
    """Le « * » de la V1 laissait n'importe quelle page lire le digest depuis le navigateur d'un
    visiteur. Le remplacer par une liste est un item du plan de mise en production."""
    from backend.config import ALLOWED_ORIGINS

    refuse = _client().get("/events", headers={"Origin": "https://ailleurs.example"})
    accepte = _client().get("/events", headers={"Origin": ALLOWED_ORIGINS[0]})

    assert refuse.headers.get("access-control-allow-origin") != "*"
    assert accepte.headers.get("access-control-allow-origin") == ALLOWED_ORIGINS[0]
