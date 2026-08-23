"""Semantique du code de sortie du Cloud Run Job.

Cloud Run Jobs relance une tache qui sort en erreur : c'est le code de sortie, et lui seul, qui
decide s'il y aura une seconde tentative. Ces trois tests fixent quand il doit y en avoir une.
"""

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
