import type { AnalyzedItem, Category } from "../types";
import { countryKey, countryLabel, resolveLocation } from "./geo";

export interface CountryBucket {
  /** Display name of the country (see countryLabel). */
  name: string;
  total: number;
  /** Shares of the total attached other than by a citation from the source (see Provenance). */
  deduced: number;
  actor: number;
  presumed: number;
  byCategory: Map<Category, number>;
}

export interface Coverage {
  byCountry: Map<string, CountryBucket>;
  /** Items attached to a country, all provenances together. */
  placed: number;
  /** Two distinct failures: no place extracted from the text, or a place extracted that is in no
   *  country (high seas, international strait, military command). Conflating them would hide which
   *  one is at fault. */
  unlocated: number;
  unresolved: number;
  deduced: number;
  actor: number;
  presumed: number;
  /** Largest number of items on a single country, to calibrate the map's ramp. */
  max: number;
}

/** Breakdown of a digest's geographic coverage.
 *
 *  A single computation, shared by the map and the KPI strip. Those two panels each described the
 *  same thing on their own and ended up contradicting each other on screen: the KPI announced "the
 *  rest has no usable location" while the legend counted, for the same digest, "0 with no place
 *  extracted · 1 place not attached to a country". Two computations, two vocabularies, no consistency
 *  constraint — hence this function. */
export function computeCoverage(items: AnalyzedItem[]): Coverage {
  const byCountry = new Map<string, CountryBucket>();
  let placed = 0;
  let unlocated = 0;
  let unresolved = 0;
  let deduced = 0;
  let actor = 0;
  let presumed = 0;

  for (const item of items) {
    const match = resolveLocation(item);
    if (!match) {
      if (item.location.trim()) unresolved += 1;
      else unlocated += 1;
      continue;
    }

    placed += 1;
    const key = countryKey(match.feature);
    let bucket = byCountry.get(key);
    if (!bucket) {
      bucket = {
        name: countryLabel(match.feature),
        total: 0,
        deduced: 0,
        actor: 0,
        presumed: 0,
        byCategory: new Map(),
      };
      byCountry.set(key, bucket);
    }
    bucket.total += 1;
    if (match.provenance === "deduced") {
      bucket.deduced += 1;
      deduced += 1;
    } else if (match.provenance === "actor") {
      bucket.actor += 1;
      actor += 1;
    } else if (match.provenance === "presumed") {
      bucket.presumed += 1;
      presumed += 1;
    }
    bucket.byCategory.set(item.category, (bucket.byCategory.get(item.category) ?? 0) + 1);
  }

  const max = Math.max(0, ...[...byCountry.values()].map((b) => b.total));
  return { byCountry, placed, unlocated, unresolved, deduced, actor, presumed, max };
}

/** What the coverage does not place, stated by cause and never aggregated into a mute "remainder".
 *  Returns an empty list when everything is placed, so the caller displays nothing. */
export function unplacedReasons(coverage: Coverage): string[] {
  const reasons: string[] = [];
  if (coverage.unlocated > 0) {
    reasons.push(`${coverage.unlocated} with no place extracted`);
  }
  if (coverage.unresolved > 0) {
    // The same wording as the map legend: two vocabularies for one count is precisely what let the
    // two panels drift apart.
    const plural = coverage.unresolved > 1;
    reasons.push(`${coverage.unresolved} place${plural ? "s" : ""} not attached to a country`);
  }
  return reasons;
}
