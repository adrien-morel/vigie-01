"""Collects the logos of the perimeter's outlets, once, into frontend/src/assets/logos/.

An operator tool, like scripts/daily_run.py: it is imported by no pipeline node and does not ship to
production. It consumes no LLM budget.

Why offline rather than an `<img src="https://.../favicon.ico">` at display time: serving the icons
from the origin sites would fire seventeen requests to third parties every time the digest is opened
(TASS, CGTN and Mehr News among them), would give those third parties the reader's IP address, and
would deliver an interface that degrades whenever one site is down. The files are therefore fetched
once, versioned with the front, and served by Vite like any other asset.

The file name is the slug of the source name (`backend/config.py`). frontend/src/lib/logos.ts applies
exactly the same slug rule and picks the set up through import.meta.glob: no manifest to keep in sync,
and a source with no file simply falls back to its monogram.

    python -m scripts.fetch_logos            # missing sources only
    python -m scripts.fetch_logos --force    # re-download everything
    python -m scripts.fetch_logos --list     # what is present / missing, with no network access
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from backend.config import SOURCES, Source

LOGO_DIR = Path(__file__).resolve().parent.parent / "frontend" / "src" / "assets" / "logos"

# Feeds not hosted by the outlet they publish: the icon of the feed's domain would be Feedburner's,
# not the newsroom's.
SITE_OVERRIDES = {
    "Breaking Defense": "https://breakingdefense.com/",
}

# A format the browser knows how to display in <img>, and nothing else: a .webmanifest or a .json
# declared as rel="icon" exist in the wild and would render nothing.
EXTENSIONS = {
    "image/svg+xml": ".svg",
    "image/png": ".png",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
ALLOWED_SUFFIXES = {".svg", ".png", ".ico", ".jpg", ".jpeg", ".webp"}

# Beyond this it is no longer an icon: some sites declare a header image of several hundred kilobytes
# as rel="icon", which we do not want to version just to display it at 22 px.
MAX_BYTES = 400_000

USER_AGENT = "vigie-01 logo collector (+https://github.com/adrien-morel/vigie-01)"
TIMEOUT = 15


def slugify(name: str) -> str:
    """Must stay the exact mirror of `slugify` in frontend/src/lib/logos.ts."""
    folded = unicodedata.normalize("NFD", name)
    folded = "".join(c for c in folded if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")


class IconLinkParser(HTMLParser):
    """Picks up the <link rel="...icon..."> tags and the site name. We stop at </head>: the page body
    contains none, and some news feeds weigh several megabytes."""

    def __init__(self) -> None:
        super().__init__()
        self.icons: list[tuple[str, str, str]] = []  # (href, rel, sizes)
        self.done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "link":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        rel = a.get("rel", "").lower()
        if "icon" in rel and a.get("href"):
            self.icons.append((a["href"], rel, a.get("sizes", "")))

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self.done = True


def fetch(url: str) -> tuple[bytes, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 - URLs come from config.py
        return response.read(MAX_BYTES + 1), response.headers.get("Content-Type", "")


def icon_rank(href: str, rel: str, sizes: str) -> tuple[int, int]:
    """Best candidate first: vector, then the largest declared size. A 16 px icon stretched into a
    22 px square is blurry on a double-density screen."""
    suffix = Path(urlsplit(href).path).suffix.lower()
    vector = 2 if suffix == ".svg" else 1 if "apple-touch" in rel else 0
    largest = 0
    for token in sizes.lower().split():
        if "x" in token:
            head = token.split("x")[0]
            if head.isdigit():
                largest = max(largest, int(head))
    return (vector, largest)


def discover(site: str) -> list[str]:
    """Icon candidates for a site, from the most promising to the conventional fallback."""
    try:
        html, _ = fetch(site)
    except Exception as exc:  # noqa: BLE001 - an unreachable site must not stop the batch
        print(f"    home page unreachable ({exc.__class__.__name__}) - falling back on /favicon.ico")
        return [urljoin(site, "/favicon.ico")]

    parser = IconLinkParser()
    try:
        parser.feed(html.decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001 - malformed HTML: we keep what was picked up before the error
        pass

    ranked = sorted(parser.icons, key=lambda i: icon_rank(*i), reverse=True)
    candidates = [urljoin(site, href) for href, _, _ in ranked]
    candidates.append(urljoin(site, "/favicon.ico"))
    seen: set[str] = set()
    return [c for c in candidates if not (c in seen or seen.add(c))]


def suffix_for(url: str, content_type: str) -> str | None:
    from_type = EXTENSIONS.get(content_type.split(";")[0].strip().lower())
    if from_type:
        return from_type
    suffix = Path(urlsplit(url).path).suffix.lower()
    return suffix if suffix in ALLOWED_SUFFIXES else None


def collect(name: str, site: str) -> Path | None:
    for url in discover(site):
        try:
            data, content_type = fetch(url)
        except Exception as exc:  # noqa: BLE001 - we simply try the next candidate
            print(f"    {url} - {exc.__class__.__name__}")
            continue
        if not data:
            continue
        if len(data) > MAX_BYTES:
            print(f"    {url} - skipped, over {MAX_BYTES // 1000} kB")
            continue
        suffix = suffix_for(url, content_type)
        if suffix is None:
            print(f"    {url} - type not displayable ({content_type or 'unknown'})")
            continue
        target = LOGO_DIR / f"{slugify(name)}{suffix}"
        for stale in LOGO_DIR.glob(f"{slugify(name)}.*"):
            stale.unlink()
        target.write_bytes(data)
        print(f"    [ok] {target.name} ({len(data) // 1000 or 1} kB) <- {url}")
        return target
    return None


def site_of(source: Source) -> str:
    """The outlet's site, not the feed's: a Feedburner feed would yield Feedburner's icon."""
    parts = urlsplit(source.url)
    return SITE_OVERRIDES.get(source.name) or f"{parts.scheme}://{parts.netloc}/"


def existing(name: str) -> Path | None:
    return next(iter(sorted(LOGO_DIR.glob(f"{slugify(name)}.*"))), None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download even if the file exists")
    parser.add_argument("--list", action="store_true", help="local state, with no network access")
    args = parser.parse_args()

    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    sites = {s.name: site_of(s) for s in SOURCES}

    if args.list:
        for name in sites:
            found = existing(name)
            print(f"{'[ok]' if found else '[--]'} {name:42} {found.name if found else 'monogram'}")
        return 0

    missing: list[str] = []
    for name, site in sites.items():
        found = existing(name)
        if found and not args.force:
            print(f"   {name} - already present ({found.name})")
            continue
        print(f"-> {name} - {site}")
        if collect(name, site) is None:
            missing.append(name)
            print("    no usable logo - the card will show a monogram")

    print(f"\n{len(sites) - len(missing)}/{len(sites)} sources with a logo.")
    if missing:
        print("Without a logo: " + ", ".join(missing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
