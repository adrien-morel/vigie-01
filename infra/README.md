# Deployment — runbook

The production rollout sequence for VIGIE-01. Every command is runnable as it stands once the
variables in the block below are filled in. Anything that cannot be automated from the repository
(GCP project, billing, IAM) is flagged **outside the repo**.

Two architectural choices are fixed here, and the rest of the file follows from them:

- **The daily run is a Cloud Run Job**, not an HTTP request. The pipeline takes ~620 s and that
  duration is rising (401 s on 2026-08-20, 513 s on the 21st, 620 s on the 22nd); a Job has no
  request timeout, where Cloud Scheduler caps at 30 min. The Cloud Run service stays dedicated to
  what it serves quickly: the digest already produced.
- **The front is on Firebase Hosting**, therefore on a different origin from the API.
  `ALLOWED_ORIGINS` on the service side must carry that origin, or the browser refuses the response.

The Job and the service share **a single image**: the same `Dockerfile`, a different command.

```bash
export PROJECT_ID=vigie-507713          # the real ID; the name shown in the console is "vigie"
export REGION=europe-west1
export REPO=vigie
export SERVICE=vigie-api
export JOB=vigie-daily
export SA=vigie-run                     # execution service account
export SCHED_SA=vigie-scheduler         # scheduler service account
export GITHUB_OWNER=adrien-morel
export GITHUB_REPO=vigie-01             # the repository, not the GCP project
export IMAGE=$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/vigie-01
```

## 1. Prerequisites outside the repo

```bash
gcloud config set project $PROJECT_ID
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com \
  firestore.googleapis.com secretmanager.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com
```

Billing active on the project: to be checked in the console, no command replaces it. **Done on
2026-09-05** on `vigie-507713`, along with enabling the six APIs above.

The project ID is not its display name: Google suffixed `vigie` into `vigie-507713`. That is not
cosmetic — the default Firebase Hosting domain derives from it, so the front's origin will be
`https://vigie-507713.web.app` and that is the string `ALLOWED_ORIGINS` must carry (§5).

Service accounts and roles. Two distinct accounts and not one: the account that runs the pipeline has
no reason to be able to trigger Jobs, and the one that triggers has no reason to read the database.

```bash
gcloud iam service-accounts create $SA       --display-name "VIGIE-01 execution"
gcloud iam service-accounts create $SCHED_SA --display-name "VIGIE-01 scheduler"

# Execution: read the secrets, write to Firestore.
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member serviceAccount:$SA@$PROJECT_ID.iam.gserviceaccount.com \
  --role roles/secretmanager.secretAccessor
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member serviceAccount:$SA@$PROJECT_ID.iam.gserviceaccount.com \
  --role roles/datastore.user
```

The scheduler's trigger permission is granted **after** the Job is created (step 6): it applies to
that precise resource, which has to exist.

## 2. Firestore database

**A definitive choice: a Firestore database's region cannot be changed after creation.** Take it
equal to `$REGION` so that the pipeline's reads do not cross a continent — the history is re-read on
every run.

```bash
gcloud firestore databases create --location=$REGION
```

Native mode (the default). The code uses neither composite indexes nor complex queries: the purge and
the sliding window filter on a single date field.

## 3. Secrets

