"""API FastAPI : expose le digest genere par le pipeline (README architecture).

/run declenche le pipeline complet (~5 min, cf. NOTES.private.md) ; /events sert une fenetre
glissante sur l'historique analyse, sans rien recalculer. Declenchement manuel en V1 (POST /run
appele a la main), remplace par Cloud Scheduler -> Cloud Run job en production.

Le digest n'est deliberement pas le resultat du dernier run : le dedoublonnage ecarte avant l'appel
LLM tout ce qui a deja ete vu dans les 7 derniers jours, donc un second run dans la meme journee ne
renvoie qu'une poignee d'items neufs. Servir ce resultat brut reviendrait a effacer l'historique
affiche a chaque collecte (cf. backend/memory/store.py).
"""

import secrets
import time

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.config import ALLOWED_ORIGINS, DIGEST_WINDOW_DAYS, RUN_TOKEN
from backend.graph import run_pipeline
from backend.logging_setup import configure_logging, get_logger
from backend.memory.store import RELATED_ITEMS_WINDOW_DAYS, last_run_at, load_digest

configure_logging()
log = get_logger("api")

app = FastAPI(title="VEILLE-01 API")

# Restreint aux origines declarees (backend/config.py, ALLOWED_ORIGINS) depuis la preparation du
# deploiement. Le « * » de la V1 evitait une configuration au demarrage ; il autorisait aussi
# n'importe quelle page a lire le digest depuis le navigateur d'un visiteur.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _authorize_run(token: str) -> None:
    """Ferme POST /run par jeton partage. Deux refus distincts, volontairement :

    503 quand aucun jeton n'est configure — le service tourne mais l'endpoint le plus couteux du
    systeme n'a pas de garde, et l'ouvrir « en attendant » est exactement ce que le plafond de
    budget interdit. Meme logique que MAX_STEPS_PER_RUN / MAX_LLM_CALLS_PER_DAY, qui font echouer
    l'import plutot que de prendre une valeur par defaut ; ici l'echec est porte par l'endpoint et
    non par le demarrage, pour que GET /events continue de servir le digest deja produit.

    401 quand un jeton est configure mais que l'appelant n'a pas le bon.

    compare_digest et non « == » : la comparaison naive s'arrete au premier octet different, ce qui
    laisse deviner le jeton octet par octet en mesurant le temps de reponse.
    """
    if not RUN_TOKEN:
        log.error("POST /run appele sans RUN_TOKEN configure : endpoint ferme")
        raise HTTPException(
            status_code=503,
            detail="RUN_TOKEN non configure : POST /run est ferme. Definir RUN_TOKEN pour l'activer.",
        )
    if not secrets.compare_digest(token, RUN_TOKEN):
        log.warning("POST /run refuse : jeton invalide")
        raise HTTPException(status_code=401, detail="Jeton invalide.")


@app.post("/run")
def run(x_run_token: str = Header(default="", alias="X-Run-Token")) -> dict:
    _authorize_run(x_run_token)

    # Le plafond de budget (garde-fou §8) ne remonte plus jusqu'ici : il tronque le run dans les
    # noeuds qui appellent le modele, qui rendent ce qu'ils ont deja produit et payé. Un run
    # tronqué est donc un succes partiel — 200 avec truncated=True — et non un 429 : repondre par
    # une erreur ferait ignorer au client un digest qui a bien ete enrichi, ce qui etait le cas
    # avant cette correction (le front ne recharge pas le digest sur erreur).
    # Debut, fin, duree et troncature sont journalises ici et pas seulement renvoyes dans le corps
    # de la reponse : Cloud Scheduler ne lit pas ce corps. Sans ces lignes, un run tronque en
    # production est indiscernable d'un run complet, et une duree qui derive (401 s le 2026-08-20,
    # 620 s le 2026-08-22) ne se voit qu'au moment ou elle depasse le timeout du service.
    started = time.monotonic()
    log.info("POST /run accepte")
    result = run_pipeline()
    duree = round(time.monotonic() - started, 1)
    if result["truncated"]:
        # Une troncature n'est pas une erreur : c'est un succes partiel, et les deux doivent se
        # distinguer dans une alerte (WARNING contre ERROR), pas se confondre dans un total d'echecs.
        log.warning("run tronque par un plafond", extra={"duree_s": duree, "items": len(result["analyzed_items"])})
    log.info(
        "POST /run termine",
        extra={"duree_s": duree, "items": len(result["analyzed_items"]), "truncated": result["truncated"]},
    )
    return {"item_count": len(result["analyzed_items"]), "truncated": result["truncated"]}


@app.get("/events")
def events(
    days: int = Query(
        DIGEST_WINDOW_DAYS,
        ge=1,
        le=RELATED_ITEMS_WINDOW_DAYS,
        description="Profondeur du digest en jours, bornee par la retention de l'historique analyse.",
    ),
) -> dict:
    items = load_digest(days)
    # 404 signifie « le pipeline n'a jamais tourne », pas « rien sur cette periode » : une fenetre
    # etroite sur un historique non vide doit rester un digest vide navigable, avec le selecteur de
    # periode disponible pour elargir.
    if not items and not load_digest(RELATED_ITEMS_WINDOW_DAYS):
        raise HTTPException(status_code=404, detail="Aucun digest genere. Appeler POST /run d'abord.")
    return {
        "generated_at": last_run_at(items),
        "window_days": days,
        "max_window_days": RELATED_ITEMS_WINDOW_DAYS,
        "items": items,
    }
