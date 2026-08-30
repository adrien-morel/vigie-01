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
    item.title_fr.toLowerCase().includes(q) ||
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
    // Les items que le vérificateur a traités sans trouver de corroboration : la file de revue
    // humaine décrite en docs/cadrage.md §6 et §9.
    case "review":
      return item.model_confidence !== null && item.corroborated !== true;
    default:
      return true;
  }
};

/** Chaque prédicat est isolé pour pouvoir recalculer les compteurs de facettes en ignorant
 *  la dimension en cours (une facette compte ce qu'elle donnerait si on la sélectionnait,
 *  pas ce qui reste après elle). */
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

/** Beaucoup de flux ne datent pas leurs items (`published` vide) : sans repli, ces items
 *  tomberaient tous en fin de tri « plus récents » quelle que soit leur fraîcheur réelle.
 *  `first_seen` — l'entrée dans l'historique — est la seule date toujours renseignée. */
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
      // Non scoré en dernier : un item sans score n'est pas un item à score nul.
      return out.sort(
        (a, b) => (b.model_confidence ?? -1) - (a.model_confidence ?? -1) || publishedMs(b) - publishedMs(a),
      );
    case "review":
      return out.sort(
        (a, b) => reviewRank(a) - reviewRank(b) || (a.model_confidence ?? 1) - (b.model_confidence ?? 1),
      );
    case "category":
      return out.sort(
        (a, b) =>
          CATEGORIES.indexOf(a.category) - CATEGORIES.indexOf(b.category) || publishedMs(b) - publishedMs(a),
      );
    default:
      return out.sort((a, b) => publishedMs(b) - publishedMs(a));
  }
}

/** Ordre de revue humaine : scoré non recoupé d'abord (le cas qui appelle un arbitrage),
 *  puis scoré recoupé, puis non scoré. */
function reviewRank(item: AnalyzedItem): number {
  if (item.model_confidence === null) return 2;
  return item.corroborated === true ? 1 : 0;
}

/** Un filtre actif, rendu retirable individuellement. Les facettes vivent dans le rail, qui sort
 *  du champ dès qu'on descend dans la liste : sans cette reprise, l'état du filtrage devient
 *  invisible au moment précis où on lit ses résultats, et un digest filtré se lit comme un digest
 *  vide. `next` porte le retrait plutôt qu'une clé à interpréter — le composant d'affichage n'a
 *  pas à connaître la forme de chaque facette. */
export interface FilterChip {
  id: string;
  /** Ce que la facette filtre, pour préfixer la valeur (« Catégorie · Contrôle export »). */
  facet: string;
  label: string;
  next: Filters;
}

const VERIFICATION_CHIP: Record<Exclude<Verification, "all">, string> = {
  scored: "Vérifiés",
  corroborated: "Avec antécédent",
  review: "À arbitrer",
};

export function activeFilterChips(f: Filters): FilterChip[] {
  const chips: FilterChip[] = [];
  const without = <K extends keyof Filters>(key: K, value: Filters[K]): Filters => ({ ...f, [key]: value });

  if (f.query.trim() !== "")
    chips.push({ id: "query", facet: "Recherche", label: `« ${f.query.trim()} »`, next: without("query", "") });

  for (const c of CATEGORIES) {
    if (!f.categories.has(c)) continue;
    const rest = new Set(f.categories);
    rest.delete(c);
    chips.push({ id: `cat:${c}`, facet: "Catégorie", label: CATEGORY_LABEL[c], next: without("categories", rest) });
  }

  for (const code of [...f.countries].sort((a, b) => sourceCountryLabel(a).localeCompare(sourceCountryLabel(b), "fr"))) {
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
      facet: "Vérification",
      label: VERIFICATION_CHIP[f.verification],
      next: without("verification", "all"),
    });

  if (f.stateAffiliated)
    chips.push({
      id: "state",
      facet: "Provenance",
      label: "Médias d'État seulement",
      next: without("stateAffiliated", false),
    });

  if (f.mapCountry !== null)
    chips.push({
      id: "map",
      facet: "Lieu de l'événement",
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
