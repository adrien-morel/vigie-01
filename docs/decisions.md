# Engineering choices

This document carries the "why" behind VIGIE-01's technical decisions: guardrails, durability
invariants, display rules, how the accumulation campaign was run. It was extracted from the
[`README.md`](../README.md), which keeps only the conclusions — a reader should be able to understand
the project in a few minutes without going through the reasoning, and find it here when they look
for it.

The product scoping — problem statement, MECE perimeter, KPIs, risk matrix, delivery plan — is in
[`scoping.md`](scoping.md). This document does not duplicate it: it documents the implementation
decisions taken to serve it.

## What the digest commits to on screen

The digest exposes the signals that commit confidence rather than a mere list of articles: the
verifier's confidence score, an antecedent found or not in the history, "state media" provenance, a
quote verified verbatim. An item outside the verifier's perimeter comes out with no score rather than
with a misleading zero.

The label reads "with / without an antecedent" and not "cross-checked". The field measures what the
history contained at the moment the article went to the verifier, and the articles of one collection
batch are mutually invisible to cross-checking (`exclude_links`): a thread of three sources can
therefore legitimately show a single antecedent. Read as "cross-checked" next to that same thread,
the label came across as a contradiction.

## What survives scrolling

A seven-day digest holds two hundred items, that is a page some fifty thousand pixels tall. Anything
not bound to the top of the screen is out of reach by the third article: the view selector, the
digest depth and the sort therefore live in the title bar itself, which thus carries something
instead of lining up a logo and a button on either side of a void.

The active filters are echoed as removable chips under that bar. The echo deliberately duplicates the
filter rail's state: the rail is where a filtering is *composed* — it carries the facet counts, which
say what each facet would yield if selected — the chips where it is *read* and undone, at the moment
one looks at its results. Without them, a digest filtered down to three items is indistinguishable
from an empty one.

The indicator tiles, by contrast, keep covering the whole digest when a filter is active, and say so.
Their denominators — escalatable items, verified items — are what make them honest; recomputing them
over a subset would make a coverage rate move with a click on a facet, which makes no sense for a
coverage measurement.

The filter rail scrolls for itself, bounded to the window's height. Stuck under the bar with no
bounded height, it kept its top pinned and pushed its bottom — the last source countries, the reset
button — off screen with no way to reach it: the wheel scrolled the page, not the rail, and the
bottom only reappeared at the end of the document. The bound is computed from the bar's measured
height, never from a constant, which drifts as soon as the bar wraps onto two lines.

## The card carries its mentions on its title line

The layout takes the full width of the window. It was capped and centred for a while, to bound the
summary's line length — on a very large screen it reaches two hundred and fifty characters, which the
eye does not follow from one line's end to the next one's start. The cap cost more than it returned:
the map, the indicator strip and the thread timelines are objects that gain from spreading out, and
two empty bands on either side of the digest read as a layout defect. What stays bounded is the
methodological notes, which are read in full or not at all.

The verification mentions sit on the card's title line rather than in a side column. The side column
was tried — it reserved two hundred pixels down the whole height of the card for one or two badges
and left an empty flank below. On the title line they take the room they ask for and no more, while
staying aligned from one card to the next: the verification state is present on *every* item, most
often "unverified" since the escalation gate makes that the majority case, and a constant piece of
information must not occupy the most readable place nor be re-read card by card.

## Outlet marks are collected, not borrowed

The outlet's mark closes the title line: the source is recognised at a glance down the list, where
its name in the card footer takes reading. The files are fetched once by `scripts/fetch_logos.py` and
versioned with the front, never loaded from the origin sites at display time. Serving them live would
send seventeen requests to third parties every time the digest is opened — TASS, CGTN and Mehr News
included — would give them the reader's IP address, and would make the interface dependent on the
availability of sites chosen precisely for their content, not for their technical reliability.

Three sources out of eighteen refused collection and are shown as monograms. The fallback is the
normal behaviour, not a fault to fix: a source added without rerunning the script is shown as a
monogram too, never as a broken image.

## The coverage map, and what it refuses to merge

The map is built on the `location` field verified per item, not on the country of the source, and
explicitly displays what it cannot place — places not attachable to a country (maritime spaces,
international straits, transnational regions). A map that showed only its successes would overstate
the real coverage.

Four attachment levels are counted separately and detailed on hover, since presumed coverage must not
read as cited coverage: the country is **cited** by the source; it is **inferred** by the model from a
named town ("Darwin" → Australia); it is inferred from the **actor** when no theatre is attachable
("Houthis" → Yemen); or, failing everything, the event is **presumed domestic** to the outlet's
country — on a judgement of the article's content, never on the outlet's origin alone, which would
place a TASS dispatch about Yemen in Russia.

The **actor** level was added on 2026-08-20 on a reading observation: five items of the week stayed
off the map even though their source explicitly named the protagonist — "Houthis attack eight Saudi
oil tankers" (Red Sea, Gulf of Aden), "Hormuz will remain under Iranian control" (an international
strait). The theatre there is either absent or correctly judged not attachable to a country: refusing
to place it is the right answer for a *place*, but it was losing information written in black and
white. The protagonist is therefore extracted and verified verbatim like the place, and the country
inferred from it follows the same bounds (emptied if the excerpt is not verified, validated against
the cartographic reference list, counted separately). It is deliberately not an extension of the
inferred level: both infer a country, but one answers "where" and the other "who". Merging them would
make the origin of an action read as its theatre — exactly the error the separation of provenances
exists to prevent. Hence the resolution order: an attachable theatre always beats the actor.

## Event threads

A **thread** brings together the articles that cover the same story — same parties, same operation,
same contract — and not the same theme nor the same country. Its timeline is drawn at the real scale
of time: three dispatches landing in twenty minutes and a story spread over three weeks must not look
alike, the gap between publications being precisely the signal (who breaks the story, how long the
pickup takes to follow). An article its feed does not date is placed on its entry into the store and
marked as such, never presented as a publication time — `first_seen` is a batch timestamp, shared by
every item of the same run.

