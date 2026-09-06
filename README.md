# VIGIE — an automated watch on export control and defence/geopolitical risk

[![CI](https://github.com/adrien-morel/vigie-01/actions/workflows/ci.yml/badge.svg)](https://github.com/adrien-morel/vigie-01/actions/workflows/ci.yml)
[![Licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)

A daily pipeline that collects, classifies and summarises open sources over a restricted
defence/geopolitics perimeter, with every statement traced back to its source. Two of its five nodes
are genuine agentic loops — the model decides for itself whether to search the history before
concluding — and both are bounded in code; the rest is a deterministic workflow. That split is
deliberate, and [`docs/decisions.md`](docs/decisions.md) says why.

**Status**: V1 pipeline working end to end (collection → deduplication → classification →
verification → thread grouping → API → frontend), with the first slice of the V2 verifier and the
first slice of V3 longitudinal reasoning shipped. **Deployed to Google Cloud on 2026-09-05**: the
digest is live at <https://vigie-507713.web.app>, served by a Cloud Run API reading a Firestore
database, fed by a batch Job, with continuous deployment on every push and the infrastructure
described in Terraform. Firestore, the one component that had never run against anything real, has
run, and the daily scheduler has been armed since 2026-09-06. **What is not yet settled**: no
unattended cycle has been observed yet — the first firing is due on 2026-09-07 — and the seven-day
purge will not be observable until 2026-09-12. Detail in [Roadmap](#roadmap).

The reasoning behind the technical decisions — guardrails, durability invariants, display rules, how
the campaign was run — is in [`docs/decisions.md`](docs/decisions.md). The product scoping is in
[`docs/scoping.md`](docs/scoping.md).

> **The three captures below predate the English pass of 2026-09-06 and show the interface in
> French.** The layout, the indicators and the display rules they document are unchanged — only the
> labels and the generated summaries are. They are not regenerated today on purpose: the history is
> bilingual until the seven-day retention window has purged the records written before the pass, so a
> capture taken now would document the transition rather than the product. Due on 2026-09-12.

![The VIGIE digest: a single command bar (views, depth, sort), a filter rail on the left, an indicator strip, and event cards carrying the verified quote, the outlet's mark, the "state media" provenance and an explicit verification state; at the top of the list, a thread bringing three sources together on one story](docs/screenshot.png)

Every card carries the signals that commit confidence — a quote verified verbatim, an antecedent
found or not in the history, "state media" provenance, the verifier's score — and an item the
verifier did not escalate comes out **without** a score rather than with a misleading zero, saying
which of the reasons applies. Those mentions are aligned from one card to the next: over a digest of
two hundred items they are scanned in one pass instead of being read card by card.

![A geographic coverage map built on the verified location of each event, with a count of the items with no place extracted and of the places not attachable to a country](docs/screenshot-map.png)

The map is built on the verified location of each event, never on the country of the source, and it
displays what it cannot place rather than overstating its coverage. Four attachment levels — cited,
inferred, actor, presumed domestic — stay counted separately.

![The Threads view: one story followed by several sources, its timeline at the real scale of time, and the crossing between the outlet's country and the event's, with the four attachment levels counted separately](docs/screenshot-threads.png)

A **thread** brings together the articles that cover the same story — same parties, same operation —
and not the same theme. Its timeline is at the real scale of time: the gap between publications is
the signal. No reliability indicator is aggregated at thread level.

## Scoping

Full scoping — problem statement, MECE perimeter, alternatives assessed, KPIs, risk matrix,
governance, delivery plan — in [`docs/scoping.md`](docs/scoping.md). Visual summary: a
[navigable slide deck](https://adrien-morel.github.io/vigie-01/slides.html) (source:
[`docs/slides.html`](docs/slides.html)).

**Value**: cut the daily synthesis time, standardise how weak signals are read, trace the
reliability of every piece of information surfaced.

**V1 perimeter**: export control, arms contracts, military movements, defence diplomacy, industrial
programmes — thematic filtering only (the location is extracted as metadata, without restricting
collection, see scoping §4).

**Sources**: 18 free RSS feeds, organised by country rather than by theme — the world's top 10 arms
exporters (SIPRI *Trends in International Arms Transfers*, 2020-24 data) plus Iran and North Korea
for export-control coverage. Every feed is validated live before integration; state sources (the only
free option available for several of those countries) are marked `state_affiliated` and stay visible
as such downstream, rather than being excluded or silently mixed in with the rest. Volume is capped
per feed (`MAX_ITEMS_PER_SOURCE_PER_RUN`, see Guardrails below) rather than treating every feed
equally: without that cap, a high-cadence press agency exhausted the daily budget at the expense of
specialised sources with lower volume but stronger signal.

## Architecture

```
Sources (RSS by country, specialised press, communiqués)
        │
        ▼
  Collector agent ───► Short memory ─────► Analyst agent
   (backend/agents/     (deduplication,     (classification, summary,
    collector.py)        before the LLM      verified quote)
                          call)              backend/agents/analyst.py
                          backend/memory/            │
                          store.py                   ▼
                                            Verifier agent
                                            (backend/agents/verifier.py)
                                            cross-checking against the history,
                                            confidence score
                                                     │
                                                     ▼
                                            Grouping agent
                                            (backend/agents/threader.py)
                                            event threads over the history
                                                     │
                                                     ▼
                                     API (FastAPI) ──► Front (filterable digest,
                                     backend/api/       threads, coverage map)
                                     main.py             frontend/ (React + Vite)
```

Implemented as a LangGraph `StateGraph` (`backend/graph.py`): each step is a node, and the shared
state (`VigieState`, `backend/state.py`) carries the items from one node to the next. Deduplication
sits *before* the LLM call, not after, so as not to spend budget on items already seen. LangSmith
traces every node with no manual instrumentation.

Four decisions shape this pipeline — the digest as a sliding window and not a snapshot of a run,
persistence behind a single interface, the deliberate separation between a deterministic workflow and
an agentic loop, and the accepted divergences of thread grouping. They are documented in
[`docs/decisions.md`](docs/decisions.md).

## Measured results

Dated figures, not targets. Definitions and methodological caveats in
[`docs/scoping.md` §7](docs/scoping.md); tooling in `backend/eval/`.

| Measurement | Result | Target |
|---|---|---|
| Classification precision (2026-08-22, n=48, blind annotation) | 37/48 = **77%**, 95% CI [63%; 87%] | ≥ 85% |
| → perimeter decision alone (in / out) | 42/48 = 87.5% — precision 89%, recall 89% (F1 0.89) | — |
| → weakest category | `industrial_program` — F1 0.64, 8 of the 11 disagreements | — |
| Source coverage (2026-08-30, 96 h window) | 17/18 feeds active | — |
| Items dropped by the per-source cap (same window) | 234 across 7 feeds | — |
| History accumulated (2026-08-30) | 45 items over one day — the 295 items accumulated up to 2026-08-22 left the 7-day sliding window during an 8-day gap with no launch, and were purged on the following run | — |
| Cost of a full run (2026-08-22) | 195 LLM calls against a cap of 200 — analysis 72, verification 50, grouping 73 | — |
| Analysis spend discarded (2026-08-30, first full batch broken down) | 99 of the 144 analysis calls (**69%**) on items not kept — out of scope 72, unverifiable quote 26 | — |
| Retest of the `arms_contract`/`industrial_program` boundary (2026-08-23, n=17, 2 arms) | target met: 2 cases gained, 0 regression introduced — but 2 **earlier** regressions found and attributed to the previous day's change | — |

That precision figure **has aged**: the classification prompt has changed twice since it was measured
(on 2026-08-22 and 2026-08-23), and remeasuring costs a whole day's budget. It remains the last blind
measurement available, not a description of the current code.

At that sample size, **the 85% target sits inside the confidence interval**: the measurement
therefore concludes neither that the product meets it nor that it falls short. The previous
measurement (75%, n=68) excluded it, but the two are not comparable — this one is the first annotated
blind, the source composition has changed, and the prompt has received the §4 boundary
clarifications.

The breakdown is what remains useful: noise filtering meets the target, fine qualification does not,
and a single boundary carries most of the gap — the one between `arms_contract` and
`industrial_program`, with a constant pattern across two measurements: the model classifies from the
visible actor (a customer navy) rather than from the subject of the article (a construction or
delivery milestone). The analysis corrected its own diagnosis along the way: the scoping document
stated nothing about that boundary, but the classification prompt had carried an undocumented rule
for five days — so on the clearest case, the model was faithfully applying a written rule the
annotation contradicts. A disagreement about the specification, not a gap in it: the rule was
**changed** and carried back into the scoping document, a delivery now belonging to the programme and
`arms_contract` tightening onto the commercial act. Probed the same day on the two remaining calls, it
is **only half effective**: the delivery case flips as intended, the funding case does not move even
though the rule names it word for word. A rule can be written, correct, and still have no effect — a
full retest with non-regression controls is owed before it can be considered settled. The precedent
that makes the operation predictable: the `defense_diplomacy` / `military_movement` boundary,
specified after an earlier measurement where it dominated, is today the best held in the sample.

Two earlier measurements (n=30 then n=88) and the definition fixes they triggered are detailed in
[§7](docs/scoping.md). What is **not** measured is said as such: the verifier, whose extension to the
five categories ran for real for the first time on 2026-08-21, produced 15 scores over 36 items that
day (5 with an antecedent), against 20 scores over 261 items — 2 with an antecedent — under the old
per-category rule. Grouping counts 11 threads. The threads' acceptance criterion is **met**: over the
sample of 65 pairs frozen and annotated on 2026-08-20, all 13 intra-thread pairs are judged to be the
same story (100% precision) — a precision, not a recall, since a story the model failed to bring
together produces no pair to annotate.

## Stack

| Component | Choice | Status |
|-----------------|-------------------------------------------|------------------------|
| Orchestration | LangGraph / LangChain | built (V1) |
| LLM | Claude Haiku through `langchain-anthropic` | built (V1) |
| Backend | Python 3.13, FastAPI | built (V1) |
| Observability | LangSmith (native per-node tracing) | built (V1) |
| Frontend | React + TypeScript + Vite | built (V1) |
| Verifier (cross-checking, confidence score) | LangGraph + bounded tool-calling | 1st slice built; perimeter extended to the 5 categories, escalation conditioned on an antecedent |
| Interactive coverage map | d3-geo + Natural Earth, on the `location` field | built (V2, 1st slice) |
| Event threads (longitudinal grouping) | LangGraph + bounded tool-calling, timeline and provenance on the front | 1st slice built (V3) |
| Deployment | Cloud Run **Job** (daily run) + service (digest); front on Firebase Hosting; continuous deployment through Cloud Build on push | **in production since 2026-09-05**; scheduler armed on 2026-09-06, first unattended cycle **not yet observed** |
| Infrastructure | Terraform, adopting the hand-created resources rather than recreating them | 26 resources under management, `plan` converged |
| Logging | Structured JSON on stdout, read by Cloud Logging | validated in production, accents included |
| Storage | Local JSON files (dev) / Firestore (production), behind a single interface | **validated against a real database on 2026-09-05**, including the budget reservation in a transaction under concurrency |

## Repository layout

```
vigie/
├── backend/
│   ├── agents/
│   │   ├── collector.py       # RSS collection by country, sources validated live
│   │   ├── analyst.py         # MECE classification, English summary, verified quote + place
│   │   ├── verifier.py        # cross-checking + confidence score (bounded tool-calling loop)
│   │   └── threader.py        # grouping into event threads (same bounded pattern)
│   ├── api/
│   │   └── main.py            # FastAPI: /health, /run, /events
│   ├── eval/
│   │   ├── build_sample.py    # stratified sample to measure precision
│   │   ├── annotate.py        # interactive manual annotation
│   │   ├── score.py           # measured precision vs target (scoping §7)
│   │   ├── candidates.py      # density of cross-check candidates, with no LLM call
│   │   ├── build_pairs.py     # freezes a sample of pairs (threads + score bands)
│   │   ├── annotate_pairs.py  # manual "same story?" annotation
│   │   └── score_pairs.py     # threading precision + effect of a threshold
│   ├── memory/
│   │   ├── store.py           # deduplication + analysed history (cross-checking and digest)
│   │   └── persistence.py     # local JSON files (dev) or Firestore (prod), same interface
│   ├── config.py              # RSS sources by country, mandatory guardrails, API exposure
│   ├── guardrails.py          # daily LLM call cap
│   ├── graph.py               # LangGraph StateGraph assembly
│   ├── job.py                 # entry point of the daily Job (deployment)
│   ├── logging_setup.py       # structured JSON log, usable by Cloud Logging
│   ├── state.py               # shared state schema (VigieState)
│   ├── requirements.txt
│   └── requirements-gcp.txt   # Firestore dependency, deployment only
├── frontend/                  # React + TypeScript + Vite, calls the real API
│   ├── src/
│   │   ├── assets/logos/      # outlet marks, collected offline (see scripts/)
│   │   ├── components/        # filterable digest, threads (timeline + provenance),
│   │   │                      #   coverage map
│   │   └── lib/               # taxonomy, filters/sort, place resolution, thread model
│   └── firebase.json          # front hosting (Firebase Hosting)
├── scripts/
│   ├── daily_run.py           # daily launch + campaign log (not part of the service)
│   └── fetch_logos.py         # one-off collection of outlet logos (not part of the service)
├── tests/                     # pytest — LLM and RSS feeds mocked
├── infra/
│   └── README.md              # production rollout runbook, command by command
├── docs/
│   ├── scoping.md             # product scoping (problem, MECE, risks, KPIs)
│   ├── decisions.md           # engineering choices: guardrails, invariants, campaign
│   ├── index.html             # GitHub Pages root (redirects to the slides)
│   ├── slides.html            # navigable slide deck
│   └── screenshot*.png        # captures against the real application — French UI, predate
│                              # the English pass, due for regeneration on 2026-09-12
├── Dockerfile                 # one image, two uses: the service and the Job
├── .dockerignore
├── .env.example
├── LICENSE
└── README.md
```

## Quick start

```bash
git clone https://github.com/adrien-morel/vigie-01.git
cd vigie-01

python -m venv .venv
source .venv/bin/activate        # .venv\Scripts\activate on Windows

pip install -r backend/requirements.txt

cp .env.example .env             # fill in ANTHROPIC_API_KEY, LANGCHAIN_API_KEY (LangSmith),
                                 # MAX_STEPS_PER_RUN, MAX_LLM_CALLS_PER_DAY (mandatory guardrails),
                                 # and RUN_TOKEN to be able to call POST /run

uvicorn backend.api.main:app --reload --port 8080
```

In a second terminal, for the frontend:

```bash
cd frontend
npm install
npm run dev
```

The outlet marks shown on the cards are versioned with the front; they are only re-collected when
`backend/config.py` gains a source (`python -m scripts.fetch_logos`, no LLM call). A source with no
logo is displayed as a monogram.

Open `http://localhost:5173`. The front reads the digest, it does not trigger it: collection is
launched server-side, through `python -m scripts.daily_run` or `POST /run` (full pipeline, ~10 min,
spends real LLM budget). That endpoint is closed behind a shared token — it answers 503 as long as
`RUN_TOKEN` is undefined, then requires the `X-Run-Token` header — because it triggers the whole
day's spending on its own. The API URL defaults to `http://localhost:8080`, overridable through
`VITE_API_BASE`; the origins allowed to call it from a browser are listed in `ALLOWED_ORIGINS`.

## History accumulation

This script predates the scheduler, armed on 2026-09-06, and is kept for a one-off launch. The
script logs **every** launch, including those that produce nothing and those that fail: a day with no
novelty and a day with no launch leave the same trace in the history, yet the first is a measurement
and the second is a hole.

```bash
python -m scripts.daily_run              # the daily launch
python -m scripts.daily_run --dry-run    # campaign status, without spending budget
```

**Campaign closed on 2026-08-20** (5 launches, 7 continuous days, 261 items). It aimed at fifteen
days of history before replaying the matching measurement; retention having been brought down the
same day from 30 to 7 days for storage cost, that base became unreachable by construction — the
oldest day is purged on every run. The measurement was therefore taken over seven days, and at that
size it discriminates (see [§10](docs/scoping.md)).

A consequence of method that holds from here on: **a corpus is frozen outside the store at the moment
it is measured**. A measurement that re-reads the history on demand is not replayable — recomputed a
week later, it finds none of the original items, and a manual annotation would be lost with them.

Why the campaign existed, the catch-up window and the coverage KPI:
[`docs/decisions.md`](docs/decisions.md).

## Roadmap

- [x] V1 — collection + deduplication + classification + traced summary + API + frontend
- [x] V1 — sources organised by country (SIPRI top 10 exporters + Iran/North Korea), validated live
- [x] V1 — Cloud Run deployment: **in production on 2026-09-05**. The repository half had been
  delivered on 2026-08-23 (structured JSON log across the five nodes, `POST /run` closed behind a
  token, restricted CORS, pinned dependencies, Python 3.13 image, execution Job); the cloud half
  followed in a single session — Firestore database, Cloud Run service and Job, continuous deployment
  through Cloud Build triggered by push, front on Firebase Hosting, and the whole adopted under
  Terraform rather than recreated, since a Firestore database's region cannot be revised. **First
  real run**: 615 s, 156 articles submitted, 61 kept, 195 calls out of 200, not truncated. **Three
  checks only production can give** have passed — Firestore on write, deduplication reading back what
  it wrote, and above all the budget reservation **in a transaction under real concurrency**: 30
  simultaneous reservations across 3 containers for 4 slots, exactly 4 accepted. What remains is the
  first unattended cycle — the scheduler was armed on 2026-09-06 and its trigger validated by a
  forced execution, but an armed trigger is not an observed cycle — and the seven-day purge, which
  can only be observed on 2026-09-12. Runbook and Terraform module in [`infra/`](infra/README.md)
- [~] V2 — verifier agent: cross-checking and confidence score delivered; perimeter extended to the
  five categories on 2026-08-20, escalation conditioned on a measured candidate antecedent rather than
  on the category, and run for real on 2026-08-21 (15 escalations over 36 items, 5 with an
  antecedent); `fetch_full_article` delivered on 2026-08-31 behind a switch, on a classification
  justification and not a citation one — the measurement that motivated it pointed at the wrong fix,
  see [§11](docs/scoping.md)
- [~] V2 — interactive coverage map delivered (filtering by country from the `location` field);
  sectorisation by theme to come
- [~] V3 — longitudinal reasoning over the history: the pipeline treated each item in isolation, when
  part of the signal lies between items (a story that evolves, a country whose frequency rises). Five
  sequenced slices, scoped in [§10](docs/scoping.md):
  - [x] event threads — group the items of a single story, displayed as a timeline at the real scale
    of time with the outlet/event-location crossing. Acceptance criterion **met** (2026-08-20): 100%
    precision over the 13 annotated intra-thread pairs
  - [ ] weekly brief — volume trends by category/country against the previous week, figures from an
    aggregation and not from the model
  - [ ] weak-signal detection — an unusual concentration of corroborated items on a country/category
    pair
  - [ ] temporal display — a time axis for the volume series, distinct from the per-story thread
  - [ ] queryable memory (natural-language questions)

## Guardrails

A daily LLM call cap, a per-run step cap, a double cap on each agentic loop, a freshness window and a
per-source cap at collection time, automatic rejection of a summary with no verifiable quote. All
checked in code, not merely declared in configuration — and a cap that is reached **truncates** the
run instead of cancelling it, so that a cost guardrail does not destroy the work it has just made you
pay for. Detail of each, and what each has cost: [`docs/decisions.md`](docs/decisions.md).

## Quality & CI

- Lint and format: `ruff` (config in `pyproject.toml`)
- Tests: `pytest` (`tests/`, LLM and RSS feeds mocked — fast, deterministic, free)
- CI: `.github/workflows/ci.yml`, runs lint + format + tests on every push/PR

## Note

A demonstration project with a portfolio purpose. The pipeline and the API are real and working (live
RSS sources, real LLM calls, real measurements), and have been in production since 2026-09-05. Two
caveats worth stating rather than leaving unsaid. The daily scheduler was armed on 2026-09-06 but
no unattended cycle has been observed yet: the trigger is validated, the autonomy is not. And the verifier only scores the items whose history
holds an antecedent to cross-check against: the others come out with no confidence score rather than
with one fabricated by default — that is a choice, not a gap.

## Licence

[MIT](LICENSE) — the code is freely reusable, including commercially, provided the copyright notice
is kept. The screenshots reproduce press headlines whose rights remain with their respective
publishers.
