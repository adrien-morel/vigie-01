import { feature } from "topojson-client";
import type { Feature, Geometry } from "geojson";
import topo from "world-atlas/countries-110m.json";

type CountryProps = { name: string };
export type CountryFeature = Feature<Geometry, CountryProps> & { id: string };

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const collection = feature(topo as any, (topo as any).objects.countries) as unknown as {
  features: CountryFeature[];
};

export const COUNTRIES: CountryFeature[] = collection.features;

/** Three Natural Earth entities (Kosovo, Northern Cyprus, Somaliland) have no numeric ISO code:
 *  without a fallback on the name, they share the key `undefined`. */
export const countryKey = (f: CountryFeature) => f.id ?? f.properties.name;

// Letters NFD does not decompose: they are not accented vowels but characters in their own right.
// Without explicit transliteration they fall into the [^a-z\s] filter and "Großbritannien" becomes
// "gro britannien", "Tromsø" becomes "troms", "Łódź" becomes "odz" — none of which matches anything
// any more.
const TRANSLIT: Record<string, string> = {
  ß: "ss",
  ø: "o",
  æ: "ae",
  œ: "oe",
  ł: "l",
  đ: "d",
  ð: "d",
  þ: "th",
  ı: "i",
};

const normalize = (s: string) =>
  s
    .toLowerCase()
    .replace(/[ßøæœłđðþı]/g, (c) => TRANSLIT[c])
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/[^a-z\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();

/** Country names in the languages of the perimeter (fr, en, de, it, es — see docs/scoping.md §4)
 *  and common variants -> the Natural Earth name carried by the topojson.
 *
 *  This table stays multilingual even though the interface is now English, and that is the point:
 *  the `location` field is a VERBATIM excerpt of the source text (guardrail §8), so it comes out in
 *  the language of the source, never translated. On a real run, "Großbritannien" and "Vereinigten
 *  Staaten" came out unattached for want of a German entry. Translating a country name into the
 *  map's index is not an inference: the country is named explicitly in the source. Attaching a town
 *  to its country is one, and it goes through `location_country`, produced by the LLM and flagged as
 *  inferred right down to the legend. */
const ALIASES: Record<string, string> = {
  // German
  "vereinigte staaten": "United States of America",
  "vereinigten staaten": "United States of America",
  "vereinigte staaten von amerika": "United States of America",
  grossbritannien: "United Kingdom",
  deutschland: "Germany",
  frankreich: "France",
  russland: "Russia",
  spanien: "Spain",
  italien: "Italy",
  polen: "Poland",
  niederlande: "Netherlands",
  belgien: "Belgium",
  schweiz: "Switzerland",
  osterreich: "Austria",
  schweden: "Sweden",
  norwegen: "Norway",
  finnland: "Finland",
  griechenland: "Greece",
  turkei: "Turkey",
  agypten: "Egypt",
  indien: "India",
  japan: "Japan",
  sudkorea: "South Korea",
  nordkorea: "North Korea",
  "vereinigte arabische emirate": "United Arab Emirates",
  "saudi arabien": "Saudi Arabia",
  litauen: "Lithuania",
  lettland: "Latvia",
  estland: "Estonia",
  // Italian (grecia/polonia/russia/china also cover Spanish or the English index)
  "stati uniti": "United States of America",
  "stati uniti d america": "United States of America",
  "regno unito": "United Kingdom",
  germania: "Germany",
  francia: "France",
  spagna: "Spain",
  cina: "China",
  giappone: "Japan",
  turchia: "Turkey",
  grecia: "Greece",
  polonia: "Poland",
  ucraina: "Ukraine",
  israele: "Israel",
  "corea del sud": "South Korea",
  "corea del nord": "North Korea",
  "arabia saudita": "Saudi Arabia",
  // Spanish
  "estados unidos": "United States of America",
  "reino unido": "United Kingdom",
  alemania: "Germany",
  espana: "Spain",
  rusia: "Russia",
  ucrania: "Ukraine",
  turquia: "Turkey",
  "corea del sur": "South Korea",
  "arabia saudi": "Saudi Arabia",
  "emiratos arabes unidos": "United Arab Emirates",
  "paises bajos": "Netherlands",
  "islas malvinas": "Falkland Is.",
  malvinas: "Falkland Is.",
  // French and English
  "etats unis": "United States of America",
  "etats unis d amerique": "United States of America",
  usa: "United States of America",
  "united states": "United States of America",
  us: "United States of America",
  amerique: "United States of America",
  "royaume uni": "United Kingdom",
  uk: "United Kingdom",
  angleterre: "United Kingdom",
  "grande bretagne": "United Kingdom",
  ecosse: "United Kingdom",
  allemagne: "Germany",
  russie: "Russia",
  "federation de russie": "Russia",
  chine: "China",
  "coree du nord": "North Korea",
  "coree du sud": "South Korea",
  coree: "South Korea",
  espagne: "Spain",
  italie: "Italy",
  israel: "Israel",
  iran: "Iran",
  france: "France",
  ukraine: "Ukraine",
  turquie: "Turkey",
  turkiye: "Turkey",
  japon: "Japan",
  inde: "India",
  bresil: "Brazil",
  "arabie saoudite": "Saudi Arabia",
  "emirats arabes unis": "United Arab Emirates",
  eau: "United Arab Emirates",
  uae: "United Arab Emirates",
  egypte: "Egypt",
  pologne: "Poland",
  suede: "Sweden",
  norvege: "Norway",
  finlande: "Finland",
  danemark: "Denmark",
  "pays bas": "Netherlands",
  hollande: "Netherlands",
  belgique: "Belgium",
  suisse: "Switzerland",
  autriche: "Austria",
  grece: "Greece",
  roumanie: "Romania",
  tchequie: "Czechia",
  "republique tcheque": "Czechia",
  taiwan: "Taiwan",
  syrie: "Syria",
  irak: "Iraq",
  liban: "Lebanon",
  jordanie: "Jordan",
  yemen: "Yemen",
  soudan: "Sudan",
  libye: "Libya",
  algerie: "Algeria",
  maroc: "Morocco",
  tunisie: "Tunisia",
  "afrique du sud": "South Africa",
  australie: "Australia",
  canada: "Canada",
  mexique: "Mexico",
  colombie: "Colombia",
  argentine: "Argentina",
  pakistan: "Pakistan",
  afghanistan: "Afghanistan",
  bielorussie: "Belarus",
  belarus: "Belarus",
  serbie: "Serbia",
  cisjordanie: "Palestine",
  "west bank": "Palestine",
  gaza: "Palestine",
  "bande de gaza": "Palestine",
  palestine: "Palestine",
  philippines: "Philippines",
  "viet nam": "Vietnam",
  vietnam: "Vietnam",
  thailande: "Thailand",
  indonesie: "Indonesia",
  malaisie: "Malaysia",
  nigeria: "Nigeria",
  ethiopie: "Ethiopia",
  kenya: "Kenya",
  tchad: "Chad",
  estonie: "Estonia",
  lettonie: "Latvia",
  lituanie: "Lithuania",
  moldavie: "Moldova",
  georgie: "Georgia",
  armenie: "Armenia",
  azerbaidjan: "Azerbaijan",
  portugal: "Portugal",
  irlande: "Ireland",
  hongrie: "Hungary",
  bulgarie: "Bulgaria",
  croatie: "Croatia",
  slovaquie: "Slovakia",
  slovenie: "Slovenia",
  "coree du sud republique de coree": "South Korea",
  // Long or official English forms that the topojson abbreviates. The `location_country` field is
  // produced in English by the LLM: without these entries, "Czech Republic" or "Democratic Republic
  // of the Congo" would be rejected even though the country meant does exist on the map.
  "czech republic": "Czechia",
  "democratic republic of the congo": "Dem. Rep. Congo",
  "dr congo": "Dem. Rep. Congo",
  drc: "Dem. Rep. Congo",
  "republic of the congo": "Congo",
  "bosnia and herzegovina": "Bosnia and Herz.",
  "north macedonia": "Macedonia",
  "south sudan": "S. Sudan",
  "central african republic": "Central African Rep.",
  "dominican republic": "Dominican Rep.",
  "equatorial guinea": "Eq. Guinea",
  "falkland islands": "Falkland Is.",
  "solomon islands": "Solomon Is.",
  "east timor": "Timor-Leste",
  "timor leste": "Timor-Leste",
  "western sahara": "W. Sahara",
  swaziland: "eSwatini",
  eswatini: "eSwatini",
  burma: "Myanmar",
  "ivory coast": "Côte d'Ivoire",
  "northern cyprus": "N. Cyprus",
  "russian federation": "Russia",
  "republic of korea": "South Korea",
  dprk: "North Korea",
  "state of palestine": "Palestine",
};

/** Natural Earth abbreviations, expanded for display. The topojson already carries English names,
 *  so this is no longer a translation table but a typography one: "Bosnia and Herz." and "S. Sudan"
 *  are index keys, not country names, and they read as truncation errors in a sentence or a legend.
 *
 *  An entity absent from here is displayed under its Natural Earth name, which is correct for every
 *  name already spelled out in full. Only add an entry when the index form is abbreviated or
 *  ambiguous — not to prefer one spelling of a full name over another. */
const COUNTRY_LABEL_OVERRIDE: Record<string, string> = {
  "United States of America": "United States",
  "Bosnia and Herz.": "Bosnia and Herzegovina",
  "Central African Rep.": "Central African Republic",
  "Dem. Rep. Congo": "DR Congo",
  "Dominican Rep.": "Dominican Republic",
  "Eq. Guinea": "Equatorial Guinea",
  "Falkland Is.": "Falkland Islands",
  "Fr. S. Antarctic Lands": "French Southern Territories",
  Macedonia: "North Macedonia",
  "N. Cyprus": "Northern Cyprus",
  "S. Sudan": "South Sudan",
  "Solomon Is.": "Solomon Islands",
  "W. Sahara": "Western Sahara",
};

/** Name of a country as displayed in the interface. */
export const countryLabel = (f: CountryFeature) => COUNTRY_LABEL_OVERRIDE[f.properties.name] ?? f.properties.name;

const BY_KEY = new Map<string, CountryFeature>();
for (const f of COUNTRIES) BY_KEY.set(countryKey(f), f);

/** The inverse of `countryKey`: from the identifier a map filter carries to the display label. A
 *  map selection transports only the key, and showing it as-is would surface a numeric code on
 *  screen. */
export const countryLabelByKey = (key: string) => {
  const f = BY_KEY.get(key);
  return f ? countryLabel(f) : key;
};

const BY_NAME = new Map<string, CountryFeature>();
for (const f of COUNTRIES) BY_NAME.set(normalize(f.properties.name), f);

/** A certain match: the text IS a country name, up to an alias or a language. */
function matchExact(name: string): CountryFeature | null {
  const key = normalize(name);
  if (!key) return null;

  const aliased = ALIASES[key];
  if (aliased) return BY_NAME.get(normalize(aliased)) ?? null;

  return BY_NAME.get(key) ?? null;
}

/** A loose match: "Taiwan Strait", "Northern Israel" — a qualified country name is still
 *  attributable. A 5-character threshold on both sides: without it, "us" would match "Russia".
 *
 *  Returns null as soon as several countries match, instead of the first one found. Measured on a
 *  real run: "Korea" is contained in "South Korea" AND in "North Korea", and a North Korean article
 *  was placed on South Korea — the topojson's iteration order was settling a choice it has no
 *  standing to settle. A fallback with two candidates is not an approximation, it is a coin toss:
 *  better to fail and hand over to the inferred country. */
function matchLoose(name: string): CountryFeature | null {
  const key = normalize(name);
  if (key.length < 5) return null;

  let found: CountryFeature | null = null;
  for (const [n, f] of BY_NAME) {
    if (n.length >= 5 && (key.includes(n) || n.includes(key))) {
      if (found && found !== f) return null;
      found = f;
    }
  }
  return found;
}

/** What an item's attachment to a country rests on. Four levels, strongest to weakest:
 *
 *  - `cited`: the source names the country. Verified verbatim.
 *  - `deduced`: the source names a place, the model infers the country from it ("Darwin" ->
 *    Australia). No verbatim anchor on the country, but a real, verified place underneath.
 *  - `actor`: the source names no attachable place, but names the protagonist, from whom the model
 *    infers the country ("Houthis" -> Yemen). One notch below `deduced` and not a variant of it:
 *    both infer a country, but `deduced` answers "where", `actor` answers "who". A Houthi strike in
 *    the Red Sea does not take place in Yemen — the map then shows where the action comes from, not
 *    where it happens, and must say so.
 *  - `presumed`: the source names neither an attachable place nor an actor; the model judges from
 *    the content that the event is located in the outlet's country. Nothing is named, only the
 *    subject is interpreted.
 *
 *  All four put the item on the map, but they do not commit to the same thing. Merging them into a
 *  single total would make presumed coverage read as cited coverage — the distinction would vanish
 *  exactly when it matters. */
export type Provenance = "cited" | "deduced" | "actor" | "presumed";

export interface LocationMatch {
  feature: CountryFeature;
  provenance: Provenance;
}

/** Source countries (codes from backend/config.py) -> topojson entity, for the presumed attachment.
 *  "INT" is deliberately absent: a multi-country or EU institutional source has no country of origin
 *  to presume, and the backend already refuses the fallback for those sources. */
const SOURCE_COUNTRY_NE: Record<string, string> = {
  US: "United States of America",
  FR: "France",
  RU: "Russia",
  CN: "China",
  DE: "Germany",
  IT: "Italy",
  GB: "United Kingdom",
  IL: "Israel",
  ES: "Spain",
  KR: "South Korea",
  IR: "Iran",
  KP: "North Korea",
};

/** What resolution needs: a shape, not the full type, so it stays testable. */
export interface Locatable {
  location: string;
  location_country?: string;
  actor_country?: string;
  domestic_to_source?: boolean;
  country: string;
}

/** Resolves an item to a topojson country, from the surest to the least sure.
 *
 *  1. `location` names exactly one country: the source is speaking, nothing to infer.
 *  2. `location` unambiguously contains a country name ("Northern Israel"): the source is still
 *     speaking, approximately but with no arbitration.
 *  3. `location_country`, inferred by the LLM ("Darwin" -> "Australia"), is only kept if it
 *     designates exactly one topojson entity — no loose fallback on this field, it is the only one
 *     with no anchor in the text, and therefore the one validated most strictly. The vocabulary
 *     being closed, an invented country falls back to "unattached" rather than painting the wrong
 *     country.
 *  4. `actor_country`, inferred from the protagonist ("Houthis" -> "Yemen"), validated as strictly
 *     as `location_country`. It comes into play in two distinct cases: no place is named, or a place
 *     is named but belongs to no country ("Strait of Hormuz"). In both, the source names someone —
 *     dropping it would lose information written in black and white. It comes AFTER the inferred
 *     place: when the theatre is attachable, that is what answers "where".
 *  5. Failing any attachable place AND any attachable actor, the country of the source — but only if
 *     the model judged the event domestic from the content of the article. The outlet's country is
 *     never enough on its own: applied without that judgement, it would paint a TASS dispatch about
 *     Yemen onto Russia.
 *
 *  The order matters: the inferred country comes after the loose match so as not to erase a real
 *  provenance, but before failure, to catch towns ("Darwin") and the cases where the loose match
 *  refuses to decide ("Korea").
 *
 *  Returns null if none of this applies — an item with no place and not domestic, or a place that is
 *  not attachable (high seas, transnational region, organisation). Those cases are counted and
 *  displayed by the map rather than silently discarded (see docs/scoping.md §11). */
export function resolveLocation(item: Locatable): LocationMatch | null {
  // Inferred from the actor, resolved here because both branches below use it: with no place at
  // all, and with a place nothing attaches. Validated as strictly as `location_country` — closed
  // topojson vocabulary, no loose fallback.
  const byActor = item.actor_country ? matchExact(item.actor_country) : null;

  if (!item.location.trim()) {
    // With no named place, `location_country` has nothing left to attach to — the backend already
    // empties it, and the invariant is restated here so callers do not have to know it. What remains
    // is the actor, which depends on no place, then the presumed attachment.
    if (byActor) return { feature: byActor, provenance: "actor" };
    if (!item.domestic_to_source) return null;
    const origin = SOURCE_COUNTRY_NE[item.country];
    const f = origin ? BY_NAME.get(normalize(origin)) : null;
    return f ? { feature: f, provenance: "presumed" } : null;
  }

  const exact = matchExact(item.location);
  if (exact) return { feature: exact, provenance: "cited" };

  const loose = matchLoose(item.location);
  if (loose) return { feature: loose, provenance: "cited" };

  const deduced = item.location_country ? matchExact(item.location_country) : null;
  if (deduced) return { feature: deduced, provenance: "deduced" };

  // A place is named but belongs to no country ("Strait of Hormuz", "Red Sea"): the backend left
  // `location_country` empty by design, which is an answer and not a gap. We do not force that place
  // into a country — we attach the item to the actor, and say so.
  return byActor ? { feature: byActor, provenance: "actor" } : null;
}

/** Source countries (backend/config.py). "INT" = multi-country / EU institutional source. */
export const SOURCE_COUNTRY_LABEL: Record<string, string> = {
  US: "United States",
  FR: "France",
  RU: "Russia",
  CN: "China",
  DE: "Germany",
  IT: "Italy",
  GB: "United Kingdom",
  IL: "Israel",
  ES: "Spain",
  KR: "South Korea",
  IR: "Iran",
  KP: "North Korea",
  INT: "International / EU",
};

export const sourceCountryLabel = (code: string) => SOURCE_COUNTRY_LABEL[code] ?? code;
