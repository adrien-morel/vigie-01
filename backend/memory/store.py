"""Nœud mémoire : dédoublonnage court terme (README architecture, docs/cadrage.md §10 V1) et
historique des items analysés — qui sert à la fois au recoupement de l'agent vérificateur (§10 V2,
cf. backend/agents/verifier.py) et au digest servi par l'API.

Un seul historique pour ces deux usages, volontairement. La version précédente en tenait deux : cet
historique d'un côté, et un fichier `.digest.json` réécrit à chaque run de l'autre. Ce second
fichier ne contenait que les items du run courant — or le dédoublonnage écarte, avant l'appel LLM,
tout ce qui a déjà été vu dans les 7 derniers jours. Conséquence : un second run dans la même
journée ne produisait qu'une poignée d'items neufs et écrasait le digest précédent, qui était perdu
pour l'affichage alors même que les items restaient présents ici. Le digest est donc désormais une
fenêtre glissante sur cet historique (`load_digest`), pas la photographie du dernier run.

Le stockage (fichiers locaux en dev, Firestore en production) est derrière
backend/memory/persistence.py.
"""

import math
import re
from collections import Counter
from datetime import UTC, date, datetime, timedelta

from backend.logging_setup import get_logger
from backend.state import AnalyzedItem, RawItem, VigieState

from .persistence import get_persistence

DEDUP_WINDOW_DAYS = 7

# Alignée sur DEDUP_WINDOW_DAYS depuis le 2026-08-20 : la fenêtre de recoupement était plus longue
# (30 jours) pour donner plus d'historique au vérificateur, mais conserver au-delà de sept jours
# coûte du stockage sans bénéfice mesuré — la campagne d'accumulation qui aurait pu le justifier
# s'arrête ce jour-là. Borne aussi la profondeur maximale consultable du digest (cf.
# backend/api/main.py) et les choix du sélecteur front (frontend/src/App.tsx, WINDOW_CHOICES).
RELATED_ITEMS_WINDOW_DAYS = 7

log = get_logger("deduplicate")


