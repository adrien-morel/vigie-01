import type { AnalyzedItem } from "../types";
import { unscoredReason } from "../lib/verification";
import { confidenceColor } from "../lib/confidence";

/** Deux silences distincts derrière un score absent, jamais un zéro ni une moyenne : le
 *  vérificateur laisse `confidence_score` à null quand il n'a pas conclu, et l'affichage doit dire
 *  laquelle des deux raisons s'applique. */
const UNSCORED = {
  "no-antecedent": {
    label: "Non vérifié · aucun antécédent",
    title:
      "Le portillon d'escalade n'a trouvé, dans la fenêtre d'historique, aucun article assez proche pour servir d'antécédent : il n'y avait rien à recouper. C'est une mesure, pas un manque.",
  },
  capped: {
    label: "Non vérifié · plafond du run",
    title:
      "Un antécédent candidat existait, mais le plafond d'escalade du run (MAX_VERIFIER_ESCALATIONS_PER_RUN) ou le budget quotidien a coupé avant cet article. Absence de mesure, pas mesure d'absence.",
  },
} as const;

export function ConfidenceGauge({ item }: { item: AnalyzedItem }) {
  const score = item.confidence_score;
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
    <span className="conf" title="Score de confiance du vérificateur — aide à la priorisation, pas une garantie de véracité.">
      <span>Confiance</span>
      <span className="conf-track" role="img" aria-label={`Score de confiance ${pct} sur 100`}>
        <span className="conf-fill" style={{ width: `${pct}%`, ["--conf-color" as string]: confidenceColor(score) }} />
      </span>
      <span className="conf-value">{score.toFixed(2)}</span>
    </span>
  );
}
