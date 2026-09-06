import { useMemo } from "react";
import type { AnalyzedItem } from "../types";
import { publishedMs } from "../lib/filters";
import { dateOrigin, formatDuration, type ThreadModel } from "../lib/threads";
import { confidenceColor } from "../lib/confidence";
import { AlertIcon, CheckIcon } from "./Icons";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** The gap below which two labels would overlap, in % of the track. We then shift the label down a
 *  row — never the node, whose abscissa encodes a real instant. */
const MIN_GAP_PCT = 17;
const MAX_ROW = 2;

/** A tick step that keeps ten marks at most, from a few minutes between two dispatches to a story
 *  running over several weeks. */
function tickStep(spanMs: number): number {
  if (spanMs <= 2 * HOUR) return 30 * MINUTE;
  if (spanMs <= 8 * HOUR) return HOUR;
  if (spanMs <= 2 * DAY) return 6 * HOUR;
  if (spanMs <= 10 * DAY) return DAY;
  return 7 * DAY;
}

/** Ticks aligned on local boundaries (the hour, midnight), not on multiples of the start instant: a
 *  mark at "14:06" does not read, "15:00" does. */
function buildTicks(startMs: number, endMs: number, step: number): number[] {
  const d = new Date(startMs);
  d.setSeconds(0, 0);
  if (step >= DAY) {
    d.setHours(0, 0, 0, 0);
  } else {
    d.setMinutes(step < HOUR ? Math.floor(d.getMinutes() / 30) * 30 : 0);
    if (step >= HOUR) d.setHours(Math.floor(d.getHours() / (step / HOUR)) * (step / HOUR));
  }

  const out: number[] = [];
  for (let t = d.getTime(); t <= endMs && out.length < 24; t += step) {
    if (t >= startMs) out.push(t);
  }
  return out;
}

function tickLabel(ms: number, step: number): string {
  const d = new Date(ms);
  if (step >= DAY) return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
  return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

function clockLabel(item: AnalyzedItem): string {
  return new Date(publishedMs(item)).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

function nodeTitle(item: AnalyzedItem, delta: number | null): string {
  const parts = [item.source];
  parts.push(
    dateOrigin(item) === "published"
      ? new Date(publishedMs(item)).toLocaleString("en-GB", {
          day: "2-digit",
          month: "long",
          hour: "2-digit",
          minute: "2-digit",
        })
      : "publication date absent from the feed — position given by entry into the store",
  );
  if (delta !== null) parts.push(`${formatDuration(delta)} after the previous publication`);
  parts.push(item.model_confidence !== null ? `confidence ${item.model_confidence.toFixed(2)}` : "unverified");
  if (item.corroborated === true) parts.push("with an antecedent in the history");
  if (item.corroborated === false) parts.push("no antecedent at collection time");
  if (item.state_affiliated) parts.push("state outlet");
  return parts.join(" · ");
}

interface Props {
  thread: ThreadModel;
  selected: number;
  onSelect: (index: number) => void;
  /** Tightened variant for the List view: same positions, less text around them. */
  compact?: boolean;
}

/** A thread's timeline, at the real scale of time: the gap between two publications is the signal
 *  (who breaks the story, how long the pickup takes to follow), and equidistant nodes would make
 *  three dispatches in twenty minutes and a story running three weeks look identical.
 *
 *  Rendered as positioned HTML rather than SVG: the labels are text at natural size, the nodes are
 *  real focusable buttons, and the track follows the available width with no measurement. */
export function ThreadTimeline({ thread, selected, onSelect, compact = false }: Props) {
  const { items, startMs, spanMs } = thread;

  // Items all stamped identically (undated feeds, collected in the same batch): no spread to
  // represent, so the track switches to an ordinal layout and says so.
  const ordinal = spanMs <= 0;

  const layout = useMemo(() => {
    const positions = items.map((item, i) =>
      ordinal
        ? items.length === 1
          ? 50
          : (i / (items.length - 1)) * 100
        : ((publishedMs(item) - startMs) / spanMs) * 100,
    );

    const rows: number[] = [];
    for (let i = 0; i < positions.length; i++) {
      let row = 0;
      while (
        row < MAX_ROW &&
        rows.some((r, j) => r === row && positions[i] - positions[j] < MIN_GAP_PCT)
      ) {
        row += 1;
      }
      rows.push(row);
    }

    const deltas = items.map((item, i) => (i === 0 ? null : publishedMs(item) - publishedMs(items[i - 1])));
    return { positions, rows, deltas, maxRow: Math.max(...rows) };
  }, [items, startMs, spanMs, ordinal]);

  const step = tickStep(spanMs);
  const ticks = ordinal ? [] : buildTicks(startMs, thread.endMs, step);
  const undated = items.length - thread.datedByPublication;

  return (
    <figure className={`tl${compact ? " tl-compact" : ""}`}>
      <div className="tl-plot" style={{ ["--rows" as string]: layout.maxRow + 1 }}>
        <div className="tl-track">
          <div className={`tl-rule${ordinal ? " tl-rule-ordinal" : ""}`} />

          {ticks.map((t) => (
            <span key={t} className="tl-tick" style={{ left: `${((t - startMs) / spanMs) * 100}%` }}>
              <i />
              <em>{tickLabel(t, step)}</em>
            </span>
          ))}

          <ol className="tl-nodes">
            {items.map((item, i) => {
              const collected = dateOrigin(item) === "first_seen";
              return (
                <li
                  key={item.link}
                  className="tl-node"
                  style={{ left: `${layout.positions[i]}%`, ["--row" as string]: layout.rows[i] }}
                >
                  <button
                    type="button"
                    className={`tl-label${collected ? " tl-label-collected" : ""}`}
                    aria-pressed={i === selected}
                    title={nodeTitle(item, layout.deltas[i])}
                    onClick={() => onSelect(i)}
                  >
                    <span className="tl-source">
                      {item.state_affiliated && (
                        <span className="tl-warn" aria-label="State outlet">
                          <AlertIcon />
                        </span>
                      )}
                      <span className="tl-name">{item.source}</span>
                      {item.corroborated === true && (
                        <span className="tl-good" aria-label="With an antecedent in the history">
                          <CheckIcon />
                        </span>
                      )}
                    </span>
                    <span className="tl-when">
                      {i === 0
                        ? ordinal
                          ? "first"
                          : clockLabel(item)
                        : `+ ${formatDuration(layout.deltas[i]!)}`}
                      {collected && " · collected"}
                    </span>
                  </button>

                  <i className="tl-stem" />
                  <i
                    className={`tl-dot${collected ? " tl-dot-collected" : ""}`}
                    style={{ ["--dot" as string]: confidenceColor(item.model_confidence) }}
                  />
                </li>
              );
            })}
          </ol>
        </div>
      </div>

      {!compact && (
        <figcaption className="tl-legend">
          <span className="tl-first">First published: {thread.breaker.source}</span>
          {ordinal ? (
            <span>Identical timestamps — order only, no measurable duration.</span>
          ) : (
            <span>Thread spread: {formatDuration(spanMs)}.</span>
          )}
          {undated > 0 && (
            <span>
              {undated} article{undated > 1 ? "s" : ""} with no publication date in the feed, placed at
              {undated > 1 ? " their" : " its"} entry into the store (a batch timestamp, not a publication one).
            </span>
          )}
        </figcaption>
      )}
    </figure>
  );
}
