import type { Category } from "../types";

/** Display order = order of the palette's categorical slots. It is fixed: a category keeps its hue
 *  whatever filters are active (the colour follows the entity, not its rank).
 *  `out_of_scope` takes a neutral grey rather than a categorical slot: it is the absence of a
 *  category, not one more category. */
export const CATEGORIES: Category[] = [
  "export_control",
  "arms_contract",
  "military_movement",
  "defense_diplomacy",
  "industrial_program",
  "out_of_scope",
];

export const CATEGORY_LABEL: Record<Category, string> = {
  export_control: "Export control",
  arms_contract: "Arms contract",
  military_movement: "Military movement",
  defense_diplomacy: "Defence diplomacy",
  industrial_program: "Industrial programme",
  out_of_scope: "Out of scope",
};

/** Rendered through var(--cat-*), defined in both light and dark in styles.css. */
export const CATEGORY_VAR: Record<Category, string> = {
  export_control: "var(--cat-1)",
  arms_contract: "var(--cat-2)",
  military_movement: "var(--cat-3)",
  defense_diplomacy: "var(--cat-4)",
  industrial_program: "var(--cat-5)",
  out_of_scope: "var(--cat-none)",
};

export const LANG_LABEL: Record<string, string> = {
  fr: "French",
  en: "English",
  de: "German",
  it: "Italian",
  es: "Spanish",
};
