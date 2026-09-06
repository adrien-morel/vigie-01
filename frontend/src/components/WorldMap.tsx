import { useMemo, useState } from "react";
import { geoNaturalEarth1, geoPath } from "d3-geo";
import type { AnalyzedItem } from "../types";
import { COUNTRIES, countryKey, type CountryFeature } from "../lib/geo";
import { computeCoverage } from "../lib/coverage";
import { CATEGORY_LABEL, CATEGORY_VAR } from "../lib/taxonomy";

const W = 960;
const H = 460;
// Nominal width of the tooltip, that of `.map-tooltip`: used to decide which side to open it on.
const TOOLTIP_W = 230;
const STEPS = ["var(--seq-250)", "var(--seq-400)", "var(--seq-550)", "var(--seq-700)"];

// Antarctica hosts no in-scope item and takes up the bottom third of the frame.
const DRAWN = COUNTRIES.filter((f) => f.properties.name !== "Antarctica");

const projection = geoNaturalEarth1().fitSize([W, H], { type: "FeatureCollection", features: DRAWN } as never);
const path = geoPath(projection);

const PATHS: { feature: CountryFeature; d: string }[] = DRAWN.map((feature) => ({
  feature,
  d: path(feature) ?? "",
})).filter((p) => p.d !== "");

interface Props {
  items: AnalyzedItem[];
  selected: string | null;
  onSelect: (id: string | null) => void;
}

export function WorldMap({ items, selected, onSelect }: Props) {
  const [hover, setHover] = useState<{ id: string; x: number; y: number; width: number } | null>(null);

  const { byCountry, unlocated, unresolved, deduced, actor, presumed, max } = useMemo(
    () => computeCoverage(items),
    [items],
  );

  // As many steps as there are distinct possible values, capped by the ramp: on a digest where no
  // country exceeds one item, a four-step ramp would suggest a gradation that does not exist. The
  // steps kept are the darkest, so that the real maximum is always the end of the ramp.
  const { steps, thresholds } = useMemo(() => {
    const count = Math.min(STEPS.length, Math.max(1, max));
    const steps = STEPS.slice(STEPS.length - count);
    return { steps, thresholds: steps.map((_, i) => Math.ceil((max * (i + 1)) / count)) };
  }, [max]);

  const stepFor = (total: number) => steps[thresholds.findIndex((t) => total <= t)] ?? steps[steps.length - 1];

  const hovered = hover ? byCountry.get(hover.id) : null;

  // The offset flips to the left of the cursor when the tooltip would overflow the frame. The bound
  // reads off the SVG's actually rendered width, not a constant: the map is fluid, and a hard-coded
  // value clipped the tooltip on countries to the east of the map as soon as the window moved away
  // from the width it had been chosen for.
  const tooltipStyle = (x: number, y: number, width: number) =>
    x + TOOLTIP_W + 14 > width
      ? { right: Math.max(8, width - x + 14), top: y + 14 }
      : { left: x + 14, top: y + 14 };

  return (
    <div className="panel panel-pad">
      <div className="panel-head">
        <h2 className="panel-title">Geographic coverage · location of the event</h2>
        {selected && (
          <button className="link-btn" onClick={() => onSelect(null)}>
            remove the filter
          </button>
        )}
      </div>

      <div className="map-wrap" onMouseLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Map of the number of items per country">
          {PATHS.map(({ feature, d }) => {
            const key = countryKey(feature);
            const bucket = byCountry.get(key);
            const isSelected = selected === key;
            return (
              <path
                key={key}
                d={d}
                className={[
                  "map-country",
                  bucket ? "has-data" : "",
                  selected && !isSelected ? "dim" : "",
                  isSelected ? "active" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                style={bucket ? { fill: stepFor(bucket.total) } : undefined}
                onMouseMove={(e) => {
                  if (!bucket) return setHover(null);
                  const box = e.currentTarget.ownerSVGElement!.getBoundingClientRect();
                  setHover({ id: feature.id, x: e.clientX - box.left, y: e.clientY - box.top, width: box.width });
                }}
                onClick={() => bucket && onSelect(isSelected ? null : key)}
              >
                {bucket && (
                  <title>
                    {bucket.name} — {bucket.total} item{bucket.total > 1 ? "s" : ""}
                    {bucket.deduced > 0 && `, of which ${bucket.deduced} inferred`}
                    {bucket.actor > 0 && `, of which ${bucket.actor} by the actor`}
                    {bucket.presumed > 0 && `, of which ${bucket.presumed} presumed`}
                  </title>
                )}
              </path>
            );
          })}
        </svg>

        {hover && hovered && (
          <div className="map-tooltip map-tooltip-body" style={tooltipStyle(hover.x, hover.y, hover.width)}>
            <strong>{hovered.name}</strong>
            {hovered.deduced > 0 && (
              <span className="tooltip-note">
                {hovered.deduced}/{hovered.total} attached by inferring the place
              </span>
            )}
            {hovered.actor > 0 && (
              <span className="tooltip-note">
                {hovered.actor}/{hovered.total} attached through the protagonist, with no attachable place — where the
                action comes from, not where it happens
              </span>
            )}
            {hovered.presumed > 0 && (
              <span className="tooltip-note">
                {hovered.presumed}/{hovered.total} presumed domestic, with no place named
              </span>
            )}
            <ul>
              {[...hovered.byCategory.entries()]
                .sort((a, b) => b[1] - a[1])
                .map(([category, n]) => (
                  <li key={category}>
                    <i className="dot" style={{ ["--dot" as string]: CATEGORY_VAR[category] }} />
                    {CATEGORY_LABEL[category]}
                    <span className="count">{n}</span>
                  </li>
                ))}
            </ul>
          </div>
        )}
      </div>

      <div className="map-legend">
        {max > 0 && (
          <span className="ramp">
            <span className="swatches">
              {steps.map((step, i) => (
                <i key={step} style={{ background: step }} title={`up to ${thresholds[i]} item(s)`} />
              ))}
            </span>
            <span>{max === 1 ? "1 item per country" : `1 to ${max} items per country`}</span>
          </span>
        )}
        <span>{unlocated} with no place extracted</span>
        <span>
          {unresolved} place{unresolved > 1 ? "s" : ""} not attached to a country
        </span>
        {deduced > 0 && <span>{deduced} inferred from a town</span>}
        {actor > 0 && <span>{actor} by the actor</span>}
        {presumed > 0 && <span>{presumed} presumed domestic</span>}
      </div>

      <p className="note" style={{ marginTop: 8 }}>
        The map is built on the <code>location</code> field verified per item, not on the country of the
        source. Four attachment levels, counted separately above and detailed on hovering a country:
        the country is <strong>cited</strong> by the source; it is <strong>inferred</strong> by the
        model from a named town (“Darwin” → Australia); failing any attachable place, it is inferred
        from the named <strong>actor</strong> (“Houthis” → Yemen), which says where the action comes
        from and not where it happens; or, failing everything, the event is{" "}
        <strong>presumed domestic</strong> to the outlet's country, on a judgement of the article's
        content — never on the outlet's origin alone, which would place a TASS dispatch about Yemen in
        Russia. What stays unplaceable is displayed rather than discarded: the real coverage is
        understated (docs/scoping.md §11).
      </p>
    </div>
  );
}
