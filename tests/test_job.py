"""Semantique du code de sortie du Cloud Run Job.

Cloud Run Jobs relance une tache qui sort en erreur : c'est le code de sortie, et lui seul, qui
decide s'il y aura une seconde tentative. Ces trois tests fixent quand il doit y en avoir une.
"""

import os

from backend import job


def test_a_complete_run_exits_zero(monkeypatch):
    monkeypatch.setattr(job, "run_pipeline", lambda: {"analyzed_items": [1, 2], "truncated": False})

    assert job.main() == 0


def test_a_truncated_run_exits_zero_because_a_retry_would_produce_nothing(monkeypatch):
    """Un run tronque a atteint le plafond quotidien d'appels : le relancer ne produirait rien
    (budget epuise, items soumis deja marques vus) et enterrerait le travail paye sous des
    tentatives en echec. La troncature se lit dans le journal, pas dans le code de sortie."""
    monkeypatch.setattr(job, "run_pipeline", lambda: {"analyzed_items": [1], "truncated": True})

    assert job.main() == 0


def test_a_failed_run_exits_one(monkeypatch):
    def _boom():
        raise RuntimeError("flux injoignable")

    monkeypatch.setattr(job, "run_pipeline", _boom)

    assert job.main() == 1


def test_job_disables_langsmith_tracing_by_default(monkeypatch):
    """Le traçage a arrêté un run plusieurs minutes le 2026-08-30 en devenant injoignable. Le Job
    est le chemin non surveillé : il ne trace pas, sauf demande explicite."""
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("VIGIE_JOB_TRACING", raising=False)

    assert job._disable_tracing_unless_opted_in() is False
    assert "LANGCHAIN_TRACING_V2" not in os.environ
    assert "LANGSMITH_TRACING" not in os.environ


def test_job_keeps_tracing_when_explicitly_opted_in(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("VIGIE_JOB_TRACING", "true")

    assert job._disable_tracing_unless_opted_in() is True
    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