No aggregate reliability indicator is computed at thread level: averaging scores of which some are
`null` would implicitly fill that gap and make an unverified thread look like a moderately reliable
one. The verification counters are therefore rendered separately, distinguishing "not escalated for
want of budget" from "outside the verifier's perimeter" — two different silences, neither of which
amounts to a score. The provenance block crosses the outlet's country with the event's country
without ever conflating them: a thread covered by a foreign state agency does not read like domestic
coverage.

An article no thread brings together says which of the four states applies to it, for the same reason
an article with no score says which of the silences applies to it. Until 2026-08-21, an absent
`thread_id` carried those four situations with no sign separating them: the history contained no
story close enough to warrant a match; the model examined a candidate and concluded it did not cover
the same story; the run cap or the daily budget cut in before the question was asked; or the article
predates the instrumentation. The first two are measurements, the third is an absence of measurement,
and the confusion was not theoretical — the 2026-08-21 run left fourteen eligible articles outside
any thread for want of budget, rendered on screen exactly like articles that had been checked and
found to belong to no story. The display was therefore asserting something the system had not
measured, which is worse than the cut itself.

Two fields are needed where the verifier makes do with the existence of a candidate antecedent, and
the difference lies in the nature of the two nodes: a verifier escalation always produces a score,
whereas a grouping escalation can legitimately attach nothing. The gate's result is therefore not
enough on its own, one also has to know whether the model concluded. The number of threads displayed
otherwise reading as the number of stories the digest contains, the Threads view additionally carries
the count of articles never submitted for matching: that is what makes it possible to accept degraded
grouping on heavy days rather than pass over it in silence.

## The digest is a sliding window, not a snapshot of the last run

Since deduplication discards, before any LLM call, whatever has already been seen in the last seven
days, a second collection on the same day produces only a handful of new items. Serving that raw
result would amount to erasing the display on every collection. `GET /events` therefore reads the
history of analysed items over a configurable depth (`?days=`, bounded by the 7-day retention), and
the same history feeds the verifier's cross-check search — one store, two uses.

## Persistence: one interface, two implementations

(`backend/memory/persistence.py`). Three states survive runs: the LLM budget counter, the links
already seen and the analysed history. In development these are JSON files; in production they are
Firestore documents, because Cloud Run's file system is ephemeral and specific to each instance. The
difference is not merely a persistence convenience: with a counter on a local disk,
`MAX_LLM_CALLS_PER_DAY` would become circumventable by a simple restart. The call reservation is
therefore exposed as a storage operation (`reserve_llm_call`), atomic through a transaction on the
Firestore side, rather than as a read-modify-write done by the caller — which would be correct
locally and wrong across instances. The local backend stays the default: nothing reaches GCP without
an explicit `VIGIE_STORAGE=firestore`.

## Deterministic workflow and agentic loop, separated deliberately

The `collect`/`deduplicate`/`analyze` nodes form a fixed code path: one LLM call per item, no dynamic
decision by the model — the right trade-off for a traceable, cheap classification task. The `verify`
and `thread` nodes are the two points of real autonomy: there the model has a search tool over the
history of analysed items and decides for itself whether to call it, how many times, before
concluding. Every escalation is bounded in code — number of items per run, number of tool iterations
per item, and a deterministic gate that decides whether the item warrants a call — so that agency
remains a controlled cost and not one proportional to the volume collected.

## Two extensions of autonomy that would cost no call

What costs is not the decision, it is the call: the daily cap counts model calls, and a full run now
consumes all 200 of them — 148 before the verifier was extended to the five categories, on
2026-08-20. Additional autonomy is therefore free as long as it adds no call — either because it
slips into a call already paid for, or because it does not go through the model at all. Both leads
below were identified on 2026-08-20; **neither is implemented**, and the second is not yet computable
for want of a counter.

**Deciding inside a call already paid for.** The analyst reads each article and does nothing but fill
in a form — category, summary, quote, place, actor. It has no latitude, when its structured response
could carry one more decision without changing the number of calls. Two candidates. The first is a
**verification priority**: the gate now says which items are eligible, on a measured basis, but
`MAX_VERIFIER_ESCALATIONS_PER_RUN` keeps cutting in order of arrival — that is, in the order the
sources are written in `backend/config.py`, then by freshness within a feed. The eligibility rule is
explicit and exposed; the cut under the cap is not, and it becomes binding again on high-volume days.
Letting the analyst mark what deserves verifying first would replace a file order with a judgement.
The second is an **abstention** — "the text provided is too short to decide" — which is the natural
precondition of `fetch_full_article`: fetching an article costs no call, only re-analysing it does,
so designating the articles that deserve it turns a job proportional to volume into a capped one. In
both cases the condition already set for the gates applies: the decision must be readable on screen,
without which it is merely one more arbitrary rule, moved from the configuration file to the model.

**Deciding the allocation with no model at all.** The per-source cap is uniform (12 items), with a
manual per-feed override (`Source.max_per_run`) already justified by yield — CGTN, Jerusalem Post and
Yonhap are capped there at the calls-per-kept-item ratio they demonstrate ([§4](scoping.md)). Making
that setting automatic requires no call: it is arithmetic in `collect()`, before any spending. All it
lacks is the means to compute it. The numerator exists — every record in the history carries its
source. The denominator does not: an item classified `out_of_scope`, or whose quote does not verify,
is discarded by a `continue` in `backend/agents/analyst.py` and leaves no trace, even though its call
was paid for. Counting takes three precautions. The rejection reasons stay separate — a source that
produces out-of-scope material is noisy, a source whose quotes fail has a truncated feed, and that is
exactly what full-text fetching would repair: conflating them would trim the very feeds the next job
is meant to save. These counters are business state, so they go through `persistence.py` and not
through the operational log of `scripts/daily_run.py`, which is the accepted exception to that rule
precisely because it carries no business state — and which does not ship to production. Finally they
must escape the seven-day purge: a quota rule whose computation base is erased every week is not a
rule.

