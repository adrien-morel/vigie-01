import type { AnalyzedItem, Category } from "../types";
import { publishedMs } from "./filters";
import { computeCoverage, type Coverage } from "./coverage";
import { unscoredReason } from "./verification";

/** Un groupe d'un seul item est un item autonome ; un groupe de plusieurs est un thread. */
export type ThreadGroup = AnalyzedItem[];

/** Regroupe une liste déjà filtrée/triée par `thread_id`, sans changer l'ordre relatif : un groupe
 *  apparaît à la position de son premier item rencontré, les occurrences suivantes du même
 *  `thread_id` s'y ajoutent plutôt que de créer une nouvelle entrée plus loin dans la liste. Un
 *  item sans `thread_id` reste seul — ce n'est pas un thread de taille 1, il n'a jamais été
 *  rapproché d'un autre dossier.
 *
 *  Chaque groupe de plusieurs items est ensuite trié par ordre chronologique croissant, quel que
 *  soit le critère de tri global (confiance, catégorie…) qui a déterminé la position du groupe
 *  lui-même : c'est ce qui fait du thread une chronologie plutôt qu'un simple paquet d'articles
 *  liés. */
export function groupThreads(items: AnalyzedItem[]): ThreadGroup[] {
  const groups: ThreadGroup[] = [];
  const indexByThreadId = new Map<string, number>();

  for (const item of items) {
    const threadId = item.thread_id;
    if (!threadId) {
      groups.push([item]);
      continue;
    }
    const existing = indexByThreadId.get(threadId);
    if (existing === undefined) {
      indexByThreadId.set(threadId, groups.length);
      groups.push([item]);
    } else {
      groups[existing].push(item);
    }
  }

  for (const group of groups) {
    if (group.length > 1) group.sort((a, b) => publishedMs(a) - publishedMs(b));
  }

  return groups;
}

/** Sur quoi repose la position d'un item dans le temps. `publishedMs` retombe sur `first_seen`
 *  quand le flux ne date pas l'article — repli indispensable au tri, mais que l'affichage ne doit
 *  jamais présenter comme une date de parution : `first_seen` est un horodatage de lot, partagé
 *  par tous les items d'un même run. Les confondre sur un axe temporel ferait lire une collecte
 *  groupée comme une salve de publications simultanées. */
export type DateOrigin = "published" | "first_seen";

