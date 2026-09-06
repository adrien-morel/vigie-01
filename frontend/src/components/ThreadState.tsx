import type { AnalyzedItem } from "../types";
import { unthreadedReason } from "../lib/threading";

/** Three distinct silences behind an absent `thread_id` — the exact counterpart of ConfidenceGauge
 *  for the verifier, with one state more than it. Without this mention, an item the run cap set aside
 *  reads exactly like an item that was checked and found to belong to no story: it is the only one of
 *  the three situations where the display would assert something the system did not measure. */
const UNTHREADED = {
  "no-candidate": {
    label: "No thread · no candidate",
    title:
      "The threader's escalation gate found, in the history window, no article whose overlap reaches the threshold: there was no match to attempt. That is a measurement, not a gap.",
  },
  examined: {
    label: "No thread · examined",
    title:
      "A candidate existed, the model examined it and concluded that no article in the window covers the same story. It is the strongest of the four states: a judgement made, not a silence.",
  },
  capped: {
    label: "No thread · not searched",
    title:
      "A candidate existed, but the run's escalation cap (MAX_THREAD_ESCALATIONS_PER_RUN) or the daily budget cut in before this article: the match was never attempted. An absence of measurement, not a measurement of absence.",
  },
} as const;

export function ThreadState({ item }: { item: AnalyzedItem }) {
  // An attached item has nothing to declare here: its thread speaks for it, in the feed as in the
  // Threads tab.
  if (item.thread_id) return null;

  const { label, title } = UNTHREADED[unthreadedReason(item)];
  return (
    <span className="badge quiet" title={title}>
      {label}
    </span>
  );
}