**Progress of 2026-08-22, partial and not to be taken as settled.** The denominator described above
received a first element: `analyst.submissions_by_source()` records the outcome given to each article
submitted, by (source, reason) pair, and the launch tool logs it. The first of the three precautions
is therefore respected by construction — the rejection reasons are separate, an off-topic feed and a
feed with excerpts too short do not get confused, which is exactly the distinction the full-text
fetching job depends on. **The other two are not**: this counter lives in memory, reset on every run,
and therefore goes neither through the persistence layer nor beyond the purge. That is deliberate —
it was built to attribute a run's analysis spending, a question opened the same day by the first
per-node budget split, and not to found a quota rule. An adaptive per-source allocation therefore
stays out of reach: it needs a durable counter, and this one is not. What is settled is the counting
method and its key; what is missing is the support.

**What forbids turning this into a pure yield rule.** An allocation that follows yield concentrates
the corpus, and the corpus is an input to everything else. Three reasons, all already measured. **The
per-source cap exists to deconcentrate**: before it, 256 items of which 35.5% TASS; after, 138 items
and a largest contributor at 8.7%. Yet TASS produces 69 of the 199 analysed items of the measured
week, the best yield in the panel — following yield would give places back to the state agency the
cap had been set to dilute, and would undo the fix through the very lever it created. **A
concentrated corpus then distorts the measurements made on it**: on 2026-08-16, on a corpus dominated
by TASS, IDF weighting corrected nothing — `infrastructures` was statistically rare there while
remaining generic vocabulary, and the best-scoring pair brought together two unrelated dispatches.
The same measurement replayed after the sources were rebalanced reversed itself: a threshold
calibrated on an unbalanced corpus settles the imbalance, not the phenomenon. **And corroboration
needs independent sources**: since `exclude_links` makes the items of one batch mutually invisible,
an antecedent necessarily comes from another day — and is only worth something if it also comes from
another editorial line. Concentrating collection would mechanically thin out what the V2 acceptance
criterion measures, that is, would make the verifier pay the budget it had been saved.

The quota rule is therefore subordinate to source diversity, never the reverse: a strictly positive
floor — a source brought down to zero stops producing the evidence that could rehabilitate it — and a
human judgement already made to be preserved, the one that capped CGTN, Jerusalem Post and Yonhap
without removing them, for want of other free coverage for China and of a usable institutional feed
for Israel and South Korea. Like both gates, such a threshold will have to be calibrated on a frozen
base rather than set by judgement.

## Thread grouping reuses this pattern, with two accepted divergences

Unlike the verifier, the `thread` node applies no per-category filter: `out_of_scope` never reaches
`analyzed_items`, so every item that gets there is already eligible to be attached to a story. And it
does not exclude the current batch — two sources covering the same event on the same day are on the
contrary the clearest case of "same story", where the verifier's corroboration requires an
independent confirmation over time. Until 2026-08-20, escalation was preceded by a free filter (the
existence of at least one keyword-overlap candidate) rather than by a similarity threshold: the
accumulated history was still too thin to calibrate one, and an uncalibrated threshold would have
been an arbitrary choice dressed up as a measurement.

**Measurement of 2026-08-18.** Over 199 real items, that free filter was cleared by 100% of items:
its query being the whole title and summary, it almost always shares a token with at least one record
in the window. It therefore did not constitute a second guardrail. The overlap score has, on the
other hand, been weighted since the same date by how rare words are in the window (IDF): the raw
count was dominated by stop words, 64% of the score being carried by tokens present in more than a
fifth of the corpus, and a third of the candidates served to the model changed — that corrected the
ranking, not the gate.

**Threshold set on 2026-08-20**, once the accumulation campaign was closed and a sample of 65 pairs
annotated by hand (§ below, `backend/eval/pairs.json`). Reweighted by the real population of each
score band, the estimated precision goes from 20.2% at ≥ 10 (the free filter, in practice) to 62.0%
at ≥ 20 on the scale actually applied. `THREAD_GATE_MIN_SCORE = 20` (`backend/config.py`) therefore
replaces the free filter, applied by `search_thread_candidates` through its `min_score` parameter —
but only when IDF weighting is active (window ≥ 3 items): below that, the score falls back to a raw
count of shared tokens, a scale on which this threshold means nothing, and the filter keeps its old
behaviour so as not to exclude the canonical thread case (two sources from the same run, history
still empty). The overlap score itself says nothing about the quality of the grouping taken in
isolation — the ground truth amounts to a single thread; it is the annotation of the intra-thread
pairs, not that score, that measures threading precision (100% over 13/13, § below).

## Guardrails, implemented from V1

- `backend/guardrails.py` — daily LLM call cap, tested both ways (real triggering verified, a normal
  run unaffected). It also covers the verifier's calls, with no separate counter. When reached, it
  **truncates** the run instead of cancelling it: the items already analysed are recorded and served,
  those not submitted to the model stay collectable on the next cycle, and the API answers an explicit
  partial success (`truncated`) rather than an error — without which the cost guardrail would destroy
  the work it has just made you pay for
- `backend/guardrails.py` — charging each call to the node that obtains it (`calls_by_node()`), added
  on 2026-08-21. This is not a guardrail but what makes the previous one arbitrable: the cap being a
  single global counter, widening one node does not consume "extra" calls, it takes them from the next
  node — observed the same day, when the extended verifier made the cap fall on grouping, last in the
  chain. The measurement is held in memory and outside the persistence layer that carries the cap, by
  design: it does not need the atomicity a reservation requires, and putting it there would mean
  changing the persistence interface and both its implementations, including a Firestore backend never
  executed against a real database. A refused call is charged to nobody — the reservation precedes the
  model call, so it cost nothing. **First real split on 2026-08-22**: analysis 72, verification 50,
  grouping 73 over a batch of 31 kept articles, that is 195 of the day's 200 calls (see below)
