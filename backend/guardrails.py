"""Garde-fou de budget LLM quotidien (cf. docs/cadrage.md §6 et §8 — non négociable).

Le compteur est porté par la couche de persistance (backend/memory/persistence.py) : fichier local
en dev, Firestore en production. La réservation est déléguée au backend plutôt que faite ici en
lecture-modification-écriture, parce que l'atomicité dépend du stockage — avec un disque local elle
est acquise (un seul processus), avec plusieurs instances Cloud Run elle demande une transaction.
Un compteur en mémoire ou en fichier sur Cloud Run se réinitialiserait à chaque cold start, ce qui
rendrait ce plafond contournable par un simple redémarrage.
"""

from collections import Counter
from datetime import UTC, date, datetime

from backend.config import MAX_LLM_CALLS_PER_DAY
from backend.logging_setup import get_logger
from backend.memory.persistence import get_persistence

log = get_logger("guardrails")


class BudgetExceeded(RuntimeError):
    pass


# Répartition des appels du run courant entre les nœuds. Délibérément en mémoire et hors de la
# couche de persistance, contrairement au compteur du plafond : ce n'est pas un garde-fou mais une
# mesure d'exploitation. Elle n'a donc pas besoin de l'atomicité que `reserve_llm_call` exige, et
# l'y porter imposerait de toucher l'interface Persistence et ses deux implémentations — dont
# FirestorePersistence, jamais validée contre une base réelle. Remise à zéro par run_pipeline(),
# seul point d'entrée d'un run : sans cela, deux runs dans le même processus (l'API sert /run sans
# redémarrer) cumuleraient leurs tallies.
#
# Raison d'être (docs/cadrage.md §11) : le budget est un compteur global unique, donc étendre le
# périmètre d'un nœud ne consomme pas des appels « en plus » — cela les retire au nœud suivant.
# Constaté le 2026-08-21, où le vérificateur étendu a fait tomber le plafond sur `thread`, dernier
# de la chaîne. Arbitrer ce partage suppose de le mesurer ; c'est ce que fait ce compteur.
_calls_by_node: Counter[str] = Counter()


def check_and_increment_llm_call(node: str = "unknown") -> None:
    """À appeler avant chaque appel LLM. Lève BudgetExceeded si le plafond quotidien est atteint.

    L'appel n'a pas lieu quand cette exception est levée : elle est déclenchée par le refus de
    réservation, en amont du modèle. L'item sur lequel elle tombe n'a donc rien coûté et reste
    entièrement à traiter — c'est ce qui permet aux nœuds appelants de le rendre à une collecte
    ultérieure plutôt que de le marquer comme vu (cf. backend/agents/analyst.py).
    """
    today = date.today().isoformat()
    if not get_persistence().reserve_llm_call(today, MAX_LLM_CALLS_PER_DAY):
        # Journalisé au point exact du refus, en plus de l'exception : c'est le seul endroit qui
        # sait *quel* nœud demandait l'appel refusé, information perdue dès que l'exception remonte.
        log.warning(
            "réservation d'appel refusée, plafond quotidien atteint",
            extra={"node": node, "plafond": MAX_LLM_CALLS_PER_DAY, "repartition": dict(_calls_by_node)},
        )
        raise BudgetExceeded(
            f"Plafond quotidien d'appels LLM atteint ({MAX_LLM_CALLS_PER_DAY}/jour) "
            f"à {datetime.now(UTC).isoformat()} : appel refusé, run tronqué "
            "(garde-fou non négociable, cf. docs/cadrage.md §6)."
        )
    # Incrémenté après la réservation, jamais avant : un appel refusé n'a rien coûté (cf. docstring
    # ci-dessus), l'imputer à un nœud lui ferait porter une dépense qu'il n'a pas obtenue.
    _calls_by_node[node] += 1


def remaining_calls_today() -> int:
    return MAX_LLM_CALLS_PER_DAY - get_persistence().calls_used(date.today().isoformat())


def calls_by_node() -> dict[str, int]:
    """Répartition des appels du run courant par nœud, dans l'ordre de première dépense."""
    return dict(_calls_by_node)


def reset_call_tally() -> None:
    """À appeler au début d'un run. N'affecte pas le plafond quotidien, qui est persistant."""
    _calls_by_node.clear()
