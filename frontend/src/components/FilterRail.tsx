import { useEffect, useState, type RefObject } from "react";
import type { AnalyzedItem, Category } from "../types";
import { CATEGORIES, CATEGORY_LABEL, CATEGORY_VAR } from "../lib/taxonomy";
import { sourceCountryLabel } from "../lib/geo";
import { applyFilters, countBy, hasActiveFilters, type Filters, type Verification } from "../lib/filters";
import { CloseIcon, FilterIcon, SearchIcon } from "./Icons";

const VERIFICATION_ROWS: { key: Verification; label: string; hint: string }[] = [
  { key: "all", label: "All items", hint: "No verification filter" },
  { key: "scored", label: "Verified", hint: "Items that went through the verifier agent" },
  {
    key: "corroborated",
    label: "With antecedent",
    hint: "An earlier article in the 7-day history deals with the same story",
  },
  {
    key: "review",
    label: "To arbitrate",
    hint: "Verified but not cross-checked — the human review queue",
  },
];

/** Beyond this, the list of source countries pushes the reset button out of the rail on a laptop
 *  screen. Selected countries stay visible whatever happens: an active filter must never hide behind
 *  a "show more". */
const COUNTRIES_SHOWN = 8;

interface Props {
  items: AnalyzedItem[];
  filters: Filters;
  onChange: (next: Filters) => void;
  /** Target of the "/" shortcut — search lives in the rail, the shortcut is global. */
  searchRef?: RefObject<HTMLInputElement | null>;
}

