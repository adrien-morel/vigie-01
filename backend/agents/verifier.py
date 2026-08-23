"""Nœud vérificateur : recoupement et score de confiance (première tranche de docs/cadrage.md §10
V2 — cf. backend/memory/store.py pour l'historique de recoupement). Contrairement à analyze(), ce
nœud a une vraie boucle agentique bornée : le LLM décide lui-même s'il cherche du contexte
supplémentaire avant de conclure.

Ce qui borne le coût a changé le 2026-08-20 : ce n'est plus la catégorie de l'item mais l'existence
d'un antécédent candidat dans l'historique (VERIFIER_GATE_MIN_SCORE). Tout le périmètre MECE est
désormais éligible, et un item dont la fenêtre ne porte rien d'assez proche n'est pas escaladé —
il produirait une non-réponse payée 2 à 3 appels.
"""

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from backend.config import (
    MAX_VERIFIER_ESCALATIONS_PER_RUN,
    MAX_VERIFIER_STEPS_PER_ITEM,
    VERIFIER_CATEGORIES,
    VERIFIER_GATE_MIN_SCORE,
)
from backend.guardrails import BudgetExceeded, check_and_increment_llm_call
from backend.logging_setup import get_logger
from backend.memory.store import has_antecedent, record_analyzed, search_related
from backend.state import AnalyzedItem, VigieState

log = get_logger("verify")

MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """Tu es un vérificateur de veille défense/géopolitique. On te donne un item déjà
classifié et résumé. Ta tâche : évaluer sa fiabilité en cherchant si des items précédents
corroborent ce dossier.

Utilise l'outil search_related_items pour chercher des items déjà analysés sur le même sujet
(entreprises, pays, type de contrat/mouvement mentionnés dans le résumé). Tu peux l'appeler
plusieurs fois avec des requêtes différentes si la première ne donne rien d'utile, mais n'insiste
pas si les résultats ne sont manifestement pas liés.

Une fois ta recherche terminée (ou si tu juges qu'aucune recherche supplémentaire n'aiderait),
conclus avec un score de confiance (0 à 1) et un booléen corroborated :
- corroborated=True si au moins un item précédent traite clairement du même dossier (même contrat,
  même mouvement, mêmes parties) — pas juste le même thème général.
- Le score de confiance reflète ta confiance globale dans le résumé, pas seulement la corroboration :
  un item non corroboré mais dont la citation est claire et non ambiguë peut avoir un score correct
  (ex. 0.6-0.7) ; un item corroboré par plusieurs sources indépendantes mérite un score élevé
  (0.85+) ; un item isolé avec un résumé qui laisse place à interprétation mérite un score plus bas."""


class _VerifierResult(BaseModel):
    confidence_score: float = Field(description="Score de confiance global, entre 0 et 1")
    corroborated: bool = Field(description="Au moins un item précédent traite clairement du même dossier")


def _make_search_tool(exclude_links: set[str]):
    @tool
    def search_related_items(query: str) -> str:
        """Cherche dans l'historique des items déjà analysés (jusqu'à 7 jours) ceux qui pourraient
        corroborer ou apporter du contexte sur le dossier en cours. `query` : mots-clés pertinents
        (ex. noms d'entreprises, de pays, type de contrat)."""
        results = search_related(query, exclude_links=exclude_links, limit=5)
        if not results:
            return "Aucun item correspondant trouvé dans l'historique."
        return "\n".join(
            f"- [{r['date']}] {r['country']}/{r['category']} : {r['title_fr']} (source : {r['source']})"
            for r in results
        )

    return search_related_items


def _verify_item(item: AnalyzedItem, exclude_links: set[str]) -> tuple[float, bool]:
    """Boucle agentique bornée par MAX_VERIFIER_STEPS_PER_ITEM. Chaque appel LLM (décision d'outil
    ou conclusion) passe par check_and_increment_llm_call() — le plafond quotidien existant
    (MAX_LLM_CALLS_PER_DAY) absorbe donc aussi ce nœud sans garde-fou séparé."""
    search_tool = _make_search_tool(exclude_links)
    llm = ChatAnthropic(model=MODEL, temperature=0).bind_tools([search_tool])

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"Catégorie : {item['category']}\n"
                f"Résumé : {item['summary']}\n"
                f"Citation : {item['citation']}\n"
                f"Pays/lieu : {item['location']}"
            )
        ),
    ]

    for _ in range(MAX_VERIFIER_STEPS_PER_ITEM):
        check_and_increment_llm_call("verify")
        response = llm.invoke(messages)
        if not response.tool_calls:
            break
        messages.append(response)
        for call in response.tool_calls:
            result = search_tool.invoke(call["args"])
            messages.append(ToolMessage(content=result, tool_call_id=call["id"]))

    check_and_increment_llm_call("verify")
    concluder = ChatAnthropic(model=MODEL, temperature=0).with_structured_output(_VerifierResult)
    messages.append(HumanMessage(content="Conclus maintenant avec ton score de confiance et corroborated."))
    conclusion = concluder.invoke(messages)
    return conclusion.confidence_score, conclusion.corroborated


