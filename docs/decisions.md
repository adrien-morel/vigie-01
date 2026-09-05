# Choix d'ingénierie

Ce document porte le « pourquoi » des décisions techniques de VIGIE-01 : garde-fous, invariants
de durabilité, règles de restitution, conduite de la campagne d'accumulation. Il a été extrait du
[`README.md`](../README.md), qui n'en garde que les conclusions — un lecteur doit pouvoir
comprendre le projet en quelques minutes sans traverser le raisonnement, et le retrouver ici
quand il le cherche.

Le cadrage produit — problématique, périmètre MECE, KPIs, matrice de risques, plan de livraison —
est dans [`cadrage.md`](cadrage.md). Ce document ne le double pas : il documente les décisions
d'implémentation prises pour le servir.

## Ce que le digest engage à l'écran

Le digest expose les signaux qui engagent la confiance plutôt que la seule liste d'articles : score de confiance du vérificateur, antécédent trouvé ou non dans l'historique, provenance « média d'État », citation vérifiée verbatim. Un item hors du périmètre du vérificateur sort sans score plutôt qu'avec un zéro trompeur.

Le libellé dit « avec / sans antécédent » et non « recoupé ». Le champ mesure ce que l'historique contenait au moment où l'article est passé au vérificateur, et les articles d'un même lot de collecte sont mutuellement invisibles au recoupement (`exclude_links`) : un thread de trois sources peut donc légitimement n'afficher qu'un seul antécédent. Lu « recoupé » à côté de ce même thread, le libellé passait pour une contradiction.

## Ce qui survit au défilement

Un digest de sept jours fait deux cents items, soit une page d'une cinquantaine de milliers de pixels. Tout ce qui n'est pas solidaire du haut de l'écran est hors de portée dès le troisième article : le sélecteur de vue, la profondeur du digest et le tri sont donc logés dans la barre de titre elle-même, qui porte ainsi quelque chose au lieu d'aligner un logo et un bouton de part et d'autre d'un vide.

Les filtres actifs sont repris en pastilles retirables sous cette barre. La reprise duplique délibérément l'état du rail de filtres : le rail est le lieu où l'on *compose* un filtrage — il porte les compteurs de facette, qui disent ce que chaque facette donnerait si on la sélectionnait — les pastilles celui où on le *lit* et le défait, au moment où l'on en regarde les résultats. Sans elles, un digest filtré à trois items ne se distingue pas d'un digest vide.

Les tuiles d'indicateurs, en revanche, continuent de porter sur l'ensemble du digest quand un filtre est actif, et le disent. Leurs dénominateurs — items escaladables, items vérifiés — sont ce qui les rend honnêtes ; les recalculer sur un sous-ensemble ferait varier un taux de couverture au gré d'un clic de facette, ce qui n'a aucun sens pour une mesure de couverture.

Le rail de filtres défile pour lui-même, borné à la hauteur de la fenêtre. Collé sous la barre sans hauteur bornée, il gardait son haut épinglé et poussait son bas — les derniers pays de source, le bouton de réinitialisation — hors de l'écran sans moyen d'y accéder : la molette défilait la page, pas le rail, et le bas ne réapparaissait qu'en fin de document. La borne se calcule sur la hauteur mesurée de la barre, jamais sur une constante, qui se décale dès que celle-ci passe sur deux lignes.

## La fiche porte ses mentions sur sa ligne de titre

Le gabarit occupe toute la largeur de la fenêtre. Il a été plafonné et centré un temps, pour borner la longueur de ligne du résumé — sur un très grand écran, elle atteint deux cent cinquante caractères, que l'œil ne suit pas d'une fin de ligne au début de la suivante. Le plafond coûtait plus qu'il ne rapportait : la carte, le bandeau d'indicateurs et les chronologies de thread sont des objets qui gagnent à s'étaler, et deux bandes vides de part et d'autre du digest se lisent comme un défaut de gabarit. Ce qui reste borné, ce sont les notes méthodologiques, qu'on lit en entier ou pas du tout.

Les mentions de vérification tiennent sur la ligne de titre de la fiche plutôt que dans une colonne d'aparté. L'aparté a été essayé — il réservait deux cents pixels sur toute la hauteur de la fiche pour une ou deux pastilles et laissait un flanc vide en dessous. Sur la ligne de titre, elles prennent la place qu'elles demandent et rien de plus, tout en restant alignées d'une fiche à l'autre : l'état de vérification est présent sur *tous* les items, le plus souvent « non vérifié » puisque le portillon d'escalade rend ce cas majoritaire, et une information constante ne doit pas occuper la place la plus lisible ni se relire fiche par fiche.

## Les marques des médias sont collectées, pas empruntées

La marque du média ferme la ligne de titre : la source se reconnaît d'un coup d'œil le long de la liste, là où son nom en pied de fiche demande une lecture. Les fichiers sont récupérés une fois par `scripts/fetch_logos.py` et versionnés avec le front, jamais chargés depuis les sites d'origine à l'affichage. Les servir en direct enverrait dix-sept requêtes vers des tiers à chaque ouverture du digest — TASS, CGTN et Mehr News compris — leur donnerait l'adresse IP du lecteur, et rendrait l'interface dépendante de la disponibilité de sites qu'on a précisément retenus pour leur contenu, pas pour leur fiabilité technique.

Trois sources sur dix-huit ont refusé la collecte et s'affichent en monogramme. Le repli est le comportement normal, pas une panne à réparer : une source ajoutée sans relancer le script s'affiche en monogramme elle aussi, jamais en image cassée.

## La carte de couverture, et ce qu'elle refuse de fusionner

La carte est construite sur le champ `location` vérifié par item, pas sur le pays de la source, et affiche explicitement ce qu'elle ne peut pas placer — lieux non rattachables à un pays (espaces maritimes, détroits internationaux, régions transnationales). Une carte qui ne montrerait que ses succès surestimerait la couverture réelle.

Quatre niveaux de rattachement sont comptés séparément et détaillés au survol, une couverture présumée ne devant pas se lire comme une couverture citée : le pays est **cité** par la source ; il est **déduit** par le modèle d'une localité nommée (« Darwin » → Australie) ; il est déduit de l'**acteur** quand aucun théâtre n'est rattachable (« Houthis » → Yémen) ; ou, à défaut de tout, l'événement est **présumé domestique** au pays du média — sur jugement du contenu de l'article, jamais sur la seule origine du média, qui placerait en Russie une dépêche TASS sur le Yémen.

