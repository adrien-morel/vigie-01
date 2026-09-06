import type { AnalyzedItem, Category } from "../types";
import { publishedMs } from "./filters";
import { computeCoverage, type Coverage } from "./coverage";
import { unscoredReason } from "./verification";

/** A group of one item is a standalone item; a group of several is a thread. */
export type ThreadGroup = AnalyzedItem[];

/** Groups an already filtered/sorted list by `thread_id`, without changing the relative order: a
 *  group appears at the position of the first of its items encountered, and later occurrences of the
 *  same `thread_id` join it rather than creating a new entry further down the list. An item with no
 *  `thread_id` stays on its own — it is not a thread of size 1, it was never brought together with
 *  another story.
 *
 *  Each group of several items is then sorted in ascending chronological order, whatever the global
 *  sort key (confidence, category…) that determined the position of the group itself: that is what
 *  makes a thread a chronology rather than a mere bundle of related articles. */
export function groupThreads(items: AnalyzedItem[]): ThreadGroup[] {
  const groups: ThreadGroup[] = [];
  const indexByThreadId = new Map<string, number>();

  for (const item of items) {
    const threadId = item.thread_id;
    if (!threadId) {
      groups.push([item]);
      continue;
    }
    const existing = indexByThreadId.get(threadId);
    if (existing === undefined) {
      indexByThreadId.set(threadId, groups.length);
      groups.push([item]);
    } else {
      groups[existing].push(item);
    }
  }

  for (const group of groups) {
    if (group.length > 1) group.sort((a, b) => publishedMs(a) - publishedMs(b));
  }

  return groups;
}

/** What an item's position in time rests on. `publishedMs` falls back on `first_seen` when the feed
 *  does not date the article — a fallback the sort cannot do without, but that the display must never
 *  present as a publication date: `first_seen` is a batch timestamp, shared by every item of the same
 *  run. Conflating them on a time axis would make one grouped collection read as a burst of
 *  simultaneous publications. */
export type DateOrigin = "published" | "first_seen";

export function dateOrigin(item: AnalyzedItem): DateOrigin {
  const t = item.published ? new Date(item.published).getTime() : NaN;
  return Number.isNaN(t) ? "first_seen" : "published";
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** Elapsed time, never rounded down to zero: two publications a few seconds apart are near
 *  simultaneous, which "0 min" would make read as "at the same time". */
export function formatDuration(ms: number): string {
  if (ms < MINUTE) return "under a minute";
  if (ms < HOUR) return `${Math.round(ms / MINUTE)} min`;
  if (ms < DAY) {
    const h = Math.floor(ms / HOUR);
    const m = Math.round((ms % HOUR) / MINUTE);
    return m === 0 ? `${h} h` : `${h} h ${String(m).padStart(2, "0")}`;
  }
  const d = Math.floor(ms / DAY);
  const h = Math.round((ms % DAY) / HOUR);
  return h === 0 ? `${d} d` : `${d} d ${h} h`;
}

export interface SourceCountryBucket {
  count: number;
  /** Number of articles from this country coming from a state outlet — not a boolean: two official
   *  agency dispatches out of five articles does not read like five out of five. */
  stateAffiliated: number;
}

/** Aggregate derived from a group of items sharing a `thread_id`. There is no thread object on the
 *  backend side (`backend/agents/threader.py` only writes the identifier onto items): this model is
 *  computed client-side, once, so that the timeline, the provenance and the header describe the same
 *  thread instead of each recomputing it on its own.
 *
 *  What is deliberately absent: any aggregated score. `model_confidence` and `corroborated` are
 *  `null` on the items the verifier did not escalate, and filling that gap with an average would make
 *  an unverified thread look like a moderately reliable one. We expose the distribution, and the
 *  display renders it as such. */
export interface ThreadModel {
  id: string;
  /** Ascending chronological order. */
  items: AnalyzedItem[];
  /** First published: who breaks the story. */
  breaker: AnalyzedItem;
  /** Most recent: carries the thread's title and category. */
  lead: AnalyzedItem;
  category: Category;
  startMs: number;
  endMs: number;
  spanMs: number;
  /** Items actually dated by their feed. The remainder is positioned by `first_seen`. */
  datedByPublication: number;
  /** Distinct sources, in order of first publication. */
  sources: string[];
  /** Countries of the outlets — never mixed with the country of the event (`coverage`). Conflating
   *  them would attach a TASS dispatch about Yemen to Russia (see `resolveLocation`, lib/geo.ts). */
  sourceCountries: Map<string, SourceCountryBucket>;
  /** Location of the events, with the four provenance levels and the attachment failures. */
  coverage: Coverage;
  scored: AnalyzedItem[];
  corroborated: number;
  singleSource: number;
  /** Unscored even though a candidate antecedent existed: the run cap or the budget left them
   *  aside. It is the only one of these counts that is an absence of measurement. */
  unscoredCapped: number;
  /** Unscored because the history held nothing close enough to cross-check — a measurement, not a
   *  gap. */
  unscoredNoAntecedent: number;
}

/** Builds a thread's model. Expects a group of at least two items sharing a `thread_id` (what
 *  `groupThreads` produces); re-sorts defensively, chronological order being the one invariant the
 *  whole rendering depends on. */
export function buildThread(group: AnalyzedItem[]): ThreadModel {
  const items = [...group].sort((a, b) => publishedMs(a) - publishedMs(b));
  const breaker = items[0];
  const lead = items[items.length - 1];

  const sources: string[] = [];
  const sourceCountries = new Map<string, SourceCountryBucket>();
  let datedByPublication = 0;
  let corroborated = 0;
  let singleSource = 0;
  let unscoredCapped = 0;
  let unscoredNoAntecedent = 0;

  for (const item of items) {
    if (!sources.includes(item.source)) sources.push(item.source);

    let bucket = sourceCountries.get(item.country);
    if (!bucket) {
      bucket = { count: 0, stateAffiliated: 0 };
      sourceCountries.set(item.country, bucket);
    }
    bucket.count += 1;
    if (item.state_affiliated) bucket.stateAffiliated += 1;

    if (dateOrigin(item) === "published") datedByPublication += 1;
    if (item.corroborated === true) corroborated += 1;
    if (item.corroborated === false) singleSource += 1;
    if (item.model_confidence === null) {
      const reason = unscoredReason(item);
      if (reason === "capped") unscoredCapped += 1;
      else unscoredNoAntecedent += 1;
    }
  }

  const startMs = publishedMs(breaker);
  const endMs = publishedMs(lead);

  return {
    id: breaker.thread_id ?? lead.link,
    items,
    breaker,
    lead,
    category: lead.category,
    startMs,
    endMs,
    spanMs: endMs - startMs,
    datedByPublication,
    sources,
    sourceCountries,
    coverage: computeCoverage(items),
    scored: items.filter((i) => i.model_confidence !== null),
    corroborated,
    singleSource,
    unscoredCapped,
    unscoredNoAntecedent,
  };
}
