# Déploiement — runbook

Séquence de mise en production de VIGIE-01. Chaque commande est exécutable telle quelle une fois
les variables du bloc ci-dessous renseignées. Ce qui n'est pas automatisable depuis le dépôt (projet
GCP, facturation, IAM) est signalé **hors dépôt**.

Deux choix d'architecture sont figés ici, et le reste du fichier en découle :

- **Le run quotidien est un Cloud Run Job**, pas une requête HTTP. Le pipeline dure ~620 s et cette
  durée monte (401 s le 2026-08-20, 513 s le 21, 620 s le 22) ; un Job n'a pas de timeout de
  requête, là où Cloud Scheduler plafonne à 30 min. Le service Cloud Run reste dédié à ce qu'il
  sert vite : le digest déjà produit.
- **Le front est sur Firebase Hosting**, donc sur une origine différente de l'API. `ALLOWED_ORIGINS`
  côté service doit porter cette origine, sinon le navigateur refuse la réponse.

Le Job et le service partagent **une seule image** : même `Dockerfile`, commande différente.

```bash
export PROJECT_ID=vigie-507713          # ID réel ; le nom affiché en console est « vigie »
export REGION=europe-west1
export REPO=vigie
export SERVICE=vigie-api
export JOB=vigie-daily
export SA=vigie-run                     # compte de service d'exécution
export SCHED_SA=vigie-scheduler         # compte de service de l'ordonnanceur
export IMAGE=$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/vigie-01
```

## 1. Prérequis hors dépôt

```bash
gcloud config set project $PROJECT_ID
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com \
  firestore.googleapis.com secretmanager.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com
```

Facturation active sur le projet : à vérifier dans la console, aucune commande ne la remplace.
**Fait le 2026-09-05** sur `vigie-507713`, ainsi que l'activation des six APIs ci-dessus.

L'ID du projet n'est pas son nom affiché : Google a suffixé `vigie` en `vigie-507713`. Ce n'est pas
cosmétique — le domaine par défaut de Firebase Hosting en dérive, donc l'origine du front sera
`https://vigie-507713.web.app` et c'est cette chaîne que `ALLOWED_ORIGINS` doit porter (§5).

Comptes de service et rôles. Deux comptes distincts et non un : celui qui exécute le pipeline n'a
aucune raison de pouvoir déclencher des Jobs, et celui qui déclenche n'a aucune raison de lire la
base.

```bash
gcloud iam service-accounts create $SA       --display-name "VIGIE-01 execution"
gcloud iam service-accounts create $SCHED_SA --display-name "VIGIE-01 ordonnanceur"

# Exécution : lire les secrets, écrire dans Firestore.
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member serviceAccount:$SA@$PROJECT_ID.iam.gserviceaccount.com \
  --role roles/secretmanager.secretAccessor
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member serviceAccount:$SA@$PROJECT_ID.iam.gserviceaccount.com \
  --role roles/datastore.user
```

Le droit de déclenchement de l'ordonnanceur se pose **après** la création du Job (étape 6) : il
porte sur cette ressource précise, elle doit exister.

## 2. Base Firestore

**Choix définitif : la région d'une base Firestore ne se change pas après création.** La prendre
égale à `$REGION` pour que les lectures du pipeline ne traversent pas de continent — l'historique
est relu à chaque run.

```bash
gcloud firestore databases create --location=$REGION
```

Mode natif (défaut). Le code n'utilise ni index composite ni requête complexe : la purge et la
fenêtre glissante filtrent sur un champ date unique.

## 3. Secrets

```bash
printf %s "$ANTHROPIC_KEY" | gcloud secrets create anthropic-api-key --data-file=-
printf %s "$LANGCHAIN_KEY" | gcloud secrets create langchain-api-key --data-file=-

# Jeton de POST /run : généré, jamais choisi à la main.
python -c "import secrets,sys; sys.stdout.write(secrets.token_urlsafe(32))" \
  | gcloud secrets create run-token --data-file=-
```

## 4. Image

```bash
gcloud artifacts repositories create $REPO --repository-format=docker --location=$REGION
gcloud auth configure-docker $REGION-docker.pkg.dev

docker build -t $IMAGE:$(git rev-parse --short HEAD) -t $IMAGE:latest .
docker push $IMAGE --all-tags
```

Étiqueter par SHA de commit et pas seulement `latest` : `latest` ne dit pas quelle version tourne
quand un run nocturne se comporte mal.

Cette construction locale est celle de l'**amorçage** — le service et le Job n'existent pas encore,
il faut bien une image pour les créer. Ensuite elle ne se refait plus à la main : Cloud Build prend
le relais (§6 bis), qui vient après §5 et §6 parce qu'il met à jour ces ressources au lieu de les
créer.

