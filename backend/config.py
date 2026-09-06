"""Central configuration: monitored sources, caps, environment keys."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    lang: str
    theme: str  # export_control | contracts | movements | diplomacy | programs
    country: str  # ISO 3166-1 alpha-2 country code, or "INT" for a multi-country/EU institutional source
    state_affiliated: bool = False  # state media or tied to an official service — see docs/scoping.md §4
    # Overrides MAX_ITEMS_PER_SOURCE_PER_RUN. Reserved for generalist feeds (national press agency,
    # no dedicated defence desk) whose LLM-calls-per-kept-item ratio, measured on an annotated
    # sample, is markedly worse than average (see docs/scoping.md §7): the default cap is enough to
    # bound the cost, but not to correct a structurally poor yield.
    max_per_run: int | None = None


# Sources checked by hand (RSS feed tested live on 2026-08-14, see docs/scoping.md §4).
# Geographic perimeter: the SIPRI top 10 arms exporters (Trends in International Arms Transfers,
# March 2025, 2020-24 data) plus Iran and North Korea for export_control coverage (regimes under
# active embargo, absent from the SIPRI ranking by volume).
SOURCES: list[Source] = [
    # United States (43% of world exports)
    Source("Breaking Defense", "https://feeds.feedburner.com/breakingdefense", "en", "programs", "US"),
    Source("Defense News", "https://www.defensenews.com/arc/outboundfeeds/rss/", "en", "contracts", "US"),
    # OFAC (Treasury) removed on 2026-08-17: the feed had been dead for over a year when we noticed
    # (last entry 2025-07-01) and counted as an "active" source in the coverage KPI (§7) without
    # producing a single item — replaced by the Bureau of Industry and Security (Federal Register),
    # which administers the Export Administration Regulations, a more direct target for the
    # export_control perimeter than the Treasury for this product.
    Source(
        "Federal Register – BIS (export control)",
        "https://www.federalregister.gov/api/v1/documents.rss"
        "?conditions%5Bagencies%5D%5B%5D=industry-and-security-bureau",
        "en",
        "export_control",
        "US",
    ),
    Source(
        "Defense.gov (DoD)",
        "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945",
        "en",
        "movements",
        "US",
    ),
    # Added on 2026-08-17: specialised naval press, reinforcing US volume (before this fix the most
    # heavily exporting country in the perimeter had no active source inside a 48 h collection
    # window — see the window fix below).
    Source("Naval News", "https://www.navalnews.com/feed/", "en", "movements", "US"),
    # France (9.6%)
    Source("Opex360", "https://opex360.com/feed/", "fr", "movements", "FR"),
    Source("Bruxelles2", "https://bruxelles2.eu/api/rss.xml", "fr", "diplomacy", "INT"),
    # Russia (7.8%, falling sharply) — no accessible independent press, TASS is state media
    Source("TASS", "https://tass.com/rss/v2.xml", "en", "movements", "RU", state_affiliated=True),
    # China (5.9%) — no accessible independent press, CGTN is state media; generalist China feed (no
    # defence-specific feed found). max_per_run lowered on 2026-08-17: on an annotated sample (n=6),
    # 6/6 out_of_scope — not a single item kept for roughly 12 calls a day at the default cap. Not
    # removed (the only China coverage available for free, §4), but capped at the cost this yield
    # justifies.
    Source(
        "CGTN (China, general news)",
        "https://www.cgtn.com/subscribe/rss/section/china.xml",
        "en",
        "movements",
        "CN",
        state_affiliated=True,
        max_per_run=5,
    ),
    # Germany (5.6%)
    Source("Hartpunkt", "https://www.hartpunkt.de/feed/", "de", "programs", "DE"),
    Source("ESUT", "https://esut.de/feed/", "de", "movements", "DE"),
    # Italy (4.8%, +138% — the fastest growth in the top 10)
    Source("Analisi Difesa", "https://www.analisidifesa.it/feed/", "it", "programs", "IT"),
    # United Kingdom (3.6%)
    Source("UK Defence Journal", "https://ukdefencejournal.org.uk/feed/", "en", "programs", "GB"),
    # Israel (3.1%) — no SIBAT/MOD feed found, generalist press filtered downstream by the LLM.
    # max_per_run lowered on 2026-08-17: 5/6 out_of_scope on an annotated sample.
    Source(
        "Jerusalem Post (general news)",
        "https://www.jpost.com/rss/rssfeedsfrontpage.aspx",
        "en",
        "diplomacy",
        "IL",
        max_per_run=8,
    ),
    # Spain (3.0%, +29%)
    Source("Infodefensa", "https://www.infodefensa.com/feed/all", "es", "contracts", "ES"),
    # South Korea (2.2%) — no DAPA feed found, generalist Yonhap dispatches filtered downstream.
    # max_per_run lowered on 2026-08-17: 4/6 out_of_scope on an annotated sample, and the highest raw
    # volume in the perimeter after TASS.
    Source("Yonhap (general news)", "https://en.yna.co.kr/RSS/national.xml", "en", "movements", "KR", max_per_run=8),
    # Iran — outside the SIPRI top 10 (0.4%, +749%, almost exclusively towards Russia),
    # export_control coverage; Mehr News is a semi-official (government) outlet. max_per_run added on
    # 2026-08-18: 5/6 out_of_scope on the annotated sample of §7 (n=68) — the same ratio as the
    # Jerusalem Post, missed by the 2026-08-17 fix which only covered three feeds. Not removed (the
    # only Iran coverage available for free, §4), but capped at the yield it demonstrates.
    Source(
        "Mehr News (Iran)",
        "https://en.mehrnews.com/rss",
        "en",
        "export_control",
        "IR",
        state_affiliated=True,
        max_per_run=8,
    ),
    # North Korea — outside the SIPRI ranking, embargoed transfers towards Russia; NK News aggregates
    # North Korean state media (KCNA), the only workable source identified
    Source(
        "NK News",
        "https://www.nknews.org/feed/",
        "en",
        "export_control",
        "KP",
        state_affiliated=True,
    ),
]

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
LANGCHAIN_API_KEY = os.getenv("LANGCHAIN_API_KEY")

# Persistence backend (see backend/memory/persistence.py): "local" (JSON files, the default) or
# "firestore" (Cloud Run, where the disk is ephemeral and not shared between instances). The default
# is deliberately local — unlike the caps below, a missing value here is not an incomplete config but
# the normal development case, and nothing should reach GCP by default.
STORAGE_BACKEND = os.getenv("VIGIE_STORAGE", "local")
FIRESTORE_PROJECT = os.getenv("FIRESTORE_PROJECT", "")
FIRESTORE_DATABASE = os.getenv("FIRESTORE_DATABASE", "(default)")

# --- API exposure (see backend/api/main.py) ---
# Shared token required by POST /run. With no value the endpoint is closed, not open: it triggers a
# full run, so it burns the daily budget (guardrail §6) and an API bill — left open, it is a free
# denial of service for anyone who knows the URL. The fallback is therefore 503, not "no control".
# Cloud Scheduler sets this token as a header on its HTTP call; IAM locking of the Cloud Run service
# can be layered on top, it does not replace this — /events must stay reachable by a browser, which
# carries no Google identity.
RUN_TOKEN = os.getenv("RUN_TOKEN", "")
# Origins allowed to call the API from a browser. The V1 "*" let any web page read the digest on
# behalf of the visitor; it has no reason to exist once the front's origin is known. The default is
# aligned with the Vite development server (see frontend/, npm run dev).
_DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", _DEFAULT_ORIGINS).split(",") if o.strip()]

# Freshness window applied at collection time (backend/agents/collector.py): past this age, an item
# is discarded before deduplication even runs. Some institutional feeds (Defense.gov, Bruxelles2,
# NK News) expose a deep history (months, even years) with no pagination by date — without this
# filter, a first run (or a run after an outage) would submit the whole history to the daily LLM
# budget at once. An item with no published/parsable date is kept out of caution; the
# MAX_LLM_CALLS_PER_DAY guardrail remains the final safety net.
#
# Raised from 48 h to 96 h on 2026-08-17: measured live, the four US sources (43% of world exports,
# see §4) fell outside the 48 h window every other day — a slower publication cadence than the press
# agency feeds that dominate the volume (TASS, Yonhap). The cost risk that 48 h existed to cover is
# now carried by MAX_ITEMS_PER_SOURCE_PER_RUN, which bounds the number of items per feed directly
# instead of bounding it indirectly through time — widening the window therefore costs no budget.
COLLECTION_LOOKBACK_HOURS = 96

# Cap on the number of items kept per source on each run (backend/agents/collector.py), on top of
# MAX_LLM_CALLS_PER_DAY which remains the global safety net. Added on 2026-08-17: without it, a
# high-cadence press agency feed (TASS, ~45 items/day inside the measured 48 h window) consumed the
# daily budget on its own, at the expense of low-volume, high-signal specialised feeds — cost was
# allocated by what each feed publishes, not by its value to the watch. The most recent items of each
# source are kept first.
MAX_ITEMS_PER_SOURCE_PER_RUN = 12

# --- Full-text fetching (backend/agents/fetcher.py) ---
# No LLM call: fetching an article is free, only submitting it to the model costs. Introduced on
# 2026-08-31 off the back of the 2026-08-30 breakdown, which put a figure on the target — 26 calls
# per run (18% of the daily budget) lost to `quote_unverified`, for want of an RSS excerpt long
# enough to carry a verifiable quote.
#
# A switch rather than a constant: the module makes outbound HTTP requests to seventeen sites, so it
# must be possible to turn it off without a redeployment if a run starts dragging on it.
FETCH_FULL_ARTICLE = os.getenv("FETCH_FULL_ARTICLE", "true").strip().lower() not in {"0", "false", "no"}
# Per-article timeout. Deliberately short: a slow article is an acceptable degradation (fall back to
# the teaser), a run overshooting its duration target is not.
FETCH_TIMEOUT_S = float(os.getenv("FETCH_TIMEOUT_S", "15"))
# Concurrency. Measured on 2026-08-31: 13.6 s for 49 articles on 8 threads, against ~108 s
# sequentially at an average 2.2 s per-request latency. The 2026-08-30 run stood at 880 s against a
# 900 s target — fetching must remain a fraction of that margin, not consume it.
FETCH_MAX_WORKERS = int(os.getenv("FETCH_MAX_WORKERS", "8"))
# Cap on characters added per article. It does not bound the call budget (which counts calls, not
# tokens) but the tail: on the 49-article sample the median is 2,841 characters and the maximum
# 35,445 — a single article worth twelve times the median.
FETCH_MAX_CHARS = int(os.getenv("FETCH_MAX_CHARS", "12000"))
# A documented per-source waiver, rather than something discovered in production. Defense.gov answers
# 403 with or without a browser header (measured on 2026-08-31; the source now redirects to war.gov):
# its items are still collected and analysed from their teaser. Do not add a source here on a first
# failure — a one-off failure is already handled by the local fallback, this list is for a stable
# refusal.
FETCH_SKIP_SOURCES = {"Defense.gov (DoD)"}

# Mandatory guardrails (see docs/scoping.md §7) — no default value: an incomplete config must fail at
# startup rather than run with no cap.
MAX_STEPS_PER_RUN = int(os.environ["MAX_STEPS_PER_RUN"])
MAX_LLM_CALLS_PER_DAY = int(os.environ["MAX_LLM_CALLS_PER_DAY"])

# Verifier agent (first slice of V2, see docs/scoping.md §10 and backend/agents/verifier.py). Since
# 2026-08-20 the whole MECE perimeter is eligible: restricting it to export_control and arms_contract
# came from budget arithmetic (~110 items/day × 1 to 3 calls against MAX_LLM_CALLS_PER_DAY=200) that
# VERIFIER_GATE_MIN_SCORE lifts, by spending a call only where the history has something to say.
# out_of_scope does not appear here: analyze() discards it before building analyzed_items, so it
# never reaches this node.
VERIFIER_CATEGORIES = {
    "export_control",
    "arms_contract",
    "military_movement",
    "defense_diplomacy",
    "industrial_program",
}
# Escalation gate: the IDF-weighted overlap score (store._overlap_score) an antecedent must reach for
# an item to be escalated. It is no longer the category that bounds the cost but this threshold — an
# item with no candidate antecedent would produce a non-answer paid for with 2 to 3 calls.
# Measured on 2026-08-20 over the 261 items of accumulated history, with candidates restricted to
# earlier dates as exclude_links does: at 20, 23% of in-scope items are escalated (~16 calls/day
# against ~71 with no gate), and the only two corroborations the verifier found over the week
# (antecedent scores 32.0 and 35.4) are above it — no corroborated item would have been lost, while
# the best antecedent of the 18 uncorroborated items tops out at 23.1. The same value as
# THREAD_GATE_MIN_SCORE, but set on its own measurement: the threader judges story matching, the
# verifier an independent confirmation over time.
VERIFIER_GATE_MIN_SCORE = 20.0
# Per-run cap, independent of MAX_LLM_CALLS_PER_DAY (which remains the global safety net): keeps a
# single run from consuming most of the daily budget on verification alone.
MAX_VERIFIER_ESCALATIONS_PER_RUN = 15
# Cap on tool iterations per escalated item, checked in code (not through MAX_STEPS_PER_RUN, which
# counts LangGraph graph nodes — a loop internal to a node function is not subject to it).
MAX_VERIFIER_STEPS_PER_ITEM = 3

# Thread node (V3 slice 1, see docs/scoping.md §10 and backend/agents/threader.py). Unlike the
# verifier, no per-category filter: out_of_scope never reaches analyzed_items
# (backend/agents/analyst.py discards it before they are built), so every item that gets this far is
# already eligible to be attached to a story.
# Per-run cap, same role as MAX_VERIFIER_ESCALATIONS_PER_RUN, higher because eligibility is wider
# (5 categories against 2): keeps a single run from consuming most of the daily budget on thread
# grouping alone.
MAX_THREAD_ESCALATIONS_PER_RUN = 20
# Cap on tool iterations per escalated item, same role as MAX_VERIFIER_STEPS_PER_ITEM.
MAX_THREAD_STEPS_PER_ITEM = 3
# Threshold on the IDF-weighted overlap score (backend/memory/store._overlap_score) required to
# escalate an item to the model — replaces the free "at least one candidate" filter used until now,
# which 100% of items cleared and which therefore had no real effect (see docs/scoping.md §10,
# measurement of 2026-08-18). Set on 2026-08-20 from the sample of 65 hand-annotated pairs
# (backend/eval/pairs.json, backend/eval/score_pairs.py): >= 20 retains an estimated 62.0% of true
# matches against 20.2% at >= 10, for an escalation volume that stays comfortably under
# MAX_THREAD_ESCALATIONS_PER_RUN. It only applies when IDF weighting is active (window >= 3 items) —
# below that corpus size the score is a raw count of shared tokens, a different scale on which this
# figure means nothing (see backend/memory/store._overlap_score).
THREAD_GATE_MIN_SCORE = 20.0

# Default depth of the digest served by GET /events, in days. The digest is a sliding window over the
# analysed history (backend/memory/store.py), not the result of the last run: otherwise a second run
# on the same day, whose deduplication discarded nearly every item, would replace yesterday's digest
# with a handful of novelties. Bounded by the history retention (RELATED_ITEMS_WINDOW_DAYS) — we
# cannot serve deeper than we keep.
DIGEST_WINDOW_DAYS = 7
