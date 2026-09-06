import type { AnalyzedItem } from "../types";
import { CATEGORY_LABEL, CATEGORY_VAR, LANG_LABEL } from "../lib/taxonomy";
import { countryLabel, resolveLocation, sourceCountryLabel } from "../lib/geo";
import { ConfidenceGauge } from "./ConfidenceGauge";
import { ThreadState } from "./ThreadState";
import { AlertIcon, CheckIcon, PinIcon } from "./Icons";
import { SourceLogo } from "./SourceLogo";

/* The attachment level, spelled out next to the place. It used to be carried by the table view,
   removed on 2026-08-20: without this mention, a card placed by the model's inference or by its
   protagonist read exactly like a card whose source names the country. The four levels never merge
   (see docs/scoping.md §11). */
const PROVENANCE_SUFFIX = {
  cited: "",
  deduced: "inferred",
  actor: "actor",
  presumed: "presumed domestic",
} as const;

function formatDate(published: string): string | null {
  const d = new Date(published);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function ItemCard({ item }: { item: AnalyzedItem }) {
  const date = formatDate(item.published);

  // The country under its display name rather than the raw excerpt, which comes out in the language
  // of the source ("Großbritannien"); the excerpt stays available in a tooltip. A place attachable to
  // no country has no display equivalent: it is shown as it is.
  const match = resolveLocation(item);
  const place = match ? countryLabel(match.feature) : item.location;
  const placeTitle = match && place !== item.location.trim() ? `Place extracted from the source: ${item.location}` : undefined;

  return (
    <article className="card" style={{ ["--cat" as string]: CATEGORY_VAR[item.category] }}>
      {/* A single header row: category on the left, verification state and the outlet's mark on the
          right. That state was first a side column; it reserved two hundred pixels down the whole
          height of the card for one or two badges and left an empty flank below. Brought back onto
          the title line, it takes the room it asks for and no more, while keeping the alignment from
          one card to the next that makes the list scannable. */}
      <div className="card-top">
        <span className="badge">
          <i className="dot" style={{ ["--dot" as string]: CATEGORY_VAR[item.category] }} />
          {CATEGORY_LABEL[item.category]}
        </span>

        <div className="card-flags">
          {item.state_affiliated && (
            <span
              className="badge warn"
              title="State outlet or semi-official agency: to be read as a claim, not as an established fact (docs/scoping.md §4, §11)."
            >
              <AlertIcon />
              State media
            </span>
          )}

          {/* "Antecedent" and not "cross-checked": the verifier never cross-checks the displayed
              articles against each other, `exclude_links` excluding the whole current batch. */}
          {item.corroborated === true && (
            <span className="badge good" title="At least one earlier article in the history deals with the same story.">
              <CheckIcon />
              With antecedent
            </span>
          )}
          {item.corroborated === false && (
            <span
              className="badge quiet"
              title="No earlier article found on this story in the history (7-day sliding window), and items from the same collection batch do not count. An isolated signal is not thereby false — it is precisely what a watch is meant to catch."
            >
              No antecedent
            </span>
          )}

          {/* Always rendered, scored or not: never a zero, never an average. */}
          <ConfidenceGauge item={item} />

          {/* Rendered only outside a thread, and then always: an item the run cap set aside would
              otherwise read as an item that had been checked and found to belong to no story. The two
              mentions are siblings — the verifier and the threader each say what they measured, and
              what they could not measure. */}
          <ThreadState item={item} />
        </div>

        {/* The mark closes the row: the source is recognised at a glance down the list, where its
            name in the card footer takes reading. */}
        <SourceLogo source={item.source} />
      </div>

      <h3>
        <a href={item.link} target="_blank" rel="noopener noreferrer">
          {item.title_en}
        </a>
      </h3>

      <p className="summary">{item.summary}</p>

      {item.citation && (
        <blockquote className="citation">
          <span className="citation-tag">
            Verified quote · original {(LANG_LABEL[item.lang] ?? item.lang).toLowerCase()}
          </span>
          {item.citation}
        </blockquote>
      )}

      <footer className="card-foot">
        <span>{item.source}</span>
        <span className="sep">·</span>
        <span>{sourceCountryLabel(item.country)}</span>
        {place && (
          <>
            <span className="sep">·</span>
            <span title={placeTitle}>
              <PinIcon /> {place}
              {match && PROVENANCE_SUFFIX[match.provenance] && ` (${PROVENANCE_SUFFIX[match.provenance]})`}
            </span>
          </>
        )}
        {date && (
          <>
            <span className="sep">·</span>
            <span>{date}</span>
          </>
        )}
        <a href={item.link} target="_blank" rel="noopener noreferrer">
          Original source ↗
        </a>
      </footer>
    </article>
  );
}
