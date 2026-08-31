"""Configuration centrale : sources de veille, plafonds, clés d'environnement."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    lang: str
    theme: str  # export_control | contrats | mouvements | diplomatie | programmes
    country: str  # code pays ISO 3166-1 alpha-2, ou "INT" pour une source multi-pays/institutionnelle UE
    state_affiliated: bool = False  # média d'État ou lié à un service officiel — cf. docs/cadrage.md §4
    # Override de MAX_ITEMS_PER_SOURCE_PER_RUN. Réservé aux flux généralistes (agence de presse
    # nationale, pas de rédaction défense dédiée) dont le ratio appels LLM / item retenu mesuré sur
    # échantillon annoté est nettement pire que la moyenne (cf. docs/cadrage.md §7) : le plafond par
    # défaut suffit à border le coût, mais pas à corriger un rendement structurellement mauvais.
    max_per_run: int | None = None


# Sources vérifiées manuellement (feed RSS testé en direct au 2026-08-14, cf. docs/cadrage.md §4).
# Périmètre géographique : top 10 exportateurs d'armement SIPRI (Trends in International Arms
# Transfers, mars 2025, données 2020-24) + Iran/Corée du Nord pour la couverture export_control
# (régimes sous embargo actif, absents du classement SIPRI par volume).
SOURCES: list[Source] = [
    # États-Unis (43% des exports mondiaux)
    Source("Breaking Defense", "https://feeds.feedburner.com/breakingdefense", "en", "programmes", "US"),
    Source("Defense News", "https://www.defensenews.com/arc/outboundfeeds/rss/", "en", "contrats", "US"),
    # OFAC (Treasury) retiré le 2026-08-17 : flux mort depuis plus d'un an au moment du constat
    # (dernière entrée 2025-07-01), comptait comme source "active" dans le KPI de couverture (§7)
    # sans produire un seul item — remplacé par le Bureau of Industry and Security (Federal
    # Register), qui administre les Export Administration Regulations, cible plus directe du
    # périmètre export_control que le Treasury pour ce produit.
    Source(
        "Federal Register – BIS (export control)",
        "https://www.federalregister.gov/api/v1/documents.rss"
        "?conditions%5Bagencies%5D%5B%5D=industry-and-security-bureau",
        "en",
        "export_control",
        "US",
    ),
    Source(
        "Defense.gov (DoD)",
        "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945",
        "en",
        "mouvements",
        "US",
    ),
    # Ajouté le 2026-08-17 : presse spécialisée navale, en renfort du volume US (le flux le plus
    # massivement exportateur du périmètre n'avait, avant ce correctif, aucune source active dans
    # une fenêtre de collecte de 48 h — cf. correctif de la fenêtre ci-dessous).
    Source("Naval News", "https://www.navalnews.com/feed/", "en", "mouvements", "US"),
    # France (9.6%)
    Source("Opex360", "https://opex360.com/feed/", "fr", "mouvements", "FR"),
    Source("Bruxelles2", "https://bruxelles2.eu/api/rss.xml", "fr", "diplomatie", "INT"),
    # Russie (7.8%, en forte baisse) — pas de presse indépendante accessible, TASS = média d'État
    Source("TASS", "https://tass.com/rss/v2.xml", "en", "mouvements", "RU", state_affiliated=True),
    # Chine (5.9%) — pas de presse indépendante accessible, CGTN = média d'État ; feed généraliste
    # Chine (pas de flux spécifique défense trouvé). max_per_run réduit le 2026-08-17 : sur
    # échantillon annoté (n=6), 6/6 hors_perimetre — aucun item retenu pour ~12 appels/jour au
    # plafond par défaut. Pas retiré (seule couverture Chine disponible gratuitement, §4), mais
    # plafonné au coût que ce rendement justifie.
    Source(
        "CGTN (Chine, généraliste)",
        "https://www.cgtn.com/subscribe/rss/section/china.xml",
        "en",
        "mouvements",
        "CN",
        state_affiliated=True,
        max_per_run=5,
    ),
    # Allemagne (5.6%)
    Source("Hartpunkt", "https://www.hartpunkt.de/feed/", "de", "programmes", "DE"),
    Source("ESUT", "https://esut.de/feed/", "de", "mouvements", "DE"),
    # Italie (4.8%, +138% — plus forte croissance du top 10)
    Source("Analisi Difesa", "https://www.analisidifesa.it/feed/", "it", "programmes", "IT"),
    # Royaume-Uni (3.6%)
    Source("UK Defence Journal", "https://ukdefencejournal.org.uk/feed/", "en", "programmes", "GB"),
    # Israël (3.1%) — pas de flux SIBAT/MOD trouvé, presse généraliste filtrée en aval par le LLM.
    # max_per_run réduit le 2026-08-17 : 5/6 hors_perimetre sur échantillon annoté.
    Source(
        "Jerusalem Post (généraliste)",
        "https://www.jpost.com/rss/rssfeedsfrontpage.aspx",
        "en",
        "diplomatie",
        "IL",
        max_per_run=8,
    ),
    # Espagne (3.0%, +29%)
    Source("Infodefensa", "https://www.infodefensa.com/feed/all", "es", "contrats", "ES"),
    # Corée du Sud (2.2%) — pas de flux DAPA trouvé, dépêches Yonhap généralistes filtrées en aval.
    # max_per_run réduit le 2026-08-17 : 4/6 hors_perimetre sur échantillon annoté, plus haut volume
    # brut du périmètre après TASS.
    Source("Yonhap (généraliste)", "https://en.yna.co.kr/RSS/national.xml", "en", "mouvements", "KR", max_per_run=8),
    # Iran — hors top 10 SIPRI (0.4%, +749% quasi exclusivement vers la Russie), couverture
    # export_control ; Mehr News est un média semi-officiel (gouvernemental). max_per_run ajouté
    # le 2026-08-18 : 5/6 hors_perimetre sur l'échantillon annoté du §7 (n=68) — même ratio que
    # Jerusalem Post, manqué lors du correctif du 2026-08-17 qui n'avait couvert que trois flux.
    # Pas retirée (seule couverture Iran disponible gratuitement, §4), mais plafonnée au rendement
    # qu'elle démontre.
    Source(
        "Mehr News (Iran)",
        "https://en.mehrnews.com/rss",
        "en",
        "export_control",
        "IR",
        state_affiliated=True,
        max_per_run=8,
    ),
    # Corée du Nord — hors classement SIPRI, transferts sous embargo vers la Russie ; NK News agrège
    # les médias d'État nord-coréens (KCNA), seule source practicable identifiée
    Source(
        "NK News",
        "https://www.nknews.org/feed/",
        "en",
        "export_control",
        "KP",
        state_affiliated=True,
    ),
]

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
LANGCHAIN_API_KEY = os.getenv("LANGCHAIN_API_KEY")

# Backend de persistance (cf. backend/memory/persistence.py) : "local" (fichiers JSON, défaut) ou
# "firestore" (Cloud Run, où le disque est éphémère et non partagé entre instances). Défaut
# volontairement local — contrairement aux plafonds ci-dessous, une valeur absente n'est pas une
# config incomplète mais le cas de développement normal, et rien ne doit partir vers GCP par défaut.
STORAGE_BACKEND = os.getenv("VIGIE_STORAGE", "local")
FIRESTORE_PROJECT = os.getenv("FIRESTORE_PROJECT", "")
FIRESTORE_DATABASE = os.getenv("FIRESTORE_DATABASE", "(default)")

# --- Exposition de l'API (cf. backend/api/main.py) ---
# Jeton partagé exigé par POST /run. Sans valeur, l'endpoint est fermé et non ouvert : il déclenche
# un run complet, donc il brûle le budget quotidien (garde-fou §6) et une facture d'API — laissé
# ouvert, il est une dénégation de service gratuite pour qui connaît l'URL. Le repli est donc 503,
# pas « pas de contrôle ». Cloud Scheduler pose ce jeton en en-tête sur son appel HTTP ; le
# verrouillage IAM du service Cloud Run peut s'ajouter par-dessus, il ne le remplace pas — /events
# doit rester joignable par un navigateur, qui ne porte pas d'identité Google.
RUN_TOKEN = os.getenv("RUN_TOKEN", "")
# Origines autorisées à appeler l'API depuis un navigateur. Le « * » de la V1 laissait n'importe
# quelle page web lire le digest au nom du visiteur ; il n'a plus de raison d'être une fois l'origine
# du front connue. Défaut calé sur le serveur de développement Vite (cf. frontend/, npm run dev).
_DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", _DEFAULT_ORIGINS).split(",") if o.strip()]

# Fenêtre de fraîcheur appliquée à la collecte (backend/agents/collector.py) : au-delà de cette
# ancienneté, un item est écarté avant même le dédoublonnage. Certains flux institutionnels
# (Defense.gov, Bruxelles2, NK News) exposent un historique profond (des mois, voire années) sans
# pagination par date — sans ce filtre, un premier run (ou un run après une coupure) soumettrait
# tout l'historique au budget LLM quotidien d'un coup. Item sans date publiée/parsable : conservé
# par prudence, le garde-fou MAX_LLM_CALLS_PER_DAY reste le filet de sécurité final.
#
# Relevé de 48 h à 96 h le 2026-08-17 : mesuré en direct, les quatre sources américaines (43 % des
# exportations mondiales, cf. §4) tombaient hors de la fenêtre à 48 h un jour sur deux — cadence de
# publication plus lente que les flux d'agence de presse qui dominent le volume (TASS, Yonhap).
# Ce risque de coût que 48 h existait pour couvrir est désormais porté par
# MAX_ITEMS_PER_SOURCE_PER_RUN, qui borne directement le nombre d'items par flux au lieu de le
# borner indirectement par le temps — élargir la fenêtre ne coûte donc plus rien en budget.
COLLECTION_LOOKBACK_HOURS = 96

# Plafond du nombre d'items retenus par source à chaque run (backend/agents/collector.py), au-delà
# de MAX_LLM_CALLS_PER_DAY qui reste le filet de sécurité global. Ajouté le 2026-08-17 : sans lui,
# un flux d'agence de presse à cadence élevée (TASS, ~45 items/jour dans la fenêtre 48 h mesurée)
# consommait le budget quotidien à lui seul, au détriment des flux spécialisés à faible volume mais
# à fort signal — le coût était alloué par ce que chaque flux publie, pas par sa valeur pour la
# veille. Les items les plus récents de chaque source sont conservés en priorité.
MAX_ITEMS_PER_SOURCE_PER_RUN = 12

# --- Récupération du texte intégral (backend/agents/fetcher.py) ---
# Aucun appel LLM : récupérer un article est gratuit, seule sa soumission au modèle coûte. Posé le
# 2026-08-31 sur la ventilation du 2026-08-30, qui a chiffré la cible — 26 appels par run (18 % du
# budget quotidien) perdus en `citation_non_verifiee`, faute d'un extrait RSS assez long pour porter
# une citation vérifiable.
#
# Interrupteur plutôt que constante : le module fait des requêtes HTTP sortantes vers dix-sept
# sites, donc il doit pouvoir être éteint sans redéploiement si un run se met à traîner dessus.
FETCH_FULL_ARTICLE = os.getenv("FETCH_FULL_ARTICLE", "true").strip().lower() not in {"0", "false", "no"}
# Délai par article. Court volontairement : un article lent est une dégradation acceptable (repli
# sur le teaser), un run qui déborde sa cible de durée ne l'est pas.
FETCH_TIMEOUT_S = float(os.getenv("FETCH_TIMEOUT_S", "15"))
# Concurrence. Mesurée le 2026-08-31 : 13,6 s pour 49 articles à 8 fils, contre ~108 s en
# séquentiel à 2,2 s de latence unitaire moyenne. Le run du 2026-08-30 tenait à 880 s pour une
# cible de 900 s — la récupération doit rester une fraction de cette marge, pas la consommer.
FETCH_MAX_WORKERS = int(os.getenv("FETCH_MAX_WORKERS", "8"))
# Plafond de caractères ajoutés par article. Ne borne pas le budget d'appels (qui compte les appels,
# pas les tokens) mais la traîne : sur le relevé de 49 articles, la médiane est à 2 841 caractères
# et le maximum à 35 445 — un seul article valant douze fois la médiane.
FETCH_MAX_CHARS = int(os.getenv("FETCH_MAX_CHARS", "12000"))
# Renoncement documenté par source, plutôt que découvert en production. Defense.gov répond 403 avec
# comme sans en-tête navigateur (mesuré le 2026-08-31, la source redirige désormais vers war.gov) :
# ses items restent collectés et analysés sur leur teaser. Ne pas y ajouter une source au premier
# échec — un échec ponctuel est déjà traité en repli local, cette liste est pour un refus stable.
FETCH_SKIP_SOURCES = {"Defense.gov (DoD)"}

# Garde-fous obligatoires (cf. docs/cadrage.md §7) — pas de valeur par défaut :
# une config incomplète doit échouer au démarrage plutôt que tourner sans plafond.
MAX_STEPS_PER_RUN = int(os.environ["MAX_STEPS_PER_RUN"])
MAX_LLM_CALLS_PER_DAY = int(os.environ["MAX_LLM_CALLS_PER_DAY"])

# Agent vérificateur (première tranche de V2, cf. docs/cadrage.md §10 et backend/agents/verifier.py).
# Depuis le 2026-08-20, tout le périmètre MECE est éligible : la restriction à export_control et
# contrat_armement datait d'une arithmétique de budget (~110 items/jour × 1 à 3 appels contre
# MAX_LLM_CALLS_PER_DAY=200) que VERIFIER_GATE_MIN_SCORE lève, en ne dépensant un appel que là où
# l'historique a quelque chose à dire. hors_perimetre n'apparaît pas ici : analyze() l'écarte avant
# de construire analyzed_items, il n'atteint jamais ce nœud.
VERIFIER_CATEGORIES = {
    "export_control",
    "contrat_armement",
    "mouvement_militaire",
    "diplomatie_defense",
    "programme_industriel",
}
# Portillon d'escalade : score de chevauchement pondéré IDF (store._overlap_score) qu'un antécédent
# doit atteindre pour qu'un item soit escaladé. Ce n'est plus la catégorie qui borne le coût, c'est
# ce seuil — un item sans antécédent candidat produirait une non-réponse payée 2 à 3 appels.
# Mesuré le 2026-08-20 sur les 261 items de l'historique accumulé, candidats restreints aux dates
# antérieures comme le fait exclude_links : à 20, 23 % des items du périmètre sont escaladés
# (~16 appels/jour contre ~71 sans portillon), et les deux seules corroborations trouvées par le
# vérificateur sur la semaine (scores d'antécédent 32,0 et 35,4) sont au-dessus — aucun item
# corroboré n'aurait été perdu, quand le meilleur antécédent des 18 items non corroborés plafonne
# à 23,1. Même valeur que THREAD_GATE_MIN_SCORE, mais posée sur sa propre mesure : le threader juge
# l'appariement de dossier, le vérificateur une confirmation indépendante dans le temps.
VERIFIER_GATE_MIN_SCORE = 20.0
# Plafond par run, indépendant de MAX_LLM_CALLS_PER_DAY (qui reste le filet de sécurité global) :
# évite qu'un seul run consomme l'essentiel du budget quotidien sur la vérification seule.
MAX_VERIFIER_ESCALATIONS_PER_RUN = 15
# Plafond d'itérations d'outil par item escaladé, vérifié en code (pas via MAX_STEPS_PER_RUN, qui
# compte les nœuds du graphe LangGraph — une boucle interne à une fonction de nœud n'y est pas
# soumise).
MAX_VERIFIER_STEPS_PER_ITEM = 3

# Nœud thread (V3 tranche 1, cf. docs/cadrage.md §10 et backend/agents/threader.py). Contrairement
# au vérificateur, pas de filtre par catégorie : hors_perimetre n'atteint jamais analyzed_items
# (backend/agents/analyst.py l'écarte avant construction), donc tout item qui arrive jusqu'ici est
# déjà éligible à être rattaché à un dossier.
# Plafond par run, même rôle que MAX_VERIFIER_ESCALATIONS_PER_RUN, plus haut car l'éligibilité est
# plus large (5 catégories contre 2) : évite qu'un seul run consomme l'essentiel du budget quotidien
# sur le seul regroupement en fils.
MAX_THREAD_ESCALATIONS_PER_RUN = 20
# Plafond d'itérations d'outil par item escaladé, même rôle que MAX_VERIFIER_STEPS_PER_ITEM.
MAX_THREAD_STEPS_PER_ITEM = 3
# Seuil sur le score de chevauchement pondéré IDF (backend/memory/store._overlap_score) requis pour
# escalader un item au modèle — remplace le filtre gratuit "au moins un candidat" utilisé jusqu'ici,
# franchi par 100 % des items et donc sans effet réel (cf. docs/cadrage.md §10, mesure du 2026-08-18).
# Posé le 2026-08-20 sur l'échantillon de 65 paires annoté à la main (backend/eval/pairs.json,
# backend/eval/score_pairs.py) : ≥ 20 retient 62,0 % de vrais appariements estimés contre 20,2 % à
# ≥ 10, pour un volume d'escalade qui reste confortable sous MAX_THREAD_ESCALATIONS_PER_RUN. Ne
# s'applique que quand la pondération IDF est active (fenêtre >= 3 items) — sous ce seuil de corpus
# le score est un compte brut de tokens partagés, une échelle différente sur laquelle ce chiffre n'a
# pas de sens (cf. backend/memory/store._overlap_score).
THREAD_GATE_MIN_SCORE = 20.0

# Profondeur par défaut du digest servi par GET /events, en jours. Le digest est une fenêtre
# glissante sur l'historique analysé (backend/memory/store.py), pas le résultat du dernier run :
# sinon un second run dans la même journée, dont le dédoublonnage a écarté presque tous les items,
# remplacerait le digest de la veille par une poignée de nouveautés. Plafonné par la rétention de
# l'historique (RELATED_ITEMS_WINDOW_DAYS) — on ne peut pas servir plus profond qu'on ne conserve.
DIGEST_WINDOW_DAYS = 7
