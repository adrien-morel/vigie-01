"""Collector node: fetches and normalises the entries of the configured RSS sources."""

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
    """Parsed publication date, or `fallback` when missing/invalid — an item with no parsable date
    must be penalised neither by the freshness window nor by the capping sort below."""
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
    """Discards items that are too old (see COLLECTION_LOOKBACK_HOURS). Keeps items with no parsable
    date — the MAX_LLM_CALLS_PER_DAY guardrail remains the final safety net."""
    return _publish_date(item, now) >= cutoff


class FeedUnavailable(Exception):
    """The feed could not be read — network, redirect, unreadable XML. Not to be confused with a
    silent feed, which read correctly and simply had nothing recent."""


def _fetch_recent(source: Source, cutoff: datetime, now: datetime) -> list[RawItem]:
    """Items of a feed inside the freshness window, sorted newest first — with no cap, reused by
    `collect()` (which applies one) and `source_freshness()` (which only cares about raw volume, see
    below).

    Raises `FeedUnavailable` if the feed could not be read, rather than returning an empty list:
    "unreachable" is an absence of measurement, "nothing recent" is one — the same distinction as the
    verifier's `None` values, and the one that was missing on OFAC.
    """
    try:
        feed = feedparser.parse(source.url)
    except Exception as exc:  # noqa: BLE001 - see below
        # Deliberately broad catch, not to be narrowed: feedparser only intercepts
        # `urllib.error.URLError` (api.py), so everything else propagates — seen for real on
        # 2026-08-30, when an `http.client.RemoteDisconnected` on a redirect killed `collect()`
        # before the first article. In an unattended Cloud Run Job, a feed that hiccups must not cost
        # the whole day.
        raise FeedUnavailable(f"{type(exc).__name__}: {exc}") from exc

    # feedparser, for its part, swallows `URLError` and returns an empty result flagged `bozo`:
    # without this test, a feed that is out of service would count as silent. `bozo` alone is not
    # enough as a criterion — plenty of valid feeds are malformed and parse anyway; it is `bozo` *and*
    # zero entries that signs a read failure.
    if getattr(feed, "bozo", False) and not feed.entries:
        raise FeedUnavailable(str(getattr(feed, "bozo_exception", "unreadable feed")))

    entries = [_parse_entry(entry, source) for entry in feed.entries]
    recent = [item for item in entries if _is_recent(item, cutoff, now)]
    recent.sort(key=lambda item: _publish_date(item, now), reverse=True)
    return recent


def collect(state: VigieState) -> VigieState:
    """LangGraph node: populates raw_items from every configured source.

    Two filters bound the volume before any LLM call: the freshness window
    (COLLECTION_LOOKBACK_HOURS) discards items that are too old, then a per-source cap
    (MAX_ITEMS_PER_SOURCE_PER_RUN, or the Source.max_per_run override) keeps only the most recent
    items of a high-volume feed — without which a high-cadence press agency would exhaust the daily
    budget at the expense of low-volume specialised feeds."""
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
            # An unreachable feed does not bring the run down: the others have already been read, and
            # the day's budget does not come back. The source is named, and so is the cause.
            unavailable[source.name] = str(exc)
            by_source[source.name] = {"recent": 0, "kept": 0, "unavailable": True}
            continue
        raw_items.extend(recent[:cap])
        by_source[source.name] = {"recent": len(recent), "kept": min(len(recent), cap)}
        if not recent:
            silent.append(source.name)

    # A silent source is logged at WARNING and not buried in the summary: this is the signal that was
    # missing for a year on OFAC, a dead feed that parsed without error and counted as active in the
    # coverage KPI (see the fix of 2026-08-17, docs/scoping.md §4).
    if silent:
        log.warning(
            "sources with no recent item",
            extra={"silent_sources": silent, "window_h": COLLECTION_LOOKBACK_HOURS},
        )
    # ERROR and not WARNING, and kept separate from the silent ones: a silent source is a measurement
    # (the feed answered), an unreachable source is a hole in the day's collection. The two filter
    # separately in a Cloud Logging alert.
    if unavailable:
        log.error(
            "unreachable sources",
            extra={"unavailable_sources": unavailable, "window_h": COLLECTION_LOOKBACK_HOURS},
        )
    log.info(
        "collection finished",
        extra={
            "sources": len(SOURCES),
            "items_collected": len(raw_items),
            "items_recent": sum(v["recent"] for v in by_source.values()),
            "silent_sources": len(silent),
            "unavailable_sources": len(unavailable),
            "by_source": by_source,
        },
    )
    return {"raw_items": raw_items}


def source_freshness() -> dict[str, int | None]:
    """Number of recent items (within COLLECTION_LOOKBACK_HOURS) per source, before capping.

    A yield measurement rather than a config-membership one, for the coverage KPI (see
    docs/scoping.md §7): a feed that parses without error but no longer publishes anything recent
    (OFAC, dead for ~1 year before being detected by simply reading the feed, see the fix of
    2026-08-17) must count as silent, not as active. No LLM call — RSS reading alone, callable from
    an operational tool (scripts/daily_run.py) at no budget cost.

    `None` for an unreachable source, never 0: the coverage KPI counts the feeds that answered, and a
    network failure counted as "zero recent items" would read as a dead feed. Same rule as the
    verifier's `None` values — we do not invent the measurement that is missing."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=COLLECTION_LOOKBACK_HOURS)
    freshness: dict[str, int | None] = {}
    for source in SOURCES:
        try:
            freshness[source.name] = len(_fetch_recent(source, cutoff, now))
        except FeedUnavailable:
            freshness[source.name] = None
    return freshness
