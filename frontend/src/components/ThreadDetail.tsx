import { useState } from "react";
import { CATEGORY_LABEL, CATEGORY_VAR } from "../lib/taxonomy";
import { formatDuration, type ThreadModel } from "../lib/threads";
import { ItemCard } from "./ItemCard";
import { ThreadTimeline } from "./ThreadTimeline";
import { ThreadProvenance } from "./ThreadProvenance";
import { AlertIcon, CheckIcon, ThreadIcon } from "./Icons";

/** The expanded view of a thread: the timeline and the provenance come ahead of the article, which
 *  becomes the detail one consults after reading the shape of the story.
 *
 *  No aggregate reliability indicator is computed here. The verification counters say how many
 *  articles were escalated and what became of the others, distinguishing "nothing close enough to
 *  cross-check in the history", which is a measurement, from "the run cap cut in before", which is an
 *  absence of measurement: neither of the two amounts to a score. */
export function ThreadDetail({ thread }: { thread: ThreadModel }) {
  const [selected, setSelected] = useState(thread.items.length - 1);
  const shown = thread.items[selected] ?? thread.lead;
  const countries = thread.coverage.byCountry.size;

  return (
    <section className="panel thread-detail" style={{ ["--cat" as string]: CATEGORY_VAR[thread.category] }}>
      <header className="td-head">
        <span className="badge">
          <i className="dot" style={{ ["--dot" as string]: CATEGORY_VAR[thread.category] }} />
          {CATEGORY_LABEL[thread.category]}
        </span>
        <span className="td-kind">
          <ThreadIcon />
          Event thread
        </span>
      </header>

      <h2 className="td-title">{thread.lead.title_en}</h2>

      <p className="td-meta">
        <span>
          {thread.items.length} article{thread.items.length > 1 ? "s" : ""}
        </span>
        <span className="sep">·</span>
        <span>
          {thread.sources.length} source{thread.sources.length > 1 ? "s" : ""} ({thread.sources.join(", ")})
        </span>
        {countries > 0 && (
          <>
            <span className="sep">·</span>
            <span>
              {countries} event {countries > 1 ? "countries" : "country"}
            </span>
          </>
        )}
        {thread.spanMs > 0 && (
          <>
            <span className="sep">·</span>
            <span>over {formatDuration(thread.spanMs)}</span>
          </>
        )}
      </p>

      <div className="td-flags">
        {thread.corroborated > 0 && (
          <span
            className="badge good"
            title="The verifier found, in the history of previous runs, at least one article dealing with the same story."
          >
            <CheckIcon />
            {thread.corroborated} with an antecedent
          </span>
        )}
        {thread.singleSource > 0 && (
          <span
            className="badge quiet"
            title="Escalated to the verifier, with no earlier article found on the same story. Cross-checking never sees the items of the current run: two articles collected in the same batch cannot corroborate each other, even when they visibly deal with the same subject."
          >
            {thread.singleSource} with no antecedent at collection time
          </span>
        )}
        {thread.unscoredCapped > 0 && (
          <span
            className="badge quiet"
            title="A candidate antecedent existed, but the run's escalation cap or the daily budget cut in before these articles. An absence of measurement, not a measurement of absence."
          >
            {thread.unscoredCapped} unverified
          </span>
        )}
        {thread.unscoredNoAntecedent > 0 && (
          <span
            className="badge quiet"
            title="The escalation gate found no article close enough in the history window: there was nothing to cross-check for these articles. That is a measurement, not a gap — and it is expected in a thread whose sources all arrived in the same batch."
          >
            {thread.unscoredNoAntecedent} with no candidate antecedent
          </span>
        )}
        {thread.breaker.state_affiliated && (
          <span
            className="badge warn"
            title="The first article published in the thread comes from a state outlet or a semi-official agency: the scoop is a claim, not an established fact."
          >
            <AlertIcon />
            Broken by a state outlet
          </span>
        )}
      </div>

      <div className="td-block">
        <h3 className="panel-title">Timeline</h3>
        <ThreadTimeline thread={thread} selected={selected} onSelect={setSelected} />
      </div>

      <div className="td-block">
        <h3 className="panel-title">Provenance</h3>
        <ThreadProvenance thread={thread} />
      </div>

      <div className="td-block">
        <h3 className="panel-title">
          Selected article · {selected + 1} of {thread.items.length}
        </h3>
        <ItemCard item={shown} />
      </div>
    </section>
  );
}
