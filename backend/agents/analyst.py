"""Nœud analyste : classification + résumé tracé (cf. docs/cadrage.md §2 et §8)."""

import difflib
import html
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import get_args

from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel, Field, ValidationError

from backend.guardrails import BudgetExceeded, check_and_increment_llm_call
from backend.logging_setup import get_logger
from backend.memory.store import mark_analyzed_as_seen
from backend.state import AnalyzedItem, Category, RawItem, VigieState

log = get_logger("analyze")

MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """Tu es un analyste de veille défense/géopolitique. Pour l'article fourni :
1. Classe-le dans une des catégories : export_control, contrat_armement, mouvement_militaire,
   diplomatie_defense, programme_industriel, ou hors_perimetre si l'article ne relève d'aucune
   de ces catégories (ex. actualité technologique générale, cybersécurité, analyse financière).
   Le filtrage est thématique uniquement — la localisation géographique de l'article n'entre pas
   en compte dans ce choix. Ces six identifiants sont un vocabulaire fermé, écrit exactement comme
   ci-dessus : ne les traduis jamais, ne les fléchis jamais dans la langue de l'article — même
   pour un article en espagnol, en allemand, en italien ou en français, réponds `diplomatie_defense`
   et non `diplomacia_defense` ou toute autre variante. Précisions de frontière :
   - Fusion-acquisition ou prise de participation dans l'industrie de défense : classe en
     programme_industriel si l'article porte sur l'opération elle-même (parties, montant, enjeu
     stratégique) ; en export_control seulement si l'article traite explicitement d'une licence,
     sanction ou embargo ; en hors_perimetre si l'article est centré sur l'analyse boursière (cours,
     réaction de marché) plutôt que sur l'opération.
   - Contenu d'opinion, tribune ou analyse prospective qui ne rapporte pas un fait ou événement daté
     et vérifiable : classe en hors_perimetre même si le thème correspond au périmètre. Un article
     qui rapporte un fait daté puis l'accompagne d'analyse reste inclus ; une simple prise de
     position n'est pas incluse.
   - diplomatie_defense vs mouvement_militaire : ce qui départage n'est pas la forme de l'acte
     rapporté mais son contenu. Un fait opérationnel accompli ou un état de fait établi (une force
     est déployée, un détroit est fermé ou sous contrôle, une frappe a eu lieu, un espace aérien est
     fermé) relève de mouvement_militaire — y compris, et surtout, quand il est rapporté par une
     déclaration ou un communiqué officiel : la déclaration n'est alors que la source qui établit le
     fait, elle n'est pas le sujet de l'article. Ne classe en diplomatie_defense que si ce qui est
     déclaré est une intention, une menace, une capacité revendiquée, une posture, une position de
     principe (ce qu'un État fera, pourrait faire, ou juge inacceptable) ou la coopération défense
     entre États — ainsi que le commentaire sur un déploiement, par opposition au déploiement
     lui-même. Un commandant déclarant qu'un détroit est fermé et sous son contrôle rapporte un fait
     accompli (mouvement_militaire) ; le même menaçant de le fermer énonce une intention
     (diplomatie_defense). Un exercice ou entraînement militaire conjoint déjà engagé (troupes
     déployées, manœuvres en cours) relève de mouvement_militaire même si le texte le qualifie en
     vocabulaire de coopération ou d'interopérabilité (renforcer l'interopérabilité, approfondir la
     coopération) : ce vocabulaire caractérise la nature de l'exercice en cours, ce n'est pas une
     annonce de coopération distincte du fait accompli qu'il accompagne. Ne bascule en
     diplomatie_defense que si aucun exercice concret n'est encore engagé à la date de l'article —
     un accord, un partenariat ou une intention de coopérer à venir, sans manœuvre en cours.
   - diplomatie_defense vs hors_perimetre : une déclaration ou un communiqué officiel attribué à un
     responsable nommé ET EN FONCTION (ou officiellement mandaté), sur la coopération, les alliances
     ou la posture défense/sécurité entre États, est un fait daté (pas une tribune) — ne classe pas
     en hors_perimetre au seul motif qu'aucun contrat ni mouvement n'est décrit. À l'inverse, une
     visite d'État, un message protocolaire ou une pression diplomatique générale (droits humains,
     politique intérieure d'un pays tiers) sans contenu défense/sécurité explicite reste
     hors_perimetre même si les deux pays ont par ailleurs une relation de défense. Le propos d'un
     ancien responsable — officier général à la retraite, ancien ministre — n'engage aucun État :
     classe-le en hors_perimetre comme une prise de position, pas en diplomatie_defense, quelle que
     soit la notoriété de la voix.
   - export_control est définie par l'instrument juridique, pas par l'effet économique : licence,
     sanction, embargo. Un droit de douane, une barrière tarifaire ou une mesure de politique
     commerciale générale n'en sont pas, même lorsqu'ils visent des composants à usage militaire —
     classe en hors_perimetre, sauf si la mesure prend la forme d'une licence, d'une sanction ou
     d'un embargo.
   - Aérospatiale, spatial et technologies civiles : n'entrent au périmètre que si l'article les
     rattache explicitement à une application de défense, à un client de défense, ou à une
     coopération industrielle impliquant un groupe de défense. Une avionique développée avec la
     filiale d'un groupe de défense relève de programme_industriel ; un lancement commercial de
     satellite par une société privée, sans lien de défense énoncé, reste hors_perimetre. Le
     critère est le lien de défense écrit dans l'article, pas la dualité supposée de la technologie.
   - programme_industriel vs les trois autres catégories : ce qui définit programme_industriel est
     le stade de constitution d'une capacité — développement, étude ou consultation préalable à un
     achat, cible de structure de forces, coopération industrielle entre programmes, remise en état
     ou modernisation d'un équipement existant — quel que soit l'acteur qui la porte (une armée, un
     ministère, deux États conjointement). Classe d'après l'objet de l'article — une capacité en
     construction — jamais d'après l'acteur visible : une demande d'informations préalable à un
     achat émise par une marine reste programme_industriel, pas mouvement_militaire, et une
     coopération industrielle entre deux États reste programme_industriel, pas diplomatie_defense.
     Distinction avec contrat_armement, à trancher dans cet ordre. D'abord : l'article rapporte-t-il
     un acte commercial ou budgétaire ? attribution ou notification d'un marché, commande passée,
     accord-cadre conclu, décision d'acquisition d'un gouvernement, ou l'argent qui la porte —
     crédits votés, demandés au parlement ou débloqués, rallonge ou crédit supplémentaire, acomptes
     versés pour sécuriser des délais de livraison. Si oui, la catégorie est contrat_armement, y
     compris quand l'article justifie cet acte par des délais de livraison, un calendrier de
     programme ou une capacité à constituer : le motif invoqué ne déplace pas la catégorie, c'est
     l'acte rapporté qui la fixe. Seulement si ce premier test échoue : tout ce qui relève de la
     fabrication et de la vie de la capacité — développement, construction, mise à l'eau ou sortie
     d'usine, livraison, entrée en service, essais de qualification, modernisation, maintien en
     condition — relève de programme_industriel, y compris quand le client militaire est nommé et
     que l'article emploie le vocabulaire de la commande. Un industriel qui livre un premier
     exemplaire à une armée rapporte un jalon de programme (programme_industriel) ; le même
     industriel remportant le marché rapporte une transaction (contrat_armement). Ce qui précède la
     transaction — demande d'informations, consultation, étude préalable — reste
     programme_industriel. Distinction avec mouvement_militaire : l'emploi
     opérationnel d'une capacité déjà existante (déploiement, exercice, frappe) n'est pas sa
     constitution. Distinction avec diplomatie_defense : dès qu'un programme, un équipement ou une
     force conjointe nommés sont en cours de constitution, la catégorie est programme_industriel
     même si l'article rapporte l'annonce par la voie d'une déclaration officielle — une force
     multinationale en cours de constitution (ex. une task force conjointe) relève de
     programme_industriel, pas de diplomatie_defense, tant qu'elle se constitue.
2. Traduis le titre en français (title_fr), fidèlement, même si le titre original est déjà en français.
3. Rédige un résumé factuel en français, 2-3 phrases maximum, sans interprétation ni spéculation.
4. Fournis une citation : un extrait VERBATIM du texte source, dans sa langue d'origine (copié-collé
   exact, jamais traduit) qui justifie le résumé. Si aucun extrait ne justifie clairement le résumé,
   catégorise en hors_perimetre et laisse la citation vide.
5. Fournis location : le THÉÂTRE de l'événement — le pays, la mer ou la région où les faits se
   déroulent — extrait VERBATIM du titre ou du texte source. Ce n'est pas le pays de l'acteur :
   « Iran plante Angriffe auf Militärziele in Europa » a pour théâtre « Europa », l'Iran étant
   l'acteur (question 7). Privilégie le nom de pays quand il est écrit tel quel.
   Laisse vide si aucun lieu n'est explicitement nommé — ne déduis jamais un lieu qui n'est pas
   écrit noir sur blanc, et ne transforme pas un gentilé en nom de pays (« Ukrainian » n'autorise
   pas « Ukraine » si le mot « Ukraine » n'apparaît nulle part).
   En revanche une forme FLÉCHIE du nom de pays reste le nom de pays, et doit être extraite telle
   qu'elle est écrite : l'allemand « Dänemarks Verteidigung » donne location = « Dänemarks »,
   le russe « Германии » donne « Германии ». C'est le mot du pays, décliné par la grammaire — pas
   un gentilé, qui lui désigne les habitants ou l'origine (« dänische », « ukrainien »).
6. Fournis location_country : le pays souverain dans lequel se trouve le lieu de location, en
   ANGLAIS et sous sa forme usuelle (« Australia », « Ukraine », « United States of America »).
   Contrairement aux champs précédents ce n'est PAS un extrait du texte : c'est la seule déduction
   autorisée, et elle ne sert qu'à placer l'item sur une carte par pays. « Darwin » donne
   « Australia », « Kharkiv » donne « Ukraine ». Laisse vide dans ces quatre cas :
   - location est vide (rien à rattacher) ;
   - le lieu n'appartient à aucun pays : haute mer, détroit international, espace, région
     transnationale (« Sahel », « Balkans »), organisation ou unité militaire ;
   - le lieu est dans plusieurs pays sans qu'un seul domine ;
   - la souveraineté du lieu est contestée ou ferait l'objet d'un désaccord entre États.
   Un champ vide est toujours préférable à un rattachement arbitré.
7. Fournis actor : le PROTAGONISTE principal de l'événement — l'État, le gouvernement, la force
   armée, le groupe armé, l'industriel ou le responsable politique qui agit — extrait VERBATIM du
   titre ou du texte source. « Houthis attack eight Saudi oil tankers » donne « Houthis » ;
   « Iran plante Angriffe » donne « Iran ». Contrairement à location, un gentilé est ici accepté
   s'il désigne l'acteur (« Iranian control » donne « Iranian »), puisque c'est l'acteur qui est
   demandé, pas un lieu. Laisse vide si l'article ne nomme aucun protagoniste, ou si le
   protagoniste est l'organisation internationale elle-même (ONU, OTAN, UE).
8. Fournis actor_country : le pays souverain auquel se rattache actor, en ANGLAIS et sous sa forme
   usuelle. Comme location_country, c'est une DÉDUCTION, pas un extrait : « Houthis » donne
   « Yemen », « Trump » donne « United States of America », « Iranian » donne « Iran », « Airbus
   Helicopters » donne « France ». Ce champ ne sert qu'à placer sur la carte un item dont le
   théâtre n'est pas rattachable. Laisse vide dans ces trois cas :
   - actor est vide ;
   - l'acteur est multinational ou sans pays : OTAN, ONU, UE, Union africaine, coalition ;
   - l'acteur se rattache à plusieurs pays sans qu'un seul domine (consortium, coentreprise).
   Un champ vide est toujours préférable à un rattachement arbitré.
9. Fournis domestic : l'événement rapporté se situe-t-il dans le pays de la source, indiqué en tête
   du message ? Réponds d'après le contenu de l'article, jamais d'après la seule origine du média :
   couvrir l'étranger est le cas le plus fréquent, et un média qui rapporte un événement survenu
   dans un pays tiers doit donner false même si l'article est écrit depuis son propre pays.
   true correspond à l'actualité intérieure : institution, administration, industrie ou forces
   armées du pays de la source agissant sur son propre territoire. Dans le doute, false.
   Ce champ ne dispense pas de renseigner les quatre précédents : réponds à tous."""