def _cutoff(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def deduplicate(state: VigieState) -> VigieState:
    """Nœud LangGraph : retire les raw_items déjà vus (clé = link), avant l'appel LLM de l'analyste.

    Placé entre collect et analyze plutôt qu'après analyze : un item déjà vu ne doit pas seulement
    être exclu du digest, il ne doit même pas être ré-analysé — sinon le budget LLM (§8) est
    consommé chaque jour sur des items déjà traités la veille.
    """
    persistence = get_persistence()
    # Une fois par run, en début de pipeline : sans purge explicite, les backends qui filtrent à la
    # lecture (Firestore) conserveraient indéfiniment des données hors fenêtre de rétention.
    persistence.purge_before(_cutoff(DEDUP_WINDOW_DAYS), _cutoff(RELATED_ITEMS_WINDOW_DAYS))

    seen = persistence.seen_links(_cutoff(DEDUP_WINDOW_DAYS))

    new_items: list[RawItem] = []
    kept: set[str] = set()
    doublons_du_lot = 0
    for item in state["raw_items"]:
        if item["link"] in kept:
            doublons_du_lot += 1
            continue
        if item["link"] in seen:
            continue
        new_items.append(item)
        kept.add(item["link"])

    # Les deux causes d'écart sont séparées : « déjà vu un jour précédent » est le fonctionnement
    # normal du dédoublonnage, « deux fois dans le même lot » signale deux flux qui republient le
    # même lien — utile à la composition des sources, invisible si on ne compte qu'un total.
    log.info(
        "dédoublonnage terminé",
        extra={
            "recus": len(state["raw_items"]),
            "retenus": len(new_items),
            "ecartes_deja_vus": len(state["raw_items"]) - len(new_items) - doublons_du_lot,
            "doublons_du_lot": doublons_du_lot,
            "liens_en_memoire": len(seen),
        },
    )

    # Ce nœud filtre, il ne marque pas : c'est mark_analyzed_as_seen(), appelé par le nœud analyze,
    # qui inscrit les liens une fois l'item réellement soumis au modèle. Marquer ici perdait
    # définitivement les items d'un run interrompu entre les deux — ils étaient réputés vus sans
    # avoir jamais été analysés, donc écartés de toutes les collectes suivantes. Constaté en réel :
    # une réponse de modèle non validable a fait échouer un run, et ses 12 items sont restés vus
    # sans exister nulle part.
    return {"raw_items": new_items}


def mark_analyzed_as_seen(items: list[RawItem]) -> None:
    """Inscrit les liens soumis à l'analyste dans la mémoire de dédoublonnage.

    Porte sur tous les items soumis, pas seulement sur ceux retenus : un item écarté en
    `hors_perimetre` ou faute de citation vérifiable a déjà coûté son appel LLM, et doit être
    écarté sans frais lors des collectes suivantes.
    """
    if not items:
        return
    today = date.today().isoformat()
    get_persistence().mark_seen({item["link"]: today for item in items})


def record_analyzed(items: list[AnalyzedItem]) -> None:
    """Écrit les items analysés du run courant dans l'historique (recoupement §10 V2 + digest).

    Appelé en fin de nœud verify, une fois `confidence_score`/`corroborated` renseignés, puis en fin
    de nœud thread, une fois `thread_id`/`has_thread_candidate`/`thread_checked` posés : l'historique
    doit porter l'item tel qu'il sera affiché, pas sa version pré-vérification — c'est lui, pas
    l'état du graphe, que `load_digest` sert au front. L'invariant « la recherche de recoupement ne
    voit jamais le run courant » est tenu par `exclude_links` côté verifier, pas par l'ordre
    d'écriture.

    `first_seen` est conservé lors d'une réécriture : un item ré-analysé ne doit pas rajeunir, sinon
    il ne sortirait jamais de la fenêtre de rétention. `thread_id` est préservé de la même façon,
    défensivement : le nœud thread (V3 tranche 1) fixe toujours explicitement ce champ sur les items
    qu'il traite, mais un futur appelant qui ne le ferait pas ne doit pas effacer un rattachement
    déjà établi.
    """
    if not items:
        return

    persistence = get_persistence()
    today = date.today().isoformat()
    now = datetime.now(UTC).isoformat()
    known = {r["link"]: r for r in persistence.analyzed_since(_cutoff(RELATED_ITEMS_WINDOW_DAYS))}

    persistence.put_analyzed(
        [
            {
                **item,
                "date": known.get(item["link"], {}).get("date", today),
                "first_seen": known.get(item["link"], {}).get("first_seen", now),
                "thread_id": item.get("thread_id") or known.get(item["link"], {}).get("thread_id"),
            }
            for item in items
        ]
    )


# Champs sans lesquels le front ne peut pas rendre une carte d'item. Avant la fusion des deux
# stores, l'historique ne conservait que 7 champs par item (assez pour le recoupement, pas pour
# l'affichage) : ces enregistrements-la restent interrogeables par le vérificateur mais sont
# écartés du digest plutôt que servis incomplets. Ils sortiront d'eux-mêmes de la rétention.
_DISPLAY_FIELDS = ("title", "citation", "location", "published", "lang")


def _is_displayable(record: dict) -> bool:
    return all(field in record for field in _DISPLAY_FIELDS)


def load_digest(days: int) -> list[dict]:
    """Items analysés des `days` derniers jours, les plus récents d'abord.

    C'est ce que sert GET /events. Les items conservent `date`/`first_seen` : le front en a besoin
    pour dater l'entrée dans le digest, qui n'est pas la date de publication de l'article.
    """
    records = [r for r in get_persistence().analyzed_since(_cutoff(days)) if _is_displayable(r)]
    records.sort(key=lambda r: (r.get("first_seen", ""), r.get("published", "")), reverse=True)
    return records


def last_run_at(records: list[dict]) -> str | None:
    """Horodatage de l'entrée la plus récente du digest — donc de la dernière collecte ayant produit
    quelque chose. Dérivé des items plutôt que stocké à part : un compteur séparé pourrait diverger
    de ce qui est réellement affiché."""
    stamps = [r["first_seen"] for r in records if r.get("first_seen")]
    return max(stamps) if stamps else None


def _tokenize(text: str) -> set[str]:
    return {tok for tok in re.findall(r"\w+", text.lower()) if len(tok) > 2}


def _record_tokens(record: dict) -> set[str]:
    return _tokenize(record.get("title_fr", "")) | _tokenize(record.get("summary", ""))


def _document_frequencies(records: list[dict]) -> Counter[str]:
    """Nombre d'items de la fenêtre contenant chaque token.

    Calculé sur la fenêtre entière, y compris les items que l'appelant exclura du classement
    (lot courant, item lui-même) : ce sont des statistiques de corpus, et les faire dépendre du
    lot du jour ferait varier le poids d'un mot d'un run à l'autre.
    """
    df: Counter[str] = Counter()
    for record in records:
        df.update(_record_tokens(record))
    return df


def _overlap_score(query_tokens: set[str], record_tokens: set[str], df: Counter[str], total: int) -> float:
    """Chevauchement de mots-clés pondéré par la rareté du mot dans l'historique (IDF).

    Le comptage brut qui précédait était dominé par les mots vides : mesuré sur 199 items réels,
    88 % des paires d'items avaient un chevauchement non nul, et 64 % du score était porté par des
    tokens présents dans plus d'un cinquième du corpus (« les », « des », « pour », « dans »).
    L'ordre des cinq candidats servis au modèle était donc en bonne part du bruit.

    log(total / df) plutôt qu'une liste de mots vides : le poids se dérive du corpus au lieu d'être
    curé à la main, ce qui écarte aussi les mots vides *du domaine* (« défense », « drones »,
    « selon ») qu'aucune liste générique ne couvrirait, et n'introduit aucun seuil à calibrer.

    Portée mesurée à l'origine, dépassée depuis : la pondération corrigeait le *classement* (un
    tiers des candidats servis au modèle change, 328 évictions sur 89 des 199 items) sans rendre le
    portillon d'escalade de backend/agents/threader.py discriminant — la requête étant le titre et
    le résumé entiers de l'item, assez longs pour partager un token rare avec au moins un des
    199 enregistrements quelle que soit la pondération, ce portillon restait franchi par 100 % des
    items. Un corpus suffisant pour régler un seuil manquait alors (cf. backend/eval/candidates.py).
    Il a depuis été mesuré et posé : THREAD_GATE_MIN_SCORE dans backend/config.py, appliqué par
    search_thread_candidates via son paramètre `min_score`, calibré le 2026-08-20 sur l'échantillon
    annoté backend/eval/pairs.json (cf. son historique dans backend/eval/score_pairs.py).

    Sous trois items, la pondération est dégénérée, et la borne se dérive plutôt que se règle : un
    token partagé par un item et une requête issue d'un autre item a `df >= 2`, donc dans une
    fenêtre de deux items tout token partagé a `df == total` et un poids nul — la pondération ne
    peut alors rien classer. On retombe sur le comptage brut, faute de corpus sur lequel mesurer
    une rareté. Le portillon se resserre donc à mesure que l'historique grandit, ce qui est le sens
    souhaité, et le cas canonique du thread (deux sources du même run sur le même dossier, cf.
    tests/test_threader.py) reste couvert quand l'historique est encore vide.
    """
    shared = query_tokens & record_tokens
    if total < 3:
        return float(len(shared))
    return sum(math.log(total / df[tok]) for tok in shared)


def search_related(query: str, exclude_links: set[str], limit: int = 5) -> list[dict]:
    """Recherche par chevauchement de mots-clés pondéré IDF dans l'historique (§10 V2,
    backend/agents/verifier.py) — cf. `_overlap_score` pour la mesure qui a motivé la pondération.

    Pas d'embeddings/vector store : cohérent avec la convention « stockage fichier local comme
    placeholder documenté avant Firestore » qui a présidé à ce module. La pondération IDF se dérive
    du corpus déjà chargé, là où un top-k sur embeddings remplacerait le seuil à calibrer par un
    `k` à calibrer, sur un historique qui ne permet pas encore de trancher.

    `exclude_links` porte tous les liens du run en cours, pas seulement celui de l'item vérifié :
    un item ne doit pas être « corroboré » par un autre item du même lot, qui n'apporte aucune
    confirmation indépendante dans le temps.
    """
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    records = get_persistence().analyzed_since(_cutoff(RELATED_ITEMS_WINDOW_DAYS))
    df = _document_frequencies(records)

    scored: list[tuple[float, dict]] = []
    for record in records:
        if record["link"] in exclude_links:
            continue
        score = _overlap_score(query_tokens, _record_tokens(record), df, len(records))
        if score > 0:
            scored.append((score, record))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        {
            "date": record["date"],
            "source": record["source"],
            "country": record.get("country", ""),
            "category": record["category"],
            "title_fr": record["title_fr"],
        }
        for _, record in scored[:limit]
    ]


