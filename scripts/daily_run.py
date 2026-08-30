"""Lancement quotidien du pipeline pendant la campagne d'accumulation d'historique.

**Intention.** L'arbitrage sur l'extension du vérificateur (docs/cadrage.md §10, V2) et la première
tranche de la V3 (fils d'événements) dépendent tous deux d'une question qu'on ne sait pas encore
trancher : combien d'items ont réellement un voisin portant sur le même dossier ? La mesure a été
tentée sur 3 jours d'historique (`python -m backend.eval.candidates`) et a conclu que l'assiette
était trop mince — 2 à 4 appariements réels sur 102 items, trop peu pour calibrer ou valider un
seuil. Deux dépêches sur le même dossier à 48 h d'écart sont rares par construction. Il faut donc
une quinzaine de jours d'historique continu avant de rejouer la mesure et de décider.

Ce script est l'outil de cette campagne : un lancement par jour, à la main, jusqu'à ce que
l'assiette soit suffisante. Il n'a pas vocation à survivre à la campagne — en production, le
déclenchement passe par Cloud Scheduler → Cloud Run (cf. backend/api/main.py).

**Clôture (2026-08-20).** La campagne s'arrête à cinq lancements et sept jours d'historique continu
(2026-08-14 → 2026-08-20, 261 items), sous l'assiette de quinze jours visée ci-dessus — décision
explicite de passer à l'évaluation, la rétention ayant été ramenée le même jour à 7 jours
(`RELATED_ITEMS_WINDOW_DAYS`, cf. backend/memory/store.py) pour limiter le coût de stockage.
L'historique glissant ne peut donc plus dépasser cette profondeur : l'assiette de quinze jours est
désormais inatteignable par construction, et non seulement repoussée.

**La mesure a néanmoins été prise, sur sept jours.** Rejouée le 2026-08-20 sur les 261 items
(`python -m backend.eval.candidates`), elle donne un signal que les 102 items de trois jours ne
donnaient pas : au seuil pondéré IDF ≥ 40, 8 items sur 261 (3,1 %) seraient escaladés, et la lecture
manuelle des meilleures paires y trouve une majorité de vrais appariements de dossier là où la
mesure précédente n'en trouvait que 2 à 4 sur l'échantillon entier. La conclusion « assiette trop
mince » ne tient donc plus à cette taille — mais un seuil ne se pose pas sur une lecture à l'œil de
huit paires. La calibration proprement dite passe par `backend/eval/build_pairs.py`, qui gèle un
échantillon de paires stratifié par bande de score : c'est lui qui porte désormais la décision, et
il a dû être construit ce jour-là précisément parce que la purge à 7 jours efface le corpus mesuré.

Le script reste utilisable pour un lancement ponctuel, mais n'est plus piloté vers l'objectif initial.

**Pourquoi un journal, et pourquoi il ne se déduit pas de l'historique analysé.** Un jour sans item
neuf (tout écarté par le dédoublonnage) et un jour où le lancement a été oublié laissent exactement
la même trace dans `.analyzed_history.json` : aucune. Le premier est une mesure — le flux n'a rien
publié de neuf dans le périmètre —, le second est un trou. Les confondre fausserait la relecture de
la campagne au moment de décider : un historique clairsemé parce que le corpus est pauvre n'appelle
pas la même conclusion qu'un historique clairsemé parce que l'opérateur a sauté quatre jours. Le
journal enregistre donc *tout lancement*, y compris ceux qui ne produisent rien et ceux qui échouent.

**Fenêtre de collecte et trous irrécupérables.** `COLLECTION_LOOKBACK_HOURS` (96 h depuis le
2026-08-17 ; 48 h à l'origine, relevé une fois le coût couvert par un plafond par source plutôt
que par le temps — cf. backend/config.py) borne ce qu'une collecte peut rattraper. Un jour sauté
est donc récupéré par le lancement suivant ; des jours consécutifs sautés au-delà de cette fenêtre
perdent définitivement les items publiés dans l'intervalle non couvert. Le script mesure l'écart
depuis le dernier lancement journalisé et le signale — l'information n'est utile qu'au moment où
elle est constatée, et elle doit rester attachée au run dans le journal.

**Pourquoi le journal ne passe pas par backend/memory/persistence.py.** L'invariant du projet
(CLAUDE.md) est que tout *état métier* survivant à un run passe par la couche de persistance. Ce
journal n'est pas de l'état métier : il ne décrit pas le produit mais l'exploitation qu'on en fait,
il n'est lu par aucun nœud du pipeline, il ne part pas en production, et il doit rester lisible même
si la persistance est justement ce qui a échoué. Un fichier local assumé, hors de l'abstraction.

Usage :
    python -m scripts.daily_run              # le lancement quotidien
    python -m scripts.daily_run --dry-run    # état de la campagne, sans lancer le pipeline
"""

