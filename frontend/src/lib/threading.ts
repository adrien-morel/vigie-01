import type { AnalyzedItem } from "../types";

/** Why an item is attached to no thread. These silences do not read the same way, and conflating
 *  them makes the screen say something false: on the 2026-08-21 run, 17 items cleared the threader's
 *  gate for 3 attached, and the other 14 were on screen indistinguishable from items that had been
 *  checked and found to belong to no story.
 *
 *  A mirror of `unscoredReason` (lib/verification.ts), with one state more: a verifier that escalates
 *  always produces a score, whereas a threader that escalates can legitimately conclude "no story".
 *  "Examined and found nothing" is therefore a third case, and it is the strongest of the silences —
 *  a judgement, not an absence. */
export type UnthreadedReason = "no-candidate" | "examined" | "capped";

/** Only to be called on an item with no `thread_id` — on an attached item the question makes no
 *  sense. */
export function unthreadedReason(item: AnalyzedItem): UnthreadedReason {
  // Tested first: an examined item has necessarily cleared the gate, and the reverse order would
  // class it as "run cap" when the model did in fact conclude.
  if (item.thread_checked === true) return "examined";
  return item.has_thread_candidate === false ? "no-candidate" : "capped";
}

/** An item the threader could attach: the honest denominator of a threading rate. It is the gate
 *  (THREAD_GATE_MIN_SCORE) that decides, not the category. */
export function isThreadEscalatable(item: AnalyzedItem): boolean {
  return item.has_thread_candidate === true;
}
