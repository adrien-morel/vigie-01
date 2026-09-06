import pytest
from fastapi.testclient import TestClient

from backend.api import main as api_main

FAKE_ITEM = {
    "source": "s",
    "lang": "fr",
    "country": "FR",
    "state_affiliated": False,
    "title": "t",
    "title_en": "t",
    "link": "l",
    "published": "",
    "category": "arms_contract",
    "summary": "r",
    "citation": "c",
    "location": "",
    "model_confidence": None,
    "corroborated": None,
}


TOKEN = "test-token"


def _client() -> TestClient:
    return TestClient(api_main.app)


def _authorized(monkeypatch) -> dict:
    """POST /run is closed behind a shared token (backend/config.RUN_TOKEN). The tests that trigger a
    run set the token rather than disabling the check: that is the real Cloud Scheduler path, and
    disabling the guardrail in the tests would amount to never testing it."""
    monkeypatch.setattr(api_main, "RUN_TOKEN", TOKEN)
    return {"X-Run-Token": TOKEN}


def test_health():
    assert _client().get("/health").json() == {"status": "ok"}


def test_events_404_when_the_pipeline_has_never_run():
    assert _client().get("/events").status_code == 404


def test_run_then_events_roundtrip(monkeypatch):
    from backend.memory import store

    def _fake_pipeline() -> dict:
        # The real pipeline writes the history in its verify node; /events reads it back from there.
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
    """The original defect: a run with no new item (all deduplicated) overwrote the previous digest.
    The digest now being a window over the history, it must survive an empty run."""
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
    """404 means "the pipeline has never run". A window that is too narrow over a non-empty history
    stays a navigable digest, otherwise the period selector would vanish from the screen."""
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
    """The budget cap no longer propagates as an exception: the nodes truncate and return what they
    produced. Answering 429 would make the front ignore a digest that really was enriched — it does
    not reload on error, which used to hide the update."""
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
    """With no token configured, the most expensive endpoint of the system is closed, not open: 503.
    The service keeps serving the digest through GET /events, which costs nothing."""
    monkeypatch.setattr(api_main, "RUN_TOKEN", "")
    monkeypatch.setattr(api_main, "run_pipeline", lambda: pytest.fail("the pipeline must not start"))

    assert _client().post("/run").status_code == 503


def test_run_rejects_a_missing_or_wrong_token(monkeypatch):
    monkeypatch.setattr(api_main, "RUN_TOKEN", TOKEN)
    monkeypatch.setattr(api_main, "run_pipeline", lambda: pytest.fail("the pipeline must not start"))

    client = _client()
    assert client.post("/run").status_code == 401
    assert client.post("/run", headers={"X-Run-Token": "wrong"}).status_code == 401


def test_cors_no_longer_answers_every_origin():
    """The V1 "*" let any page read the digest from a visitor's browser. Replacing it with a list is
    an item of the production rollout plan."""
    from backend.config import ALLOWED_ORIGINS

    refused = _client().get("/events", headers={"Origin": "https://elsewhere.example"})
    accepted = _client().get("/events", headers={"Origin": ALLOWED_ORIGINS[0]})

    assert refused.headers.get("access-control-allow-origin") != "*"
    assert accepted.headers.get("access-control-allow-origin") == ALLOWED_ORIGINS[0]