```bash
printf %s "$ANTHROPIC_KEY" | gcloud secrets create anthropic-api-key --data-file=-
printf %s "$LANGCHAIN_KEY" | gcloud secrets create langchain-api-key --data-file=-

# POST /run token: generated, never chosen by hand.
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

Tag by commit SHA and not only `latest`: `latest` does not say which version is running when an
overnight run misbehaves.

This local build is the **bootstrap** one — the service and the Job do not exist yet, and an image is
needed to create them. After that it is no longer done by hand: Cloud Build takes over (§6 bis),
which comes after §5 and §6 because it updates those resources rather than creating them.

## 5. Cloud Run service — serves the digest

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

`FIRESTORE_DATABASE` is omitted: the code applies `(default)`, and passing the literal `(default)` on
the command line requires an escaping that breaks silently.

**A single `--set-env-vars`, and that is structural.** This flag does not accumulate: repeated,
gcloud keeps only the last one. The runbook listed them on four lines until 2026-09-05 — as it stood,
the service would have started with `ALLOWED_ORIGINS` as its only variable, and therefore **with no
budget cap at all**. The error would not have shown at deployment time but on the first run. All the
pairs on one line, comma-separated.

`FETCH_FULL_ARTICLE` appears there explicitly, at `false`. The code defaults to `true`: not setting it
would let a module shipped on an inconclusive paired result (+2/−1 out of 10) switch itself on in
production by a mere configuration default, when the switch exists precisely to make that a decision.
At `false` for the first run — which exists to validate Firestore, not the fetcher — then to be
flipped with `gcloud run services update --update-env-vars FETCH_FULL_ARTICLE=true`.

`--allow-unauthenticated` applies to the whole service because `GET /events` is read by a browser,
which presents no Google identity. It is `RUN_TOKEN` that closes `POST /run`, the one expensive
endpoint — with no token configured it answers 503, never 200.

`MAX_STEPS_PER_RUN` and `MAX_LLM_CALLS_PER_DAY` have no default value in the code: their absence
fails the import of `backend/config.py`. That is deliberate — the service must refuse to start rather
than run with no budget guardrail.

Startup probe on `/health`. The TCP default says "the port is listening", not "the application has
imported its configuration" — yet the import is precisely what fails when a cap is missing:

```bash
gcloud run services update $SERVICE --region $REGION \
  --startup-probe httpGet.path=/health,initialDelaySeconds=5,periodSeconds=5,failureThreshold=6
```

**Do not run this from Git Bash on Windows.** MSYS converts any argument starting with `/` into a
Windows path: `httpGet.path=/health` went out as `C:/Program Files/Git/health`, the probe hit `/`, and
the revision never started. The symptom misleads — the logs show `Application startup complete`, the
application was fine. `MSYS_NO_PATHCONV=1` does not save the day: it breaks the gcloud launcher
itself. Use PowerShell or `cmd` for this command. Then check what was actually set, since the service
template keeps a wrong probe and serves it again on every subsequent deployment:

```bash
gcloud run services describe $SERVICE --region $REGION \
  --format="value(spec.template.spec.containers[0].startupProbe.httpGet.path)"
```

## 6. Cloud Run Job — runs the daily run

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

`--max-retries 0` is a budget guardrail, not an oversight: a retried task redoes a collection and pays
for the calls again. The code already exits 0 on a truncated run, precisely so as not to trigger a
retry (`backend/job.py`); `--max-retries 0` covers the remaining case, a real failure — which we want
to see and diagnose, not blindly retry on tomorrow's budget.

`--task-timeout 3600` leaves ~5× the observed duration. No `RUN_TOKEN` here: the Job exposes no
endpoint, it runs the pipeline directly.

Under PowerShell, attach the value to the flag: `"--args=-m,backend.job"`. Detached, `-m,backend.job`
is taken for a flag because it starts with a dash, and gcloud returns
`argument --args: expected one argument`.

**First manual launch, before automating** — it is Firestore's first execution of its existence:

```bash
gcloud run jobs execute $JOB --region $REGION --wait

gcloud run jobs executions logs read \
  "$(gcloud run jobs executions list --job $JOB --region $REGION --limit 1 --format 'value(name)')" \
  --region $REGION
```

To read in the log, in this order: `run started`, a `collection finished` whose `items_collected` is
non-zero, a `deduplication finished` whose `links_in_memory` is non-zero **on the second run** (if it
stays at zero, persistence is not reading back what it wrote), then `run finished` with
`llm_calls_by_node` filled in.

Three checks that do not follow from a successful run:

- **Budget reservation in a transaction — verified on 2026-09-05.** 30 simultaneous reservations
  across 3 containers for 4 slots: exactly 4 accepted, 26 refused, the counter at 200 on the nose. The
  tasks were genuinely interleaved — one read 2 slots left while the other two read 4 — and the
  Firestore transaction serialised everything all the same.

  **The method prescribed here until that date was the wrong instrument**, and it is worth recounting:
  "launch two simultaneous executions of the Job". Tried, it produced **a single reservation in
  total** and the two executions did not even overlap — deduplication had marked every item on the
  first run, nothing was left to analyse, and so nothing to reserve. A counter left under the cap
  would then have passed for proof when no race had taken place. The full pipeline is too indirect an
  instrument: you have to aim at the function, and the remaining slots have to be **fewer than the
  attempts**.

  ```bash
  gcloud run jobs execute $JOB --region $REGION --tasks 3 \
    "--args=-m,backend.eval.probe_budget_concurrency,--yes"
  ```

  The probe issues no model call — a reservation is a counter increment — and can be rerun on any day
  when the budget is nearly spent.
- **Seven-day purge.** After eight days of runs, `links_in_memory` must stabilise rather than grow
  indefinitely.
- **Digest served.** `curl https://<service>/events` must return the Job's items — that is what proves
  the service and the Job see the same database.

