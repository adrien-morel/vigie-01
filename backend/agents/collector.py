"""Nœud collecteur : récupère et normalise les entrées des sources RSS configurées."""

from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

import feedparser

from backend.config import COLLECTION_LOOKBACK_HOURS, MAX_ITEMS_PER_SOURCE_PER_RUN, SOURCES, Source
from backend.logging_setup import get_logger
from backend.state import RawItem, VigieState

log = get_logger("collect")


def _parse_entry(entry, source: Source) -> RawItem:
    return RawItem(
        source=source.name,
        theme=source.theme,
        lang=source.lang,
        country=source.country,
        state_affiliated=source.state_affiliated,
        title=entry.get("title", ""),
        link=entry.get("link", ""),
        published=entry.get("published", ""),
        raw_text=entry.get("summary", ""),
    )


def _publish_date(item: RawItem, fallback: datetime) -> datetime:
    """Date de publication parsée, ou `fallback` si absente/invalide — un item sans date parsable
    ne doit être pénalisé ni par la fenêtre de fraîcheur ni par le tri de plafonnage ci-dessous."""
    if not item["published"]:
        return fallback
    try:
        published = parsedate_to_datetime(item["published"])
    except (TypeError, ValueError):
        return fallback
    if published.tzinfo is None:
        published = published.replace(tzinfo=UTC)
    return published


def _is_recent(item: RawItem, cutoff: datetime, now: datetime) -> bool:
    """Écarte les items trop anciens (cf. COLLECTION_LOOKBACK_HOURS). Conserve les items sans
    date parsable — le garde-fou MAX_LLM_CALLS_PER_DAY reste le filet de sécurité final."""
    return _publish_date(item, now) >= cutoff


class FeedUnavailable(Exception):
    """Le flux n'a pas pu être lu — réseau, redirection, XML illisible. À ne pas confondre avec un
    flux muet, qui s'est lu correctement et n'avait simplement rien de récent."""


def _fetch_recent(source: Source, cutoff: datetime, now: datetime) -> list[RawItem]:
    """Items d'un flux dans la fenêtre de fraîcheur, triés du plus récent au plus ancien —
    sans plafond, réutilisé par `collect()` (qui l'applique) et `source_freshness()` (qui ne
    s'intéresse qu'au volume brut, cf. ci-dessous).

    Lève `FeedUnavailable` si le flux n'a pas pu être lu, plutôt que de rendre une liste vide :
    « injoignable » est une absence de mesure, « rien de récent » en est une — même distinction
    que les `None` du vérificateur, et c'est elle qui a manqué sur OFAC.
    """
    try:
        feed = feedparser.parse(source.url)
    except Exception as exc:  # noqa: BLE001 - cf. ci-dessous
        # Rattrapage volontairement large, et à ne pas resserrer : feedparser n'intercepte que
        # `urllib.error.URLError` (api.py), donc tout le reste remonte — vu en réel le 2026-08-30,
        # un `http.client.RemoteDisconnected` sur une redirection a tué `collect()` avant le
        # premier article. Dans un Job Cloud Run non surveillé, un flux qui hoquette ne doit pas
        # coûter la journée entière.
        raise FeedUnavailable(f"{type(exc).__name__}: {exc}") from exc

    # feedparser, lui, avale `URLError` et rend un résultat vide marqué `bozo` : sans ce test, un
    # flux hors service compterait comme muet. `bozo` seul ne suffit pas comme critère — beaucoup
    # de flux valides sont mal formés et se parsent quand même ; c'est `bozo` *et* zéro entrée qui
    # signe l'échec de lecture.
    if getattr(feed, "bozo", False) and not feed.entries:
        raise FeedUnavailable(str(getattr(feed, "bozo_exception", "flux illisible")))

    entries = [_parse_entry(entry, source) for entry in feed.entries]
    recent = [item for item in entries if _is_recent(item, cutoff, now)]
    recent.sort(key=lambda item: _publish_date(item, now), reverse=True)
    return recent


