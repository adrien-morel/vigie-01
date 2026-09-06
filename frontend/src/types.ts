export type Category =
  | "export_control"
  | "arms_contract"
  | "military_movement"
  | "defense_diplomacy"
  | "industrial_program"
  | "out_of_scope";

/** Mirror of AnalyzedItem (backend/state.py). model_confidence and corroborated are only filled in
 *  for the items the verifier's gate retained (see has_antecedent_candidate below). */
export interface AnalyzedItem {
  source: string;
  lang: string;
  country: string;
  state_affiliated: boolean;
  title: string;
  title_en: string;
  link: string;
  published: string;
  category: Category;
  summary: string;
  citation: string;
  location: string;
  /** Country inferred from `location` by the LLM, English name — not verifiable verbatim.
   *  Optional: digests produced before it was introduced do not carry it. */
  location_country?: string;
  /** Protagonist named by the source, verified verbatim, and the country the LLM infers from it.
   *  They attach the item to the country of WHO acts, when no theatre is attachable — one notch
   *  below `location_country`, which answers "where". Optional: absent from digests produced before
   *  they were introduced. */
  actor?: string;
  actor_country?: string;
  /** No attachable place or actor, but the model judges the event to be located in the country of
   *  the source (`country`). A presumed attachment, the weakest of the four. */
  domestic_to_source?: boolean;
  /** The model's self-assessment, not a calibrated probability — the name has said so since
   *  2026-08-30. Null when the verifier did not conclude, never filled in with a zero. */
  model_confidence: number | null;
  corroborated: boolean | null;
  /** Result of the verifier's escalation gate (VERIFIER_GATE_MIN_SCORE, backend/config.py): did the
   *  history hold a candidate antecedent at verification time? It separates a null
   *  `model_confidence` that is a measurement — nothing close enough to cross-check — from a null
   *  that is a cap being reached. Written on every item by the verify node, escalated or not. */
  has_antecedent_candidate: boolean;
  /** Attachment to a story shared with other items (V3 slice 1, backend/agents/threader.py).
   *  Optional: digests produced before it was introduced do not carry it. `null`/absent = not yet
   *  attached to another item, not a value to fill in. */
  thread_id?: string | null;
  /** What the thread node did with this item, when `thread_id` is null (backend/state.py).
   *  `has_thread_candidate`: did the history hold a candidate above THREAD_GATE_MIN_SCORE;
   *  `thread_checked`: did the model conclude. Two are needed where the verifier makes do with
   *  `has_antecedent_candidate`, since a threader escalation can legitimately attach nothing
   *  (see lib/threading.ts). Written on every item by the thread node, escalated or not. */
  has_thread_candidate: boolean;
  thread_checked: boolean;
  /** Timestamp of entry into the history — not the article's publication date, which feeds often
   *  omit. It is the only date always present, and therefore the one that orders the digest. */
  first_seen?: string;
  /** Day of entry (`YYYY-MM-DD`), which carries the sliding window on the backend side. */
  date?: string;
}

export interface Digest {
  /** Last entry in the digest: the last collection that actually produced something. */
  generated_at: string | null;
  /** Depth served, in days. The digest is a sliding window over the analysed history, not the
   *  result of the last run (see backend/memory/store.py). */
  window_days: number;
  /** Maximum consultable depth, bounded by the history retention on the backend side. */
  max_window_days: number;
  items: AnalyzedItem[];
}
