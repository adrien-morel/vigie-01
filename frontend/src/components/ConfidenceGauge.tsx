import type { AnalyzedItem } from "../types";
import { unscoredReason } from "../lib/verification";
import { confidenceColor } from "../lib/confidence";

/** Two distinct silences behind an absent score, never a zero and never an average: the verifier
 *  leaves `model_confidence` at null when it did not conclude, and the display must say which of the
 *  two reasons applies. */
const UNSCORED = {
  "no-antecedent": {
    label: "Unverified · no antecedent",
    title:
      "The escalation gate found, in the history window, no article close enough to serve as an antecedent: there was nothing to cross-check. That is a measurement, not a gap.",
  },
  capped: {
    label: "Unverified · run cap",
    title:
      "A candidate antecedent existed, but the run's escalation cap (MAX_VERIFIER_ESCALATIONS_PER_RUN) or the daily budget cut in before this article. An absence of measurement, not a measurement of absence.",
  },
} as const;

export function ConfidenceGauge({ item }: { item: AnalyzedItem }) {
  const score = item.model_confidence;
  if (score === null) {
    const { label, title } = UNSCORED[unscoredReason(item)];
    return (
      <span className="badge quiet" title={title}>
        {label}
      </span>
    );
  }

  const pct = Math.round(score * 100);
  return (
    <span className="conf" title="The verifier's confidence score — an aid to prioritisation, not a guarantee of truth.">
      <span>Confidence</span>
      <span className="conf-track" role="img" aria-label={`Confidence score ${pct} out of 100`}>
        <span className="conf-fill" style={{ width: `${pct}%`, ["--conf-color" as string]: confidenceColor(score) }} />
      </span>
      <span className="conf-value">{score.toFixed(2)}</span>
    </span>
  );
}