- `backend/graph.py` — per-run step cap (`MAX_STEPS_PER_RUN`), applied through LangGraph's
  `recursion_limit` — protection against a runaway agent loop (scoping §8), tested both ways
- `backend/agents/verifier.py` — a double cap on agentic escalation: the number of items escalated per
  run and the number of tool iterations per item. Checked in code and not through `MAX_STEPS_PER_RUN`,
  which counts graph nodes and does not bound a loop internal to a node
- `backend/agents/threader.py` — the same double cap (`MAX_THREAD_ESCALATIONS_PER_RUN`,
  `MAX_THREAD_STEPS_PER_ITEM`), with no separate budget counter: grouping goes through the shared daily
  guardrail. Its per-run cap is higher than the verifier's, eligibility being wider (five categories
  against two), and it is preceded by a gate with no LLM cost that only escalates items whose best
  candidate reaches `THREAD_GATE_MIN_SCORE` (set on 2026-08-20, see below)
- `backend/agents/collector.py` — freshness window (`COLLECTION_LOOKBACK_HOURS`): several institutional
  feeds expose months of history with no pagination by date; without this filter, a first run would
  submit the whole backlog to the daily budget at once
- `backend/agents/collector.py` — per-source cap (`MAX_ITEMS_PER_SOURCE_PER_RUN`, overridable through
  `Source.max_per_run`): added on 2026-08-17, measured in real conditions — without it, a high-cadence
  press agency (TASS, ~45 items/day in the window then in force) consumed the daily budget on its own,
  at the expense of low-volume, high-signal specialised feeds. It complements the freshness window
  above rather than replacing it: that one bounds age, this one bounds volume
- `backend/agents/analyst.py` — systematic traceability: a summary with no verifiable quote in the
  source text is rejected automatically, not merely flagged
- `backend/agents/analyst.py` — breakdown of the outcome given to each submitted article, by source
  (`submissions_by_source()`), added on 2026-08-22. Same status and same scope as the per-node charging
  above: an operational measurement, in memory, reset per run. It exists because this node pays one
  call per submitted article **before** knowing whether it will be kept, and because discarded articles
  leave no trace anywhere else — the analysed history holds only the kept ones, the launch log counts
  only what each feed offered before the per-source cap. The key is the (source, outcome) pair and not
  the source alone: "how much was lost" without "why" does not distinguish an off-topic feed from a
  feed whose excerpts are too short to carry a verifiable quote, two problems that do not call for the
  same remedy — one is settled at source composition, the other by full-text fetching

The first two guardrails were initially declared in configuration without being checked in code — a
gap found by self-audit and fixed, rather than discovered in an external review. It is the kind of
check that a technical audit repeated periodically during development is meant to catch.

**Measured counterpart of the per-source cap.** The cap does not defer collection, it discards it:
keeping the most recent items, it lets the feed's tail age out of the window, where it is never picked
up. Over a 96 h window, 279 items are discarded that way across 7 feeds — more than the entire
analysed history — concentrated on Yonhap (-97), TASS (-88) and CGTN (-37). The figure is logged on
every launch next to the coverage KPI, because it is visible nowhere else: nothing in the analysed
history distinguishes "the source published nothing" from "we discarded its feed tail". The
comparison it enables is the real contribution — TASS discards 88 items while producing 69 of the 199
analysed items, where Yonhap discards 97 for 10: the cap trims a low-yield generalist feed in one
case, the most productive feed in the other.

**What a run costs, measured on 2026-08-22.** The first full batch of a day consumes nearly the whole
cap: 195 calls out of 200, split into analysis 72, verification 50, grouping 73. Two things follow
that the total did not show. First, an agentic escalation costs about 3.7 calls and not one — 3.85 per
verification escalation, 3.65 per grouping escalation — the loop paying one call per tool iteration
plus one to conclude. Second, and this is the consequence to keep, the escalation caps are
over-subscribed relative to the budget: together they authorise 140 calls, leaving only 60 for
analysis, which pays one per submitted article with no discretion and consumed 72 that day. The run
only held because verification did not use all its slots. A heavier batch truncates, and it is
grouping — last in the chain — that absorbs the shortfall, as observed the day before.

The split between the three nodes is not settled for all that, and not out of indecision: 41 of the 72
analysis calls, that is 21% of the daily budget, went on articles discarded afterwards, and as long as
that share is not attributed to feeds, arbitrating would amount to dividing an envelope one of whose
three parts has not been measured. That is what the per-source breakdown instrumented the same day is
meant to provide. One option is on the other hand already ruled out: tightening the grouping gate for
a budget reason would silently invalidate a threshold calibrated on a matching-precision measurement.

## Running the accumulation campaign

Several open decisions — extending the verifier ([§10](scoping.md) V2) and calibrating thread grouping
— rest on a quantity a short history cannot measure: the proportion of items that have, in the
history, a neighbour dealing with the same story. Two dispatches on the same story 48 h apart are rare
by construction; the measurement only means something over several weeks. Before automatic
triggering (Cloud Scheduler) was armed on 2026-09-06, the pipeline was launched once a day by hand,
and the script remains usable for a one-off launch:

```bash
python -m scripts.daily_run              # the daily launch
python -m scripts.daily_run --dry-run    # campaign status, without spending budget
```

