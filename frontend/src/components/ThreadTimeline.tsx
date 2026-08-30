import { useMemo } from "react";
import type { AnalyzedItem } from "../types";
import { publishedMs } from "../lib/filters";
import { dateOrigin, formatDuration, type ThreadModel } from "../lib/threads";
import { confidenceColor } from "../lib/confidence";
import { AlertIcon, CheckIcon } from "./Icons";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** Écart en dessous duquel deux étiquettes se chevaucheraient, en % de la piste. On décale alors
 *  l'étiquette d'une rangée — jamais le nœud, dont l'abscisse encode un instant réel. */
const MIN_GAP_PCT = 17;
const MAX_ROW = 2;

/** Pas de graduation gardant une dizaine de repères au plus, de quelques minutes entre deux
 *  dépêches à plusieurs semaines de dossier. */
function tickStep(spanMs: number): number {
  if (spanMs <= 2 * HOUR) return 30 * MINUTE;
  if (spanMs <= 8 * HOUR) return HOUR;
  if (spanMs <= 2 * DAY) return 6 * HOUR;
  if (spanMs <= 10 * DAY) return DAY;
  return 7 * DAY;
}

/** Graduations alignées sur les frontières locales (heure pleine, minuit), pas sur des multiples
 *  de l'instant de départ : un repère à « 14:06 » ne se lit pas, « 15 h » si. */
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
  if (step >= DAY) return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "short" });
  return d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

function clockLabel(item: AnalyzedItem): string {
  return new Date(publishedMs(item)).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

function nodeTitle(item: AnalyzedItem, delta: number | null): string {
  const parts = [item.source];
  parts.push(
    dateOrigin(item) === "published"
      ? new Date(publishedMs(item)).toLocaleString("fr-FR", {
          day: "2-digit",
          month: "long",
          hour: "2-digit",
          minute: "2-digit",
        })
      : "date de publication absente du flux — position donnée par l'entrée en base",
  );
  if (delta !== null) parts.push(`${formatDuration(delta)} après la parution précédente`);
  parts.push(item.model_confidence !== null ? `confiance ${item.model_confidence.toFixed(2)}` : "non vérifié");
  if (item.corroborated === true) parts.push("avec antécédent dans l'historique");
  if (item.corroborated === false) parts.push("sans antécédent à la collecte");
  if (item.state_affiliated) parts.push("média d'État");
  return parts.join(" · ");
}

interface Props {
  thread: ThreadModel;
  selected: number;
  onSelect: (index: number) => void;
  /** Variante resserrée pour la vue Liste : mêmes positions, moins de texte autour. */
  compact?: boolean;
}

/** Chronologie d'un thread, à l'échelle réelle du temps : l'écart entre deux parutions est le
 *  signal (qui sort l'information, combien de temps la reprise met à suivre), et des nœuds
 *  équidistants rendraient identiques trois dépêches en vingt minutes et un dossier de trois
 *  semaines.
 *
 *  Rendu en HTML positionné plutôt qu'en SVG : les étiquettes sont du texte à taille naturelle,
 *  les nœuds de vrais boutons focusables, et la piste suit la largeur disponible sans mesure. */
export function ThreadTimeline({ thread, selected, onSelect, compact = false }: Props) {
  const { items, startMs, spanMs } = thread;

  // Items tous horodatés à l'identique (flux non datés, collectés dans le même lot) : aucun
  // étalement à représenter, la piste bascule en disposition ordinale et le dit.
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
                        <span className="tl-warn" aria-label="Média d'État">
                          <AlertIcon />
                        </span>
                      )}
                      <span className="tl-name">{item.source}</span>
                      {item.corroborated === true && (
                        <span className="tl-good" aria-label="Avec antécédent dans l'historique">
                          <CheckIcon />
                        </span>
                      )}
                    </span>
                    <span className="tl-when">
                      {i === 0
                        ? ordinal
                          ? "premier"
                          : clockLabel(item)
                        : `+ ${formatDuration(layout.deltas[i]!)}`}
                      {collected && " · collecté"}
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
          <span className="tl-first">Première parution : {thread.breaker.source}</span>
          {ordinal ? (
            <span>Horodatages identiques — ordre seul, aucune durée mesurable.</span>
          ) : (
            <span>Étalement du thread : {formatDuration(spanMs)}.</span>
          )}
          {undated > 0 && (
            <span>
              {undated} article{undated > 1 ? "s" : ""} sans date de publication dans le flux, placé
              {undated > 1 ? "s" : ""} à leur entrée en base (horodatage de lot, pas de parution).
            </span>
          )}
        </figcaption>
      )}
    </figure>
  );
}
