import type { AnalyzedItem } from "../types";

/** Pourquoi un item n'est rattaché à aucun thread. Ces silences ne se lisent pas de la même façon,
 *  et les confondre fait dire à l'écran quelque chose de faux : au run du 2026-08-21, 17 items
 *  franchissaient le portillon du threader pour 3 rattachés, et les 14 autres étaient à l'affichage
 *  indiscernables d'items dont on avait vérifié qu'ils n'appartenaient à aucun dossier.
 *
 *  Miroir de `unscoredReason` (lib/verification.ts), avec un état de plus : le vérificateur qui
 *  escalade produit toujours un score, alors que le threader qui escalade peut légitimement conclure
 *  « aucun dossier ». « Examiné et rien trouvé » est donc un troisième cas, et c'est le plus fort des
 *  silences — un jugement, pas une absence. */
export type UnthreadedReason = "no-candidate" | "examined" | "capped";

/** À n'appeler que sur un item sans `thread_id` — sur un item rattaché, la question n'a pas de sens. */
export function unthreadedReason(item: AnalyzedItem): UnthreadedReason {
  // Testé en premier : un item examiné a forcément franchi le portillon, l'ordre inverse le
  // classerait en « plafond du run » alors que le modèle a bel et bien conclu.
  if (item.thread_checked === true) return "examined";
  return item.has_thread_candidate === false ? "no-candidate" : "capped";
}

/** Un item que le threader pouvait rattacher : le dénominateur honnête d'un taux de threading.
 *  C'est le portillon (THREAD_GATE_MIN_SCORE) qui en décide, pas la catégorie. */
export function isThreadEscalatable(item: AnalyzedItem): boolean {
  return item.has_thread_candidate === true;
}
