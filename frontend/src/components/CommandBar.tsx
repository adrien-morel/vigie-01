import type { ReactElement } from "react";
import { CloseIcon, ListIcon, MapIcon, ThreadIcon } from "./Icons";
import { activeFilterChips, EMPTY_FILTERS, type Filters, type SortKey } from "../lib/filters";

export type View = "list" | "threads" | "map";

const VIEWS: { key: View; label: string; icon: () => ReactElement }[] = [
  { key: "list", label: "List", icon: ListIcon },
  { key: "threads", label: "Threads", icon: ThreadIcon },
  { key: "map", label: "Map", icon: MapIcon },
];

interface Props {
  view: View;
  onView: (v: View) => void;
  threadCount: number;
  sort: SortKey;
  onSort: (s: SortKey) => void;
  sortLabels: Record<SortKey, string>;
  windowDays: number;
  maxWindowDays: number;
  windowChoices: number[];
  onWindow: (d: number) => void;
  windowLabel: (d: number) => string;
}

/** Reading controls, housed in the title bar itself.
 *
 *  A digest of two hundred items makes a page some fifty thousand pixels tall: anything that does not
 *  stick to the top of the screen is out of reach by the third article. The view selector, the depth
 *  and the sort are exactly what one needs *while* reading, not only before. */
export function CommandBar(props: Props) {
  const {
    view,
    onView,
    threadCount,
    sort,
    onSort,
    sortLabels,
    windowDays,
    maxWindowDays,
    windowChoices,
    onWindow,
    windowLabel,
  } = props;

  return (
    <div className="commandbar">
      <div className="segmented" role="group" aria-label="View">
        {VIEWS.map(({ key, label, icon: Icon }) => (
          <button key={key} aria-pressed={view === key} onClick={() => onView(key)}>
            <Icon /> {label}
            {key === "threads" && threadCount > 0 && <span className="seg-count">{threadCount}</span>}
          </button>
        ))}
      </div>

      <div className="commandbar-selects">
        <label className="sr-only" htmlFor="window">
          Digest depth
        </label>
        <select id="window" value={windowDays} onChange={(e) => onWindow(Number(e.target.value))}>
          {windowChoices
            .filter((d) => d <= maxWindowDays)
            .map((d) => (
              <option key={d} value={d}>
                {windowLabel(d)}
              </option>
            ))}
        </select>

        <label className="sr-only" htmlFor="sort">
          Sort by
        </label>
        <select id="sort" value={sort} onChange={(e) => onSort(e.target.value as SortKey)}>
          {(Object.keys(sortLabels) as SortKey[]).map((key) => (
            <option key={key} value={key}>
              {sortLabels[key]}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

/** An echo of the active filters under the bar, as removable chips. It deliberately duplicates the
 *  rail's state: the rail is where a filtering is composed (it carries the facet counts), the chips
 *  where it is read and undone — the rail leaves the viewport as soon as you scroll down the list,
 *  and without the echo a digest filtered down to three items is indistinguishable from an empty one.
 *  Rendered only when there is something to say: a permanently empty row is height stolen from the
 *  digest. */
export function FilterChips({ filters, onChange }: { filters: Filters; onChange: (f: Filters) => void }) {
  const chips = activeFilterChips(filters);
  if (chips.length === 0) return null;

  return (
    <div className="chips page-rule">
      <span className="chips-label">Filters</span>
      {chips.map((chip) => (
        <button
          key={chip.id}
          className="chip"
          onClick={() => onChange(chip.next)}
          title={`Remove the ${chip.facet.toLowerCase()} filter: ${chip.label}`}
        >
          {/* The facet names the dimension filtered on: "Spain" alone does not say whether it is the
              outlet's country or the event's, two distinct filters everywhere else. */}
          <span className="chip-facet">{chip.facet}</span>
          {chip.label}
          <CloseIcon />
        </button>
      ))}
      <button className="link-btn chips-clear" onClick={() => onChange(EMPTY_FILTERS)}>
        clear all
      </button>
    </div>
  );
}