class _Analysis(BaseModel):
    category: Category = Field(description="Catégorie du périmètre MECE ou hors_perimetre (thématique uniquement)")
    title_fr: str = Field(description="Titre traduit en français, fidèle au titre original")
    summary: str = Field(description="Résumé factuel en français, 2-3 phrases maximum")
    citation: str = Field(description="Extrait verbatim du texte source, langue d'origine, justifiant le résumé")
    location: str = Field(
        description="Extrait verbatim nommant le pays/lieu principal de l'article ; vide si non mentionné"
    )
    location_country: str = Field(
        description="Pays souverain du lieu de location, nom anglais usuel ; vide si le lieu n'est dans aucun pays, "
        "est transnational ou de souveraineté contestée"
    )
    actor: str = Field(
        default="",
        description="Extrait verbatim nommant le protagoniste principal (État, force, groupe armé, industriel, "
        "responsable) ; vide si aucun n'est nommé ou si le protagoniste est une organisation internationale",
    )
    actor_country: str = Field(
        default="",
        description="Pays souverain de l'acteur, nom anglais usuel ; vide si l'acteur est multinational, "
        "sans pays, ou se rattache à plusieurs pays sans qu'un seul domine",
    )
    domestic: bool = Field(
        description="L'événement rapporté se situe-t-il dans le pays de la source ? false dès que l'article "
        "couvre l'étranger, et dans le doute"
    )