## 5. Service Cloud Run — sert le digest

```bash
gcloud run deploy $SERVICE \
  --image $IMAGE:latest \
  --region $REGION \
  --service-account $SA@$PROJECT_ID.iam.gserviceaccount.com \
  --allow-unauthenticated \
  --port 8080 \
  --memory 512Mi --cpu 1 \
  --min-instances 0 --max-instances 2 \
  --timeout 900 \
  --set-env-vars "VIGIE_STORAGE=firestore,FIRESTORE_PROJECT=$PROJECT_ID,MAX_STEPS_PER_RUN=20,MAX_LLM_CALLS_PER_DAY=200,VIGIE_LOG_FORMAT=json,VIGIE_LOG_LEVEL=INFO,ALLOWED_ORIGINS=https://$PROJECT_ID.web.app,FETCH_FULL_ARTICLE=false" \
  --set-secrets "ANTHROPIC_API_KEY=anthropic-api-key:latest,LANGCHAIN_API_KEY=langchain-api-key:latest,RUN_TOKEN=run-token:latest"
```

`FIRESTORE_DATABASE` est omis : le code applique `(default)`, et passer la valeur littérale
`(default)` en ligne de commande demande un échappement qui casse silencieusement.
**Un seul `--set-env-vars`, et c'est structurel.** Ce drapeau ne s'accumule pas : répété, gcloud ne
garde que le dernier. Le runbook les listait sur quatre lignes jusqu'au 2026-09-05 — tel quel, le
service serait parti avec `ALLOWED_ORIGINS` pour seule variable, donc **sans aucun plafond de
budget**. L'erreur ne se serait pas vue au déploiement mais au premier run. Toutes les paires sur
une ligne, séparées par des virgules.

`FETCH_FULL_ARTICLE` y figure explicitement, à `false`. Le code vaut `true` par défaut : ne pas le
poser laisserait un module livré sur un bilan apparié non concluant (+2/−1 sur 10) s'activer en
production par simple défaut de configuration, alors que l'interrupteur existe pour que ce soit une
décision. À `false` pour le premier run — qui existe pour valider Firestore, pas le fetcher — puis
à basculer par `gcloud run services update --update-env-vars FETCH_FULL_ARTICLE=true`.


`--allow-unauthenticated` porte sur le service entier parce que `GET /events` est lu par un
navigateur, qui ne présente pas d'identité Google. C'est `RUN_TOKEN` qui ferme `POST /run`, le seul
endpoint coûteux — sans jeton configuré il répond 503, jamais 200.

`MAX_STEPS_PER_RUN` et `MAX_LLM_CALLS_PER_DAY` n'ont pas de valeur par défaut dans le code : leur
absence fait échouer l'import de `backend/config.py`. C'est voulu — le service doit refuser de
démarrer plutôt que tourner sans garde-fou de budget.

Sonde de démarrage sur `/health`. Le défaut TCP dit « le port écoute », pas « l'application a
importé sa configuration » — or c'est précisément l'import qui échoue quand un plafond manque :

```bash
gcloud run services update $SERVICE --region $REGION \
  --startup-probe httpGet.path=/health,initialDelaySeconds=5,periodSeconds=5,failureThreshold=6
```

**À ne pas lancer depuis Git Bash sous Windows.** MSYS convertit tout argument commençant par `/`
en chemin Windows : `httpGet.path=/health` est parti en `C:/Program Files/Git/health`, la sonde a
tapé sur `/`, et la révision n'a jamais démarré. Le symptôme trompe — les journaux montrent
`Application startup complete`, l'application allait bien. `MSYS_NO_PATHCONV=1` ne sauve pas la
mise : il casse le lanceur gcloud lui-même. Passer par PowerShell ou `cmd` pour cette commande.
Vérifier ensuite ce qui a réellement été posé, le gabarit du service gardant une sonde fausse et la
resservant à chaque déploiement suivant :

```bash
gcloud run services describe $SERVICE --region $REGION \
  --format="value(spec.template.spec.containers[0].startupProbe.httpGet.path)"
```

## 6. Job Cloud Run — exécute le run quotidien

