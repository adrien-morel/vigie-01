import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiUnreachable, NoDigestYet, fetchDigest } from "./api";
import type { AnalyzedItem, Digest } from "./types";
import { EMPTY_FILTERS, applyFilters, hasActiveFilters, sortItems, type Filters, type SortKey } from "./lib/filters";
import { buildThread, groupThreads } from "./lib/threads";
import { unthreadedReason } from "./lib/threading";
import { FilterRail } from "./components/FilterRail";
import { CommandBar, FilterChips, type View } from "./components/CommandBar";
import { KpiStrip } from "./components/KpiStrip";
import { ItemCard } from "./components/ItemCard";
import { ThreadGroupCard } from "./components/ThreadGroup";
import { ThreadDetail } from "./components/ThreadDetail";
import { WorldMap } from "./components/WorldMap";
import { ArrowUpIcon, GitHubIcon, LinkedInIcon, MoonIcon, SunIcon } from "./components/Icons";

type Status =
  | { kind: "loading" }
  | { kind: "ready"; digest: Digest }
  | { kind: "empty" }
  | { kind: "error"; message: string };

// A stable reference: a `[]` literal recreated on every render would invalidate the memos downstream.
const NO_ITEMS: AnalyzedItem[] = [];

// Bounded at runtime by `max_window_days`: retention is decided on the backend side.
const WINDOW_CHOICES = [1, 3, 7];

const SORT_LABEL: Record<SortKey, string> = {
  recent: "Most recent",
  confidence: "Confidence, descending",
  review: "Human review order",
  category: "By category",
};

/** Where the project and its author live. Two links and nothing more: the digest is the work, these
 *  say who built it and where to read the code. They sit in the sticky bar as well as in the footer
 *  because a digest page runs past fifty thousand pixels — a footer alone is unreachable in
 *  practice. */
const GITHUB_URL = "https://github.com/adrien-morel/vigie-01";
const LINKEDIN_URL = "https://www.linkedin.com/in/adrien-morel";

function windowLabel(days: number): string {
  if (days === 1) return "last 24 h";
  return `last ${days} days`;
}

