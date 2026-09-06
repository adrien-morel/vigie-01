import type { AnalyzedItem } from "../types";

/** Why an item carries no score. These silences do not read the same way: "nothing close enough to
 *  cross-check in the window" is a measurement, "the run cap cut in before reaching it" is an
 *  absence of measurement. Conflating them would suggest a gap where the system did in fact look. */
export type UnscoredReason = "no-antecedent" | "capped";

/** Only to be called on an item whose `model_confidence` is null — on a scored item the question
 *  makes no sense. */
export function unscoredReason(item: AnalyzedItem): UnscoredReason {
  return item.has_antecedent_candidate === false ? "no-antecedent" : "capped";
}

/** An item the verifier could score: the honest denominator of a verification rate. Since the gate,
 *  it is no longer the category that decides but the presence of a candidate antecedent in the
 *  history. */
export function isEscalatable(item: AnalyzedItem): boolean {
  return item.has_antecedent_candidate === true;
}