## 6 bis. Continuous deployment — Cloud Build

From here on, the image is no longer built by hand: a push on the default branch triggers
[`cloudbuild.yaml`](../cloudbuild.yaml), which tests, builds, pushes, then points the service **and**
the Job at that commit's image.

This section comes **after** §5 and §6 and not before: the trigger updates existing resources
(`run services update`, `run jobs update`), it does not create them. That is deliberate. The runtime
configuration — caps, secrets, timeouts — is set once, by the runbook. A full `deploy` in the build
file would rewrite it on every push, and a forgotten `MAX_LLM_CALLS_PER_DAY` would only be visible on
the first run running with no guardrail.

**The trigger never executes the Job.** A run consumes the daily cap of 200 calls: triggered by push,
it would empty the budget on every commit and the scheduler's execution would have nothing left to
spend. Triggering belongs to Cloud Scheduler, alone (§7).

A dedicated build service account. Four roles, one of them regularly forgotten: updating a service
that runs under `$SA` requires the right to act on its behalf.

```bash
export BUILD_SA=vigie-build
gcloud iam service-accounts create $BUILD_SA --display-name "VIGIE-01 build"

for ROLE in roles/artifactregistry.writer roles/run.developer roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member serviceAccount:$BUILD_SA@$PROJECT_ID.iam.gserviceaccount.com --role $ROLE
done

# actAs on the execution account, and on it alone — not at project level.
gcloud iam service-accounts add-iam-policy-binding $SA@$PROJECT_ID.iam.gserviceaccount.com \
  --member serviceAccount:$BUILD_SA@$PROJECT_ID.iam.gserviceaccount.com \
  --role roles/iam.serviceAccountUser
```

Connecting the GitHub repository, in **2nd generation**. It is done almost entirely on the command
line: a single click stays manual, the OAuth authorisation.

One prerequisite first, without which creation fails on `could not assert Secret Manager
permissions`: Cloud Build's internal service account deposits the GitHub token in Secret Manager, so
it needs the right to create a secret **and** to set its policy. No narrower predefined role covers
both.

```bash
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member "serviceAccount:service-$PROJECT_NUMBER@gcp-sa-cloudbuild.iam.gserviceaccount.com" \
  --role roles/secretmanager.admin
```

```bash
gcloud builds connections create github vigie-github --region=$REGION
```

The command returns `PENDING_USER_OAUTH` and prints a link: that is the click. It authorises Google,
then GitHub offers to install the **Google Cloud Build** application.

**The trap is right there.** GitHub offers "Only select repositories" with a list, and the repository
you have just opened is not necessarily ticked in it — the connection then goes to `COMPLETE` while
the application cannot see the right repository, and the next step fails on `does not exist or is not
accessible`. Check what Cloud Build actually sees rather than assuming it:

```bash
curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://cloudbuild.googleapis.com/v2/projects/$PROJECT_ID/locations/$REGION/connections/vigie-github:fetchLinkableRepositories" \
  | grep remoteUri
```

If the repository is missing, add it to the installation's scope at
`https://github.com/settings/installations` — the connection itself stays valid and does not need
redoing.

```bash
gcloud builds repositories create $GITHUB_REPO \
  --remote-uri=https://github.com/$GITHUB_OWNER/$GITHUB_REPO.git \
  --connection=vigie-github --region=$REGION
```

**The trigger itself is not created here**: Terraform creates it, together with the repository and the
IAM prerequisite above (`infra/terraform`, variable `enable_build_trigger`). The connection, on the
other hand, stays outside Terraform, like the state bucket — it carries a GitHub token, and declaring
it would bring that token into the state's perimeter.

**Everything is regional, including what the console shows.** The build, the repository connection
and the trigger live in `$REGION` and not in `global` — consistent with the rest of the project, but
the Cloud Build console opens on `global` and therefore looks empty. Observed on 2026-09-05:
`gcloud builds list --region global` returns nothing where `--region europe-west1` returns the build.
Two reflexes, then: the region selector, and `?project=vigie-507713` in the URL — a link with no
project falls back on the last project visited, which may have been deleted in the meantime.

```bash
gcloud builds list --region $REGION --limit 5
gcloud builds triggers list --region $REGION
```