export function FilterRail({ items, filters, onChange, searchRef }: Props) {
  const [showAllCountries, setShowAllCountries] = useState(false);
  // Below 900 px the rail goes full width above the content: unfolded, it pushed the first article
  // a thousand pixels below the bar. It therefore becomes a drawer, opened on demand — and always
  // open as soon as there is room to display it as a column.
  const [narrow, setNarrow] = useState(() => matchMedia("(max-width: 900px)").matches);
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    const query = matchMedia("(max-width: 900px)");
    const onChangeQuery = (e: MediaQueryListEvent) => setNarrow(e.matches);
    query.addEventListener("change", onChangeQuery);
    return () => query.removeEventListener("change", onChangeQuery);
  }, []);

  const set = <K extends keyof Filters>(key: K, value: Filters[K]) => onChange({ ...filters, [key]: value });

  const toggleIn = <T,>(source: Set<T>, value: T): Set<T> => {
    const next = new Set(source);
    if (!next.delete(value)) next.add(value);
    return next;
  };

  const categoryCounts = countBy(applyFilters(items, filters, "categories"), (i) => i.category);
  const countryCounts = countBy(applyFilters(items, filters, "countries"), (i) => i.country);
  const stateCount = applyFilters(items, filters, "stateAffiliated").filter((i) => i.state_affiliated).length;

  const presentCategories = CATEGORIES.filter((c) => (categoryCounts.get(c) ?? 0) > 0 || filters.categories.has(c));
  const presentCountries = [...countryCounts.keys()].sort((a, b) =>
    sourceCountryLabel(a).localeCompare(sourceCountryLabel(b), "en"),
  );
  const shownCountries =
    showAllCountries || presentCountries.length <= COUNTRIES_SHOWN
      ? presentCountries
      : presentCountries.filter((code, i) => i < COUNTRIES_SHOWN || filters.countries.has(code));
  const hiddenCountries = presentCountries.length - shownCountries.length;

  const total = categoryCounts.size ? [...categoryCounts.values()].reduce((a, b) => a + b, 0) : 0;
  const open = !narrow || drawerOpen;

  return (
    <aside className="rail">
      {narrow && (
        <button
          className="rail-toggle"
          aria-expanded={drawerOpen}
          onClick={() => setDrawerOpen((v) => !v)}
        >
          <FilterIcon />
          Filters
          {hasActiveFilters(filters) && <span className="seg-count">active</span>}
          <span className="topbar-spacer" />
          <span aria-hidden>{drawerOpen ? "▲" : "▼"}</span>
        </button>
      )}

      {open && (
        <>
          <div className="search">
            <SearchIcon />
            <input
              ref={searchRef}
              type="search"
              value={filters.query}
              onChange={(e) => set("query", e.target.value)}
              placeholder="Title, summary, quote…"
              aria-label="Search the digest"
            />
            {filters.query === "" ? (
              <kbd className="search-kbd" aria-hidden>
                /
              </kbd>
            ) : (
              <button className="search-clear" onClick={() => set("query", "")} aria-label="Clear the search">
                <CloseIcon />
              </button>
            )}
          </div>

          <section className="panel panel-pad">
            <div className="panel-head">
              <h2 className="panel-title">Category</h2>
              {filters.categories.size > 0 && (
                <button className="link-btn" onClick={() => set("categories", new Set())}>
                  all
                </button>
              )}
            </div>

            {total > 0 && (
              <div className="stack" role="img" aria-label="Breakdown of items by category">
                {presentCategories.map((c) => {
                  const n = categoryCounts.get(c) ?? 0;
                  if (n === 0) return null;
                  return (
                    <span
                      key={c}
                      style={{ flex: n, background: CATEGORY_VAR[c] }}
                      title={`${CATEGORY_LABEL[c]} — ${n}`}
                    />
                  );
                })}
              </div>
            )}

            {presentCategories.map((c) => {
              const n = categoryCounts.get(c) ?? 0;
              const on = filters.categories.has(c);
              return (
                <button
                  key={c}
                  className="filter-row"
                  aria-pressed={on}
                  disabled={n === 0 && !on}
                  onClick={() => set("categories", toggleIn(filters.categories, c))}
                >
                  <i className="dot" style={{ ["--dot" as string]: CATEGORY_VAR[c] }} />
                  {CATEGORY_LABEL[c]}
                  <span className="count">{n}</span>
                </button>
              );
            })}
          </section>

          <section className="panel panel-pad">
            <h2 className="panel-title">Verification</h2>
            {VERIFICATION_ROWS.map((row) => (
              <button
                key={row.key}
                className="filter-row"
                aria-pressed={filters.verification === row.key}
                title={row.hint}
                onClick={() => set("verification", row.key)}
              >
                <span className="check">{filters.verification === row.key ? "✓" : ""}</span>
                {row.label}
              </button>
            ))}
            {/* Four permanent lines of explanation in the rail are four filters pushed below the
                fold: the substance moves into a tooltip, and the visible line keeps only what reads
                at a glance. Since 2026-08-20 the verifier covers the five in-scope categories — what
                bounds its cost is the escalation gate, not the category (VERIFIER_GATE_MIN_SCORE,
                backend/config.py). */}
            <p
              className="note"
              style={{ marginTop: 6 }}
              title="An item is only escalated to the verifier if the history holds an antecedent close enough to cross-check against. The others come out with no score rather than with a default value, and the item card says which of the reasons applies."
            >
              Escalated only if the history has an antecedent to cross-check.
            </p>
          </section>

          <section className="panel panel-pad">
            <h2 className="panel-title">Provenance</h2>
            <button
              className="filter-row"
              aria-pressed={filters.stateAffiliated}
              title="China, Russia, Iran, North Korea: no free independent source identified."
              onClick={() => set("stateAffiliated", !filters.stateAffiliated)}
            >
              <span className="check">{filters.stateAffiliated ? "✓" : ""}</span>
              State media only
              <span className="count">{stateCount}</span>
            </button>

            <div className="panel-head" style={{ marginTop: 14 }}>
              <h2 className="panel-title">Source country</h2>
              {filters.countries.size > 0 && (
                <button className="link-btn" onClick={() => set("countries", new Set())}>
                  all
                </button>
              )}
            </div>
            {shownCountries.map((code) => {
              const on = filters.countries.has(code);
              return (
                <button
                  key={code}
                  className="filter-row"
                  aria-pressed={on}
                  onClick={() => set("countries", toggleIn(filters.countries, code))}
                >
                  <span className="check">{on ? "✓" : ""}</span>
                  {sourceCountryLabel(code)}
                  <span className="count">{countryCounts.get(code)}</span>
                </button>
              );
            })}
            {hiddenCountries > 0 && (
              <button className="link-btn rail-more" onClick={() => setShowAllCountries(true)}>
                show {hiddenCountries} more countries
              </button>
            )}
            {showAllCountries && presentCountries.length > COUNTRIES_SHOWN && (
              <button className="link-btn rail-more" onClick={() => setShowAllCountries(false)}>
                show fewer
              </button>
            )}
          </section>

          {hasActiveFilters(filters) && (
            <button className="btn btn-ghost" onClick={() => onChange({ ...filters, ...RESET })}>
              Reset filters
            </button>
          )}
        </>
      )}
    </aside>
  );
}

const RESET: Partial<Filters> = {
  query: "",
  categories: new Set<Category>(),
  countries: new Set<string>(),
  verification: "all",
  stateAffiliated: false,
  mapCountry: null,
};
