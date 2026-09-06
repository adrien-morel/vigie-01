import { useMemo } from "react";
import type { AnalyzedItem } from "../types";
import { countryKey, resolveLocation, sourceCountryLabel, type Provenance } from "../lib/geo";
import { unplacedReasons } from "../lib/coverage";
import type { ThreadModel } from "../lib/threads";
import { AlertIcon } from "./Icons";

/** A fixed height, dictated by the text: since each article draws its own strand, it is the number
 *  of strands that carries the quantity, not the size of the block. */
const BLOCK_H = 54;
const GAP = 10;
/** Inset of the anchors from the block's edges, so that a strand never leaves from the very edge. */
const ANCHOR_PAD = 7;
const UNPLACED = "__unplaced";

/** The provenance level is carried by the shape of the strand, never by colour alone: the
 *  distinction must survive colour blindness as well as black-and-white printing. Patterns calibrated
 *  for a thick stroke with round caps — the "dotted" one is a zero-length dash the round cap rounds
 *  off. The same values serve the strand and its legend sample. */
const DASH: Record<Provenance, string | undefined> = {
  cited: undefined,
  deduced: "10 8",
  actor: "3 5",
  presumed: "0.01 9",
};

const PROVENANCE_LABEL: Record<Provenance, string> = {
  cited: "cited",
  deduced: "inferred",
  actor: "actor",
  presumed: "presumed",
};

const PROVENANCE_HINT: Record<Provenance, string> = {
  cited: "the country is named by the source, verified verbatim",
  deduced: 'country inferred by the model from a named town ("Darwin" → Australia)',
  actor:
    'no attachable place: country inferred from the named protagonist ("Houthis" → Yemen). ' +
    "Says where the action comes from, not where it happens",
  presumed: "no place named: event judged domestic to the outlet from the content of the article",
};

interface Block {
  key: string;
  label: string;
  count: number;
  detail: string;
  stateAffiliated?: number;
  y: number;
}

interface Strand {
  item: AnalyzedItem;
  from: string;
  to: string;
  provenance: Provenance | null;
  leftIndex: number;
  rightIndex: number;
  leftSlot: number;
  leftOf: number;
  rightSlot: number;
  rightOf: number;
}

const plural = (n: number, word: string) => `${n} ${word}${n > 1 ? "s" : ""}`;

/** Vertical position of a strand within its block: evenly spread, never flush against the edges. */
const anchor = (blockY: number, slot: number, of: number) =>
  blockY + ANCHOR_PAD + ((BLOCK_H - 2 * ANCHOR_PAD) * (slot + 0.5)) / of;

/** Spreads the strands of one block in the order of the opposite block, to limit gratuitous
 *  crossings: a crossing should mean an attachment that genuinely crosses, not a sorting artefact. */
function assignSlots(strands: Strand[], side: "left" | "right") {
  const groups = new Map<string, Strand[]>();
  for (const s of strands) {
    const key = side === "left" ? s.from : s.to;
    const group = groups.get(key);
    if (group) group.push(s);
    else groups.set(key, [s]);
  }
  for (const group of groups.values()) {
    group.sort((a, b) =>
      side === "left" ? a.rightIndex - b.rightIndex : a.leftIndex - b.leftIndex,
    );
    group.forEach((s, i) => {
      if (side === "left") {
        s.leftSlot = i;
        s.leftOf = group.length;
      } else {
        s.rightSlot = i;
        s.rightOf = group.length;
      }
    });
  }
}

/** The crossing of "who tells it" × "where the event happens".
 *
 *  Two distinct dimensions the interface must never conflate: on the left the outlet's country, on
 *  the right the event's country as `resolveLocation` resolves it. An outlet's country does not on
 *  its own attach an article — otherwise a TASS dispatch about Yemen would read as Russian news (see
 *  lib/geo.ts, docs/scoping.md §11). It is the gap between the two columns that carries the
 *  information: a thread covered by a foreign state agency does not read like domestic coverage.
 *
 *  One strand per article, rather than a thick ribbon per feed: the quantity is counted instead of
 *  estimated, each strand stays traceable to its article on hover, and the provenance level reads on
 *  the strand itself. */