`^master$` and not `^main$`: it is the repository's default branch, and the one
`.github/workflows/ci.yml` already covers. Renaming it would mean changing both at the same moment,
plus the remote's `HEAD` — with nothing gained for the deployment.

The build file replays `ruff` and `pytest` before building. GitHub Actions covers the same ground on
the same push, but the two triggers are independent: without that step, a commit whose tests fail
would go to production while the Actions tab turns red.

The front is not in this pipeline (§8). It needs separate Firebase credentials, and since
`VITE_API_BASE` is frozen into the bundle at build time, rebuilding it only makes sense when the API's
URL or the front itself changes — not on every backend commit.

## 7. Scheduler

```bash
gcloud scheduler jobs create http vigie-daily-trigger \
  --location $REGION \
  --schedule "30 6 * * *" --time-zone "Europe/Paris" \
  --uri "https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/$JOB:run" \
  --http-method POST \
  --oauth-service-account-email $SCHED_SA@$PROJECT_ID.iam.gserviceaccount.com
```

OAuth and not OIDC: the Cloud Run Admin API expects a Google access token, not an identity token. The
scheduler only triggers — it does not wait for the Job to finish, so its 30 min limit does not apply
to the run's duration.

This trigger replaces `scripts/daily_run.py`, a campaign tool that does not ship to production.

Prefer creating it through Terraform (`infra/terraform`, variable `enable_scheduler`), so that the
resource and the invoker permission are declared together rather than set by hand.

**What arming it commits you to.** From the first firing, the 200 daily calls are spent by 06:30 every
day. Every future measurement — the classification precision first of all, which costs a whole day's
budget — therefore requires pausing the scheduler the evening before:

```bash
gcloud scheduler jobs pause  vigie-daily-trigger --location $REGION
gcloud scheduler jobs resume vigie-daily-trigger --location $REGION
```

## 8. Front

```bash
cd frontend
cp .env.production.example .env.production   # put the service's real URL in it
npm ci && npm run build
npx firebase-tools login
npx firebase-tools use --add $PROJECT_ID
npx firebase-tools deploy --only hosting
```

Then check from the real origin, not from `localhost`: open the Firebase URL and confirm the digest
loads. A misconfigured CORS only shows here — the CI covers Python only.

`VITE_API_BASE` is frozen into the bundle at build time: changing the API's URL means rebuilding and
redeploying the front, not merely updating the service.

If the Firebase origin differs from `https://$PROJECT_ID.web.app`:

```bash
gcloud run services update $SERVICE --region $REGION \
  --update-env-vars "ALLOWED_ORIGINS=https://<real-origin>"
```

**The front and the backend ship together when the served shape changes.** The English pass of
2026-09-06 renamed the stored fields (`title_fr` → `title_en`) and the category identifiers: the old
front reads a field the new backend no longer serves, and the reverse. Neither order avoids a short
window of blank titles on the public URL — the point is to keep it to minutes by having the front
build ready before the push that triggers Cloud Build.

## 9. Observability

The log is structured JSON (`backend/logging_setup.py`), so it filters by field and not by grep. Two
alerts, on two signals that do not say the same thing — **created on 2026-09-06 and managed by the
Terraform module** (`infra/terraform/alerts.tf`), not to be recreated by hand:

```
# Failure — the run produced no digest.
resource.type="cloud_run_job" severity>=ERROR

# Truncation — a partial success: a cap cut in, the digest exists but is incomplete.
resource.type="cloud_run_job" jsonPayload.truncated=true
```

Conflating them would make a daily truncation pass for an outage, or the reverse.

Useful queries over the same fields: `jsonPayload.llm_calls_by_node` (how the day's 200 calls split
between `analyze`, `verify` and `thread`), `jsonPayload.analyze_by_source` (the share of the budget
spent on discarded items, and for what reason), `jsonPayload.silent_sources` (a feed that no longer
publishes — the defect that stayed invisible for a year on OFAC).

The field names are those of the English pass of 2026-09-06. A saved query written against the
earlier names (`items_collectes`, `liens_en_memoire`, `sources_muettes`) returns nothing rather than
an error — and matches nothing on the records written before that date either, since the fields are
in the log lines, not in the store.

## 10. Closing

Observe a full daily cycle with no intervention before considering the deployment done, then update
`README.md` (status, roadmap), `docs/scoping.md` §10 and §11, `docs/decisions.md` and
`docs/slides.html`.