The script logs **every launch**, including those that produce no new item and those that fail. That
distinction cannot be deduced from the analysed history: a day with no novelty and a day with no
launch leave the same trace in it, yet the first is a measurement and the second is a hole.
`COLLECTION_LOOKBACK_HOURS` (96 h) bounds what a collection catches up on — a skipped day is recovered
by the next launch, consecutive skipped days beyond that window permanently lose the items published
in the uncovered interval. The gap since the last launch is therefore measured and flagged on every
run. Every launch also measures, at no LLM cost, how many sources produced at least one recent item
(`sources_active`/`sources_targeted`/`sources_silent` in the log) — a source that parses without error
but no longer publishes anything recent must show as silent, not as active (see the coverage KPI,
`scoping.md` §7).

The measurement this campaign feeds is then replayed with no LLM call at all:

```bash
python -m backend.eval.candidates
```

### Closure, and why the measurements are now frozen

The campaign stopped on 2026-08-20 at five launches and seven continuous days (261 items), short of
the fifteen targeted. That is not an abandonment part-way: history retention was brought down the same
day from 30 to 7 days for storage cost, which makes the base originally targeted unreachable by
construction — the oldest day is purged on every run, the history can never again exceed seven days.
Waiting longer would have produced no wider corpus.

The measurement was therefore taken over seven days, and at that size it settles what it had to
settle: the IDF-weighted score discriminates (3% of items at threshold 40, 12% at 30, 34% at 20),
where the gate in production let 100% of items through. What seven days did not give, at that stage,
is the *threshold* itself — a scale that separates does not say where to cut.

Hence the consequence of method, which holds for any later measurement: **a corpus must be frozen
outside the store at the moment it is measured**. A measurement that re-reads the history on demand is
not replayable, since recomputed a week later it finds none of the original items — and a manual
annotation, which costs human time, would be lost with them. `backend/eval/build_pairs.py` applies
that rule to story matching, as `build_sample.py` already did for classification: it writes a
self-contained sample, carrying all the context needed to annotate and compute, and archives any
already annotated version before replacing it.

```bash
python -m backend.eval.build_pairs      # freezes the sample (no LLM call)
python -m backend.eval.annotate_pairs   # human judgement: same story?
python -m backend.eval.score_pairs      # threading precision, effect of a threshold
```

The sample mixes two populations that answer the same question without being conflated: the pairs the
model actually grouped into threads — all of them, since those are exactly the ones the V3 slice 1
acceptance criterion judges — and candidate pairs drawn by score band, which alone make it possible to
read where the rate of true matches collapses. The rates are reweighted by the real population of each
band at computation time: the sample being stratified, a raw count would over-weight the high bands,
deliberately over-drawn because they are sparsely populated.

### Result, and the threshold that follows from it

The 65 pairs were annotated on 2026-08-20. All 13 intra-thread pairs are judged to be the same story —
100% precision, the V3 slice 1 acceptance criterion met. Recall is not measurable by construction: a
story the node failed to bring together produces no pair to annotate, so this figure says "what is
grouped is grouped correctly", not "threading brings together everything it should".

The 52 candidate pairs, for their part, calibrate the escalation gate: the rate of true matches per
band goes from 0% (score 0-10) to 12.5% (10-15), 37.5% (15-20), 50% (20-25), 75% (25-30), 87.5%
(30-40). Reweighted by the real population of each band, the estimated precision of a gate at ≥ 20 is
62.0% over ~62 candidate pairs a week, against 20.2% at ≥ 10 (the free filter it replaces). That figure
was published at 64.7% before being corrected on 2026-08-20: the calibration comes out of
`backend/eval/candidates.py`, which weights in `log(n / (1 + df))`, while the threshold is applied by
`store._overlap_score`, which weights in `log(n / df)`. Rescored on the applied scale, 4 of the 52
annotated pairs change band and the estimated precision falls to 62.0% — the threshold chosen does not
move, the figure that justifies it does. A measurement that does not bear exactly on the code it sets
always ends up drifting from something. `THREAD_GATE_MIN_SCORE = 20` (`backend/config.py`) is the
direct consequence of that measurement, applied by `search_thread_candidates`
(`backend/memory/store.py`) through its `min_score` parameter — never wired by judgement, exactly what
this sample was meant to avoid.

## The verifier moves from the category to the gate

The verifier only escalated `export_control` and `arms_contract`. That restriction was never a product
choice: it was a cost bound, set when the arithmetic said opening the five categories would cost 220
to 440 calls a day against a cap of 200 shared with analysis. It bounded spending by refusing to look
at four categories out of five, not by telling verifiable items from the rest.

**What the 2026-08-20 measurement showed, and which was not what was expected.** The question asked was
"does the threshold calibrated for the threader transpose to the verifier?", looking for calls it
might save there. Answer: no, and for a reason that turns the problem around. Under the per-category
rule, the verifier only handled ~3 items a day, that is ~7 calls out of 200 — a gate there would have
saved ~6 calls a day while erasing 80% of the score coverage, which is precisely what the V2
acceptance criterion measures. The threshold is worth nothing as a saver; it is worth something as the
*condition of the extension*. The five categories with no gate cost ~71 calls/day; with a gate at
≥ 20, ~16. That is what makes the extension affordable, and it is the "pre-filter deterministically"
branch left open since 2026-08-16.

**What warranted believing in the gate this time.** The same measurement, attempted on 2026-08-16 over
102 items, had concluded in the negative: the best correct match only arrived in tenth position, behind
six false positives, on a corpus dominated by a single source. Replayed over the 261 items accumulated
after the sources were revised, it reverses — the only two items the verifier judged corroborated over
the week carry the two highest antecedent scores of the twenty scored items (32.0 and 35.4), while the
eighteen uncorroborated top out at 23.1. A gate at 20 would therefore have lost no corroboration. The
qualitative control says the same as the rates, which was not the case on 16 August: the pairs above 30
are the same Raytheon contract seen by two sources and the same K9 howitzer selection, those around 20
are thematic noise correctly rejected by the model.

