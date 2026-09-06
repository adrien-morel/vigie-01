/** Outlet logos, collected offline by `python -m scripts.fetch_logos` and versioned in
 *  `src/assets/logos/`. Nothing is loaded from the origin sites at display time: seventeen requests
 *  to third parties every time the digest is opened would give them the reader's IP address, and the
 *  interface would degrade as soon as one site went down.
 *
 *  No manifest to keep in sync: the file name is the slug of the source name, and the set is picked
 *  up at build time. A source with no file — three were at collection time, their sites refusing the
 *  request — falls back on its monogram, never on a broken image. */
const FILES = import.meta.glob("../assets/logos/*", {
  eager: true,
  query: "?url",
  import: "default",
}) as Record<string, string>;

const BY_SLUG = new Map<string, string>();
for (const [path, url] of Object.entries(FILES)) {
  const file = path.split("/").pop() ?? "";
  BY_SLUG.set(file.replace(/\.[^.]+$/, ""), url);
}

/** Exact mirror of `slugify` in scripts/fetch_logos.py — the two name the same file. */
function slugify(name: string): string {
  return name
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

export const sourceLogo = (source: string): string | null => BY_SLUG.get(slugify(source)) ?? null;

/** A readable fallback when the logo is missing: the initials of the first two words, or the first
 *  two letters of a single-word name. The full name is still carried by the element's title — the
 *  monogram is a scanning cue, not an identification. */
export function monogram(source: string): string {
  const words = source.split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}
