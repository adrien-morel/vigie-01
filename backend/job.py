"""Point d'entrée du Cloud Run Job qui exécute le run quotidien.

Le pipeline est un traitement par lot de ~10 minutes, pas une requête : le déclencher par HTTP
imposerait de tenir la connexion ouverte pendant toute sa durée, sous le timeout du service *et*
sous celui de l'ordonnanceur (30 min au maximum côté Cloud Scheduler). Un Job n'a pas de timeout de
requête, et le service Cloud Run reste dédié à ce qu'il sait faire vite : servir le digest déjà
produit par GET /events.

Même image que le service, commande différente — pas deux constructions à tenir synchrones.
"""

import sys

from backend.graph import run_pipeline
from backend.logging_setup import configure_logging, get_logger

log = get_logger("job")


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
