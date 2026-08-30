import type { AnalyzedItem } from "../types";

/** Pourquoi un item ne porte pas de score. Ces silences ne se lisent pas de la même façon :
 *  « rien d'assez proche à recouper dans la fenêtre » est une mesure, « le plafond du run a coupé
 *  avant d'y arriver » est une absence de mesure. Les confondre laisserait croire à un manque
 *  là où le système a bel et bien regardé. */
export type UnscoredReason = "no-antecedent" | "capped";

/** À n'appeler que sur un item dont `confidence_score` est nul — sur un item scoré, la question
 *  n'a pas de sens. */
export function unscoredReason(item: AnalyzedItem): UnscoredReason {
  return item.has_antecedent_candidate === false ? "no-antecedent" : "capped";
}

/** Un item que le vérificateur pouvait scorer : le dénominateur honnête d'un taux de vérification.
 *  Depuis le portillon, ce n'est plus la catégorie qui en décide mais la présence d'un antécédent
 *  candidat dans l'historique. */
export function isEscalatable(item: AnalyzedItem): boolean {
  return item.has_antecedent_candidate === true;
}
