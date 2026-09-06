import type { AnalyzedItem, Category } from "../types";
import { CATEGORIES, CATEGORY_LABEL } from "./taxonomy";
import { countryKey, countryLabelByKey, resolveLocation, sourceCountryLabel } from "./geo";

export type Verification = "all" | "scored" | "corroborated" | "review";
export type SortKey = "recent" | "confidence" | "review" | "category";

export interface Filters {
  query: string;
  categories: Set<Category>;
  countries: Set<string>;
  verification: Verification;
  stateAffiliated: boolean;
  mapCountry: string | null;
}

export const EMPTY_FILTERS: Filters = {
  query: "",
  categories: new Set(),
  countries: new Set(),
  verification: "all",
  stateAffiliated: false,
  mapCountry: null,
};

export const hasActiveFilters = (f: Filters) =>
  f.query.trim() !== "" ||
  f.categories.size > 0 ||
  f.countries.size > 0 ||
  f.verification !== "all" ||
  f.stateAffiliated ||
  f.mapCountry !== null;

const matchesQuery = (item: AnalyzedItem, query: string) => {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return (
    item.title_en.toLowerCase().includes(q) ||
    item.title.toLowerCase().includes(q) ||
    item.summary.toLowerCase().includes(q) ||
    item.citation.toLowerCase().includes(q) ||
    item.source.toLowerCase().includes(q) ||
    item.location.toLowerCase().includes(q)
  );
};

const matchesVerification = (item: AnalyzedItem, v: Verification) => {
  switch (v) {
    case "scored":
      return item.model_confidence !== null;
    case "corroborated":
      return item.corroborated === true;
    // Items the verifier handled without finding corroboration: the human review queue described in
    // docs/scoping.md §6 and §9.
    case "review":
      return item.model_confidence !== null && item.corroborated !== true;
    default:
      return true;
  }
};

/** Each predicate is isolated so that facet counts can be recomputed while ignoring the dimension
 *  in hand (a facet counts what it would yield if it were selected, not what is left after it). */
const PREDICATES = {
  query: (i: AnalyzedItem, f: Filters) => matchesQuery(i, f.query),
  categories: (i: AnalyzedItem, f: Filters) => f.categories.size === 0 || f.categories.has(i.category),
  countries: (i: AnalyzedItem, f: Filters) => f.countries.size === 0 || f.countries.has(i.country),
  verification: (i: AnalyzedItem, f: Filters) => matchesVerification(i, f.verification),
  stateAffiliated: (i: AnalyzedItem, f: Filters) => !f.stateAffiliated || i.state_affiliated,
  mapCountry: (i: AnalyzedItem, f: Filters) => {
    if (f.mapCountry === null) return true;
    const match = resolveLocation(i);
    return match !== null && countryKey(match.feature) === f.mapCountry;
  },
} satisfies Record<keyof Filters, (i: AnalyzedItem, f: Filters) => boolean>;

type Dimension = keyof typeof PREDICATES;

export function applyFilters(items: AnalyzedItem[], f: Filters, except?: Dimension): AnalyzedItem[] {
  const active = (Object.keys(PREDICATES) as Dimension[]).filter((d) => d !== except);
  return items.filter((i) => active.every((d) => PREDICATES[d](i, f)));
}

/** Many feeds do not date their items (`published` empty): with no fallback, those items would all
 *  land at the end of a "most recent" sort whatever their real freshness. `first_seen` — entry into
 *  the history — is the only date always filled in. */
export const publishedMs = (item: AnalyzedItem) => {
  for (const candidate of [item.published, item.first_seen]) {
    const t = candidate ? new Date(candidate).getTime() : NaN;
    if (!Number.isNaN(t)) return t;
  }
  return 0;
};

export function sortItems(items: AnalyzedItem[], key: SortKey): AnalyzedItem[] {
  const out = [...items];
  switch (key) {
    case "confidence":
      // Unscored last: an item with no score is not an item with a score of zero.
      return out.sort(
        (a, b) => (b.model_confidence ?? -1) - (a.model_confidence ?? -1) || publishedMs(b) - publishedMs(a),
      );
    case "review":
      return out.sort((a, b) => reviewRank(a) - reviewRank(b) || (a.model_confidence ?? 1) - (b.model_confidence ?? 1));
    case "category":
      return out.sort(
        (a, b) => CATEGORIES.indexOf(a.category) - CATEGORIES.indexOf(b.category) || publishedMs(b) - publishedMs(a),
      );
    default:
      return out.sort((a, b) => publishedMs(b) - publishedMs(a));
  }
}

/** Human review order: scored without an antecedent first (the case that calls for a judgement),
 *  then scored with one, then unscored. */
function reviewRank(item: AnalyzedItem): number {
  if (item.model_confidence === null) return 2;
  return item.corroborated === true ? 1 : 0;
}

/** An active filter, rendered so it can be removed on its own. The facets live in the rail, which
 *  leaves the viewport as soon as you scroll down the list: without this echo, the state of the
 *  filtering becomes invisible at the precise moment you are reading its results, and a filtered
 *  digest reads as an empty one. `next` carries the removal rather than a key to interpret — the
 *  display component has no business knowing the shape of each facet. */
export interface FilterChip {
  id: string;
  /** What the facet filters on, to prefix the value ("Category · Export control"). */
  facet: string;
  label: string;
  next: Filters;
}

const VERIFICATION_CHIP: Record<Exclude<Verification, "all">, string> = {
  scored: "Verified",
  corroborated: "With antecedent",
  review: "To arbitrate",
};

export function activeFilterChips(f: Filters): FilterChip[] {
  const chips: FilterChip[] = [];
  const without = <K extends keyof Filters>(key: K, value: Filters[K]): Filters => ({ ...f, [key]: value });

  if (f.query.trim() !== "")
    chips.push({ id: "query", facet: "Search", label: `“${f.query.trim()}”`, next: without("query", "") });

  for (const c of CATEGORIES) {
    if (!f.categories.has(c)) continue;
    const rest = new Set(f.categories);
    rest.delete(c);
    chips.push({ id: `cat:${c}`, facet: "Category", label: CATEGORY_LABEL[c], next: without("categories", rest) });
  }

  for (const code of [...f.countries].sort((a, b) => sourceCountryLabel(a).localeCompare(sourceCountryLabel(b), "en"))) {
    const rest = new Set(f.countries);
    rest.delete(code);
    chips.push({
      id: `country:${code}`,
      facet: "Source",
      label: sourceCountryLabel(code),
      next: without("countries", rest),
    });
  }

  if (f.verification !== "all")
    chips.push({
      id: "verification",
      facet: "Verification",
      label: VERIFICATION_CHIP[f.verification],
      next: without("verification", "all"),
    });

  if (f.stateAffiliated)
    chips.push({
      id: "state",
      facet: "Provenance",
      label: "State media only",
      next: without("stateAffiliated", false),
    });

  if (f.mapCountry !== null)
    chips.push({
      id: "map",
      facet: "Event location",
      label: countryLabelByKey(f.mapCountry),
      next: without("mapCountry", null),
    });

  return chips;
}

export function countBy<K extends string>(items: AnalyzedItem[], key: (i: AnalyzedItem) => K): Map<K, number> {
  const out = new Map<K, number>();
  for (const i of items) out.set(key(i), (out.get(key(i)) ?? 0) + 1);
  return out;
}