export function ThreadProvenance({ thread }: { thread: ThreadModel }) {
  const { left, right, strands, height } = useMemo(() => {
    const leftBlocks: Block[] = [...thread.sourceCountries.entries()]
      .sort((a, b) => b[1].count - a[1].count)
      .map(([code, bucket]) => ({
        key: code,
        label: sourceCountryLabel(code),
        count: bucket.count,
        stateAffiliated: bucket.stateAffiliated,
        detail:
          bucket.stateAffiliated === 0
            ? plural(bucket.count, "article")
            : bucket.stateAffiliated === bucket.count
              ? `${plural(bucket.count, "article")} · state outlet`
              : `${plural(bucket.count, "article")} · ${bucket.stateAffiliated} from a state outlet`,
        y: 0,
      }));

    const rightBlocks: Block[] = [...thread.coverage.byCountry.entries()]
      .sort((a, b) => b[1].total - a[1].total)
      .map(([key, bucket]) => {
        const cited = bucket.total - bucket.deduced - bucket.actor - bucket.presumed;
        // The count first, as in the outlets column, so the two compare.
        const parts: string[] = [plural(bucket.total, "article")];
        if (cited > 0) parts.push(`${cited} cited`);
        if (bucket.deduced > 0) parts.push(`${bucket.deduced} inferred`);
        if (bucket.actor > 0) parts.push(`${bucket.actor} by the actor`);
        if (bucket.presumed > 0) parts.push(`${bucket.presumed} presumed`);
        return { key, label: bucket.name, count: bucket.total, detail: parts.join(" · "), y: 0 };
      });

    const unplacedCount = thread.coverage.unlocated + thread.coverage.unresolved;
    if (unplacedCount > 0) {
      rightBlocks.push({
        key: UNPLACED,
        label: "Unattached",
        count: unplacedCount,
        detail: unplacedReasons(thread.coverage).join(" · "),
        y: 0,
      });
    }

    const span = (n: number) => Math.max(0, n * (BLOCK_H + GAP) - GAP);
    const total = Math.max(span(leftBlocks.length), span(rightBlocks.length), BLOCK_H);
    // Columns centred against each other: aligned at the top, two columns of different heights would
    // send every strand slanting downwards.
    const place = (blocks: Block[]) => {
      const offset = (total - span(blocks.length)) / 2;
      blocks.forEach((b, i) => {
        b.y = offset + i * (BLOCK_H + GAP);
      });
    };
    place(leftBlocks);
    place(rightBlocks);

    const drawn: Strand[] = thread.items.map((item) => {
      const match = resolveLocation(item);
      const to = match ? countryKey(match.feature) : UNPLACED;
      return {
        item,
        from: item.country,
        to,
        provenance: match ? match.provenance : null,
        leftIndex: leftBlocks.findIndex((b) => b.key === item.country),
        rightIndex: rightBlocks.findIndex((b) => b.key === to),
        leftSlot: 0,
        leftOf: 1,
        rightSlot: 0,
        rightOf: 1,
      };
    });
    assignSlots(drawn, "left");
    assignSlots(drawn, "right");

    return { left: leftBlocks, right: rightBlocks, strands: drawn, height: total };
  }, [thread]);

  const { placed, deduced, actor, presumed } = thread.coverage;
  const counts: Record<Provenance, number> = {
    cited: placed - deduced - actor - presumed,
    deduced,
    actor,
    presumed,
  };

  return (
    <div className="pv-wrap">
      <div className="pv" style={{ height }}>
        <div className="pv-col">
          <span className="pv-head">Outlets</span>
          {left.map((b) => (
            <div
              key={b.key}
              className="pv-block pv-block-left"
              style={{ top: b.y, height: BLOCK_H }}
              title={`${b.label} — ${b.detail}`}
            >
              <strong>
                {b.stateAffiliated ? (
                  <i className="pv-state" aria-label="State outlet">
                    <AlertIcon />
                  </i>
                ) : null}
                {b.label}
              </strong>
              <span>{b.detail}</span>
            </div>
          ))}
        </div>

        <svg
          className="pv-flow"
          viewBox={`0 0 100 ${height}`}
          height={height}
          preserveAspectRatio="none"
          role="img"
          aria-label="Attachment of each article to the place of its event"
        >
          {strands.map((s) => {
            const y0 = anchor(left[s.leftIndex].y, s.leftSlot, s.leftOf);
            const y1 = anchor(right[s.rightIndex].y, s.rightSlot, s.rightOf);
            return (
              <path
                key={s.item.link}
                className={`pv-strand${s.to === UNPLACED ? " pv-strand-unplaced" : ""}`}
                /* Crossed control points (58 then 42) rather than both in the middle: the strand
                   leaves and rejoins its blocks flat, with all the curvature concentrated in one
                   clean central inflection. */
                d={`M 0 ${y0} C 58 ${y0}, 42 ${y1}, 100 ${y1}`}
                strokeDasharray={s.provenance ? DASH[s.provenance] : "1.5 3.5"}
                vectorEffect="non-scaling-stroke"
              >
                <title>
                  {s.item.source} → {right[s.rightIndex].label}
                  {s.provenance
                    ? ` (${PROVENANCE_LABEL[s.provenance]}${s.item.location ? ` · “${s.item.location}”` : ""})`
                    : " · place not attachable"}
                </title>
              </path>
            );
          })}
        </svg>

        <div className="pv-col">
          <span className="pv-head">Event location</span>
          {right.map((b) => (
            <div
              key={b.key}
              className={`pv-block pv-block-right${b.key === UNPLACED ? " pv-block-unplaced" : ""}`}
              style={{ top: b.y, height: BLOCK_H }}
              title={`${b.label} — ${b.detail}`}
            >
              <strong>{b.label}</strong>
              <span>{b.detail}</span>
            </div>
          ))}
        </div>
      </div>

      {/* The four levels are always displayed, including at zero: a level hidden because it is empty
          would read as a level that does not exist. */}
      <ul className="pv-key">
        {(Object.keys(PROVENANCE_LABEL) as Provenance[]).map((p) => (
          <li key={p}>
            <svg className="pv-sample" width="36" height="10" aria-hidden="true">
              <line x1="2" y1="5" x2="34" y2="5" strokeDasharray={DASH[p]} />
            </svg>
            <b>{PROVENANCE_LABEL[p]}</b>
            <span className="pv-count">{counts[p]}</span>
            <span className="pv-hint">{PROVENANCE_HINT[p]}</span>
          </li>
        ))}
      </ul>

      <p className="note pv-note">
        One strand per article: on the left the <strong>outlet</strong>'s country, on the right the{" "}
        <strong>event</strong>'s, resolved article by article on the <code>location</code> field — never
        on the outlet's origin, which attaches nothing on its own. The four levels are never added
        together, and what cannot be placed is displayed rather than discarded (docs/scoping.md §11).
      </p>
    </div>
  );
}
