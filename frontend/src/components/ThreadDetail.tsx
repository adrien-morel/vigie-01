import { useState } from "react";
import { CATEGORY_LABEL, CATEGORY_VAR } from "../lib/taxonomy";
import { formatDuration, type ThreadModel } from "../lib/threads";
import { ItemCard } from "./ItemCard";
import { ThreadTimeline } from "./ThreadTimeline";
import { ThreadProvenance } from "./ThreadProvenance";
import { AlertIcon, CheckIcon, ThreadIcon } from "./Icons";

/** Vue déployée d'un thread : la chronologie et la provenance passent devant l'article, qui
 *  devient le détail qu'on consulte après avoir lu la forme du dossier.
 *
 *  Aucun indicateur agrégé de fiabilité n'est calculé ici. Les compteurs de vérification disent
 *  combien d'articles ont été escaladés et ce qu'il est advenu des autres, en distinguant « rien
 *  d'assez proche à recouper dans l'historique », qui est une mesure, de « le plafond du run a
 *  coupé avant », qui est une absence de mesure : aucun des deux ne vaut un score. */
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
          Thread d'événements
        </span>
      </header>

      <h2 className="td-title">{thread.lead.title_fr}</h2>

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
              {countries} pays d'événement
            </span>
          </>
        )}
        {thread.spanMs > 0 && (
          <>
            <span className="sep">·</span>
            <span>sur {formatDuration(thread.spanMs)}</span>
          </>
        )}
      </p>

      <div className="td-flags">
        {thread.corroborated > 0 && (
          <span className="badge good" title="Le vérificateur a trouvé, dans l'historique des runs précédents, au moins un article traitant du même dossier.">
            <CheckIcon />
            {thread.corroborated} avec antécédent
          </span>
        )}
        {thread.singleSource > 0 && (
          <span className="badge quiet" title="Escaladés au vérificateur, sans article antérieur trouvé sur le même dossier. Le recoupement ne voit jamais les items du run en cours : deux articles collectés dans le même lot ne peuvent pas se corroborer l'un l'autre, même s'ils traitent visiblement du même sujet.">
            {thread.singleSource} sans antécédent à la collecte
          </span>
        )}
        {thread.unscoredCapped > 0 && (
          <span className="badge quiet" title="Un antécédent candidat existait, mais le plafond d'escalade du run ou le budget quotidien a coupé avant ces articles. Absence de mesure, pas mesure d'absence.">
            {thread.unscoredCapped} non vérifié{thread.unscoredCapped > 1 ? "s" : ""}
          </span>
        )}
        {thread.unscoredNoAntecedent > 0 && (
          <span className="badge quiet" title="Le portillon d'escalade n'a trouvé aucun article assez proche dans la fenêtre d'historique : il n'y avait rien à recouper pour ces articles. C'est une mesure, pas un manque — et c'est attendu dans un thread dont toutes les sources sont arrivées dans le même lot.">
            {thread.unscoredNoAntecedent} sans antécédent candidat
          </span>
        )}
        {thread.breaker.state_affiliated && (
          <span className="badge warn" title="Le premier article paru du thread émane d'un média d'État ou d'une agence semi-officielle : la primeur est une revendication, pas un fait établi.">
            <AlertIcon />
            Primeur d'un média d'État
          </span>
        )}
      </div>

      <div className="td-block">
        <h3 className="panel-title">Chronologie</h3>
        <ThreadTimeline thread={thread} selected={selected} onSelect={setSelected} />
      </div>

      <div className="td-block">
        <h3 className="panel-title">Provenance</h3>
        <ThreadProvenance thread={thread} />
      </div>

      <div className="td-block">
        <h3 className="panel-title">
          Article sélectionné · {selected + 1} sur {thread.items.length}
        </h3>
        <ItemCard item={shown} />
      </div>
    </section>
  );
}