def _clean_text(raw_html: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", raw_html)).strip()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _extract_verified(extract: str, source_text: str) -> bool:
    """Vérifie qu'un extrait (citation ou zone_evidence) est bien un verbatim du texte source."""
    return bool(extract.strip()) and _normalize(extract) in _normalize(source_text)


_llm = None

# Noms anglais des codes pays de backend/config.py, pour la question `domestic` : « RU » se lit
# mal, « Russia » non. "INT" (source multi-pays / institutionnelle UE) n'a pas de pays d'origine
# et est traité à part — la question n'a pas de sens pour ce cas.
_SOURCE_COUNTRY_NAME: dict[str, str] = {
    "US": "the United States",
    "FR": "France",
    "RU": "Russia",
    "CN": "China",
    "DE": "Germany",
    "IT": "Italy",
    "GB": "the United Kingdom",
    "IL": "Israel",
    "ES": "Spain",
    "KR": "South Korea",
    "IR": "Iran",
    "KP": "North Korea",
}

_KNOWN_CATEGORIES: tuple[str, ...] = get_args(Category)


def _normalize_category(value: str) -> str:
    """Répare une quasi-correspondance de catégorie plutôt qu'une variante inconnue.

    Vu en conditions réelles sur une source hispanophone : le modèle a répondu
    `diplomacia_defense`, l'inflexion espagnole de `diplomatie_defense`, malgré la consigne du
    prompt (les identifiants sont un vocabulaire fermé). Un filet, pas une contrainte dure : ne
    corrige que si un candidat domine nettement les cinq autres catégories, pour ne jamais faire
    basculer un item d'une vraie catégorie vers une autre par accident — calibré sur les six
    identifiants (aucune paire ne dépasse un score de 0.55 entre elles), la marge ci-dessous ne
    peut donc pas confondre deux catégories réelles, seulement rattraper une variante de langue.
    """
    if value in _KNOWN_CATEGORIES:
        return value
    scored = sorted(
        ((difflib.SequenceMatcher(None, value, c).ratio(), c) for c in _KNOWN_CATEGORIES),
        reverse=True,
    )
    best_score, best = scored[0]
    runner_up_score = scored[1][0]
    if best_score >= 0.7 and best_score - runner_up_score >= 0.2:
        return best
    return value


def classify_item(item: RawItem) -> _Analysis:
    """Appelle le LLM pour un item, sans filtrage. Réutilisé par analyze() et par l'éval (backend/eval/)."""
    global _llm
    if _llm is None:
        _llm = ChatAnthropic(model=MODEL, temperature=0).with_structured_output(_Analysis, include_raw=True)

    clean_text = _clean_text(item["raw_text"])
    # Le pays de la source n'est donné que pour la question 7. Il est placé en tête et nommé comme
    # tel pour ne pas contaminer l'extraction de location, qui doit rester un verbatim du texte :
    # une source russe couvrant l'Ukraine ne doit pas se mettre à produire « Russia ».
    origin = _SOURCE_COUNTRY_NAME.get(item["country"], "an international or multi-country outlet")
    check_and_increment_llm_call("analyze")
    result = _llm.invoke(
        [
            ("system", SYSTEM_PROMPT),
            (
                "human",
                f"Pays de la source (métadonnée, ne fait pas partie de l'article, à n'utiliser que "
                f"pour la question 7) : {origin}\n\nTitre : {item['title']}\n\nTexte : {clean_text}",
            ),
        ]
    )
    if result["parsed"] is not None:
        return result["parsed"]

    # Échec de validation : avant d'abandonner (comme avant ce correctif), on tente de réparer la
    # catégorie sur les arguments bruts de l'appel d'outil — la seule classe d'échec de validation
    # rencontrée en conditions réelles jusqu'ici, cf. `_normalize_category`. Un item vraiment mal
    # formé (champ requis manquant) échoue de la même façon qu'avant : `_Analysis(**args)` relève
    # alors la même ValidationError, propagée à l'appelant sans traitement spécial.
    tool_calls = getattr(result["raw"], "tool_calls", None) or []
    if tool_calls and isinstance(tool_calls[0].get("args"), dict):
        args = tool_calls[0]["args"]
        if isinstance(args.get("category"), str):
            args = {**args, "category": _normalize_category(args["category"])}
        return _Analysis(**args)

    raise result["parsing_error"] or ValueError("réponse structurée sans tool_call exploitable")


# Sort réservé à chaque item soumis au modèle, par source. Même statut que `calls_by_node` dans
# backend/guardrails.py, et pour la même raison : une mesure d'exploitation, en mémoire, hors de la
# couche de persistance, remise à zéro par run_pipeline().
#
# Raison d'être (docs/cadrage.md §11) : `analyze` paie un appel par item soumis, avant de savoir si
# l'item sera retenu — un item classé hors_perimetre a coûté exactement le même appel qu'un item
# qui atteint le digest. Mesuré au run du 2026-08-22 : 72 appels pour 31 items retenus, soit 41
# appels (21 % du budget du jour) dépensés sur des items écartés. C'est le plus gros poste unique
# du budget quotidien, et il était invisible : les items écartés ne sont enregistrés nulle part —
# ni dans l'historique analysé, qui ne porte que les retenus, ni dans le journal de campagne, qui
# ne compte que les items soumis par flux avant plafonnage. Sans cette ventilation, on ne peut pas
# dire si ces 41 appels viennent de quelques flux généralistes ou de tout le panel, donc pas décider
# si la dépense est réductible à la collecte ou si elle est le prix du tri lui-même.
#
# La clé est (source, sort) et non la seule source : « combien de perdu » sans « pourquoi » ne
# distingue pas un flux hors sujet d'un flux dont les extraits sont trop courts pour porter une
# citation vérifiable — deux problèmes qui n'ont pas le même remède.
_submissions: Counter[tuple[str, str]] = Counter()


def submissions_by_source() -> dict[str, dict[str, int]]:
    """Sort des items soumis au modèle pendant le run courant, par source puis par sort."""
    by_source: dict[str, dict[str, int]] = {}
    for (source, outcome), count in _submissions.items():
        by_source.setdefault(source, {})[outcome] = count
    return {source: dict(sorted(outcomes.items())) for source, outcomes in sorted(by_source.items())}


def reset_submission_tally() -> None:
    """À appeler au début d'un run, comme reset_call_tally()."""
    _submissions.clear()


@dataclass
class _Progress:
    """Ce que le nœud a réellement soumis au modèle, et s'il s'est arrêté avant la fin du lot.

    Mutable et partagé avec le générateur plutôt que renvoyé en fin d'itération : l'appelant doit
    pouvoir lire ces deux informations même si l'itération s'interrompt en cours de route.
    """

    # Les items dont le sort est réglé — retenus ou écartés. Inscrits dans la mémoire de
    # dédoublonnage en sortie de nœud, y compris si le nœud échoue en cours de route : ce qui a été
    # payé ne doit pas être repayé, ce qui n'a pas été traité doit rester collectable.
    submitted: list[RawItem] = field(default_factory=list)
    truncated: bool = False


def analyze(state: VigieState) -> VigieState:
    """Nœud LangGraph : classe et résume chaque raw_item, rejette les résumés non tracés."""
    analyzed_items: list[AnalyzedItem] = []
    progress = _Progress()
    try:
        analyzed_items.extend(_analyze_items(state["raw_items"], progress))
    finally:
        mark_analyzed_as_seen(progress.submitted)

    # La ventilation part dans le journal du nœud et non seulement en fin de run : c'est le poste
    # de dépense le plus lourd du budget quotidien (41 des 72 appels du 2026-08-22 sur des items
    # écartés) et il doit rester lisible même si le run s'interrompt après ce nœud.
    par_source = submissions_by_source()
    par_sort: Counter[str] = Counter()
    for outcomes in par_source.values():
        par_sort.update(outcomes)
    if progress.truncated:
        log.warning("analyse tronquée par le plafond quotidien", extra={"soumis": len(progress.submitted)})
    log.info(
        "analyse terminée",
        extra={
            "recus": len(state["raw_items"]),
            "soumis": len(progress.submitted),
            "retenus": len(analyzed_items),
            "par_sort": dict(sorted(par_sort.items())),
            "par_source": par_source,
            "truncated": progress.truncated,
        },
    )
    return {"analyzed_items": analyzed_items, "truncated": progress.truncated}


def _analyze_items(raw_items: list[RawItem], progress: _Progress) -> Iterator[AnalyzedItem]:
    """Générateur : `progress` se remplit au fil de la consommation, pour que l'appelant sache
    exactement ce qui a été soumis au modèle même si l'itération s'interrompt."""
    for item in raw_items:
        progress.submitted.append(item)
        try:
            result = classify_item(item)
        except BudgetExceeded:
            # Le plafond quotidien tronque le lot, il ne détruit pas le travail déjà payé : on cesse
            # d'itérer et on rend les items déjà analysés, que l'appelant enregistrera normalement.
            #
            # Cet item-ci, en revanche, n'a rien coûté : le plafond est vérifié *avant* l'appel
            # (backend/guardrails.py), qui n'a donc pas eu lieu. Le retirer des soumis est ce qui le
            # garde collectable demain — le laisser le ferait marquer « vu » sans avoir jamais été
            # analysé, exactement la perte que `mark_analyzed_as_seen` a été déplacé ici pour éviter.
            progress.submitted.pop()
            progress.truncated = True
            # Aucun sort inscrit non plus : l'item n'a pas été soumis, il repart à la collecte.
            return
        except (ValidationError, ValueError):
            # Le modèle peut renvoyer une catégorie hors énumération — vu en conditions réelles sur
            # une source hispanophone (« diplomacia_defense » au lieu de « diplomatie_defense »).
            # `classify_item` tente déjà de réparer ce cas précis (`_normalize_category`) ; ce
            # `except` couvre ce qui reste après cette réparation — variante non reconnue, champ
            # requis manquant, ou l'absence totale de tool_call que `classify_item` remonte en
            # `ValueError` faute d'exception de parsing à propager. Un item mal formé se traite comme
            # un item non classable : on l'écarte, comme un résumé sans citation vérifiable. Le faire
            # remonter ferait perdre tout le run, y compris les items déjà analysés avant lui — un
            # coût sans rapport avec celui d'un item raté.
            # L'appel LLM a bien eu lieu : le budget (§8) est décompté, ici comme ailleurs.
            _submissions[(item["source"], "reponse_invalide")] += 1
            log.warning(
                "réponse du modèle non exploitable, item écarté",
                extra={"source": item["source"], "lien": item["link"]},
            )
            continue
        clean_text = _clean_text(item["raw_text"])

        if result.category == "hors_perimetre":
            _submissions[(item["source"], "hors_perimetre")] += 1
            continue
        if not _extract_verified(result.citation, clean_text):
            # Garde-fou traçabilité (docs/cadrage.md §8) : pas de citation vérifiable, pas de résumé.
            _submissions[(item["source"], "citation_non_verifiee")] += 1
            continue

        # location est une métadonnée pour la carte (docs/cadrage.md §4) : ne filtre pas la
        # collecte (pas de restriction géographique en V1), mais reste soumise au même garde-fou de
        # traçabilité que la citation — pas de lieu inventé, vide plutôt que non vérifiable.
        #
        # Le titre fait partie du texte vérifiable, contrairement à la citation qui doit justifier
        # le résumé et vient donc du corps. Mesuré sur un run réel : la vérification contre le seul
        # corps effaçait des extractions correctes, 10 des 11 lieux vides ayant leur pays nommé dans
        # le titre et nulle part ailleurs (les extraits RSS sont souvent tronqués, cf. §11).
        location = result.location if _extract_verified(result.location, f"{item['title']} {clean_text}") else ""

        # location_country est la seule sortie du LLM soustraite au garde-fou verbatim, parce
        # qu'elle est par construction absente du texte : « Darwin » ne contient pas « Australia ».
        # Deux contreparties la bornent. Ici : pas de lieu vérifié, pas de pays — sinon un lieu
        # rejeté au verbatim reviendrait par la porte de derrière placer l'item sur la carte.
        # À la restitution : le front ne retient ce pays que s'il existe dans le référentiel de la
        # carte, et le marque comme déduit (frontend/src/lib/geo.ts).
        location_country = result.location_country.strip() if location else ""

        # L'acteur suit exactement la même discipline que le lieu, un cran plus bas sur la carte.
        # Mesuré sur l'historique du 2026-08-20 : cinq items sans rattachement nommaient pourtant
        # leur protagoniste dans le titre (« Houthis », « Iran », « Trump »). Le théâtre était soit
        # absent, soit non rattachable (Mer Rouge, Golfe d'Aden, détroit d'Ormuz) — refuser d'y
        # placer l'item est correct pour un *lieu*, mais laissait perdre une information que la
        # source nomme noir sur blanc.
        #
        # Le garde-fou verbatim s'applique donc à `actor` comme à `location` : un protagoniste non
        # retrouvé dans le texte est un protagoniste inventé, et il est écarté plutôt que signalé.
        # Le titre entre dans le texte vérifiable pour la même raison que plus haut — c'est là que
        # le protagoniste est nommé le plus souvent, les extraits RSS étant tronqués.
        actor = result.actor if _extract_verified(result.actor, f"{item['title']} {clean_text}") else ""

        # Et `actor_country` est à `actor` ce que `location_country` est à `location` : la déduction
        # n'est autorisée que si l'extrait qui la porte a été vérifié, sinon un acteur rejeté au
        # verbatim reviendrait placer l'item sur la carte par la porte de derrière.
        actor_country = result.actor_country.strip() if actor else ""

        # Repli de dernier recours pour les items sans aucun lieu nommé : le modèle a jugé, sur le
        # contenu de l'article, que l'événement se situe dans le pays de la source. Trois bornes.
        #
        # Il ne s'applique qu'à `location` vide : si un lieu a été extrait mais n'est rattachable à
        # aucun pays (« Black Sea »), c'est une réponse, pas un manque — la remplacer par le pays du
        # média serait une régression, pas un repli.
        #
        # Il est refusé aux sources "INT", qui n'ont pas de pays d'origine.
        #
        # Et il reste plus faible que `location_country`, qui déduit d'un lieu nommé : ici rien
        # n'est nommé, seul le contenu est jugé. La restitution le distingue donc en « présumé »,
        # et non en « déduit » (frontend/src/lib/geo.ts). Le pays de la source ne suffit jamais à
        # lui seul : sans ce jugement, un média d'État couvrant l'étranger gonflerait l'empreinte
        # de son propre pays, et le périmètre en sur-échantillonne délibérément (cf. §4).
        domestic_to_source = bool(result.domestic) and not location and item["country"] != "INT"

        # Inscrit avant le `yield` et non après : un consommateur qui cesse d'itérer (le nœud
        # s'arrête sur BudgetExceeded) ne reprendrait jamais la main ici, et l'item serait compté
        # perdu alors qu'il a bien été produit.
        _submissions[(item["source"], "retenu")] += 1

        yield AnalyzedItem(
            source=item["source"],
            lang=item["lang"],
            country=item["country"],
            state_affiliated=item["state_affiliated"],
            title=item["title"],
            title_fr=result.title_fr,
            link=item["link"],
            published=item["published"],
            category=result.category,
            summary=result.summary,
            citation=result.citation,
            location=location,
            location_country=location_country,
            actor=actor,
            actor_country=actor_country,
            domestic_to_source=domestic_to_source,
            model_confidence=None,
            corroborated=None,
            thread_id=None,
        )