def verify(state: VigieState) -> VigieState:
    """Nœud LangGraph : ajoute confidence_score/corroborated aux items que le portillon retient,
    plafonné à MAX_VERIFIER_ESCALATIONS_PER_RUN par run. Les autres gardent
    confidence_score/corroborated à None — pas de score fabriqué sans base réelle.

    Le portillon (store.has_antecedent, seuil VERIFIER_GATE_MIN_SCORE) est calculé pour tout le lot
    en une lecture d'historique, avant la boucle : un item n'est escaladé que si la fenêtre porte un
    antécédent dont le chevauchement pondéré IDF atteint le seuil. Il remplace la restriction par
    catégorie qui tenait ce rôle jusqu'au 2026-08-20 — laquelle bornait le coût en refusant de
    regarder quatre catégories sur cinq, pas en distinguant les items vérifiables des autres.

    Son résultat est écrit sur chaque item (has_antecedent_candidate), escaladé ou non. Sans lui,
    deux silences très différents seraient indistinguables à l'affichage : « l'historique ne portait
    rien à recouper », qui est une mesure, et « le plafond du run ou le budget a coupé avant », qui
    est une absence de mesure.

    L'historique est écrit deux fois, et c'est voulu. Une première fois avant l'escalade : ce nœud
    fait des appels réseau, et une panne à mi-parcours ne doit pas faire perdre des items déjà
    analysés et payés. Une seconde fois après, pour que l'historique porte les items tels qu'ils
    seront affichés, scores compris — il alimente aussi le digest servi par l'API
    (cf. store.load_digest). L'écriture est un upsert par lien qui préserve la date de première
    vue : la seconde passe met à jour, elle ne duplique pas.

    L'invariant « search_related_items ne voit jamais le run en cours, seulement l'historique des
    runs précédents » ne repose donc pas sur l'ordre d'écriture mais sur `exclude_links`, qui porte
    tous les liens du lot — deux items du même run ne se corroborent pas mutuellement.

    Si le plafond quotidien tombe pendant l'escalade, la vérification s'arrête là mais le nœud va
    jusqu'au bout : les items restants sont conservés tels quels, `confidence_score`/`corroborated`
    à None, et l'historique est écrit comme d'habitude. Un item analysé et payé ne doit pas être
    perdu parce que sa vérification, elle, n'a pas pu être financée.
    """
    current_links = {item["link"] for item in state["analyzed_items"]}
    record_analyzed(state["analyzed_items"])

    gate = has_antecedent(
        {item["link"]: f"{item['title_fr']} {item['summary']}" for item in state["analyzed_items"]},
        exclude_links=current_links,
        min_score=VERIFIER_GATE_MIN_SCORE,
    )

    escalated = 0
    budget_exhausted = False
    updated_items: list[AnalyzedItem] = []
    for original in state["analyzed_items"]:
        item: AnalyzedItem = {**original, "has_antecedent_candidate": gate[original["link"]]}
        escalatable = (
            not budget_exhausted
            and item["category"] in VERIFIER_CATEGORIES
            and gate[item["link"]]
            and escalated < MAX_VERIFIER_ESCALATIONS_PER_RUN
        )
        if not escalatable:
            updated_items.append(item)
            continue

        escalated += 1
        try:
            confidence_score, corroborated = _verify_item(item, current_links)
        except BudgetExceeded:
            # Plus rien à financer : cet item et tous les suivants restent non vérifiés. C'est
            # exactement l'état « hors périmètre du vérificateur » que porte déjà None, et que la
            # restitution rend comme tel — pas de score fabriqué pour combler le vide.
            budget_exhausted = True
            updated_items.append(item)
            continue
        updated_items.append({**item, "confidence_score": confidence_score, "corroborated": corroborated})

    record_analyzed(updated_items)

    # `eligibles` compte le portillon franchi, `escalades` ce que le plafond du run a laissé passer :
    # l'écart entre les deux est exactement la mesure perdue, et c'est ce que le plan de mise en
    # production demande de rendre visible sous Scheduler (aujourd'hui, une troncature ne laisse
    # aucune trace exploitable hors du corps de la réponse HTTP).
    eligibles = sum(1 for i in updated_items if gate[i["link"]] and i["category"] in VERIFIER_CATEGORIES)
    if budget_exhausted:
        log.warning("vérification tronquée par le plafond quotidien", extra={"escalades": escalated})
    if escalated >= MAX_VERIFIER_ESCALATIONS_PER_RUN:
        log.warning(
            "plafond d'escalades du run atteint",
            extra={"plafond": MAX_VERIFIER_ESCALATIONS_PER_RUN, "eligibles": eligibles},
        )
    log.info(
        "vérification terminée",
        extra={
            "items": len(updated_items),
            "eligibles": eligibles,
            "escalades": escalated,
            "avec_antecedent": sum(1 for i in updated_items if i.get("corroborated")),
            "sans_antecedent": sum(1 for i in updated_items if i.get("corroborated") is False),
            "budget_epuise": budget_exhausted,
        },
    )
    return {"analyzed_items": updated_items, "truncated": state.get("truncated", False) or budget_exhausted}
