"""Assemble le pipeline en StateGraph LangGraph : collect → deduplicate → analyze → verify → thread
(README §architecture).

deduplicate est placé avant analyze, pas après (cf. backend/memory/store.py) : filtrer les items déjà
vus avant l'appel LLM plutôt qu'après évite de payer un appel pour ré-analyser un item déjà traité.

verify (backend/agents/verifier.py) est la première tranche de docs/cadrage.md §10 V2 : recoupement
et score de confiance pour les items à catégorie sensible (VERIFIER_CATEGORIES), avec sa propre
boucle agentique bornée à l'intérieur du nœud.

thread (backend/agents/threader.py) est la première tranche de docs/cadrage.md §10 V3 : regroupement
en fils chronologiques, placé après verify pour que sa fenêtre d'historique voie déjà les items du
run courant (verify les a écrits), avec sa propre boucle agentique bornée elle aussi.
"""

import time

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from backend.agents.analyst import analyze, reset_submission_tally, submissions_by_source
from backend.agents.collector import collect
from backend.agents.threader import thread_events
from backend.agents.verifier import verify
from backend.config import MAX_STEPS_PER_RUN
from backend.guardrails import calls_by_node, reset_call_tally
from backend.logging_setup import configure_logging, get_logger
from backend.memory.store import deduplicate
from backend.state import VigieState

log = get_logger("run")


def build_graph() -> CompiledStateGraph:
    builder = StateGraph(VigieState)
    builder.add_node("collect", collect)
    builder.add_node("analyze", analyze)
    builder.add_node("deduplicate", deduplicate)
    builder.add_node("verify", verify)
    builder.add_node("thread", thread_events)

    builder.add_edge(START, "collect")
    builder.add_edge("collect", "deduplicate")
    builder.add_edge("deduplicate", "analyze")
    builder.add_edge("analyze", "verify")
    builder.add_edge("verify", "thread")
    builder.add_edge("thread", END)

    return builder.compile()


def run_pipeline() -> VigieState:
    """Lève langgraph.errors.GraphRecursionError si MAX_STEPS_PER_RUN est dépassé
    (garde-fou §8 "boucle d'agent incontrôlée", non négociable — cf. docs/cadrage.md).
    """
    # Idempotent : un run lancé par l'API trouve la journalisation déjà installée, un run lancé
    # en ligne de commande (scripts/, python -c) l'installe ici.
    configure_logging()
    # Le tally par nœud est une mesure du run, pas du jour : le remettre à zéro ici, seul point
    # d'entrée d'un run, évite que deux runs servis par le même processus (l'API ne redémarre pas
    # entre deux POST /run) cumulent leurs répartitions. Sans effet sur le plafond quotidien, qui
    # est persistant et n'a surtout pas à être remis à zéro par un run.
    reset_call_tally()
    # Même portée et même raison que le tally d'appels ci-dessus : ce que `analyze` a soumis relève
    # de *ce* run, pas de la journée (cf. backend/agents/analyst.py).
    reset_submission_tally()
    graph = build_graph()
    started = time.monotonic()
    log.info("run démarré")
    try:
        result = graph.invoke(
            {"raw_items": [], "analyzed_items": [], "truncated": False},
            config={"recursion_limit": MAX_STEPS_PER_RUN},
        )
    except Exception:
        # Journalisé puis relancé : sous Cloud Scheduler, l'exception n'est visible nulle part
        # ailleurs — le corps de la réponse HTTP n'est pas lu par l'ordonnanceur.
        log.exception("run interrompu par une erreur", extra={"duree_s": round(time.monotonic() - started, 1)})
        raise

    # Les deux mesures d'exploitation sortaient jusqu'ici par scripts/daily_run.py seul, qui est un
    # outil d'opérateur et ne part pas en production (Cloud Scheduler le remplace). Les émettre ici
    # est ce qui les rend disponibles en cloud, où elles sont la seule façon de savoir comment les
    # 200 appels du jour se sont répartis.
    log.info(
        "run terminé",
        extra={
            "duree_s": round(time.monotonic() - started, 1),
            "items": len(result["analyzed_items"]),
            "truncated": result["truncated"],
            "llm_calls_by_node": calls_by_node(),
            "llm_calls_total": sum(calls_by_node().values()),
            "analyze_by_source": submissions_by_source(),
        },
    )
    return result
