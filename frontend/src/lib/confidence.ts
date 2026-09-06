/** A sequential blue ramp: the score is a magnitude, not a verdict. Deliberately no red/green —
 *  docs/scoping.md §9 warns that a confidence score read as a guarantee (or as an alert) invalidates
 *  the guardrail of non-goal §3. `null` (an item never escalated to the verifier) falls back on a
 *  neutral grey rather than a point on the ramp. */
export function confidenceColor(score: number | null): string {
  if (score === null) return "var(--ink-muted)";
  if (score < 0.4) return "var(--seq-250)";
  if (score < 0.6) return "var(--seq-400)";
  if (score < 0.8) return "var(--seq-550)";
  return "var(--seq-700)";
}
