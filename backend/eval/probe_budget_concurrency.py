"""Sonde de concurrence sur la réservation de budget LLM.

Raison d'être : `check_and_increment_llm_call` incrémente un compteur quotidien partagé, et son
atomicité est une propriété du **stockage**, pas de l'appelant (`backend/memory/persistence.py`).
Le backend Firestore l'implémente en transaction, mais cette transaction n'avait jamais été
exercée sous concurrence réelle — et c'est le seul garde-fou du projet qui ne peut être faux qu'en
production. Un test unitaire à LLM simulé ne l'atteint pas : il n'y a rien à sérialiser dans un
processus unique qui écrit un fichier JSON.

Ce que la sonde mesure, et ce qu'elle ne mesure pas. Elle lance `--attempts` réservations
simultanées et compte les acceptations. Le verdict ne tient que si le nombre de places restantes
est **inférieur au nombre de tentatives** : avec un budget entier, toutes réussissent et la sonde
ne prouve rien. C'est le piège du 2026-09-05, où deux exécutions du pipeline complet n'avaient
produit qu'une seule réservation — le dédoublonnage les avait affamées avant que la course puisse
avoir lieu.

Lancer de préférence sur plusieurs tâches Cloud Run (`--tasks N`) et non sur des threads seuls :
des threads d'un même processus ne détecteraient pas un verrou posé côté client, alors que le
scénario réel est bien celui de deux conteneurs distincts.

**Aucun appel au modèle n'est émis.** Une réservation est un incrément de compteur ; la sonde
consomme donc du budget *comptable* — au plus `--attempts` unités, remises à zéro au changement de
jour — mais pas un centime d'API.

    python -m backend.eval.probe_budget_concurrency --yes [--attempts 10]
"""

import argparse
import concurrent.futures as futures
import os
from collections import Counter

from backend.guardrails import BudgetExceeded, check_and_increment_llm_call, remaining_calls_today
from backend.logging_setup import configure_logging, get_logger

log = get_logger("eval.probe_budget")


def _attempt(_: int) -> str:
    try:
        check_and_increment_llm_call("probe")
        return "accepte"
    except BudgetExceeded:
        return "refuse"
    except Exception as exc:  # noqa: BLE001 — on veut le nom du défaut, pas son traitement
        return f"erreur:{type(exc).__name__}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempts", type=int, default=10, help="réservations simultanées par tâche")
    # Garde-fou d'invocation : la sonde consomme du budget comptable, elle ne doit pas pouvoir
    # partir d'un `-m` tapé de travers.
    parser.add_argument("--yes", action="store_true", help="confirme la consommation de budget")
    args = parser.parse_args()

    configure_logging()

    if not args.yes:
        log.error("sonde non confirmée, rien n'a été tenté", extra={"attempts": args.attempts})
        return 2

    task = os.getenv("CLOUD_RUN_TASK_INDEX", "local")
    avant = remaining_calls_today()

    with futures.ThreadPoolExecutor(max_workers=args.attempts) as pool:
        issues = list(pool.map(_attempt, range(args.attempts)))

    tally = dict(Counter(issues))
    log.info(
        "sonde de concurrence terminée",
        extra={
            "task": task,
            "attempts": args.attempts,
            "issues": tally,
            "restant_avant": avant,
            "restant_apres": remaining_calls_today(),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