```bash
gcloud run jobs create $JOB \
  --image $IMAGE:latest \
  --region $REGION \
  --service-account $SA@$PROJECT_ID.iam.gserviceaccount.com \
  --command python --args "-m,backend.job" \
  --memory 1Gi --cpu 1 \
  --task-timeout 3600 \
  --max-retries 0 \
  --set-env-vars "VIGIE_STORAGE=firestore,FIRESTORE_PROJECT=$PROJECT_ID,MAX_STEPS_PER_RUN=20,MAX_LLM_CALLS_PER_DAY=200,VIGIE_LOG_FORMAT=json,VIGIE_LOG_LEVEL=INFO,FETCH_FULL_ARTICLE=false" \
  --set-secrets "ANTHROPIC_API_KEY=anthropic-api-key:latest,LANGCHAIN_API_KEY=langchain-api-key:latest"

gcloud run jobs add-iam-policy-binding $JOB --region $REGION \
  --member serviceAccount:$SCHED_SA@$PROJECT_ID.iam.gserviceaccount.com \
  --role roles/run.invoker
```

`--max-retries 0` est un garde-fou de budget, pas une négligence : une tâche relancée refait une
collecte et repaie des appels. Le code sort déjà en 0 sur un run tronqué, précisément pour ne pas
déclencher de relance (`backend/job.py`) ; `--max-retries 0` couvre le cas restant, l'échec réel —
qu'on veut voir et diagnostiquer, pas réessayer à l'aveugle sur le budget du lendemain.

`--task-timeout 3600` laisse ~5× la durée observée. Pas de `RUN_TOKEN` ici : le Job n'expose aucun
endpoint, il exécute le pipeline directement.

Sous PowerShell, accoler la valeur au drapeau : `"--args=-m,backend.job"`. Détachée, `-m,backend.job`
est prise pour un drapeau parce qu'elle commence par un tiret, et gcloud rend
`argument --args: expected one argument`.

**Premier lancement manuel, avant d'automatiser** — c'est la première exécution de Firestore de son
existence :

```bash
gcloud run jobs execute $JOB --region $REGION --wait

gcloud run jobs executions logs read \
  "$(gcloud run jobs executions list --job $JOB --region $REGION --limit 1 --format 'value(name)')" \
  --region $REGION
```

À lire dans le journal, dans cet ordre : `run démarré`, un `collecte terminée` dont
`items_collectes` est non nul, un `dédoublonnage terminé` dont `liens_en_memoire` est non nul **au
second run** (s'il reste à zéro, la persistance ne relit pas ce qu'elle a écrit), puis `run terminé`
avec `llm_calls_by_node` renseigné.

Trois vérifications qui ne se déduisent pas d'un run réussi :

- **Réservation de budget en transaction.** `reserve_llm_call` est transactionnelle côté Firestore
  et ne l'a jamais été contre une base réelle. La voir marcher sur un run séquentiel ne prouve rien
  sur la concurrence : lancer deux exécutions simultanées et vérifier que le total consommé sur la
  journée ne dépasse pas `MAX_LLM_CALLS_PER_DAY`. Si ce garde-fou est faux, il n'est faux qu'en
  production.
- **Purge à sept jours.** Après huit jours de runs, `liens_en_memoire` doit se stabiliser et non
  croître indéfiniment.
- **Digest servi.** `curl https://<service>/events` doit rendre les items du Job — c'est ce qui
  prouve que le service et le Job voient la même base.

## 6 bis. Déploiement continu — Cloud Build

À partir d'ici, l'image ne se construit plus à la main : un push sur la branche par défaut déclenche
[`cloudbuild.yaml`](../cloudbuild.yaml), qui teste, construit, pousse, puis fait pointer le service
**et** le Job sur l'image de ce commit.

Cette section vient **après** §5 et §6 et non avant : le déclencheur met à jour des ressources
existantes (`run services update`, `run jobs update`), il ne les crée pas. C'est délibéré. La
configuration d'exécution — plafonds, secrets, timeouts — reste posée une seule fois, par le
runbook. Un `deploy` complet dans le fichier de build la réécrirait à chaque push, et un oubli de
`MAX_LLM_CALLS_PER_DAY` n'y serait visible qu'au premier run tournant sans garde-fou.

**Le déclencheur n'exécute jamais le Job.** Un run consomme le plafond quotidien de 200 appels :
déclenché par push, il viderait le budget à chaque commit et l'exécution de l'ordonnanceur n'aurait
plus rien à dépenser. Le déclenchement appartient à Cloud Scheduler, seul (§7).

Compte de service dédié au build. Quatre rôles, dont un régulièrement oublié : mettre à jour un
service qui s'exécute sous `$SA` demande le droit d'agir en son nom.

```bash
export BUILD_SA=vigie-build
gcloud iam service-accounts create $BUILD_SA --display-name "VIGIE-01 build"

for ROLE in roles/artifactregistry.writer roles/run.developer roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member serviceAccount:$BUILD_SA@$PROJECT_ID.iam.gserviceaccount.com --role $ROLE
done

# actAs sur le compte d'exécution, et sur lui seul — pas au niveau du projet.
gcloud iam service-accounts add-iam-policy-binding $SA@$PROJECT_ID.iam.gserviceaccount.com \
  --member serviceAccount:$BUILD_SA@$PROJECT_ID.iam.gserviceaccount.com \
  --role roles/iam.serviceAccountUser
```