export function dateOrigin(item: AnalyzedItem): DateOrigin {
  const t = item.published ? new Date(item.published).getTime() : NaN;
  return Number.isNaN(t) ? "first_seen" : "published";
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** Durée écoulée, en français, sans jamais arrondir à zéro : deux parutions séparées de quelques
 *  secondes sont quasi simultanées, ce que « 0 min » ferait lire comme « en même temps ». */
export function formatDuration(ms: number): string {
  if (ms < MINUTE) return "moins d'une minute";
  if (ms < HOUR) return `${Math.round(ms / MINUTE)} min`;
  if (ms < DAY) {
    const h = Math.floor(ms / HOUR);
    const m = Math.round((ms % HOUR) / MINUTE);
    return m === 0 ? `${h} h` : `${h} h ${String(m).padStart(2, "0")}`;
  }
  const d = Math.floor(ms / DAY);
  const h = Math.round((ms % DAY) / HOUR);
  return h === 0 ? `${d} j` : `${d} j ${h} h`;
}

export interface SourceCountryBucket {
  count: number;
  /** Nombre d'articles de ce pays émanant d'un média d'État — pas un booléen : deux dépêches
   *  d'agence officielle sur cinq articles ne se lit pas comme cinq sur cinq. */
  stateAffiliated: number;
}

/** Agrégat dérivé d'un groupe d'items partageant un `thread_id`. Il n'existe aucun objet thread
 *  côté backend (`backend/agents/threader.py` ne fait qu'écrire l'identifiant sur des items) : ce
 *  modèle est calculé côté client, une fois, pour que la chronologie, la provenance et l'en-tête
 *  décrivent le même thread au lieu de le recalculer chacun de leur côté.
 *
 *  Ce qui est délibérément absent : tout score agrégé. `model_confidence` et `corroborated` valent
 *  `null` sur les items que le vérificateur n'a pas escaladés, et combler ce vide par une moyenne
 *  ferait passer un thread non vérifié pour un thread moyennement fiable. On expose la
 *  distribution, l'affichage la rend telle quelle. */
export interface ThreadModel {
  id: string;
  /** Chronologique croissant. */
  items: AnalyzedItem[];
  /** Premier paru : qui sort l'information. */
  breaker: AnalyzedItem;
  /** Plus récent : porte le titre et la catégorie du thread. */
  lead: AnalyzedItem;
  category: Category;
  startMs: number;
  endMs: number;
  spanMs: number;
  /** Items réellement datés par leur flux. Le complément est positionné par `first_seen`. */
  datedByPublication: number;
  /** Sources distinctes, dans l'ordre de première parution. */
  sources: string[];
  /** Pays des médias — jamais mélangé au pays de l'événement (`coverage`). Les confondre
   *  rattacherait une dépêche TASS sur le Yémen à la Russie (cf. `resolveLocation`, lib/geo.ts). */
  sourceCountries: Map<string, SourceCountryBucket>;
  /** Lieu des événements, avec les quatre niveaux de provenance et les échecs de rattachement. */
  coverage: Coverage;
  scored: AnalyzedItem[];
  corroborated: number;
  singleSource: number;
  /** Non scorés alors qu'un antécédent candidat existait : le plafond du run ou le budget les a
   *  laissés de côté. C'est le seul des trois comptes qui soit une absence de mesure. */
  unscoredCapped: number;
  /** Non scorés parce que l'historique ne portait rien d'assez proche à recouper — une mesure, pas
   *  un manque. */
  unscoredNoAntecedent: number;
  /** Non scorés parce qu'analysés avant le 2026-08-20, quand le vérificateur ne couvrait que deux
   *  catégories. Tombe à zéro dès que la fenêtre de rétention a dépassé cette date. */
}

/** Construit le modèle d'un thread. Attend un groupe d'au moins deux items partageant un
 *  `thread_id` (ce que produit `groupThreads`) ; retrie par sécurité, l'ordre chronologique étant
 *  le seul invariant dont tout le rendu dépend. */
export function buildThread(group: AnalyzedItem[]): ThreadModel {
  const items = [...group].sort((a, b) => publishedMs(a) - publishedMs(b));
  const breaker = items[0];
  const lead = items[items.length - 1];

  const sources: string[] = [];
  const sourceCountries = new Map<string, SourceCountryBucket>();
  let datedByPublication = 0;
  let corroborated = 0;
  let singleSource = 0;
  let unscoredCapped = 0;
  let unscoredNoAntecedent = 0;

  for (const item of items) {
    if (!sources.includes(item.source)) sources.push(item.source);

    let bucket = sourceCountries.get(item.country);
    if (!bucket) {
      bucket = { count: 0, stateAffiliated: 0 };
      sourceCountries.set(item.country, bucket);
    }
    bucket.count += 1;
    if (item.state_affiliated) bucket.stateAffiliated += 1;

    if (dateOrigin(item) === "published") datedByPublication += 1;
    if (item.corroborated === true) corroborated += 1;
    if (item.corroborated === false) singleSource += 1;
    if (item.model_confidence === null) {
      const reason = unscoredReason(item);
      if (reason === "capped") unscoredCapped += 1;
      else unscoredNoAntecedent += 1;
    }
  }

  const startMs = publishedMs(breaker);
  const endMs = publishedMs(lead);

  return {
    id: breaker.thread_id ?? lead.link,
    items,
    breaker,
    lead,
    category: lead.category,
    startMs,
    endMs,
    spanMs: endMs - startMs,
    datedByPublication,
    sources,
    sourceCountries,
    coverage: computeCoverage(items),
    scored: items.filter((i) => i.model_confidence !== null),
    corroborated,
    singleSource,
    unscoredCapped,
    unscoredNoAntecedent,
  };
}
