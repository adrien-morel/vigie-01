import type { AnalyzedItem } from "../types";
import { isEscalatable } from "../lib/verification";
import { computeCoverage, unplacedReasons } from "../lib/coverage";

const pct = (n: number, d: number) => (d === 0 ? null : `${Math.round((n / d) * 100)}%`);

/** The digest is a post-filtering artefact: backend/agents/analyst.py discards `out_of_scope` items
 *  and those whose citation cannot be verified verbatim before building `analyzed_items`. The front
 *  therefore sees neither the volume collected nor the volume discarded — no tile may pretend
 *  otherwise. */
export function KpiStrip({ items, filtered }: { items: AnalyzedItem[]; filtered: boolean }) {
  const sources = new Set(items.map((i) => i.source));
  // What makes an item escalatable is no longer its category but the existence of a candidate
  // antecedent in the history (the gate of 2026-08-20): a digest where nothing cross-checks
  // therefore legitimately has a low denominator, and saying so beats displaying a rate over a base
  // the verifier never had to handle.
  const escalatable = items.filter(isEscalatable);
  const scored = items.filter((i) => i.model_confidence !== null);
  const corroborated = items.filter((i) => i.corroborated === true);
  const stateAffiliated = items.filter((i) => i.state_affiliated);
  // The same computation as the map, by design: the two panels used to describe coverage each on
  // their own and contradicted each other on screen (see lib/coverage.ts).
  const coverage = computeCoverage(items);
  const unplaced = unplacedReasons(coverage);

  return (
    /* The scope note is a sibling of the grid, never a cell that spans it: `.kpis` is `auto-fit`,
       which only shares the width evenly by collapsing its empty tracks. An element placed on
       `grid-column: 1 / -1` fills them all, nothing collapses any more, and the five tiles bunch up
       on the left at 156 px each instead of occupying the strip.
       The tiles describe the whole digest, never the selection: their denominators (escalatable
       items, verified items) are what make them honest, and recomputing them over a filtered subset
       would make a coverage rate move with a click on a facet. */
    <div className="kpis-panel">
      {filtered && (
        <p className="kpis-scope">Measurements cover the whole digest — the active filters do not apply to them.</p>
      )}

      <div className="kpis">
        <div className="kpi">
          <span className="kpi-value">{items.length}</span>
          <span className="kpi-label">Events kept</span>
          <span className="kpi-note">
            {sources.size} source{sources.size > 1 ? "s" : ""} represented · only items with a verified quote enter the
            digest
          </span>
        </div>

        <div className="kpi">
          <span className="kpi-value">
            {escalatable.length === 0 ? "—" : scored.length}
            {escalatable.length > 0 && <small>/ {escalatable.length}</small>}
          </span>
          <span className="kpi-label">Verified</span>
          <span className="kpi-note">
            {escalatable.length === 0
              ? "no candidate antecedent in this digest: nothing to cross-check"
              : `${pct(scored.length, escalatable.length)} of escalatable items`}
          </span>
        </div>

        <div className="kpi">
          <span className="kpi-value">{scored.length === 0 ? "—" : corroborated.length}</span>
          <span className="kpi-label">With an antecedent in the history</span>
          <span className="kpi-note">
            {scored.length === 0
              ? "not applicable: no verified item"
              : `${pct(corroborated.length, scored.length)} of verified items · tracked, not maximised`}
          </span>
        </div>

        <div className="kpi">
          <span className="kpi-value">{stateAffiliated.length}</span>
          <span className="kpi-label">From a state outlet</span>
          <span className="kpi-note">
            {pct(stateAffiliated.length, items.length) ?? "—"} of the digest · to be read as claims
          </span>
        </div>

        <div className="kpi">
          <span className="kpi-value">{coverage.byCountry.size}</span>
          <span className="kpi-label">Countries covered</span>
          <span className="kpi-note">
            {coverage.placed} item{coverage.placed > 1 ? "s" : ""} of {items.length} attached to a country
            {unplaced.length > 0 && ` — ${unplaced.join(", ")}`}
          </span>
        </div>
      </div>
    </div>
  );
}
