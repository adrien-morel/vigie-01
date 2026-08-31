"""Récupération du texte intégral d'un article (docs/cadrage.md §10, outil tier 1).

Raison d'être — **et une attribution corrigée en la mesurant.** La ventilation du 2026-08-30
imputait à ce module 26 appels perdus par run en `citation_non_verifiee` (18 % du budget), en
supposant que l'extrait RSS était trop court pour porter une citation vérifiable. Mesuré le
2026-08-31 sur un lot Opex360/ESUT réel, en bras appariés : **c'était le mauvais objet.** Sur les
6 échecs constatés, 4 relevaient de pure typographie — apostrophes courbes contre droites — et se
règlent dans `analyst._normalize`, sans une seule requête HTTP ; les 2 autres sont de vraies
paraphrases, que rien ici ne rattrape. Ce seul repli typographique a fait passer la rétention du
lot de 2/10 à 5/10, quand l'enrichissement n'ajoute qu'un item net.

**La justification qui tient est donc la classification, pas la citation.** Les points 38/39
(docs/cadrage.md §7) ont montré deux items ESUT **mal classés** à cause d'un teaser tronqué — un
correctif de prompt ne peut pas compenser un extrait qui ne contient pas l'information à classer.
C'est cette classe de gain, et elle seule, que la validation du 2026-08-31 a reproduite : les deux
bascules favorables du lot sont deux `hors_perimetre` devenus des items retenus une fois l'article
entier lu. Sur 10 items appariés, le bilan est de +2 gains, −1 régression : un signal orienté dans
le sens attendu, **mais pas une mesure concluante** à cet effectif — d'où l'interrupteur
`FETCH_FULL_ARTICLE`, et non un comportement câblé en dur.

Ce module ne consomme aucun appel LLM : récupérer un article est gratuit, seule sa soumission au
modèle coûte, et elle a lieu de toute façon.

Invariant central — **on ajoute, on ne remplace pas.** Le texte intégral est concaténé au teaser
plutôt que substitué. Trois conséquences, toutes voulues :

- Le corpus vérifiable ne fait que croître, donc **une citation donnée qui se vérifie aujourd'hui
  continue de se vérifier** après enrichissement. Un garde-fou de traçabilité qu'on peut casser
  rétroactivement serait un mauvais échange.

  **Ce que cet invariant ne dit pas**, et qui a été observé en réel le 2026-08-31 : il porte sur une
  chaîne de caractères, pas sur le sort de l'item. Devant un texte plus long, le modèle **choisit
  une autre citation** — 1 item sur 10 du lot de validation est ainsi passé de `retenu` à
  `citation_non_verifiee` alors que sa citation d'origine restait vérifiable. Le module ne peut donc
  pas promettre l'absence de régression au niveau de l'item, et ne doit pas être présenté comme le
  faisant.
- Un fetch en échec dégrade un item, il ne le perd pas : on retombe exactement sur le comportement
  d'avant ce module. C'est la même règle que pour un flux injoignable (correctif du 2026-08-30) —
  l'échec est local, nommé et journalisé, il ne fait pas tomber ce qui l'entoure.
- Une extraction qui ramène le chrome du site (bandeau cookies, mentions légales) ajoute du bruit
  mais ne retire aucune information.
"""

import html
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests
import trafilatura

from backend.config import (
    FETCH_MAX_CHARS,
    FETCH_MAX_WORKERS,
    FETCH_SKIP_SOURCES,
    FETCH_TIMEOUT_S,
)
from backend.logging_setup import get_logger
from backend.state import RawItem

log = get_logger("fetch")

# En-tête navigateur. Mesuré le 2026-08-31 sur les 18 sources : trois flux refusent un GET nu et
# répondent 200 avec cet en-tête — Breaking Defense (403), TASS (403), NK News (520). Ce n'est pas
# une astuce de contournement mais la conséquence d'un défaut d'`User-Agent` : le client par défaut
# de `requests` est filtré par les CDN. Les articles restent publics et lus tels que publiés.
#
# Le relevé corrige au passage la note de cadrage qui annonçait « 2 sources bloquées, Defense.gov et
# Federal Register » : Federal Register répond 200 sans en-tête particulier (son problème est ailleurs,
# cf. `_anchor_overlap`), et trois sources bloquées n'avaient pas été vues.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
}