Le niveau **acteur** a été ajouté le 2026-08-20 sur un constat de lecture : cinq items de la semaine restaient hors carte alors que leur source nommait explicitement le protagoniste — « Houthis attack eight Saudi oil tankers » (Mer Rouge, Golfe d'Aden), « Hormuz will remain under Iranian control » (détroit international). Le théâtre y est soit absent, soit correctement jugé non rattachable à un pays : refuser de le placer est la bonne réponse pour un *lieu*, mais laissait perdre une information écrite noir sur blanc. Le protagoniste est donc extrait et vérifié verbatim comme le lieu, et le pays qu'on en déduit suit les mêmes bornes (vidé si l'extrait n'est pas vérifié, validé contre le référentiel cartographique, compté à part). Ce n'est délibérément pas une extension du niveau déduit : les deux déduisent un pays, mais l'un répond « où » et l'autre « qui ». Les fondre ferait lire l'origine d'une action comme son théâtre — exactement l'erreur que la séparation des provenances existe pour empêcher. D'où l'ordre de résolution : un théâtre rattachable gagne toujours sur l'acteur.

## Les threads d'événements

Un **thread** rassemble les articles qui couvrent le même dossier — mêmes parties, même opération, même contrat — et non le même thème ni le même pays. Sa chronologie est tracée à l'échelle réelle du temps : trois dépêches tombées en vingt minutes et un dossier étalé sur trois semaines ne doivent pas se ressembler, l'écart entre les parutions étant précisément le signal (qui sort l'information, combien de temps la reprise met à suivre). Un article que son flux ne date pas est placé sur son entrée en base et marqué comme tel, jamais présenté comme une heure de parution — `first_seen` est un horodatage de lot, partagé par tous les items d'un même run.

Aucun indice de fiabilité agrégé n'est calculé au niveau du thread : moyenner des scores dont une partie vaut `null` comblerait implicitement ce vide et ferait passer un thread non vérifié pour un thread moyennement fiable. Les compteurs de vérification sont donc rendus séparément, en distinguant « non escaladé faute de budget » de « hors du périmètre du vérificateur » — deux silences différents, dont aucun ne vaut un score. Le bloc de provenance croise le pays du média et le pays de l'événement sans jamais les confondre : un thread couvert par une agence d'État étrangère ne se lit pas comme une couverture domestique.

Un article qu'aucun thread ne rassemble dit lequel des quatre états le concerne, pour la même raison qu'un article sans score dit lequel des trois silences s'applique à lui. Jusqu'au 2026-08-21, un `thread_id` absent portait ces quatre situations sans qu'aucun signe ne les sépare : l'historique ne contenait aucun dossier assez proche pour valoir un rapprochement ; le modèle a examiné un candidat et conclu qu'il ne couvrait pas le même dossier ; le plafond du run ou le budget quotidien a coupé avant que la question soit posée ; ou l'article est antérieur à l'instrumentation. Les deux premières sont des mesures, la troisième une absence de mesure, et la confusion n'était pas théorique — le run du 2026-08-21 a laissé quatorze articles éligibles hors de tout thread faute de budget, rendus à l'écran exactement comme des articles dont on aurait vérifié qu'ils n'appartenaient à aucun dossier. L'affichage affirmait donc quelque chose que le système n'avait pas mesuré, ce qui est plus grave que la coupure elle-même.

Deux champs sont nécessaires là où le vérificateur se contente de l'existence d'un antécédent candidat, et la différence tient à la nature des deux nœuds : une escalade du vérificateur produit toujours un score, alors qu'une escalade du regroupement peut légitimement ne rien rattacher. Le résultat du portillon ne suffit donc pas à lui seul, il faut aussi savoir si le modèle a conclu. Le nombre de threads affichés se lisant par ailleurs comme le nombre de dossiers que contient le digest, la vue Threads porte en plus le compte des articles jamais soumis au rapprochement : c'est ce qui rend possible d'assumer un regroupement dégradé les jours chargés plutôt que de le taire.

## Le digest est une fenêtre glissante, pas la photographie du dernier run

Le dédoublonnage écartant, avant tout appel LLM, ce qui a déjà été vu dans les sept derniers jours, une seconde collecte dans la même journée ne produit qu'une poignée d'items neufs. Servir ce résultat brut reviendrait à effacer l'affichage à chaque collecte. `GET /events` lit donc l'historique des items analysés sur une profondeur paramétrable (`?days=`, bornée par la rétention de 7 jours), et le même historique alimente la recherche de recoupement du vérificateur — un seul stock, deux usages.

## Persistance : une interface, deux implémentations

(`backend/memory/persistence.py`). Trois états survivent aux runs : le compteur de budget LLM, les liens déjà vus et l'historique analysé. En développement ce sont des fichiers JSON ; en production ce sont des documents Firestore, parce que le système de fichiers de Cloud Run est éphémère et propre à chaque instance. La différence n'est pas qu'un confort de persistance : avec un compteur sur disque local, `MAX_LLM_CALLS_PER_DAY` redeviendrait contournable par un simple redémarrage. La réservation d'appel est donc exposée comme une opération du stockage (`reserve_llm_call`), atomique par transaction côté Firestore, plutôt que comme une lecture-modification-écriture faite par l'appelant — qui serait correcte en local et fausse en multi-instance. Le backend local reste le défaut : rien ne part vers GCP sans `VIGIE_STORAGE=firestore` explicite.

## Workflow déterministe et boucle agentique, séparés volontairement

Les nœuds `collect`/`deduplicate`/`analyze` forment un chemin de code fixe : un appel LLM par item, aucune décision dynamique du modèle — c'est le bon compromis pour une tâche de classification traçable et bon marché. Les nœuds `verify` et `thread` sont les deux points d'autonomie réelle : le modèle y dispose d'un outil de recherche dans l'historique des items analysés et décide lui-même s'il l'appelle, combien de fois, avant de conclure. Chaque escalade est bornée en code — nombre d'items par run, nombre d'itérations d'outil par item, et un portillon déterministe qui décide si l'item mérite un appel — pour que l'agentivité reste un coût maîtrisé et non proportionnel au volume collecté.

## Deux extensions d'autonomie qui ne coûteraient pas d'appel

Ce qui coûte n'est pas la décision, c'est l'appel : le plafond quotidien compte des appels au modèle, et un run complet en consomme désormais la totalité des 200 — 148 avant que le vérificateur soit étendu aux cinq catégories, le 2026-08-20. Une autonomie supplémentaire est donc gratuite tant qu'elle n'ajoute pas d'appel — soit qu'elle se glisse dans un appel déjà payé, soit qu'elle ne passe pas par le modèle du tout. Les deux pistes ci-dessous ont été identifiées le 2026-08-20 ; **aucune n'est implémentée**, et la seconde n'est pas encore calculable faute de compteur.

**Décider à l'intérieur d'un appel déjà payé.** L'analyste lit chaque article et ne fait que remplir un formulaire — catégorie, résumé, citation, lieu, acteur. Il n'a aucune latitude, alors que sa réponse structurée peut porter une décision de plus sans changer le nombre d'appels. Deux candidates. La première est une **priorité de vérification** : le portillon dit désormais quels items sont éligibles, sur une base mesurée, mais `MAX_VERIFIER_ESCALATIONS_PER_RUN` continue de couper dans l'ordre d'arrivée — c'est-à-dire dans l'ordre où les sources sont écrites dans `backend/config.py`, puis par fraîcheur à l'intérieur d'un flux. La règle d'éligibilité est explicite et exposée ; la coupure sous plafond ne l'est pas, et elle redevient contraignante les jours à fort volume. Laisser l'analyste marquer ce qui mérite d'être vérifié en premier remplacerait un ordre de fichier par un jugement. La seconde est une **abstention** — « le texte fourni est trop court pour trancher » — qui est le préalable naturel de `fetch_full_article` : récupérer un article ne coûte aucun appel, seule sa réanalyse en coûte un, donc désigner les articles qui la méritent transforme un chantier proportionnel au volume en un chantier plafonné. Dans les deux cas s'applique la condition déjà posée aux portillons : la décision doit être lisible à l'écran, sans quoi elle n'est qu'un arbitraire de plus, déplacé du fichier de configuration vers le modèle.

**Décider de l'allocation sans modèle du tout.** Le plafond par source est uniforme (12 items), avec un override manuel par flux (`Source.max_per_run`) déjà justifié par le rendement — CGTN, Jerusalem Post et Yonhap y sont plafonnés au ratio appels/item retenu qu'ils démontrent ([§4](cadrage.md)). Rendre ce réglage automatique ne demande aucun appel : c'est de l'arithmétique dans `collect()`, avant toute dépense. Il manque seulement de quoi le calculer. Le numérateur existe — chaque enregistrement de l'historique porte sa source. Le dénominateur, non : un item classé `hors_perimetre`, ou dont la citation ne se vérifie pas, est écarté par un `continue` dans `backend/agents/analyst.py` et ne laisse aucune trace, alors que son appel a été payé. Compter suppose trois précautions. Les motifs de rejet restent séparés — une source qui produit du hors-périmètre est bruyante, une source dont les citations échouent a un flux tronqué, et c'est exactement ce que la récupération du texte intégral réparerait : les confondre ferait rogner les flux que le chantier suivant doit sauver. Ces compteurs sont de l'état métier, ils passent donc par `persistence.py` et non par le journal d'exploitation de `scripts/daily_run.py`, qui est l'exception assumée à cette règle précisément parce qu'il ne porte pas d'état métier — et qui ne part pas en production. Enfin ils échappent à la purge de sept jours : une règle de quota dont la base de calcul est effacée chaque semaine n'est pas une règle.

**Avancement du 2026-08-22, partiel et à ne pas prendre pour l'acquis.** Le dénominateur décrit ci-dessus a reçu un premier élément : `analyst.submissions_by_source()` inscrit le sort réservé à chaque article soumis, par couple (source, motif), et l'outil de lancement le journalise. La première des trois précautions est donc respectée par construction — les motifs de rejet sont séparés, un flux hors sujet et un flux à extraits trop courts ne se confondent pas, ce qui est exactement la distinction dont dépend le chantier de récupération du texte intégral. **Les deux autres ne le sont pas** : ce compteur vit en mémoire, remis à zéro à chaque run, et ne passe donc ni par la couche de persistance ni au-delà de la purge. C'est délibéré — il a été construit pour attribuer la dépense d'analyse d'un run, question ouverte le jour même par la première répartition du budget par nœud, et non pour fonder une règle de quota. Une allocation adaptative par source reste donc hors d'atteinte : elle demande un compteur durable, et celui-ci ne l'est pas. Ce qui est acquis est la méthode de comptage et sa clé ; ce qui manque est le support.

**Ce qui interdit d'en faire une règle de rendement pure.** Une allocation qui suit le rendement concentre le corpus, et le corpus est un intrant de tout le reste. Trois raisons, toutes déjà mesurées. **Le plafond par source existe pour déconcentrer** : avant lui, 256 items dont 35,5 % de TASS ; après, 138 items et un plus gros contributeur à 8,7 %. Or TASS produit 69 des 199 items analysés de la semaine mesurée, le meilleur rendement du panel — suivre le rendement rendrait des places à l'agence d'État que le plafond avait été posé pour diluer, et défairait le correctif par le bouton même qu'il a créé. **Un corpus concentré fausse ensuite les mesures qu'on fait dessus** : le 2026-08-16, sur un corpus dominé par TASS, la pondération IDF ne corrigeait rien — `infrastructures` y était statistiquement rare tout en restant du vocabulaire générique, et la paire la mieux notée réunissait deux dépêches sans rapport. La même mesure rejouée après le rééquilibrage des sources s'est inversée : un seuil calibré sur un corpus déséquilibré règle le déséquilibre, pas le phénomène. **Et la corroboration a besoin de sources indépendantes** : `exclude_links` rendant les items d'un même lot mutuellement invisibles, un antécédent vient nécessairement d'un autre jour — et ne vaut quelque chose que s'il vient aussi d'une autre ligne éditoriale. Concentrer la collecte raréfierait mécaniquement ce que le critère d'acceptation V2 mesure, c'est-à-dire ferait payer au vérificateur le budget qu'on lui aurait économisé.

La règle de quota est donc subordonnée à la diversité des sources, jamais l'inverse : plancher strictement positif — une source ramenée à zéro cesse de produire les preuves qui pourraient la réhabiliter — et jugement humain déjà rendu à préserver, celui qui a plafonné CGTN, Jerusalem Post et Yonhap sans les retirer, faute d'autre couverture gratuite pour la Chine et de flux institutionnel exploitable pour Israël et la Corée du Sud. Comme les deux portillons, un tel seuil devra être calibré sur une assiette gelée plutôt que posé au jugé.

## Le regroupement en threads réutilise ce patron, avec deux divergences assumées

Contrairement au vérificateur, le nœud `thread` n'applique aucun filtre par catégorie : `hors_perimetre` n'atteint jamais `analyzed_items`, donc tout item qui arrive là est déjà éligible à être rattaché à un dossier. Et il n'exclut pas le lot en cours — deux sources qui couvrent le même événement le même jour sont au contraire le cas le plus net de « même dossier », là où la corroboration du vérificateur exige une confirmation indépendante dans le temps. Jusqu'au 2026-08-20, l'escalade était précédée d'un filtre gratuit (existence d'au moins un candidat au chevauchement de mots-clés) plutôt que d'un seuil de similarité : l'historique accumulé était encore trop mince pour en calibrer un, et un seuil non calibré aurait été un choix arbitraire déguisé en mesure.

**Mesure du 2026-08-18.** Sur 199 items réels, ce filtre gratuit était franchi par 100 % des items :
sa requête étant le titre et le résumé entiers, elle partage presque toujours un token avec au moins
un enregistrement de la fenêtre. Il ne constituait donc pas un second garde-fou. Le score de
chevauchement a en revanche été pondéré depuis la même date par la rareté des mots dans la fenêtre
(IDF) : le comptage brut était dominé par les mots vides, 64 % du score étant porté par des tokens
présents dans plus d'un cinquième du corpus, et un tiers des candidats servis au modèle a changé —
cela corrigeait le classement, pas le portillon.

**Seuil posé le 2026-08-20**, une fois la campagne d'accumulation close et un échantillon de
65 paires annoté à la main (§ ci-dessous, `backend/eval/pairs.json`). Repondérée par la population
réelle de chaque bande de score, la précision estimée passe de 20,2 % à ≥ 10 (le filtre gratuit en
pratique) à 62,0 % à ≥ 20 sur l'échelle effectivement appliquée. `THREAD_GATE_MIN_SCORE = 20` (`backend/config.py`) remplace donc le
filtre gratuit, appliqué par `search_thread_candidates` via son paramètre `min_score` — mais
seulement quand la pondération IDF est active (fenêtre ≥ 3 items) : en dessous, le score retombe sur
un compte brut de tokens partagés, une échelle sur laquelle ce seuil n'a pas de sens, et le filtre
garde son ancien comportement pour ne pas exclure le cas canonique du thread (deux sources du même
run, historique encore vide). Le score de chevauchement, lui, ne dit rien de la qualité du
regroupement pris isolément — la vérité terrain se limite à un seul thread ; c'est l'annotation des
paires intra-thread, pas ce score, qui mesure la précision du threading (100 % sur 13/13, § ci-dessous).

## Garde-fous, implémentés dès V1

- `backend/guardrails.py` — plafond d'appels LLM par jour, testé dans les deux sens (déclenchement réel vérifié, run normal non affecté). Couvre aussi les appels du vérificateur, sans compteur séparé. Atteint, il **tronque** le run au lieu de l'annuler : les items déjà analysés sont enregistrés et servis, ceux qui n'ont pas été soumis au modèle restent collectables au cycle suivant, et l'API répond un succès partiel explicite (`truncated`) plutôt qu'une erreur — sans quoi le garde-fou de coût détruirait le travail qu'il vient de faire payer
- `backend/guardrails.py` — imputation de chaque appel au nœud qui l'obtient (`calls_by_node()`), ajoutée le 2026-08-21. Ce n'est pas un garde-fou mais ce qui rend le précédent arbitrable : le plafond étant un compteur global unique, étendre un nœud ne consomme pas des appels « en plus », cela les retire au nœud suivant — constaté le jour même, où le vérificateur étendu a fait tomber le plafond sur le regroupement, dernier de la chaîne. La mesure est tenue en mémoire et hors de la couche de persistance qui porte le plafond, à dessein : elle n'a pas besoin de l'atomicité qu'exige une réservation, et l'y porter imposerait de modifier l'interface de persistance et ses deux implémentations, dont un backend Firestore jamais exécuté contre une base réelle. Un appel refusé n'est imputé à personne — la réservation précède l'appel au modèle, elle n'a donc rien coûté. **Première répartition réelle le 2026-08-22** : analyse 72, vérification 50, regroupement 73 sur un lot de 31 articles retenus, soit 195 des 200 appels du jour (cf. plus bas)
- `backend/graph.py` — plafond de steps par run (`MAX_STEPS_PER_RUN`), appliqué via le `recursion_limit` LangGraph — protection contre une boucle d'agent incontrôlée (cadrage §8), testée dans les deux sens
- `backend/agents/verifier.py` — double plafond sur l'escalade agentique : nombre d'items escaladés par run et nombre d'itérations d'outil par item. Vérifié en code et non via `MAX_STEPS_PER_RUN`, qui compte les nœuds du graphe et ne borne pas une boucle interne à un nœud
- `backend/agents/threader.py` — même double plafond (`MAX_THREAD_ESCALATIONS_PER_RUN`, `MAX_THREAD_STEPS_PER_ITEM`), sans compteur de budget distinct : le regroupement passe par le garde-fou quotidien commun. Le plafond par run y est plus haut que celui du vérificateur, l'éligibilité étant plus large (cinq catégories contre deux), et il est précédé d'un portillon sans coût LLM qui n'escalade que les items dont le meilleur candidat atteint `THREAD_GATE_MIN_SCORE` (posé le 2026-08-20, cf. plus bas)
- `backend/agents/collector.py` — fenêtre de fraîcheur (`COLLECTION_LOOKBACK_HOURS`) : plusieurs flux institutionnels exposent des mois d'historique sans pagination par date ; sans ce filtre, un premier run soumettrait tout l'arriéré au budget quotidien d'un seul coup
- `backend/agents/collector.py` — plafond par source (`MAX_ITEMS_PER_SOURCE_PER_RUN`, override possible par `Source.max_per_run`) : ajouté le 2026-08-17, mesuré en conditions réelles — sans lui, une agence de presse à cadence élevée (TASS, ~45 items/jour dans la fenêtre alors en vigueur) consommait le budget quotidien à elle seule, au détriment des flux spécialisés à faible volume mais fort signal. Complète la fenêtre de fraîcheur ci-dessus plutôt que de la remplacer : elle borne l'ancienneté, celui-ci borne le volume
- `backend/agents/analyst.py` — traçabilité systématique : un résumé sans citation vérifiable dans le texte source est rejeté automatiquement, pas seulement signalé
- `backend/agents/analyst.py` — ventilation du sort réservé à chaque article soumis, par source (`submissions_by_source()`), ajoutée le 2026-08-22. Même statut et même portée que l'imputation par nœud ci-dessus : une mesure d'exploitation, en mémoire, remise à zéro par run. Elle existe parce que ce nœud paie un appel par article soumis **avant** de savoir s'il sera retenu, et que les articles écartés ne laissent aucune trace ailleurs — l'historique analysé ne porte que les retenus, le journal de lancement ne compte que ce que chaque flux a offert avant le plafond par source. La clé est le couple (source, sort) et non la source seule : « combien de perdu » sans « pourquoi » ne distingue pas un flux hors sujet d'un flux dont les extraits sont trop courts pour porter une citation vérifiable, deux problèmes qui n'appellent pas le même remède — l'un se règle à la composition des sources, l'autre par la récupération du texte intégral

Les deux premiers garde-fous étaient initialement déclarés en config sans être vérifiés en code — écart trouvé par auto-audit et corrigé, plutôt que découvert en revue externe. C'est le type de vérification qu'un audit technique répété périodiquement pendant le développement doit attraper.

**Contrepartie mesurée du plafond par source.** Le plafond ne diffère pas la collecte, il l'écarte :
conservant les items les plus récents, il laisse la queue du flux vieillir hors de la fenêtre, où
elle n'est jamais reprise. Sur une fenêtre de 96 h, 279 items sont ainsi écartés sur 7 flux — plus
que l'historique analysé entier — concentrés sur Yonhap (-97), TASS (-88) et CGTN (-37). Le chiffre
est journalisé à chaque lancement à côté du KPI de couverture, parce qu'il n'est visible nulle part
ailleurs : rien dans l'historique analysé ne distingue « la source n'a rien publié » de « on a
écarté sa queue de flux ». La comparaison qu'il permet est le vrai apport — TASS écarte 88 items
tout en produisant 69 des 199 items analysés, là où Yonhap en écarte 97 pour 10 : le plafond rogne
un flux généraliste à faible rendement dans un cas, le flux le plus productif dans l'autre.

**Ce que coûte un run, mesuré le 2026-08-22.** Le premier lot complet d'une journée consomme la
quasi-totalité du plafond : 195 appels sur 200, répartis en analyse 72, vérification 50,
regroupement 73. Deux choses s'en déduisent qui ne se lisaient pas dans le total. D'abord, une
escalade agentique coûte environ 3,7 appels et non un — 3,85 par escalade de vérification, 3,65 par
escalade de regroupement —, la boucle payant un appel par itération d'outil plus un pour conclure.
Ensuite, et c'est la conséquence à retenir, les plafonds d'escalade sont sur-souscrits par rapport
au budget : ils autorisent ensemble 140 appels, ce qui ne laisse que 60 appels à l'analyse, laquelle
en paie un par article soumis sans discrétion possible et en a consommé 72 ce jour-là. Le run n'a
tenu que parce que la vérification n'a pas utilisé tous ses créneaux. Un lot plus lourd tronque, et
c'est le regroupement — dernier de la chaîne — qui absorbe le déficit, comme constaté la veille.

Le partage entre les trois nœuds n'est pas tranché pour autant, et pas par indécision : 41 des 72
appels d'analyse, soit 21 % du budget quotidien, portent sur des articles écartés après coup, et
tant que cette part n'est pas attribuée à des flux, arbitrer reviendrait à répartir une enveloppe
dont on n'a pas mesuré une des trois parts. C'est ce que la ventilation par source instrumentée le
même jour doit fournir. Une option est en revanche déjà écartée : resserrer le portillon du
regroupement pour une raison de budget périmerait sans le dire un seuil calibré sur une mesure de
précision d'appariement.

## Conduite de la campagne d'accumulation

Plusieurs décisions ouvertes — l'extension du vérificateur ([§10](cadrage.md) V2) et le calibrage du regroupement en threads — reposent sur une quantité qu'un historique court ne permet pas de mesurer : la proportion d'items ayant, dans l'historique, un voisin traitant du même dossier. Deux dépêches sur un même dossier à 48 h d'écart sont rares par construction ; la mesure n'a de sens que sur plusieurs semaines. Tant que le déclenchement automatique (Cloud Scheduler) n'est pas déployé, le pipeline est lancé une fois par jour à la main :

```bash
python -m scripts.daily_run              # le lancement quotidien
python -m scripts.daily_run --dry-run    # état de la campagne, sans consommer de budget
```

Le script journalise **chaque lancement**, y compris ceux qui ne produisent aucun item neuf et ceux qui échouent. Cette distinction ne se déduit pas de l'historique analysé : un jour sans nouveauté et un jour non lancé y laissent la même trace, alors que le premier est une mesure et le second un trou. `COLLECTION_LOOKBACK_HOURS` (96 h) borne ce qu'une collecte rattrape — un jour sauté est récupéré par le lancement suivant, des jours consécutifs sautés au-delà de cette fenêtre perdent définitivement les items publiés dans l'intervalle non couvert. L'écart depuis le dernier lancement est donc mesuré et signalé à chaque run. Chaque lancement mesure aussi, sans coût LLM, combien de sources ont produit au moins un item récent (`sources_active`/`sources_targeted`/`sources_silent` dans le journal) — une source qui se parse sans erreur mais ne publie plus rien de récent doit apparaître comme silencieuse, pas comme active (cf. KPI de couverture, `cadrage.md` §7).

La mesure qu'alimente cette campagne se rejoue ensuite sans aucun appel LLM :

```bash
python -m backend.eval.candidates
```

### Clôture, et pourquoi les mesures sont désormais gelées

La campagne s'est arrêtée le 2026-08-20 à cinq lancements et sept jours continus (261 items), sous les quinze jours visés. Ce n'est pas un abandon en cours de route : la rétention de l'historique a été ramenée le même jour de 30 à 7 jours pour le coût de stockage, ce qui rend l'assiette initialement visée inatteignable par construction — le jour le plus ancien est purgé à chaque run, l'historique ne peut plus jamais dépasser sept jours. Attendre plus longtemps n'aurait produit aucun corpus plus large.

La mesure a donc été prise sur sept jours, et à cette taille elle tranche ce qu'elle devait trancher : le score pondéré IDF discrimine (3 % des items au seuil 40, 12 % à 30, 34 % à 20), là où le portillon en production laissait passer 100 % des items. Ce que sept jours ne donnaient pas, à ce stade, c'est le *seuil* lui-même — une échelle qui sépare ne dit pas où couper.

D'où la conséquence de méthode, qui vaut pour toute mesure ultérieure : **un corpus doit être gelé hors du stock au moment où il est mesuré**. Une mesure qui relit l'historique à la demande n'est pas rejouable, puisque recalculée une semaine plus tard elle ne retrouve plus aucun des items d'origine — et une annotation manuelle, qui coûte du temps humain, serait perdue avec eux. `backend/eval/build_pairs.py` applique cette règle à l'appariement de dossiers, comme `build_sample.py` le faisait déjà pour la classification : il écrit un échantillon autonome, portant tout le contexte nécessaire à l'annotation et au calcul, et archive toute version déjà annotée avant de la remplacer.

```bash
python -m backend.eval.build_pairs      # gèle l'échantillon (aucun appel LLM)
python -m backend.eval.annotate_pairs   # jugement humain : même dossier ?
python -m backend.eval.score_pairs      # précision du threading, effet d'un seuil
```

L'échantillon mêle deux populations qui répondent à la même question sans se confondre : les paires que le modèle a effectivement regroupées en threads — toutes, puisque ce sont exactement celles que juge le critère d'acceptation de la V3 tranche 1 — et des paires candidates tirées par bande de score, qui seules permettent de lire où le taux de vrais appariements s'effondre. Les taux sont repondérés par la population réelle de chaque bande au moment du calcul : l'échantillon étant stratifié, un comptage brut sur-pondérerait les bandes hautes, volontairement sur-tirées parce que peu peuplées.

### Résultat, et le seuil qui en découle

Les 65 paires ont été annotées le 2026-08-20. Les 13 paires intra-thread sont toutes jugées même
dossier — précision 100 %, critère d'acceptation de la V3 tranche 1 atteint. Rappel non mesurable
par construction : un dossier que le nœud n'a pas su rapprocher ne produit aucune paire à annoter,
donc ce chiffre dit « ce qui est groupé l'est bien », pas « le threading rapproche tout ce qu'il
devrait ».

Les 52 paires candidates, elles, calibrent le portillon d'escalade : le taux de vrais appariements
par bande passe de 0 % (score 0-10) à 12,5 % (10-15), 37,5 % (15-20), 50 % (20-25), 75 % (25-30),
87,5 % (30-40). Repondérée par la population réelle de chaque bande, la précision estimée d'un
portillon à ≥ 20 est de 62,0 % sur ~62 paires candidates/semaine, contre 20,2 % à ≥ 10 (le filtre
gratuit qu'il remplace). Ce chiffre a été publié à 64,7 % avant d'être corrigé le 2026-08-20 : la
calibration sort de `backend/eval/candidates.py`, qui pondère en `log(n / (1 + df))`, quand le seuil
est appliqué par `store._overlap_score`, qui pondère en `log(n / df)`. Rescorées sur l'échelle
appliquée, 4 des 52 paires annotées changent de bande et la précision estimée tombe à 62,0 % — le
seuil retenu ne bouge pas, le chiffre qui le justifie si. Une mesure qui ne porte pas exactement sur
le code qu'elle règle finit toujours par dériver de quelque chose. `THREAD_GATE_MIN_SCORE = 20` (`backend/config.py`) est la conséquence
directe de cette mesure, appliqué par `search_thread_candidates` (`backend/memory/store.py`) via son
paramètre `min_score` — jamais câblé au jugé, exactement ce que cet échantillon devait éviter.

## Le vérificateur passe de la catégorie au portillon

Le vérificateur n'escaladait que `export_control` et `contrat_armement`. Cette restriction n'a jamais
été un choix de sens produit : c'était une borne de coût, posée quand l'arithmétique disait qu'ouvrir
les cinq catégories coûterait 220 à 440 appels par jour contre un plafond de 200 partagé avec
l'analyse. Elle bornait la dépense en refusant de regarder quatre catégories sur cinq, pas en
distinguant les items vérifiables des autres.

**Ce que la mesure du 2026-08-20 a montré, et qui n'était pas l'attendu.** La question posée était
« le seuil calibré pour le threader se transpose-t-il au vérificateur ? », en cherchant s'il y
ferait économiser des appels. Réponse : non, et pour une raison qui retourne le problème. Sous la
règle par catégorie, le vérificateur ne traitait que ~3 items par jour, soit ~7 appels sur 200 — un
portillon y aurait économisé ~6 appels quotidiens en effaçant 80 % de la couverture de score, c'est-
à-dire précisément ce que le critère d'acceptation V2 mesure. Le seuil ne vaut rien comme
économiseur ; il vaut comme *condition de l'extension*. Les cinq catégories sans portillon coûtent
~71 appels/jour ; avec un portillon à ≥ 20, ~16. C'est ce qui rend l'extension finançable, et c'est
la branche « pré-filtrer de façon déterministe » restée ouverte depuis le 2026-08-16.

**Ce qui autorisait à croire au portillon, cette fois.** La même mesure, tentée le 2026-08-16 sur
102 items, avait conclu par la négative : le meilleur appariement correct n'arrivait qu'en dixième
position, derrière six faux positifs, sur un corpus dominé par une source unique. Rejouée sur les
261 items accumulés après la révision des sources, elle s'inverse — les deux seuls items que le
vérificateur a jugés corroborés sur la semaine portent les deux scores d'antécédent les plus élevés
des vingt items scorés (32,0 et 35,4), quand les dix-huit non corroborés plafonnent à 23,1. Un
portillon à 20 n'aurait donc perdu aucune corroboration. Le contrôle qualitatif dit la même chose
que les taux, ce qui n'était pas le cas en août 16 : les paires au-dessus de 30 sont le même contrat
Raytheon vu par deux sources et la même sélection d'obusier K9, celles autour de 20 sont du bruit
thématique correctement rejeté par le modèle.

**Le critère d'acceptation V2 est réécrit, pas contourné.** « Score de confiance sur 100 % des
événements » supposait un budget que le produit n'a pas, et aurait fait payer un appel pour produire
une non-réponse là où l'historique n'a rien à recouper. Il devient : score sur 100 % des items
retenus par une règle d'éligibilité explicite et mesurée. Une règle d'éligibilité n'est acceptable
qu'exposée — l'interface dit donc lequel des silences s'applique à un item sans score : aucun
antécédent candidat (une mesure : le système a regardé et n'a rien trouvé à recouper), plafond du
run ou budget épuisé (une absence de mesure), ou item analysé avant l'extension. Les confondre
laisserait lire un manque là où il y a un résultat.

**Ce qui n'est pas acquis.** L'extension est câblée et éprouvée contre l'historique réel sans appel
LLM — le portillon rejoué sur le lot du 2026-08-20 retient 11 items sur 27 — mais elle n'a pas
tourné sur un run complet, le budget quotidien étant épuisé le jour du câblage. Elle ne doit pas
être présentée comme validée avant. Deux effets restent à observer en réel : le plafond par run
(`MAX_VERIFIER_ESCALATIONS_PER_RUN = 15`) redevient contraignant les jours à fort volume, alors
qu'il ne l'était plus sous la règle par catégorie ; et le score de confiance lui-même est, sur les
vingt items mesurés, presque constant — 0,65 pour douze d'entre eux, 0,82 et 0,92 pour les deux
corroborés. Il se comporte comme une fonction de `corroborated` plutôt que comme un jugement propre,
ce qui est un argument de plus pour le renommer `model_confidence`. **Renommé le 2026-08-30**, côté
état, API, front et tests. Le champ du schéma que remplit le modèle (`_VerifierResult`) garde en
revanche l'ancien nom : `with_structured_output` envoie ce schéma au modèle, propriétés comprises,
donc le renommer serait une modification de prompt — à retester, alors que le renommage du champ
stocké ne change rien à ce que le modèle voit. Unifier les deux noms reste à faire, comme un
changement de prompt à part entière.

## Rendre le pipeline observable avant de le rendre autonome

Le diagnostic de mise en production, posé le 2026-08-22, n'a pas trouvé ce qu'il cherchait.
`infra/` était vide, ce qui se voyait ; mais le vrai blocage était ailleurs : **le pipeline ne
journalisait rien**. Aucun `logging`, aucun `print` dans `backend/`. Tout ce qui avait été
instrumenté les deux jours précédents — la répartition des 200 appels quotidiens entre les nœuds, la
ventilation de la dépense d'analyse par source et par sort — ne sortait du processus que par
`scripts/daily_run.py`, un outil d'opérateur qui ne part pas en production. Sous un ordonnanceur, ces
mesures auraient disparu au moment précis où elles deviennent la seule fenêtre sur le système.

D'où l'ordre retenu : **la journalisation d'abord, l'infrastructure ensuite**. Déployer un pipeline
muet, c'est accepter de ne pas savoir pourquoi un run nocturne a rendu trois articles.

**Le format est une décision, pas une préférence.** Une ligne de sortie est un objet JSON, la
sévérité est portée par le champ `severity` — le seul que Cloud Logging promeut, `level` étant ignoré
— et les mesures sont des champs structurés, jamais interpolées dans le message. La différence est
opérationnelle : une troncature se filtre par `jsonPayload.truncated=true`, pas par un grep sur du
texte libre, et une alerte peut donc distinguer un échec d'un succès partiel. C'est la même
distinction que l'API tient déjà dans son code de retour (200 avec `truncated`, jamais 429) ; elle
n'aurait servi à rien si le journal l'avait effacée.

Ce que le journal porte a été choisi sur les défauts déjà rencontrés, pas sur ce qui était facile à
compter : les sources muettes en `WARNING` (une source qui se parse sans erreur mais ne publie plus
est restée invisible près d'un an), l'écart entre articles éligibles et articles réellement escaladés
à chaque nœud d'escalade (c'est cet écart, et non le total, qui dit ce qu'un plafond a coûté), le
sort de chaque article soumis par source, et le nœud qui demandait l'appel au moment où le plafond
quotidien l'a refusé.

**Un détail qui n'en est pas un.** `configure_logging()` bascule stdout en UTF-8. Sous Windows, la
sortie redirigée retombe sur la page de code ANSI, et une dépêche en cyrillique dans un champ du
journal ferait échouer l'écriture — c'est-à-dire que la journalisation ferait tomber le run qu'elle
documente. Même piège que l'encodage explicite exigé partout ailleurs sur les fichiers, rencontré
deux fois avant d'être traité.

## Un Job pour le run, un service pour le digest

Le pipeline dure ~620 s, et cette durée monte avec la couverture du vérificateur : 401 s le
2026-08-20, 513 s le 21, 620 s le 22. Le déclencher par requête HTTP imposerait de tenir une
connexion ouverte pendant tout ce temps, sous le délai du service *et* sous celui de l'ordonnanceur,
qui plafonne à 30 minutes. Relever des délais fonctionnerait aujourd'hui et se paierait le jour où
un lot lourd les dépasse.

Le run quotidien est donc un **Job**, sans délai de requête, et le service ne porte que ce qu'il sert
vite : le digest déjà produit. Les deux partagent une seule image, avec une commande différente —
deux images à tenir synchrones seraient une divergence en attente.

**Le code de sortie du Job est une décision de budget.** Un Job qui sort en erreur est relancé. Or un
run tronqué a atteint le plafond quotidien d'appels : le relancer ne produirait rien — le budget est
épuisé, les articles soumis sont déjà marqués vus — mais enterrerait le travail payé sous une pile de
tentatives en échec. Une troncature sort donc en 0, et se lit dans le journal. Le nombre de reprises
est fixé à zéro pour le cas restant, l'échec réel : on veut le voir et le diagnostiquer, pas le
réessayer à l'aveugle sur le budget du lendemain.

## Fermer l'endpoint qui dépense

`POST /run` était public et non authentifié. Ce n'est pas une question d'exposition de données — il
n'en rend aucune — mais de dépense : il déclenche un run complet, donc la totalité du budget
quotidien et une facture d'API. Laissé ouvert derrière une URL publique, c'est un déni de service
gratuit pour qui la connaît.

Il exige désormais un jeton partagé, et **répond 503 tant qu'aucun jeton n'est configuré** plutôt que
de rester ouvert « en attendant ». C'est la même logique que les plafonds obligatoires, dont l'absence
fait échouer l'import : un garde-fou non configuré doit fermer, pas s'effacer. La différence est que
l'échec est porté par l'endpoint et non par le démarrage, pour que le digest continue d'être servi.

Le verrouillage par identité de la plateforme ne remplace pas ce jeton : `GET /events` est lu par un
navigateur, qui ne présente pas d'identité. Le service reste donc joignable, et c'est l'endpoint
coûteux qui est fermé — pas l'inverse. Dans le même mouvement, CORS abandonne le `*` de la V1, qui
laissait n'importe quelle page lire le digest depuis le navigateur d'un visiteur.

## Épingler, et ce que l'épinglage ne couvre pas

Aucune version n'était fixée. Une version majeure publiée entre deux constructions d'image aurait
cassé le déploiement sans qu'une ligne du dépôt ait bougé, et le diagnostic se serait fait en
production. Les trois fichiers de dépendances sont donc épinglés à l'exact, relevés depuis
l'environnement où la suite de tests passe.

Une exception était signalée dans le fichier plutôt que masquée : le client de la base managée n'est
pas installé localement, son épinglage venait de l'index public et non d'un environnement où il
avait tourné. C'était cohérent avec le statut du composant qu'il installe — écrit, documenté, jamais
exécuté contre une base réelle. **Cette ligne a été vérifiée le 2026-09-05**, à la première
construction en cloud puis au premier traitement réel : la version épinglée s'installe et
fonctionne. L'exception disparaît donc, et avec elle le seul endroit du projet où une dépendance
était épinglée sans preuve.

## Un flux qui hoquette ne doit pas coûter la journée

Le 2026-08-30, une lecture des flux a échoué sur un `http.client.RemoteDisconnected` levé au milieu
d'une redirection. Elle n'a rien retourné de dégradé : elle a fait tomber `collect()` en entier,
avant qu'un seul article soit analysé. La cause est une hypothèse fausse sur la bibliothèque de
lecture RSS — `feedparser.parse` intercepte `urllib.error.URLError` et rien d'autre, si bien que
toute erreur d'une autre famille traverse la fonction. L'appel suivant a réussi : c'est une panne
transitoire, donc exactement celle qui se produira un jour dans un Job non surveillé, à l'heure où
personne ne relance. Le correctif rend l'échec local à la source : `FeedUnavailable`, la source
nommée, le run continue avec les dix-sept autres.

Le même correctif défait une confusion plus ancienne, et plus coûteuse à diagnostiquer. Quand
`feedparser` *attrape* l'erreur, il rend un résultat vide marqué `bozo` — que le code lisait comme
« ce flux n'a rien publié de récent ». Une panne réseau se présentait donc comme un flux mort, ce
qui est le diagnostic exactement inverse : le premier se réessaie, le second se remplace. C'est la
confusion qu'avait produite OFAC en 2026-08-17, dans l'autre sens. Une source injoignable est
désormais un troisième état, distinct du muet : `source_freshness()` rend `None` et jamais `0`, le
KPI de couverture compte trois catégories, et le journal sort les injoignables en ERROR quand les
muettes restent en WARNING — deux filtres différents dans une alerte. Le critère n'est pas `bozo`
seul, qui serait faux : beaucoup de flux valides sont mal formés et rendent quand même leurs
entrées. C'est `bozo` **et** zéro entrée.

## Récupérer l'article entier : ce que la mesure a corrigé avant qu'on code

La ventilation du 2026-08-30 avait chiffré une cible — 26 appels par run perdus faute de citation
vérifiable, 18 % du budget quotidien — et nommé le correctif : aller chercher le texte intégral,
puisque l'extrait RSS serait trop court pour porter une citation. La cible était juste, le correctif
non. Passer 10 items en bras appariés avant d'écrire le module a montré que **4 des 6 échecs de
citation sont de pure typographie** : le modèle rend une apostrophe droite là où la source écrit une
apostrophe courbe, des guillemets droits là où elle met des chevrons, et la comparaison verbatim
repliait déjà la casse et les espaces mais pas ces signes-là. Les 2 autres échecs sont de vraies
paraphrases, hors de portée de tout correctif d'extraction — leur plus long fragment commun avec la
source fait 7 et 12 caractères, et le garde-fou de traçabilité a raison de les refuser.

Replier la typographie ne relâche pas ce garde-fou, il le rend applicable : une apostrophe courbe et
une apostrophe droite sont le même signe, pas le même octet, et ce que le contrôle doit établir —
que les mots de la citation sont ceux de la source — reste intact. Le gain est celui d'une
comparaison corrigée, pas d'une exigence abaissée : sur le lot de validation, la rétention passe de
2/10 à 5/10 sans une requête HTTP ni un appel de plus.

C'est le même schéma que l'incident de cadrage du 2026-08-22, où une mesure de précision avait lu un
désaccord de spécification comme une lacune de spécification. Une mesure qui nomme un correctif sans
l'avoir isolé peut désigner le mauvais objet, et **le vérifier coûte toujours moins cher que de
construire le mauvais**.

### Ce que le module garde comme justification, et pourquoi il reste derrière un interrupteur

La récupération du texte intégral est livrée quand même, mais pour la classification et non pour la
citation : les deux bascules favorables du lot de validation sont deux articles sortis de
`hors_perimetre` une fois lus en entier — la classe de défaut déjà relevée sur deux items ESUT, où
le teaser ne contient pas ce qu'il faut pour classer. Le bilan complet est de +2 gains pour
−1 régression sur 10 items : orienté dans le sens attendu, **non concluant à cet effectif**. D'où
`FETCH_FULL_ARTICLE`, un interrupteur, plutôt qu'un comportement câblé — et d'où le refus d'annoncer
un gain de budget tant qu'un lot complet ne l'a pas produit.

La régression mérite d'être consignée plutôt que lissée, parce qu'elle borne un invariant qu'on
serait tenté d'énoncer trop largement. Concaténer l'article au teaser, au lieu de le remplacer,
garantit qu'une **citation donnée** qui se vérifie continue de se vérifier — le corpus vérifiable ne
fait que croître. Cela ne garantit pas le **sort de l'item** : devant un texte plus long, le modèle
choisit une autre citation, et celle-là peut échouer. L'invariant porte sur une chaîne de
caractères, pas sur une décision.

### Trois relevés de faisabilité, dont deux corrigent une note antérieure

Sonder avant de coder a corrigé deux suppositions et évité un troisième arbitraire. *Les sources
bloquées ne sont pas celles qu'on croyait* : trois flux refusent un GET nu et répondent 200 avec un
en-tête de navigateur, quand la note en annonçait deux — dont une, Federal Register, qui répond en
réalité 200 sans rien de particulier. Son problème est ailleurs : l'extraction y ramène les mentions
légales du site. Une seule source résiste vraiment, et fait l'objet d'un renoncement nommé plutôt
que d'une découverte en production. *Le contrôle d'ancrage doit partir du teaser, pas du titre* :
un titre est un résumé, qu'un article bien écrit ne reprend pas mot pour mot, et ancrer dessus
rejetait à tort 7 extractions correctes sur 9 — un garde-fou qui écarte le bon travail coûte plus
cher que pas de garde-fou du tout. *Le score d'ancrage ne décide de rien* : les deux seules
extractions défaillantes sont déjà prises par la règle « teaser trop court pour ancrer », si bien
qu'il ne reste aucune séparation positif/négatif sur laquelle calibrer un seuil. Il est donc mesuré
et journalisé, sans plafonner quoi que ce soit — même ordre que pour le portillon du threader, resté
un filtre gratuit jusqu'à ce qu'un échantillon annoté permette de le poser.

## Le traçage n'a pas à pouvoir arrêter ce qu'il observe

Pendant le run du 2026-08-30, le service de traçage est devenu injoignable et le pipeline s'est
arrêté plusieurs minutes sur ses délais d'expiration. Le client attend 60 s en lecture par envoi, et
cette valeur n'est pas réglable par variable d'environnement dans la version épinglée : la borner
supposerait de construire le client nous-mêmes, donc d'entretenir du code de traçage à l'intérieur
du chemin d'exécution du run — remède plus lourd que le mal.

Le traçage est donc éteint **sur le Job seulement**, et rallumable par variable. Le Job est le
chemin non surveillé et celui qui a le moins de marge : 880 s mesurées contre une cible de 900 s,
avec un relèvement du timeout Cloud Run prévu par-dessus. Un observatoire qui peut faire tomber
l'observé n'y a pas sa place par défaut. En développement, où l'on est devant l'écran et où une
trace vaut une session de débogage, le défaut reste inchangé — c'est là que le traçage gagne sa
place.

Détail qui n'en est pas un : deux variables activent le traçage, l'ancienne et celle du renommage,
et elles sont lues indépendamment. En neutraliser une seule laisse le traçage actif par l'autre.

## Ce que la validation locale prouve, et ce qu'elle ne prouve pas

L'image a été construite et le conteneur exercé : le service répond, l'endpoint de run refuse sans
jeton puis avec un mauvais jeton, CORS accepte l'origine déclarée et refuse les autres. Le Job a
tourné de bout en bout contre des flux RSS réels, plafond d'appels forcé à zéro — 142 articles
collectés, refus de réservation tracé jusqu'au nœud demandeur, troncature propagée, sortie en 0.
La chaîne complète a donc été vérifiée sans dépenser un appel.

Ce que cela ne prouvait pas : **la base de production n'avait toujours jamais tourné**. C'était la
seule inconnue qu'aucune quantité de travail local ne levait, et elle portait sur le garde-fou le
moins négociable du projet — la réservation d'appel en transaction, dont l'atomicité ne veut rien
dire hors conditions concurrentes réelles. Si elle est fausse, elle n'est fausse qu'en production.

**Levée le 2026-09-05, mais pas par la méthode prescrite** — et c'est ce détour qui mérite d'être
retenu. Le mode opératoire demandait « deux exécutions simultanées », en comparant le total
consommé au plafond. Exécuté tel quel, il a rendu un résultat conforme et **sans aucune valeur** :
les deux traitements n'ont produit qu'**une seule** réservation à eux deux, et ne se sont même pas
chevauchés dans le temps. Le dédoublonnage avait marqué tous les articles au traitement précédent,
il ne restait donc rien à analyser, donc rien à réserver. Un compteur resté sous le plafond serait
passé pour une preuve alors qu'aucune course n'avait eu lieu.

Le pipeline complet est un instrument trop indirect pour cette question : ce qu'il faut viser, c'est
la fonction elle-même, et il faut que **les places restantes soient moins nombreuses que les
tentatives**, sans quoi tout le monde réussit et rien n'est démontré. D'où une sonde dédiée, versée
au dépôt plutôt qu'improvisée — 30 réservations simultanées réparties sur 3 conteneurs distincts
pour 4 places : exactement 4 acceptées, 26 refusées, compteur s'arrêtant sur le plafond. Les
conteneurs étaient bien entrelacés, l'un lisant deux places restantes quand les deux autres en
lisaient quatre. La transaction tient.

La leçon dépasse ce garde-fou : **un mode opératoire n'est pas une preuve, et un test qui passe ne
dit pas qu'il a mesuré quelque chose.** C'est le troisième cas recensé dans ce projet d'une mesure
qui aurait nommé sa conclusion sans avoir isolé son objet.

## Adopter l'infrastructure plutôt que la recréer

Le module Terraform a été écrit **après** que l'infrastructure existe, et c'est ce qui a déterminé
sa forme. Le réflexe — décrire l'état voulu et laisser l'outil converger — aurait proposé de
détruire ce qui tournait, à commencer par la base : la région d'une base Firestore n'est pas
révisable après création, donc tout écart sur ce champ se traduit par un remplacement, donc par la
perte de l'historique.

Le module adopte donc, par des blocs `import` versionnés plutôt que par des commandes impératives
dont le dépôt ne garderait aucune trace. Le critère de réussite n'était pas « l'infrastructure
existe » mais **« le plan n'annonce aucun changement »**.

Y arriver a demandé de corriger la configuration, jamais les ressources. Quatre attributs avaient
été posés par les commandes de création sans être déclarés — protection contre la suppression, mise
à l'échelle au niveau du service, deux réglages de processeur. Les laisser absents ne les aurait pas
laissés tranquilles : le premier `apply` les aurait annulés. **Déclarer ce qui existe est la
différence entre adopter un service et le modifier en croyant l'adopter.**

Trois choses restent délibérément hors du module, pour une raison commune : elles portent ou
produisent des secrets. Les valeurs dans Secret Manager — seules les enveloppes sont gérées, une
valeur déclarée par Terraform se retrouvant en clair dans son état. La connexion au dépôt de code,
qui dépose un jeton GitHub. Et le compartiment qui héberge l'état lui-même, qu'on ne peut pas faire
gérer par ce dont il contient l'état.

Une quatrième exclusion n'a rien à voir avec les secrets : **l'image**. Terraform tient la
configuration, Cloud Build tient l'image. Sans cette séparation explicite, les deux se disputent à
chaque publication de code — l'un veut l'image du dernier `apply`, l'autre celle du dernier commit.

## Ce qu'exécuter un mode opératoire révèle, et qu'aucune relecture ne trouve

Le runbook de mise en production avait été écrit avec soin, relu, et jamais exécuté. Le jour où il
l'a été, il a produit **sept défauts**, dont aucun n'était visible à la lecture et dont deux
auraient coûté cher.

Le premier est le pire. Les variables d'environnement étaient passées sur quatre lignes
successives, ce qui se lit très bien. Mais l'option ne s'accumule pas : répétée, seule la dernière
est retenue. Le service serait parti avec une seule variable — et **sans aucun plafond de budget**.
L'erreur ne se serait pas vue au déploiement, seulement au premier traitement, en dépense.

Le deuxième est une leçon sur l'environnement d'exécution plus que sur le produit : sous Git Bash,
tout argument commençant par une barre oblique est réécrit en chemin Windows. La sonde de démarrage
`/health` est devenue un chemin de fichier, elle interrogeait la racine, et la révision ne démarrait
jamais — pendant que les journaux affichaient un démarrage applicatif parfaitement normal. Le
symptôme désignait l'application, la cause était dans le terminal.

Les cinq autres sont du même ordre : un droit non documenté sur Secret Manager sans lequel la
connexion au dépôt échoue ; un écran d'autorisation qui rend un état « terminé » alors que la portée
accordée ne couvre pas le dépôt visé ; une console qui s'ouvre sur une région différente de celle où
tout a été créé, et paraît donc vide.

Il n'y a pas de conclusion élégante à en tirer, seulement une règle de conduite : **un mode
opératoire non exécuté est une hypothèse, pas une procédure.** Les sept défauts sont consignés à
l'endroit exact où ils se produisent, et non dans une liste séparée — c'est la seule forme qui les
remettra sous les yeux de qui rejouera la séquence.
