"""Schéma d'état partagé du graphe LangGraph (VigieState, cf. README)."""

from typing import Literal, TypedDict

# Catégories du périmètre MECE (cf. docs/cadrage.md §4) + hors_perimetre pour les items
# des flux sources qui sortent du périmètre restreint (ex. actualité tech générale, cyber).
Category = Literal[
    "export_control",
    "contrat_armement",
    "mouvement_militaire",
    "diplomatie_defense",
    "programme_industriel",
    "hors_perimetre",
]


class RawItem(TypedDict):
    source: str
    theme: str
    lang: str
    country: str  # code pays de la source (cf. backend/config.py), pas de l'article
    state_affiliated: bool  # média d'État ou lié à un service officiel (cf. backend/config.py)
    title: str
    link: str
    published: str  # ISO 8601 si fourni par le flux, chaîne vide sinon
    raw_text: str


class AnalyzedItem(TypedDict):
    source: str
    lang: str
    country: str
    state_affiliated: bool
    title: str  # titre original, dans la langue de la source
    title_fr: str  # titre traduit, pour un digest lisible en français quelle que soit la source
    link: str
    published: str
    category: Category
    summary: str
    citation: str  # extrait vérifié du texte source, langue d'origine (garde-fou §8 : verbatim = non traduisible)
    location: str  # pays/lieu vérifié, métadonnée pour la carte V2 (§4) ; ne filtre pas la collecte
    # Pays déduit du lieu ci-dessus, nom anglais. Seul champ non vérifiable verbatim (le pays d'une
    # ville n'est pas dans le texte) : vide dès que location l'est, et validé contre le référentiel
    # de la carte à l'affichage, où il est signalé comme déduit et non comme cité.
    location_country: str
    # Protagoniste de l'événement, vérifié verbatim comme location. Distinct du lieu : un article
    # peut nommer son acteur sans nommer de théâtre rattachable (« Houthis attack eight Saudi oil
    # tankers » — Mer Rouge et Golfe d'Aden ne sont d'aucun pays).
    actor: str
    # Pays déduit de l'acteur ci-dessus, nom anglais. Même statut que location_country — déduction
    # non vérifiable verbatim, vide dès que `actor` l'est, validée contre le référentiel de la carte
    # à l'affichage — mais un cran plus faible : elle rattache l'item au pays de qui agit, pas au
    # pays où les faits ont lieu. Signalée comme telle à l'affichage, jamais fondue dans le déduit.
    actor_country: str
    # Vrai uniquement si aucun lieu n'a été extrait ET que le modèle juge, sur le contenu, que
    # l'événement se situe dans le pays de la source (champ `country` ci-dessus). Rattachement
    # présumé, plus faible que location_country : distingué comme tel à l'affichage.
    domestic_to_source: bool
    # Renseignés par le vérificateur en V2 (cf. docs/cadrage.md §10) ; absents en V1.
    # `model_confidence` et non `confidence_score` : c'est l'auto-évaluation du modèle, pas une
    # probabilité calibrée. Mesuré le 2026-08-20 sur vingt items, il se comporte d'ailleurs comme
    # une fonction de `corroborated` (0,65 pour douze d'entre eux) plutôt que comme un jugement
    # propre — raison de plus pour que le nom ne promette pas ce qu'il ne tient pas.
    model_confidence: float | None
    corroborated: bool | None
    # Le portillon d'escalade du vérificateur : l'historique portait-il un antécédent candidat au
    # moment de la vérification (cf. VERIFIER_GATE_MIN_SCORE) ? Sépare deux `model_confidence` à
    # None que rien ne distinguait jusque-là : False = mesure (rien à vérifier dans la fenêtre),
    # True = silence (plafond du run ou budget épuisé avant d'y arriver). Absent des
    # enregistrements écrits avant le 2026-08-20, où la restriction par catégorie tenait ce rôle.
    has_antecedent_candidate: bool | None
    # Renseigné par le nœud thread en V3 tranche 1 (cf. docs/cadrage.md §10) ; None tant qu'aucun
    # autre item du même dossier n'a été retrouvé — jamais comblé par une valeur fabriquée.
    thread_id: str | None
    # Les deux champs qui rendent un thread_id nul lisible, exactement comme has_antecedent_candidate
    # le fait pour un model_confidence nul. Sans eux, `thread_id: None` porte trois états que rien ne
    # sépare : « l'historique ne portait aucun dossier candidat », qui est une mesure ; « le modèle a
    # regardé et n'a rien rapproché », qui en est une plus forte encore ; et « le plafond du run ou le
    # budget a coupé avant d'y arriver », qui est une absence de mesure. Constaté au run du
    # 2026-08-21 : 17 items éligibles, 3 rattachés, et les 14 autres indiscernables à l'écran d'items
    # sans dossier — l'affichage disait donc quelque chose de faux.
    #
    # Portillon d'escalade du threader (THREAD_GATE_MIN_SCORE) : l'historique portait-il un candidat
    # au-dessus du seuil ? Écrit sur tous les items, escaladés ou non — la sonde ne coûte aucun appel.
    has_thread_candidate: bool | None
    # Le modèle a-t-il conclu sur cet item ? False couvre aussi bien « jamais soumis » (portillon non
    # franchi, plafond du run, budget déjà épuisé) que « soumis mais interrompu par BudgetExceeded
    # avant la conclusion » : dans les deux cas rien n'a été jugé. Un booléen distinct du portillon
    # parce que, contrairement au vérificateur, une escalade du threader ne produit pas toujours un
    # résultat — le modèle peut légitimement conclure qu'aucun candidat ne couvre le même dossier.
    thread_checked: bool | None


class VigieState(TypedDict):
    raw_items: list[RawItem]
    analyzed_items: list[AnalyzedItem]
    # Vrai si le plafond quotidien d'appels LLM (backend/guardrails.py) a arrêté le run avant la fin
    # du lot. Le run reste un succès partiel : les items déjà analysés sont conservés et servis, et
    # ce drapeau dit à l'appelant que le lot n'a pas été traité en entier — sans lui, une collecte
    # tronquée serait indiscernable d'une collecte complète pauvre en nouveautés.
    truncated: bool