def collect(state: VigieState) -> VigieState:
    """Nœud LangGraph : peuple raw_items à partir de toutes les sources configurées.

    Deux filtres bornent le volume avant tout appel LLM : la fenêtre de fraîcheur
    (COLLECTION_LOOKBACK_HOURS) écarte les items trop anciens, puis un plafond par source
    (MAX_ITEMS_PER_SOURCE_PER_RUN, ou l'override Source.max_per_run) ne garde que les items les
    plus récents d'un flux à fort volume — sans quoi une agence de presse à cadence élevée
    épuiserait le budget quotidien au détriment des flux spécialisés à faible volume."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=COLLECTION_LOOKBACK_HOURS)
    raw_items: list[RawItem] = []
    by_source: dict[str, dict[str, int]] = {}
    silent: list[str] = []
    unavailable: dict[str, str] = {}
    for source in SOURCES:
        cap = source.max_per_run or MAX_ITEMS_PER_SOURCE_PER_RUN
        try:
            recent = _fetch_recent(source, cutoff, now)
        except FeedUnavailable as exc:
            # Un flux injoignable ne fait pas tomber le run : les autres ont déjà été lus, et le
            # budget du jour ne se rattrape pas. La source est nommée, la cause aussi.
            unavailable[source.name] = str(exc)
            by_source[source.name] = {"recents": 0, "retenus": 0, "indisponible": True}
            continue
        raw_items.extend(recent[:cap])
        by_source[source.name] = {"recents": len(recent), "retenus": min(len(recent), cap)}
        if not recent:
            silent.append(source.name)

    # Une source muette est journalisée en WARNING et non noyée dans le récapitulatif : c'est le
    # signal qui a manqué pendant un an sur OFAC, flux mort qui se parsait sans erreur et comptait
    # comme actif dans le KPI de couverture (cf. correctif du 2026-08-17, docs/cadrage.md §4).
    if silent:
        log.warning(
            "sources sans item récent",
            extra={"sources_muettes": silent, "fenetre_h": COLLECTION_LOOKBACK_HOURS},
        )
    # ERROR et non WARNING, et séparé des muettes : une source muette est une mesure (le flux a
    # répondu), une source injoignable est un trou dans la collecte du jour. Les deux se filtrent
    # distinctement dans une alerte Cloud Logging.
    if unavailable:
        log.error(
            "sources injoignables",
            extra={"sources_indisponibles": unavailable, "fenetre_h": COLLECTION_LOOKBACK_HOURS},
        )
    log.info(
        "collecte terminée",
        extra={
            "sources": len(SOURCES),
            "items_collectes": len(raw_items),
            "items_recents": sum(v["recents"] for v in by_source.values()),
            "sources_muettes": len(silent),
            "sources_indisponibles": len(unavailable),
            "par_source": by_source,
        },
    )
    return {"raw_items": raw_items}


def source_freshness() -> dict[str, int | None]:
    """Nombre d'items récents (dans COLLECTION_LOOKBACK_HOURS) par source, avant plafonnage.

    Mesure de rendement plutôt que d'appartenance à la config, pour le KPI de couverture (cf.
    docs/cadrage.md §7) : un flux qui se parse sans erreur mais ne publie plus rien de récent
    (OFAC, mort ~1 an avant d'être détecté par simple lecture du flux, cf. correctif du
    2026-08-17) doit compter comme silencieux, pas comme actif. Aucun appel LLM — lecture RSS
    seule, appelable depuis un outil d'exploitation (scripts/daily_run.py) sans coût budgétaire.

    `None` pour une source injoignable, jamais 0 : le KPI de couverture compte les flux qui ont
    répondu, et un échec réseau compté comme « zéro item récent » se lirait comme un flux mort.
    C'est la même règle que les `None` du vérificateur — on n'invente pas la mesure qui manque."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=COLLECTION_LOOKBACK_HOURS)
    freshness: dict[str, int | None] = {}
    for source in SOURCES:
        try:
            freshness[source.name] = len(_fetch_recent(source, cutoff, now))
        except FeedUnavailable:
            freshness[source.name] = None
    return freshness