import argparse
import json
import sys
import time
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from backend.agents.analyst import submissions_by_source
from backend.agents.collector import source_freshness
from backend.config import (
    COLLECTION_LOOKBACK_HOURS,
    MAX_ITEMS_PER_SOURCE_PER_RUN,
    MAX_LLM_CALLS_PER_DAY,
    SOURCES,
)
from backend.graph import run_pipeline
from backend.guardrails import calls_by_node, remaining_calls_today
from backend.memory.persistence import get_persistence
from backend.memory.store import RELATED_ITEMS_WINDOW_DAYS

# JSONL plutôt que JSON : un lancement n'a qu'à ajouter une ligne, sans relire ni réécrire le
# fichier — un plantage en cours d'écriture ne peut pas corrompre les lancements déjà journalisés.
LOG_FILE = Path(__file__).resolve().parent / ".run_log.jsonl"


def _s(count: int) -> str:
    """Marque du pluriel — l'interface du produit est en français, ses sorties d'exploitation aussi."""
    return "s" if count > 1 else ""


def _read_log() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    entries = []
    for line in LOG_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def _append_log(entry: dict) -> None:
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _history_shape() -> tuple[int, dict[str, int]]:
    """Taille et répartition par jour de l'historique analysé, dans la fenêtre de rétention.

    Lu par la couche de persistance, comme backend/eval/candidates.py : la campagne doit se relire
    à l'identique si le stockage passe sur Firestore.
    """
    cutoff = (date.today() - timedelta(days=RELATED_ITEMS_WINDOW_DAYS)).isoformat()
    records = get_persistence().analyzed_since(cutoff)
    return len(records), dict(sorted(Counter(r.get("date", "?") for r in records).items()))


def _hours_since_last(entries: list[dict]) -> float | None:
    for entry in reversed(entries):
        started = entry.get("started_at")
        if started:
            return (datetime.now(UTC) - datetime.fromisoformat(started)).total_seconds() / 3600
    return None


def _print_campaign(entries: list[dict]) -> None:
    if not entries:
        print("\nCampagne : aucun lancement journalisé pour l'instant.")
        return
    days = {e["started_at"][:10] for e in entries if e.get("started_at")}
    failed = sum(1 for e in entries if e.get("error"))
    truncated = sum(1 for e in entries if e.get("truncated"))
    holes = sum(1 for e in entries if e.get("lookback_exceeded"))
    first = min(days) if days else "?"
    print(
        f"\nCampagne depuis le {first} : {len(entries)} lancement{_s(len(entries))} "
        f"sur {len(days)} jour{_s(len(days))} distinct{_s(len(days))} — "
        f"échecs : {failed}, tronqués par le budget : {truncated}, "
        f"trous au-delà de {COLLECTION_LOOKBACK_HOURS} h : {holes}."
    )
    print(f"Journal : {LOG_FILE}")