def has_antecedent(queries: dict[str, str], exclude_links: set[str], min_score: float) -> dict[str, bool]:
    """Portillon d'escalade du vérificateur (backend/agents/verifier.py) : pour chaque item — clé, le
    lien ; valeur, la requête — dit si l'historique porte au moins un antécédent dont le score de
    chevauchement atteint `min_score`.

    Un lot entier plutôt qu'une sonde par item : la fenêtre et ses fréquences documentaires sont
    chargées une fois, là où `search_related` relit l'historique à chaque appel. Le vérificateur
    couvrant tout le périmètre depuis le 2026-08-20, une sonde par item aurait multiplié la lecture
    de l'historique par le volume du run (~110), sur un backend Firestore dont le coût de lecture
    est déjà un point ouvert du déploiement (docs/cadrage.md §11).

    `exclude_links` porte tout le lot courant, comme `search_related` : un antécédent est une
    confirmation indépendante dans le temps, pas une reprise simultanée de la même dépêche. Un
    historique vide rend donc tout le lot inéligible — c'est le comportement voulu, escalader un
    item dont l'historique n'a rien à dire coûte 2 à 3 appels pour produire une non-réponse.

    Même réserve d'échelle que `search_thread_candidates` : sous trois items dans la fenêtre,
    `_overlap_score` retombe sur un compte brut de tokens, échelle sur laquelle un seuil mesuré en
    pondéré n'a pas de sens — le portillon retombe alors sur « au moins un candidat ».
    """
    records = get_persistence().analyzed_since(_cutoff(RELATED_ITEMS_WINDOW_DAYS))
    df = _document_frequencies(records)
    total = len(records)
    floor = min_score if total >= 3 else 0.0
    candidates = [(_record_tokens(record), record["link"]) for record in records]

    gate: dict[str, bool] = {}
    for link, query in queries.items():
        query_tokens = _tokenize(query)
        found = False
        for record_tokens, candidate_link in candidates:
            if candidate_link in exclude_links:
                continue
            score = _overlap_score(query_tokens, record_tokens, df, total)
            if score > 0 and score >= floor:
                found = True
                break
        gate[link] = found
    return gate


