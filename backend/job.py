"""Point d'entrée du Cloud Run Job qui exécute le run quotidien.

Le pipeline est un traitement par lot de ~10 minutes, pas une requête : le déclencher par HTTP
imposerait de tenir la connexion ouverte pendant toute sa durée, sous le timeout du service *et*
sous celui de l'ordonnanceur (30 min au maximum côté Cloud Scheduler). Un Job n'a pas de timeout de
requête, et le service Cloud Run reste dédié à ce qu'il sait faire vite : servir le digest déjà
produit par GET /events.

Même image que le service, commande différente — pas deux constructions à tenir synchrones.
"""

import os
import sys

from backend.graph import run_pipeline
from backend.logging_setup import configure_logging, get_logger

log = get_logger("job")

# Variables par lesquelles LangChain active l'envoi des traces vers LangSmith. Les deux noms
# coexistent (l'ancien et celui introduit par le renommage LangSmith) et sont lues indépendamment :
# en neutraliser une seule laisse le traçage actif par l'autre.
_TRACING_VARS = ("LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING")


def _disable_tracing_unless_opted_in() -> bool:
    """Éteint le traçage sur le Job, sauf demande explicite via `VIGIE_JOB_TRACING=true`.

    Mesuré le 2026-08-30 : le service LangSmith est devenu injoignable **pendant** un run et le
    pipeline s'est arrêté plusieurs minutes sur ses délais d'expiration. Le client LangSmith attend
    60 s en lecture par envoi (`timeout_ms` vaut `(10_000, 60_000)` par défaut) et cette valeur n'est
    pas réglable par variable d'environnement dans la version épinglée — la borner supposerait de
    construire le client nous-mêmes, donc d'entretenir du code de traçage dans le chemin du run.

    Le Job est le chemin non surveillé, et celui qui a le moins de marge : 880 s mesurées contre une
    cible de 900 s, dont on relève par ailleurs le timeout Cloud Run. Un observatoire qui peut
    arrêter ce qu'il observe n'y a pas sa place par défaut. Le traçage garde toute sa valeur en
    développement, où l'on est devant l'écran — d'où l'inversion du défaut ici seulement, et pas
    dans `.env` : `uvicorn` et les scripts d'éval continuent de tracer normalement.

    Rend True si le traçage a été laissé actif.
    """
    if os.getenv("VIGIE_JOB_TRACING", "").strip().lower() in {"1", "true", "yes"}:
        log.info("traçage LangSmith laissé actif sur le Job, à la demande explicite")
        return True
    disabled = [var for var in _TRACING_VARS if os.environ.pop(var, None) is not None]
    if disabled:
        log.info("traçage LangSmith éteint sur le Job", extra={"variables": disabled})
    return False


def main() -> int:
    """Code de sortie 0 si le run est allé au bout, 1 s'il a échoué.

    **Un run tronqué sort en 0**, et c'est la décision qui compte ici : Cloud Run Jobs relance une
    tâche qui sort en erreur, or un run tronqué a atteint le plafond quotidien d'appels (§6). Le
    relancer ne produirait rien — le budget est épuisé, le dédoublonnage a déjà marqué les items
    soumis — mais effacerait le travail payé sous une pile de tentatives en échec. La troncature est
    un succès partiel : elle se voit en WARNING dans le journal et en `truncated` dans les champs
    structurés, pas dans le code de sortie.
    """
    configure_logging()
    _disable_tracing_unless_opted_in()
    try:
        result = run_pipeline()
    except Exception:
        # run_pipeline journalise déjà l'exception avec sa durée ; ici on ne fait que traduire
        # l'échec en code de sortie, seul signal que Cloud Run Jobs sait lire.
        log.error("run quotidien en échec, sortie en erreur")
        return 1

    log.info(
        "run quotidien terminé",
        extra={"items": len(result["analyzed_items"]), "truncated": result["truncated"]},
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