def main(dry_run: bool) -> int:
    entries = _read_log()
    gap_hours = _hours_since_last(entries)
    remaining_before = remaining_calls_today()
    history_before, by_date_before = _history_shape()

    print(f"Budget : {remaining_before}/{MAX_LLM_CALLS_PER_DAY} appels restants aujourd'hui.")
    print(
        f"Historique : {history_before} item{_s(history_before)} "
        f"sur {len(by_date_before)} jour{_s(len(by_date_before))} — {by_date_before}"
    )

    # « Active » veut dire « a produit un item récent », pas « le flux se parse sans erreur » —
    # un flux mort (OFAC, ~1 an sans nouvelle entrée avant d'être détecté par ce constat) passait
    # inaperçu du KPI de couverture (docs/cadrage.md §7) tant que le test était le second. Lecture
    # RSS seule, aucun coût de budget.
    freshness = source_freshness()
    # Trois états, pas deux : `None` signale un flux injoignable, que compter comme silencieux
    # ferait passer une panne réseau pour un flux mort — exactement l'inverse du diagnostic OFAC.
    unavailable = sorted(name for name, count in freshness.items() if count is None)
    silent = sorted(name for name, count in freshness.items() if count == 0)
    active_count = len(SOURCES) - len(silent) - len(unavailable)
    print(f"Couverture : {active_count}/{len(SOURCES)} sources actives dans les {COLLECTION_LOOKBACK_HOURS} h.")
    if silent:
        print(f"  Silencieuse{_s(len(silent))} : {', '.join(silent)}")
    if unavailable:
        print(f"  Injoignable{_s(len(unavailable))} : {', '.join(unavailable)}")

    # Contrepartie du plafond par source, à journaliser parce qu'elle est invisible partout ailleurs :
    # `source_freshness()` mesure le volume *avant* plafonnage, la collecte n'en garde que les plus
    # récents, et rien dans l'historique analysé ne distingue ensuite « la source n'a rien publié »
    # de « on a écarté sa queue de flux ». Sans ce chiffre, le KPI de couverture (§7) surestime ce
    # que la campagne a réellement vu, et l'assiette de l'évaluation à venir n'est pas
    # interprétable — même raison d'être que le journal des lancements lui-même.
    dropped = {
        source.name: freshness[source.name] - (source.max_per_run or MAX_ITEMS_PER_SOURCE_PER_RUN)
        for source in SOURCES
        if freshness[source.name] is not None
        and freshness[source.name] > (source.max_per_run or MAX_ITEMS_PER_SOURCE_PER_RUN)
    }
    if dropped:
        total = sum(dropped.values())
        detail = ", ".join(f"{name} (-{count})" for name, count in sorted(dropped.items(), key=lambda p: -p[1]))
        print(f"  Écartés par le plafond par source : {total} item{_s(total)} sur {len(dropped)} flux — {detail}")

    if gap_hours is None:
        print("Aucun lancement journalisé auparavant : début de campagne.")
    else:
        print(f"Dernier lancement il y a {gap_hours:.1f} h.")
        if gap_hours > COLLECTION_LOOKBACK_HOURS:
            print(
                f"  /!\\ Au-delà de la fenêtre de collecte ({COLLECTION_LOOKBACK_HOURS} h) : les items "
                "publiés dans l'intervalle non couvert sont définitivement perdus. Trou à retenir en "
                "relisant la campagne — l'historique seul ne le montrera pas."
            )

    # ~110 items/jour à ~1 appel chacun : sous ce seuil le run sera tronqué. Ce n'est pas une erreur
    # (le run reste un succès partiel, cf. docs/cadrage.md §8) mais ça se sait avant, pas après.
    if remaining_before < 110:
        print("  Budget insuffisant pour un lot complet : le run sera probablement tronqué.")

    if dry_run:
        print("\n--dry-run : pipeline non lancé.")
        _print_campaign(entries)
        return 0

    started = datetime.now(UTC)
    clock = time.monotonic()
    analyzed, truncated, error = 0, False, None
    by_node: dict[str, int] = {}
    by_source: dict[str, dict[str, int]] = {}
    try:
        result = run_pipeline()
        analyzed = len(result["analyzed_items"])
        truncated = result["truncated"]
        # Relevé après le run, avant tout autre appel : c'est la répartition de *ce* run entre les
        # nœuds. Sans elle, on sait qu'un plafond global a tronqué le lot mais pas lequel des nœuds
        # a consommé quoi — l'arbitrage du partage restait donc impossible (docs/cadrage.md §11).
        by_node = calls_by_node()
        # Le pendant du précédent côté `analyze` : la répartition par nœud dit *combien* ce nœud a
        # dépensé, celle-ci dit sur *quoi*. Les deux sont nécessaires — un `analyze` cher parce que
        # le lot est gros et un `analyze` cher parce qu'un flux remplit le lot d'items hors sujet
        # n'appellent pas le même arbitrage de budget.
        by_source = submissions_by_source()
    except Exception as exc:  # noqa: BLE001 — voir ci-dessous
        # Rattrapage volontairement large : un échec non journalisé est précisément le trou que ce
        # journal existe pour éviter. L'exception est enregistrée puis rendue par le code de sortie.
        error = f"{type(exc).__name__}: {exc}"

    duration = time.monotonic() - clock
    remaining_after = remaining_calls_today()
    history_after, by_date_after = _history_shape()

    # Le compteur de budget est quotidien : un run à cheval sur minuit repart du plafond plein et la
    # différence n'a plus de sens. Ne rien affirmer vaut mieux qu'un chiffre faux.
    consumed = remaining_before - remaining_after
    llm_calls = consumed if consumed >= 0 else None

    entry = {
        "started_at": started.isoformat(),
        "duration_s": round(duration, 1),
        "analyzed": analyzed,
        "truncated": truncated,
        "llm_calls": llm_calls,
        "llm_calls_by_node": by_node,
        "analyze_by_source": by_source,
        "history_before": history_before,
        "history_after": history_after,
        "history_by_date": by_date_after,
        "gap_hours": round(gap_hours, 1) if gap_hours is not None else None,
        "lookback_exceeded": gap_hours is not None and gap_hours > COLLECTION_LOOKBACK_HOURS,
        "sources_active": active_count,
        "sources_targeted": len(SOURCES),
        "sources_silent": silent,
        "sources_unavailable": unavailable,
        "error": error,
    }
    _append_log(entry)

    print()
    if error:
        print(f"ÉCHEC après {duration:.0f} s : {error}")
    else:
        print(
            f"Run terminé en {duration:.0f} s — {analyzed} item{_s(analyzed)} retenu{_s(analyzed)}"
            f"{', run tronqué par le budget' if truncated else ''}."
        )
    print(
        f"Historique : {history_before} → {history_after} item{_s(history_after)} "
        f"sur {len(by_date_after)} jour{_s(len(by_date_after))}."
    )
    print(f"Appels LLM consommés : {llm_calls if llm_calls is not None else 'indéterminé (jour changé)'}.")
    if by_node:
        # Le total par nœud peut être inférieur à `llm_calls` si un autre processus a consommé du
        # budget pendant le run : les deux chiffres ne mesurent pas la même chose (ce run vs. le
        # jour), et les réconcilier de force masquerait précisément ce cas.
        detail = ", ".join(f"{node} {count}" for node, count in sorted(by_node.items(), key=lambda p: -p[1]))
        print(f"  Répartition par nœud : {detail} (total {sum(by_node.values())}).")
    if by_source:
        outcomes = Counter()
        for tally in by_source.values():
            outcomes.update(tally)
        submitted = sum(outcomes.values())
        wasted = submitted - outcomes.get("retenu", 0)
        share = f"{100 * wasted / submitted:.0f} %" if submitted else "—"
        print(
            f"  Soumis à l'analyse : {submitted} item{_s(submitted)} pour {outcomes.get('retenu', 0)} "
            f"retenu{_s(outcomes.get('retenu', 0))} — {wasted} appel{_s(wasted)} ({share}) sur des items écartés."
        )
        motifs = ", ".join(
            f"{name} {count}" for name, count in sorted(outcomes.items(), key=lambda p: -p[1]) if name != "retenu"
        )
        if motifs:
            print(f"    Motifs : {motifs}")
        # Les cinq premiers seulement : la ventilation complète part au journal, cette ligne n'est là
        # que pour voir tout de suite si la dépense écartée est concentrée ou diffuse.
        worst = sorted(
            ((source, sum(t.values()) - t.get("retenu", 0)) for source, t in by_source.items()),
            key=lambda p: -p[1],
        )[:5]
        detail = ", ".join(f"{source} (-{count})" for source, count in worst if count)
        if detail:
            print(f"    Plus gros contributeurs : {detail}")
    _print_campaign(entries + [entry])

    return 1 if error else 0


if __name__ == "__main__":
    # La console Windows par défaut (cp1252) n'a pas « → » ; le journal et les sorties d'exploitation
    # sont en français avec ce genre de caractère, pas question de les appauvrir pour ce seul terminal.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="affiche l'état de la campagne et sort, sans lancer le pipeline ni consommer de budget",
    )
    args = parser.parse_args()
    raise SystemExit(main(args.dry_run))