def analyzed_window(days: int = RELATED_ITEMS_WINDOW_DAYS) -> dict[str, dict]:
    """Fenêtre d'historique indexée par lien, pour un appelant qui doit résoudre un lien vers son
    enregistrement complet (ex. backend/agents/threader.py, pour patcher thread_id sans repartir
    d'un enregistrement partiel — put_analyzed remplace par lien, pas de patch partiel, cf.
    backend/memory/persistence.py)."""
    return {r["link"]: r for r in get_persistence().analyzed_since(_cutoff(days))}


def search_thread_candidates(query: str, exclude_link: str, limit: int = 5, min_score: float = 0.0) -> list[dict]:
    """Recherche par chevauchement de mots-clés pondéré IDF pour le nœud thread (V3 tranche 1, cf.
    backend/agents/threader.py) — même primitive que search_related, fonction séparée plutôt que
    paramètre supplémentaire pour ne rien changer au comportement déjà testé du vérificateur.

    Deux différences volontaires avec search_related : `exclude_link` ne porte que le lien de
    l'item courant, pas tout le lot du run (un fil n'exige pas de confirmation indépendante dans le
    temps comme la corroboration — deux sources qui couvrent le même événement le même jour sont le
    cas le plus net de « même dossier ») ; le résultat inclut `link`, `thread_id` et `score` pour que
    l'appelant puisse rattacher un dossier à l'enregistrement historique retrouvé et, pour `score`,
    appliquer le portillon d'escalade de backend/agents/threader.py.

    `min_score` filtre en plus du `score > 0` déjà appliqué, mais seulement quand la pondération IDF
    est active (fenêtre >= 3 items, cf. _overlap_score) : sous ce seuil de corpus le score retombe
    sur un compte brut de tokens partagés, une échelle sur laquelle un seuil mesuré sur corpus
    pondéré (cf. THREAD_GATE_MIN_SCORE, calibré le 2026-08-20 sur backend/eval/pairs.json) n'a pas de
    sens — l'ignorer alors préserve le cas canonique du thread (deux sources du même run, historique
    encore vide, cf. tests/test_threader.py) plutôt que de le rendre inéligible faute de corpus.
    """
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    records = get_persistence().analyzed_since(_cutoff(RELATED_ITEMS_WINDOW_DAYS))
    df = _document_frequencies(records)
    total = len(records)
    floor = min_score if total >= 3 else 0.0

    scored: list[tuple[float, dict]] = []
    for record in records:
        if record["link"] == exclude_link:
            continue
        score = _overlap_score(query_tokens, _record_tokens(record), df, total)
        if score > 0 and score >= floor:
            scored.append((score, record))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        {
            "link": record["link"],
            "thread_id": record.get("thread_id"),
            "date": record["date"],
            "source": record["source"],
            "country": record.get("country", ""),
            "category": record["category"],
            "title_fr": record["title_fr"],
            "score": score,
        }
        for score, record in scored[:limit]
    ]