**The V2 acceptance criterion is rewritten, not circumvented.** "A confidence score on 100% of events"
assumed a budget the product does not have, and would have paid a call to produce a non-answer where
the history has nothing to cross-check. It becomes: a score on 100% of the items retained by an
explicit, measured eligibility rule. An eligibility rule is only acceptable when exposed — the
interface therefore says which of the silences applies to an item with no score: no candidate
antecedent (a measurement: the system looked and found nothing to cross-check), the run cap or the
budget exhausted (an absence of measurement), or an item analysed before the extension. Conflating them
would let a gap be read where there is a result.

**What is not settled.** The extension is wired and exercised against the real history with no LLM call
— the gate replayed over the 2026-08-20 batch retains 11 items out of 27 — but it had not run on a full
run, the daily budget being exhausted on the day it was wired. It must not be presented as validated
before that. Two effects remain to be observed for real: the per-run cap
(`MAX_VERIFIER_ESCALATIONS_PER_RUN = 15`) becomes binding again on high-volume days, when it no longer
was under the per-category rule; and the confidence score itself is, over the twenty items measured,
almost constant — 0.65 for twelve of them, 0.82 and 0.92 for the two corroborated. It behaves like a
function of `corroborated` rather than like a judgement of its own, which is one more argument for
renaming it `model_confidence`. **Renamed on 2026-08-30**, in the state, the API, the front and the
tests. The field of the schema the model fills (`_VerifierResult`) kept the old name at the time:
`with_structured_output` sends that schema to the model, properties included, so renaming it is a
prompt change — to be retested, whereas renaming the stored field changes nothing the model sees.
**The two names were unified on 2026-09-06**, in the pass that rewrote both prompts in English: that
pass had to be retested end to end anyway, so the rename rode along with it instead of costing a
retest of its own.

## Making the pipeline observable before making it autonomous

The production readiness diagnosis, made on 2026-08-22, did not find what it was looking for. `infra/`
was empty, which was visible; but the real blocker lay elsewhere: **the pipeline logged nothing**. No
`logging`, no `print` in `backend/`. Everything instrumented over the previous two days — the split of
the 200 daily calls between nodes, the breakdown of analysis spending by source and by outcome — left
the process only through `scripts/daily_run.py`, an operator tool that does not ship to production.
Under a scheduler, those measurements would have vanished at the exact moment they become the only
window on the system.

Hence the order chosen: **logging first, infrastructure second**. Deploying a mute pipeline is
accepting not to know why an overnight run returned three articles.

**The format is a decision, not a preference.** One output line is a JSON object, the severity is
carried by the `severity` field — the only one Cloud Logging promotes, `level` being ignored — and the
measurements are structured fields, never interpolated into the message. The difference is
operational: a truncation filters on `jsonPayload.truncated=true`, not by grepping free text, and an
alert can therefore tell a failure from a partial success. It is the same distinction the API already
holds in its return code (200 with `truncated`, never 429); it would have served no purpose if the log
had erased it.

What the log carries was chosen from the defects already met, not from what was easy to count: silent
sources at `WARNING` (a source that parses without error but no longer publishes stayed invisible for
nearly a year), the gap between eligible articles and articles actually escalated at each escalation
node (it is that gap, and not the total, that says what a cap cost), the outcome of each submitted
article by source, and the node that was asking for the call when the daily cap refused it.

**A detail that is not one.** `configure_logging()` switches stdout to UTF-8. On Windows, redirected
output falls back to the ANSI code page, and a dispatch in Cyrillic inside a log field would make the
write fail — that is, logging would bring down the run it documents. The same trap as the explicit
encoding required everywhere else on files, met twice before being dealt with.

## A Job for the run, a service for the digest

The pipeline takes ~620 s, and that duration rises with the verifier's coverage: 401 s on 2026-08-20,
513 s on the 21st, 620 s on the 22nd. Triggering it over an HTTP request would mean holding a
connection open for all that time, under the service's timeout *and* under the scheduler's, which caps
at 30 minutes. Raising timeouts would work today and would be paid for the day a heavy batch exceeds
them.

The daily run is therefore a **Job**, with no request timeout, and the service carries only what it
serves quickly: the digest already produced. The two share a single image, with a different command —
two images to keep in sync would be a divergence waiting to happen.

**The Job's exit code is a budget decision.** A Job that exits with an error is retried. Yet a truncated
run has reached the daily call cap: retrying it would produce nothing — the budget is spent, the
submitted articles are already marked seen — but would bury the work paid for under a pile of failed
attempts. A truncation therefore exits 0, and is read in the log. The number of retries is set to zero
for the remaining case, a real failure: we want to see and diagnose it, not blindly retry it on
tomorrow's budget.

## Closing the endpoint that spends

`POST /run` was public and unauthenticated. That is not a question of exposing data — it returns none —
but of spending: it triggers a full run, hence the whole daily budget and an API bill. Left open behind
a public URL, it is a free denial of service for anyone who knows it.

It now requires a shared token, and **answers 503 as long as no token is configured** rather than
staying open "in the meantime". That is the same logic as the mandatory caps, whose absence fails the
import: an unconfigured guardrail must close, not efface itself. The difference is that the failure is
carried by the endpoint and not by startup, so that the digest keeps being served.

Platform identity locking does not replace that token: `GET /events` is read by a browser, which
presents no identity. The service therefore stays reachable, and it is the expensive endpoint that is
closed — not the reverse. In the same move, CORS drops the V1 `*`, which let any page read the digest
from a visitor's browser.

## Pinning, and what pinning does not cover

No version was fixed. A major version published between two image builds would have broken the
deployment without a line of the repository moving, and the diagnosis would have happened in
production. The three dependency files are therefore pinned exactly, taken from the environment where
the test suite passes.

One exception was flagged in the file rather than hidden: the managed database's client is not
installed locally, its pin came from the public index and not from an environment where it had run.
That was consistent with the status of the component it installs — written, documented, never executed
against a real database. **That line was verified on 2026-09-05**, at the first cloud build and then at
the first real run: the pinned version installs and works. The exception therefore disappears, and with
it the only place in the project where a dependency was pinned without proof.

