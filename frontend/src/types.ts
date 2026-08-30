export type Category =
  | "export_control"
  | "contrat_armement"
  | "mouvement_militaire"
  | "diplomatie_defense"
  | "programme_industriel"
  | "hors_perimetre";

/** Miroir de AnalyzedItem (backend/state.py). confidence_score et corroborated ne sont
 *  renseignés que pour les items que le portillon du vérificateur a retenus (cf.
 *  has_antecedent_candidate ci-dessous). */
export interface AnalyzedItem {
  source: string;
  lang: string;
  country: string;
  state_affiliated: boolean;
  title: string;
  title_fr: string;
  link: string;
  published: string;
  category: Category;
  summary: string;
  citation: string;
  location: string;
  /** Pays déduit de `location` par le LLM, nom anglais — non vérifiable verbatim.
   *  Optionnel : les digests produits avant son introduction ne le portent pas. */
  location_country?: string;
  /** Protagoniste nommé par la source, vérifié verbatim, et le pays qu'en déduit le LLM.
   *  Rattachent l'item au pays de QUI agit, quand aucun théâtre n'est rattachable — un cran
   *  sous `location_country`, qui répond lui à « où ». Optionnels : absents des digests
   *  produits avant leur introduction. */
  actor?: string;
  actor_country?: string;
  /** Aucun lieu ni acteur rattachable, mais le modèle juge l'événement situé dans le pays de
   *  la source (`country`). Rattachement présumé, le plus faible des quatre. */
  domestic_to_source?: boolean;
  confidence_score: number | null;
  corroborated: boolean | null;
  /** Résultat du portillon d'escalade du vérificateur (VERIFIER_GATE_MIN_SCORE, backend/config.py) :
   *  l'historique portait-il un antécédent candidat au moment de la vérification ? Sépare un
   *  `confidence_score` nul qui est une mesure — rien d'assez proche à recouper — d'un nul qui est
   *  un plafond atteint. Écrit sur tous les items par le nœud verify, escaladés ou non. */
  has_antecedent_candidate: boolean;
  /** Rattachement à un dossier partagé avec d'autres items (V3 tranche 1, backend/agents/threader.py).
   *  Optionnel : les digests produits avant son introduction ne le portent pas. `null`/absent = pas
   *  encore rattaché à un autre item, pas une valeur à combler. */
  thread_id?: string | null;
  /** Ce que le nœud thread a fait de cet item, quand `thread_id` est nul (backend/state.py).
   *  `has_thread_candidate` : l'historique portait-il un candidat au-dessus de THREAD_GATE_MIN_SCORE ;
   *  `thread_checked` : le modèle a-t-il conclu. Il en faut deux là où le vérificateur se contente
   *  d'`has_antecedent_candidate`, une escalade du threader pouvant légitimement ne rien rattacher
   *  (cf. lib/threading.ts). Écrits sur tous les items par le nœud thread, escaladés ou non. */
  has_thread_candidate: boolean;
  thread_checked: boolean;
  /** Horodatage d'entrée dans l'historique — pas la date de publication de l'article, souvent
   *  absente des flux. C'est la seule date toujours présente, donc celle qui ordonne le digest. */
  first_seen?: string;
  /** Jour d'entrée (`YYYY-MM-DD`), qui porte la fenêtre glissante côté backend. */
  date?: string;
}

export interface Digest {
  /** Dernière entrée du digest : la dernière collecte ayant réellement produit quelque chose. */
  generated_at: string | null;
  /** Profondeur servie, en jours. Le digest est une fenêtre glissante sur l'historique analysé,
   *  pas le résultat du dernier run (cf. backend/memory/store.py). */
  window_days: number;
  /** Profondeur maximale consultable, bornée par la rétention de l'historique côté backend. */
  max_window_days: number;
  items: AnalyzedItem[];
}
