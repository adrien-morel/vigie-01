import { monogram, sourceLogo } from "../lib/logos";

/** The outlet's mark, in a fixed-size cartouche. The light background is constant, in light as in
 *  dark: favicons are drawn for a white background, and many are dark glyphs on transparency — placed
 *  straight onto the dark surface, they disappear. */
export function SourceLogo({ source }: { source: string }) {
  const url = sourceLogo(source);

  if (!url) {
    return (
      <span className="logo logo-mono" title={source} aria-hidden>
        {monogram(source)}
      </span>
    );
  }

  return (
    <span className="logo" title={source}>
      <img src={url} alt="" loading="lazy" decoding="async" />
    </span>
  );
}