function relativeStamp(iso: string): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return iso;
  const minutes = Math.round((Date.now() - then.getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return then.toLocaleDateString("en-GB", { day: "2-digit", month: "long", hour: "2-digit", minute: "2-digit" });
}

/** What this list of threads does not say. The number of threads displayed reads spontaneously as the
 *  number of stories the digest contains; it no longer is as soon as the run cap has cut in, and the
 *  gap is visible nowhere else but here and on the cards concerned. */
function UnexaminedNote({ count }: { count: number }) {
  return (
    <p className="note">
      {count} item{count > 1 ? "s" : ""} in this digest had a candidate story in the history but{" "}
      {count > 1 ? "were" : "was"} never submitted for matching: the run's escalation cap or the daily
      budget cut in first. Their lack of a thread is not a measurement — each card concerned says so.
    </p>
  );
}

export default function App() {
  const [status, setStatus] = useState<Status>({ kind: "loading" });
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [view, setView] = useState<View>("list");
  const [sort, setSort] = useState<SortKey>("recent");
  // `null` = let the backend apply its default window.
  const [windowDays, setWindowDays] = useState<number | null>(null);
  // Three states: no explicit choice (follow the system), light, dark. The button offers the opposite
  // of the *effective* theme, without which the first click would change nothing on screen.
  const [theme, setTheme] = useState<"light" | "dark" | null>(
    () => (localStorage.getItem("vigie-theme") as "light" | "dark" | null) ?? null,
  );
  const [systemDark, setSystemDark] = useState(() => matchMedia("(prefers-color-scheme: dark)").matches);
  const effectiveTheme = theme ?? (systemDark ? "dark" : "light");

  const chromeRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  // Two thresholds on the same scroll listener: the bar detaches from the page as soon as anything
  // has scrolled under it, the back-to-top button only appears once returning by scroll has stopped
  // being practical.
  const [detached, setDetached] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const query = matchMedia("(prefers-color-scheme: dark)");
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    if (theme) {
      document.documentElement.dataset.theme = theme;
      localStorage.setItem("vigie-theme", theme);
    } else {
      delete document.documentElement.dataset.theme;
    }
  }, [theme]);

  // Real height of the sticky header, published as a CSS variable. The rail and the tables key off
  // it: a hard-coded constant drifts as soon as the bar wraps onto two lines (narrow window) or a run
  // banner is added to it, and the drift is paid in content unreachable under the rail — precisely the
  // defect this version fixes.
  useEffect(() => {
    const node = chromeRef.current;
    if (!node) return;
    const publish = () =>
      document.documentElement.style.setProperty("--chrome-h", `${Math.round(node.getBoundingClientRect().height)}px`);
    publish();
    const observer = new ResizeObserver(publish);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const onScroll = () => {
      setDetached(window.scrollY > 4);
      setScrolled(window.scrollY > 900);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Reading shortcuts: "/" to search without leaving the keyboard, Escape to get back out of the
  // field. Ignored when the keystroke is already aimed at an input.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const typing = target instanceof HTMLInputElement || target instanceof HTMLSelectElement;
      if (e.key === "/" && !typing && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        searchRef.current?.focus();
        searchRef.current?.select();
      } else if (e.key === "Escape" && typing) {
        searchRef.current?.blur();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const load = useCallback(async () => {
    try {
      setStatus({ kind: "ready", digest: await fetchDigest(windowDays ?? undefined) });
    } catch (e) {
      if (e instanceof NoDigestYet) setStatus({ kind: "empty" });
      else if (e instanceof ApiUnreachable)
        setStatus({ kind: "error", message: `API unreachable at ${e.message}. Is the uvicorn server running?` });
      else setStatus({ kind: "error", message: (e as Error).message });
    }
  }, [windowDays]);

  useEffect(() => {
    void load();
  }, [load]);

  const items = status.kind === "ready" ? status.digest.items : NO_ITEMS;
  const visible = useMemo(() => sortItems(applyFilters(items, filters), sort), [items, filters, sort]);
  // Built on the *filtered* items: a filter can take a thread below the two articles that define it,
  // in which case it disappears from the tab — hence the note displayed further down.
  const threads = useMemo(
    () =>
      groupThreads(visible)
        .filter((group) => group.length > 1)
        .map(buildThread),
    [visible],
  );
  // Items whose threader gate had retained a candidate story, but that the run cap or the daily budget
  // never submitted to the model. Without this count, a short list of threads reads as "there were no
  // more stories" when it says "we did not look any further" — on the 2026-08-21 run, 17 eligible
  // items for 3 attached. Counted over the whole digest and not over the filtered selection, like the
  // measurement tiles (see components/KpiStrip.tsx).
  const unexamined = useMemo(
    () => items.filter((i) => !i.thread_id && unthreadedReason(i) === "capped").length,
    [items],
  );

  return (
    <div className="app">
      {/* A single sticky bar. Separating a title bar from a command bar gave two near-empty strips on a
          wide screen — a logo on the left, a button on the right, a void in the middle — for 120 px of
          height stolen from the digest. The mark, the views and the settings therefore share one line. */}
      <div className={`chrome${detached ? " is-detached" : ""}`} ref={chromeRef}>
        <header className="topbar page-rule">
          <div className="brand" title="Defence & export-control watch">
            {/* The same file as the tab icon: the figurative mark exists in a single place, and does not
                redeclare its colour in a component. */}
            <img className="brand-mark" src="/favicon.svg" alt="" width={20} height={20} />
            <strong>VIGIE</strong>
          </div>

          {status.kind === "ready" && (
            <CommandBar
              view={view}
              onView={setView}
              threadCount={threads.length}
              sort={sort}
              onSort={setSort}
              sortLabels={SORT_LABEL}
              windowDays={status.digest.window_days}
              maxWindowDays={status.digest.max_window_days}
              windowChoices={WINDOW_CHOICES}
              onWindow={setWindowDays}
              windowLabel={windowLabel}
            />
          )}

          <div className="topbar-actions">
            {status.kind === "ready" && status.digest.generated_at && (
              <span className="stamp" title={`Window served: ${windowLabel(status.digest.window_days)}`}>
                collected {relativeStamp(status.digest.generated_at)}
              </span>
            )}

            <a
              className="icon-btn"
              href={GITHUB_URL}
              target="_blank"
              rel="noopener noreferrer"
              aria-label="Source code on GitHub"
              title="Source code on GitHub"
            >
              <GitHubIcon />
            </a>
            <a
              className="icon-btn"
              href={LINKEDIN_URL}
              target="_blank"
              rel="noopener noreferrer"
              aria-label="Adrien Morel on LinkedIn"
              title="Adrien Morel on LinkedIn"
            >
              <LinkedInIcon />
            </a>

            <button
              className="icon-btn"
              onClick={() => setTheme(effectiveTheme === "dark" ? "light" : "dark")}
              aria-label={effectiveTheme === "dark" ? "Switch to the light theme" : "Switch to the dark theme"}
              title={effectiveTheme === "dark" ? "Light theme" : "Dark theme"}
            >
              {effectiveTheme === "dark" ? <SunIcon /> : <MoonIcon />}
            </button>
          </div>
        </header>

        {status.kind === "ready" && <FilterChips filters={filters} onChange={setFilters} />}
      </div>

      {status.kind === "loading" && (
        <div className="body">
          <div className="skeleton" style={{ height: 320 }} />
          <div className="content">
            <div className="skeleton" style={{ height: 88 }} />
            <div className="skeleton" style={{ height: 150 }} />
            <div className="skeleton" style={{ height: 150 }} />
          </div>
        </div>
      )}

      {status.kind === "empty" && (
        <div className="state">
          <h2>No digest generated</h2>
          <p>
            The pipeline has not run yet. Running <code>python -m scripts.daily_run</code>, or{" "}
            <code>POST /run</code> on the API, triggers the RSS collection, deduplication,
            classification and verification — allow a few minutes.
          </p>
        </div>
      )}

      {status.kind === "error" && (
        <div className="state error">
          <h2>Digest unavailable</h2>
          <p>{status.message}</p>
          <button className="btn btn-ghost" onClick={() => void load()}>
            Try again
          </button>
        </div>
      )}

      {status.kind === "ready" && (
        <div className="body">
          <FilterRail items={items} filters={filters} onChange={setFilters} searchRef={searchRef} />

          <main className="content">
            <KpiStrip items={items} filtered={visible.length !== items.length} />

            {view === "map" && (
              <WorldMap
                items={applyFilters(items, filters, "mapCountry")}
                selected={filters.mapCountry}
                onSelect={(id) => setFilters({ ...filters, mapCountry: id })}
              />
            )}

            {items.length === 0 ? (
              // An empty window over a non-empty history: it is the depth that needs widening, not the
              // filters.
              <div className="state">
                <h2>No item in this period</h2>
                <p>
                  Nothing was collected over the last {status.digest.window_days} days. Widen the
                  period, or run the pipeline again.
                </p>
                {status.digest.window_days < status.digest.max_window_days && (
                  <button className="btn btn-ghost" onClick={() => setWindowDays(status.digest.max_window_days)}>
                    Show the {windowLabel(status.digest.max_window_days)}
                  </button>
                )}
              </div>
            ) : visible.length === 0 ? (
              <div className="state">
                <h2>No item matches</h2>
                <p>The active filters exclude every item in this digest.</p>
                <button className="btn btn-ghost" onClick={() => setFilters(EMPTY_FILTERS)}>
                  Reset filters
                </button>
              </div>
            ) : view === "threads" ? (
              threads.length === 0 ? (
                <div className="state">
                  <h2>No thread in this period</h2>
                  <p>
                    A thread is born from matching at least two articles dealing with the same story.
                    Most items stay isolated: that is the normal state of a watch, not an anomaly.
                    Threads will appear here as the history accumulates.
                  </p>
                  {unexamined > 0 && <UnexaminedNote count={unexamined} />}
                  {hasActiveFilters(filters) && (
                    <button className="btn btn-ghost" onClick={() => setFilters(EMPTY_FILTERS)}>
                      Reset filters
                    </button>
                  )}
                </div>
              ) : (
                <div className="list">
                  {hasActiveFilters(filters) && (
                    <p className="note">
                      Threads are rebuilt on the filtered items: an article excluded by a filter is
                      absent from its timeline, and a thread reduced to a single article is no longer
                      displayed here.
                    </p>
                  )}
                  {unexamined > 0 && <UnexaminedNote count={unexamined} />}
                  {threads.map((thread) => (
                    <ThreadDetail key={thread.id} thread={thread} />
                  ))}
                </div>
              )
            ) : (
              <div className="list">
                {groupThreads(visible).map((group) =>
                  group.length > 1 ? (
                    <ThreadGroupCard key={group[0].thread_id} items={group} onOpen={() => setView("threads")} />
                  ) : (
                    <ItemCard key={group[0].link} item={group[0]} />
                  ),
                )}
              </div>
            )}

            {/* What the digest is, said once, at the end — for whoever arrives at this page without
                context. The links repeat those in the bar on purpose: the bar's are icons, reachable
                at any scroll position; these are named, and read. */}
            <footer className="colophon">
              <p>
                <strong>VIGIE</strong> — an automated watch on defence and export control. Seventeen
                RSS feeds across twelve countries, classified and summarised by an LLM agent, every
                summary backed by a quote verified verbatim against its source.
              </p>
              <p className="colophon-links">
                <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer">
                  <GitHubIcon /> Source code
                </a>
                <a href={LINKEDIN_URL} target="_blank" rel="noopener noreferrer">
                  <LinkedInIcon /> Adrien Morel
                </a>
              </p>
            </footer>
          </main>
        </div>
      )}

      {/* Back to the top: a digest page runs past 50,000 pixels, scrolling back is not a workable
          navigation option. */}
      {scrolled && (
        <button
          className="to-top"
          onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
          title="Back to the top"
        >
          <ArrowUpIcon />
          Top of page
        </button>
      )}
    </div>
  );
}