# Longueur minimale de teaser, en tokens d'au moins 4 caractères, pour qu'il puisse servir d'ancre.
# En dessous, on ne peut pas vérifier que l'extraction a bien ramené *cet* article — on s'abstient.
_MIN_ANCHOR_TOKENS = 5


class ArticleUnavailable(Exception):
    """L'article n'a pas pu être récupéré ou extrait. À traiter comme une dégradation locale :
    l'item reste analysable sur son teaser, comme avant ce module."""


def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"\w+", text.lower()) if len(w) >= 4]


def _anchor_overlap(teaser: str, text: str) -> float | None:
    """Part des tokens du teaser retrouvés dans le texte extrait, ou `None` si le teaser est trop
    court pour ancrer quoi que ce soit.

    Mesure ce qu'aucune vérification de statut HTTP ne dit : l'extraction a-t-elle ramené *cet*
    article, ou le chrome du site ? Deux cas réels au relevé du 2026-08-31 sur 49 articles —
    Federal Register rend 3 669 caractères de mentions légales (« This site displays a prototype of
    a Web 2.0 version of the daily Federal Register… ») et CGTN rend un bandeau cookies suivi du
    menu de navigation. Les deux ont un teaser trop court pour ancrer (0 et 37 caractères), donc
    **la règle d'ancrabilité seule les écarte** et aucun seuil n'est nécessaire pour les attraper.

    C'est pourquoi ce score est **mesuré et journalisé, mais ne décide de rien**. Les deux seuls
    négatifs du relevé étant pris par une autre règle, il ne reste aucune séparation positif/négatif
    sur laquelle calibrer un seuil : le poser au jugé serait un arbitraire déguisé en mesure, très
    exactement ce que THREAD_GATE_MIN_SCORE a évité en restant un filtre gratuit jusqu'à disposer
    de son échantillon annoté. Instrumenter d'abord, plafonner ensuite — même ordre que pour
    `has_antecedent_candidate`.

    Ordres de grandeur du relevé, pour une calibration future : 42 des 44 items ancrables sont à
    ≥ 0,67 et la moitié à 1,00 ; les deux plus bas (0,20 et 0,42) ne sont pas du chrome mais des
    extractions courtes, où le teaser porte une phrase que le corps de l'article ne reprend pas.
    """
    anchor = _tokens(teaser)
    if len(anchor) < _MIN_ANCHOR_TOKENS:
        return None
    body = set(_tokens(text))
    return sum(1 for w in anchor if w in body) / len(anchor)