Connexion du dépôt GitHub : **hors dépôt**. Elle passe par l'installation de l'application Cloud
Build sur `adrien-morel/vigie-01` (console Cloud Build → Dépôts → Connecter), une autorisation OAuth
qu'aucune commande ne remplace.

```bash
gcloud builds triggers create github \
  --name vigie-deploy \
  --region $REGION \
  --repo-owner adrien-morel --repo-name vigie-01 \
  --branch-pattern "^master$" \
  --build-config cloudbuild.yaml \
  --service-account "projects/$PROJECT_ID/serviceAccounts/$BUILD_SA@$PROJECT_ID.iam.gserviceaccount.com"
```

`^master$` et non `^main$` : c'est la branche par défaut du dépôt, et celle que couvre déjà
`.github/workflows/ci.yml`. La renommer imposerait de changer les deux au même moment, plus le
`HEAD` du remote — sans rien apporter au déploiement.

Le fichier de build rejoue `ruff` et `pytest` avant de construire. GitHub Actions couvre le même
terrain sur le même push, mais les deux déclencheurs sont indépendants : sans cette étape, un commit
dont les tests échouent partirait en production pendant que l'onglet Actions vire au rouge.

Le front n'est pas dans ce pipeline (§8). Il demande des identifiants Firebase distincts, et
`VITE_API_BASE` étant figé dans le bundle à la construction, le reconstruire n'a de sens qu'au
changement de l'URL de l'API ou du front lui-même — pas à chaque commit backend.

## 7. Ordonnanceur

```bash
gcloud scheduler jobs create http vigie-daily-trigger \
  --location $REGION \
  --schedule "30 6 * * *" --time-zone "Europe/Paris" \
  --uri "https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/$JOB:run" \
  --http-method POST \
  --oauth-service-account-email $SCHED_SA@$PROJECT_ID.iam.gserviceaccount.com
```

OAuth et non OIDC : l'API Cloud Run Admin attend un jeton d'accès Google, pas un jeton d'identité.
L'ordonnanceur ne fait que déclencher — il n'attend pas la fin du Job, donc sa limite de 30 min ne
s'applique pas à la durée du run.

Ce déclencheur remplace `scripts/daily_run.py`, outil de campagne qui ne part pas en production.

## 8. Front

```bash
cd frontend
cp .env.production.example .env.production   # y mettre l'URL réelle du service
npm ci && npm run build
npx firebase-tools login
npx firebase-tools use --add $PROJECT_ID
npx firebase-tools deploy --only hosting
```

Puis vérifier depuis l'origine réelle, pas depuis `localhost` : ouvrir l'URL Firebase et confirmer
que le digest se charge. Un CORS mal réglé ne se voit qu'ici — la CI ne couvre que le Python.

`VITE_API_BASE` est figé dans le bundle à la construction : changer l'URL de l'API impose de
reconstruire et redéployer le front, pas seulement de mettre à jour le service.

Si l'origine Firebase diffère de `https://$PROJECT_ID.web.app` :

```bash
gcloud run services update $SERVICE --region $REGION \
  --update-env-vars "ALLOWED_ORIGINS=https://<origine-reelle>"
```

## 9. Observabilité

Le journal est du JSON structuré (`backend/logging_setup.py`), donc filtrable par champ et pas par
grep. Deux alertes, sur deux signaux qui ne disent pas la même chose :

```
# Échec — le run n'a pas produit de digest.
resource.type="cloud_run_job" severity>=ERROR

# Troncature — succès partiel : un plafond a coupé, le digest existe mais est incomplet.
resource.type="cloud_run_job" jsonPayload.truncated=true
```

Les confondre ferait passer une troncature quotidienne pour une panne, ou l'inverse.

Requêtes utiles sur les mêmes champs : `jsonPayload.llm_calls_by_node` (répartition des 200 appels
du jour entre `analyze`, `verify` et `thread`), `jsonPayload.analyze_by_source` (part du budget
dépensée sur des items écartés, et pour quel motif), `jsonPayload.sources_muettes` (flux qui ne
publie plus — le défaut resté invisible un an sur OFAC).

## 10. Clôture

Observer un cycle quotidien complet sans intervention avant de considérer le déploiement fait, puis
mettre à jour `README.md` (statut, roadmap), `docs/cadrage.md` §10 et §11, `docs/decisions.md` et
`docs/slides.html`.