## A feed that hiccups must not cost the day

On 2026-08-30, a feed read failed on an `http.client.RemoteDisconnected` raised in the middle of a
redirect. It returned nothing degraded: it brought down `collect()` in its entirety, before a single
article was analysed. The cause is a false assumption about the RSS reading library — `feedparser.parse`
intercepts `urllib.error.URLError` and nothing else, so that any error of another family goes straight
through the function. The next call succeeded: it is a transient outage, therefore exactly the one that
will one day occur in an unattended Job, at the hour when nobody relaunches. The fix makes the failure
local to the source: `FeedUnavailable`, the source named, the run continues with the other seventeen.

The same fix undoes an older confusion, and one more costly to diagnose. When `feedparser` *does* catch
the error, it returns an empty result flagged `bozo` — which the code read as "this feed published
nothing recent". A network outage therefore presented as a dead feed, which is exactly the inverse
diagnosis: the first is retried, the second is replaced. It is the confusion OFAC had produced on
2026-08-17, in the other direction. An unreachable source is now a third state, distinct from silent:
`source_freshness()` returns `None` and never `0`, the coverage KPI counts three categories, and the log
emits the unreachable ones at ERROR while the silent ones stay at WARNING — two different filters in an
alert. The criterion is not `bozo` alone, which would be wrong: plenty of valid feeds are malformed and
return their entries anyway. It is `bozo` **and** zero entries.

## Fetching the whole article: what the measurement corrected before we wrote code

The 2026-08-30 breakdown had put a figure on a target — 26 calls per run lost for want of a verifiable
quote, 18% of the daily budget — and named the fix: go and get the full text, since the RSS excerpt
would be too short to carry a quote. The target was right, the fix was not. Running 10 items in paired
arms before writing the module showed that **4 of the 6 quote failures are pure typography**: the model
renders a straight apostrophe where the source writes a curly one, straight quotes where it uses
guillemets, and the verbatim comparison already folded case and whitespace but not those marks. The
other 2 failures are genuine paraphrases, beyond the reach of any extraction fix — their longest common
fragment with the source is 7 and 12 characters, and the traceability guardrail is right to refuse
them.

Folding typography does not loosen that guardrail, it makes it applicable: a curly apostrophe and a
straight apostrophe are the same sign, not the same byte, and what the check must establish — that the
words of the quote are the source's — stays intact. The gain is that of a corrected comparison, not of
a lowered requirement: on the validation batch, retention goes from 2/10 to 5/10 with not one HTTP
request and not one extra call.

It is the same pattern as the scoping incident of 2026-08-22, where a precision measurement read a
disagreement about the specification as a gap in it. A measurement that names a fix without having
isolated it can point at the wrong object, and **checking always costs less than building the wrong
one**.

### What the module keeps as justification, and why it stays behind a switch

Full-text fetching is shipped all the same, but for classification and not for the quote: the two
favourable flips in the validation batch are two articles that left `out_of_scope` once read in full —
the class of defect already noted on two ESUT items, where the teaser does not contain what is needed
to classify. The full balance is +2 gains for −1 regression over 10 items: pointing the expected way,
**inconclusive at that sample size**. Hence `FETCH_FULL_ARTICLE`, a switch, rather than hard-wired
behaviour — and hence the refusal to announce a budget gain until a full batch has produced one.

The regression deserves recording rather than smoothing over, because it bounds an invariant one would
be tempted to state too broadly. Concatenating the article to the teaser, instead of replacing it,
guarantees that a **given quote** that verifies keeps verifying — the verifiable corpus only grows. It
does not guarantee the **fate of the item**: faced with a longer text, the model picks a different
quote, and that one may fail. The invariant bears on a string of characters, not on a decision.

### Three feasibility readings, two of which correct an earlier note

Probing before coding corrected two assumptions and avoided a third arbitrary choice. *The blocked
sources are not the ones we thought*: three feeds refuse a bare GET and answer 200 with a browser
header, where the note announced two — one of which, Federal Register, in fact answers 200 with nothing
special. Its problem is elsewhere: the extraction there brings back the site's legal notices. Only one
source genuinely resists, and is the subject of a named waiver rather than a discovery in production.
*The anchor check must start from the teaser, not the title*: a title is a summary, which a well-written
article does not repeat word for word, and anchoring on it wrongly rejected 7 correct extractions out of
9 — a guardrail that discards good work costs more than no guardrail at all. *The anchor score decides
nothing*: the only two failing extractions are already caught by the "teaser too short to anchor" rule,
so that no positive/negative separation is left on which to calibrate a threshold. It is therefore
measured and logged, without capping anything — the same order as for the threader's gate, which stayed
a free filter until an annotated sample allowed it to be set.

## Tracing has no business being able to stop what it observes

During the 2026-08-30 run, the tracing service became unreachable and the pipeline stalled for several
minutes on its timeouts. The client waits 60 s on read per send, and that value is not settable through
an environment variable in the pinned version: bounding it would mean building the client ourselves, and
therefore maintaining tracing code inside the run's execution path — a remedy heavier than the ailment.

Tracing is therefore turned off **on the Job only**, and can be turned back on through a variable. The
Job is the unattended path and the one with the least margin: 880 s measured against a 900 s target,
with a raise of the Cloud Run timeout planned on top. An observatory that can bring down the observed
has no place there by default. In development, where someone is at the screen and a trace is worth a
debugging session, the default is unchanged — that is where tracing earns its place.

A detail that is not one: two variables enable tracing, the old one and the one from the rename, and
they are read independently. Neutralising only one leaves tracing active through the other.

## What local validation proves, and what it does not