def fetch_full_article(url: str, timeout: float | None = None) -> str:
    """Texte de l'article à `url`, extrait du HTML. Lève `ArticleUnavailable` sur tout échec.

    `trafilatura` plutôt qu'une extraction au regex : il est fait pour retirer le boilerplate, là
    où découper sur des balises produit exactement les faux négatifs relevés à la sonde d'ancrage
    du 2026-08-22 (typographie et insertions inline coupant la chaîne recherchée).
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout or FETCH_TIMEOUT_S, allow_redirects=True)
    except requests.RequestException as exc:
        raise ArticleUnavailable(f"réseau : {type(exc).__name__}") from exc
    if response.status_code != 200:
        raise ArticleUnavailable(f"HTTP {response.status_code}")
    text = trafilatura.extract(response.text, include_comments=False, include_tables=False)
    if not text or not text.strip():
        raise ArticleUnavailable("extraction vide")
    return text.strip()


@dataclass
class FetchTally:
    """Sort de chaque tentative de récupération. Même statut que `analyst.submissions_by_source()` :
    mesure d'exploitation, en mémoire, hors persistance, remise à zéro à chaque run."""

    enriched: int = 0
    skipped_source: int = 0
    not_anchorable: int = 0
    no_gain: int = 0
    failed: int = 0
    chars_added: int = 0
    overlaps: list[float] = field(default_factory=list)

    def as_dict(self) -> dict[str, float | int]:
        summary: dict[str, float | int] = {
            "enrichis": self.enriched,
            "source_exclue": self.skipped_source,
            "teaser_non_ancrable": self.not_anchorable,
            "sans_gain": self.no_gain,
            "echecs": self.failed,
            "caracteres_ajoutes": self.chars_added,
        }
        if self.overlaps:
            ordered = sorted(self.overlaps)
            summary["ancrage_median"] = round(ordered[len(ordered) // 2], 3)
            summary["ancrage_min"] = round(ordered[0], 3)
        return summary


def _enrich_one(item: RawItem) -> tuple[RawItem, str, float | None, str]:
    """Rend (item, texte à ajouter, score d'ancrage, motif). Texte vide = item inchangé."""
    # Renoncement documenté par source plutôt que découverte en production. Mesuré le 2026-08-31 :
    # Defense.gov répond 403 avec comme sans en-tête navigateur (et redirige désormais vers
    # war.gov). Ses items restent collectés et analysés sur leur teaser.
    if item["source"] in FETCH_SKIP_SOURCES:
        return item, "", None, "source_exclue"

    teaser = html.unescape(re.sub(r"<[^>]+>", " ", item["raw_text"])).strip()
    try:
        text = fetch_full_article(item["link"])
    except ArticleUnavailable as exc:
        log.warning(
            "article non récupéré, repli sur le teaser",
            extra={"source": item["source"], "lien": item["link"], "motif": str(exc)},
        )
        return item, "", None, "echec"

    overlap = _anchor_overlap(teaser, text)
    if overlap is None:
        # Teaser trop court pour vérifier que l'extraction porte bien cet article. C'est le cas de
        # Federal Register (teaser vide) et d'une partie de CGTN — précisément les deux sources dont
        # l'extraction ramène le chrome du site. On s'abstient plutôt que d'ajouter du bruit.
        return item, "", None, "teaser_non_ancrable"
    if len(text) <= len(teaser):
        # Rien à gagner : l'extraction n'apporte pas plus que ce dont le modèle dispose déjà.
        return item, "", overlap, "sans_gain"
    return item, text[:FETCH_MAX_CHARS], overlap, "enrichi"


def enrich_items(items: list[RawItem]) -> FetchTally:
    """Complète `raw_text` de chaque item avec le texte intégral de l'article, en place.

    Appelé depuis `analyze` et non depuis `collect` : à ce point du graphe, le lot a déjà subi le
    plafond par source **et** le dédoublonnage, donc on ne récupère que des articles qui seront
    réellement soumis au modèle.

    Concurrent par nécessité, pas par élégance : le run du 2026-08-30 a duré 880 s contre une cible
    de 900 s (docs/cadrage.md §11), donc une récupération séquentielle de ~110 articles à ~2,2 s de
    latence unitaire ferait sortir le run de sa cible à elle seule. Mesuré à 8 fils : 13,6 s pour
    49 articles.
    """
    tally = FetchTally()
    if not items:
        return tally

    with ThreadPoolExecutor(max_workers=FETCH_MAX_WORKERS) as pool:
        results = list(pool.map(_enrich_one, items))

    for item, text, overlap, outcome in results:
        if overlap is not None:
            tally.overlaps.append(overlap)
        if outcome == "enrichi":
            # Échappé avant concaténation : `raw_text` est du HTML de flux, et l'analyste le repasse
            # par `_clean_text` (retrait des balises puis `html.unescape`). Échapper ici garantit que
            # le texte ajouté traverse ce nettoyage à l'identique — sans quoi une esperluette ou un
            # chevron du corps de l'article ressortirait transformé, et une citation verbatim
            # portant dessus échouerait à se vérifier.
            item["raw_text"] = f"{item['raw_text']}\n\n{html.escape(text)}"
            tally.enriched += 1
            tally.chars_added += len(text)
        elif outcome == "source_exclue":
            tally.skipped_source += 1
        elif outcome == "teaser_non_ancrable":
            tally.not_anchorable += 1
        elif outcome == "sans_gain":
            tally.no_gain += 1
        else:
            tally.failed += 1

    log.info("récupération du texte intégral terminée", extra={"soumis": len(items), **tally.as_dict()})
    return tally
