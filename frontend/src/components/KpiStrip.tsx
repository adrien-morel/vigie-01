import type { AnalyzedItem } from "../types";
import { isEscalatable } from "../lib/verification";
import { computeCoverage, unplacedReasons } from "../lib/coverage";

const pct = (n: number, d: number) => (d === 0 ? null : `${Math.round((n / d) * 100)} %`);

/** Le digest est un artefact d'après-filtrage : backend/agents/analyst.py écarte les items
 *  `hors_perimetre` et ceux dont la citation n'est pas vérifiable verbatim avant de construire
 *  `analyzed_items`. Le front ne voit donc ni le volume collecté ni le volume écarté — aucune
 *  tuile ne doit prétendre le contraire. */
export function KpiStrip({ items, filtered }: { items: AnalyzedItem[]; filtered: boolean }) {
  const sources = new Set(items.map((i) => i.source));
  // Ce qui rend un item escaladable n'est plus sa catégorie mais l'existence d'un antécédent
  // candidat dans l'historique (portillon du 2026-08-20) : un digest où rien ne se recoupe a donc
  // légitimement un dénominateur bas, et le dire vaut mieux qu'afficher un taux sur une assiette
  // que le vérificateur n'a jamais eu à traiter.
  const escalatable = items.filter(isEscalatable);
  const scored = items.filter((i) => i.model_confidence !== null);
  const corroborated = items.filter((i) => i.corroborated === true);
  const stateAffiliated = items.filter((i) => i.state_affiliated);
  // Même calcul que la carte, à dessein : les deux panneaux décrivaient la couverture chacun de
  // son côté et se contredisaient à l'écran (cf. lib/coverage.ts).
  const coverage = computeCoverage(items);
  const unplaced = unplacedReasons(coverage);

  return (
    /* La mention de portée est sœur de la grille, jamais une cellule qui la traverse : `.kpis` est
       en `auto-fit`, qui ne répartit également la largeur qu'en effondrant ses pistes vides. Un
       élément posé sur `grid-column: 1 / -1` les remplit toutes, plus rien ne s'effondre, et les
       cinq tuiles se tassent à gauche sur 156 px chacune au lieu d'occuper le bandeau.
       Les tuiles décrivent le digest entier, jamais la sélection : leurs dénominateurs (items
       escaladables, items vérifiés) sont ce qui les rend honnêtes, et les recalculer sur un
       sous-ensemble filtré ferait varier un taux de couverture au gré d'un clic de facette. */
    <div className="kpis-panel">
      {filtered && (
        <p className="kpis-scope">
          Mesures portant sur l'ensemble du digest — les filtres actifs ne s'y appliquent pas.
        </p>
      )}

      <div className="kpis">
        <div className="kpi">
          <span className="kpi-value">{items.length}</span>
          <span className="kpi-label">Événements retenus</span>
          <span className="kpi-note">
            {sources.size} source{sources.size > 1 ? "s" : ""} représentée{sources.size > 1 ? "s" : ""} · seuls les
            items à citation vérifiée entrent au digest
          </span>
        </div>

        <div className="kpi">
          <span className="kpi-value">
            {escalatable.length === 0 ? "—" : scored.length}
            {escalatable.length > 0 && <small>/ {escalatable.length}</small>}
          </span>
          <span className="kpi-label">Vérifiés</span>
          <span className="kpi-note">
            {escalatable.length === 0
              ? "aucun antécédent candidat dans ce digest : rien à recouper"
              : `${pct(scored.length, escalatable.length)} des items escaladables`}
          </span>
        </div>

        <div className="kpi">
          <span className="kpi-value">{scored.length === 0 ? "—" : corroborated.length}</span>
          <span className="kpi-label">Avec antécédent dans l'historique</span>
          <span className="kpi-note">
            {scored.length === 0
              ? "sans objet : aucun item vérifié"
              : `${pct(corroborated.length, scored.length)} des items vérifiés · indicateur suivi, pas maximisé`}
          </span>
        </div>

        <div className="kpi">
          <span className="kpi-value">{stateAffiliated.length}</span>
          <span className="kpi-label">Issus d'un média d'État</span>
          <span className="kpi-note">
            {pct(stateAffiliated.length, items.length) ?? "—"} du digest · à lire comme revendications
          </span>
        </div>

        <div className="kpi">
          <span className="kpi-value">{coverage.byCountry.size}</span>
          <span className="kpi-label">Pays couverts</span>
          <span className="kpi-note">
            {coverage.placed} item{coverage.placed > 1 ? "s" : ""} sur {items.length} rattaché
            {coverage.placed > 1 ? "s" : ""} à un pays
            {unplaced.length > 0 && ` — ${unplaced.join(", ")}`}
          </span>
        </div>
  </div>
    </div>
  );
}