The image was built and the container exercised: the service answers, the run endpoint refuses with no
token and then with a wrong token, CORS accepts the declared origin and refuses the others. The Job ran
end to end against real RSS feeds, with the call cap forced to zero — 142 articles collected, the
reservation refusal traced to the requesting node, truncation propagated, exit 0. The whole chain was
therefore verified without spending a single call.

What that did not prove: **the production database had still never run**. It was the only unknown no
amount of local work would lift, and it bore on the least negotiable guardrail in the project — the call
reservation in a transaction, whose atomicity means nothing outside real concurrent conditions. If it is
wrong, it is only wrong in production.

**Lifted on 2026-09-05, but not by the prescribed method** — and it is that detour that deserves keeping.
The runbook asked for "two simultaneous executions", comparing the total consumed against the cap. Run as
written, it returned a conforming result **of no value whatsoever**: the two runs produced **a single**
reservation between them, and did not even overlap in time. Deduplication had marked every article on the
previous run, so nothing was left to analyse, and therefore nothing to reserve. A counter left under the
cap would have passed for proof when no race had taken place.

The full pipeline is too indirect an instrument for that question: what must be aimed at is the function
itself, and **the remaining slots must be fewer than the attempts**, without which everyone succeeds and
nothing is demonstrated. Hence a dedicated probe, committed to the repository rather than improvised — 30
simultaneous reservations spread across 3 distinct containers for 4 slots: exactly 4 accepted, 26
refused, the counter stopping on the cap. The containers were genuinely interleaved, one reading two
remaining slots while the other two read four. The transaction holds.

The lesson goes beyond that guardrail: **a runbook is not a proof, and a test that passes does not say it
measured anything.** It is the third recorded case in this project of a measurement that would have named
its conclusion without having isolated its object.

## Adopting the infrastructure rather than recreating it

The Terraform module was written **after** the infrastructure existed, and that determined its form. The
reflex — describe the desired state and let the tool converge — would have proposed destroying what was
running, starting with the database: a Firestore database's region is not revisable after creation, so any
divergence on that field translates into a replacement, and therefore into the loss of the history.

The module therefore adopts, through versioned `import` blocks rather than through imperative commands of
which the repository would keep no trace. The success criterion was not "the infrastructure exists" but
**"the plan announces no change"**.

Getting there meant correcting the configuration, never the resources. Four attributes had been set by the
creation commands without being declared — deletion protection, service-level scaling, two CPU settings.
Leaving them absent would not have left them alone: the first `apply` would have cancelled them.
**Declaring what exists is the difference between adopting a service and modifying it while believing you
are adopting it.**

Three things stay deliberately outside the module, for a common reason: they carry or produce secrets. The
values in Secret Manager — only the envelopes are managed, a value declared by Terraform ending up in clear
in its state. The connection to the code repository, which deposits a GitHub token. And the bucket that
hosts the state itself, which cannot be managed by the thing whose state it contains.

A fourth exclusion has nothing to do with secrets: **the image**. Terraform holds the configuration, Cloud
Build holds the image. Without that explicit separation, the two fight on every code publication — one
wants the last `apply`'s image, the other the last commit's.

## What running a runbook reveals, and no re-reading finds

The production rollout runbook had been written with care, re-read, and never executed. The day it was, it
produced **seven defects**, none of which was visible on reading and two of which would have cost dearly.

The first is the worst. The environment variables were passed on four successive lines, which reads very
well. But the option does not accumulate: repeated, only the last is kept. The service would have started
with a single variable — and **with no budget cap at all**. The error would not have shown at deployment,
only on the first run, in spending.

The second is a lesson about the execution environment more than about the product: under Git Bash, any
argument starting with a slash is rewritten into a Windows path. The `/health` startup probe became a file
path, it queried the root, and the revision never started — while the logs showed a perfectly normal
application startup. The symptom pointed at the application, the cause was in the terminal.

The other five are of the same order: an undocumented permission on Secret Manager without which the
repository connection fails; an authorisation screen that returns a "complete" state when the scope granted
does not cover the repository targeted; a console that opens on a region different from the one where
everything was created, and therefore looks empty.

There is no elegant conclusion to draw from it, only a rule of conduct: **an unexecuted runbook is a
hypothesis, not a procedure.** The seven defects are recorded at the exact place they occur, and not in a
separate list — that is the only form that will put them back in front of whoever replays the sequence.

## Arming the scheduler, and what that commits

The scheduler was written on 2026-09-05 and left unarmed: creating it before the first manual run had
validated the production database would have scheduled an unattended execution on a path never exercised.
That run happened the same day, so the reason lapsed — and what remained was a system in production whose
every run was still triggered by hand, which the public digest reflected as content frozen at the last
manual launch.

Two things were declared together on 2026-09-06, because arming one without the other is the configuration
that must not persist: the scheduler, and the two alert policies of runbook §9. Those had been written as
Cloud Logging queries on 2026-08-23 and had stayed queries for two weeks. **A query in a document is a
hypothesis; a resource in the state is a thing that exists** — the same rule as the runbook above, applied
to itself.

The alerts are log-match conditions and not log-based metrics, for the reason that governs every threshold
in this project: the signal is the presence of a line, not a rate. A metric would need a threshold and a
window, and there is no measurement from which to set either. They also stay two policies rather than one:
a failure means the run produced no digest, a truncation means a cap cut in and the digest exists but is
incomplete. Merged, a daily truncation would read as an outage — and an alert that cries failure for an
expected event is muted within the week, then misses the real outage.

**What arming commits.** From the first firing, the 200 daily calls are spent by 06:30, every day. Every
future measurement — the classification precision first of all, which costs a whole day's budget — therefore
requires pausing the scheduler the evening before rather than flipping the Terraform variable, which would
destroy the resource and its invoker binding. That is a real constraint, and it is the price of the system
running on its own; it is recorded in `enable_scheduler`'s description so that it is read at the moment it
matters.
