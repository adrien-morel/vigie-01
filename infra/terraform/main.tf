locals {
  apis = [
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "firestore.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "monitoring.googleapis.com",
  ]

  # Containers only: the versions are never managed here. A secret value set by Terraform ends up in
  # clear in the state, and therefore in the bucket. They are created by runbook §3 and this module
  # adopts nothing but the envelope.
  secrets = ["anthropic-api-key", "langchain-api-key", "run-token"]

  # Shared by the service and the Job. ALLOWED_ORIGINS and RUN_TOKEN concern the service only: the
  # Job exposes no endpoint.
  env_common = {
    VIGIE_STORAGE         = "firestore"
    FIRESTORE_PROJECT     = var.project_id
    MAX_STEPS_PER_RUN     = "20"
    MAX_LLM_CALLS_PER_DAY = "200"
    VIGIE_LOG_FORMAT      = "json"
    VIGIE_LOG_LEVEL       = "INFO"
    FETCH_FULL_ARTICLE    = var.fetch_full_article
  }
}

resource "google_project_service" "apis" {
  for_each = toset(local.apis)

  project = var.project_id
  service = each.key

  # Disabling an API on destroy would cut resources this module does not own.
  disable_on_destroy = false
}

# A Firestore database's region cannot be changed after creation: any change to location_id
# traduirait par un remplacement, donc par la perte de l'historique. prevent_destroy est ici le
# a guardrail, not a stylistic precaution.
resource "google_firestore_database" "default" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  lifecycle {
    prevent_destroy = true
  }
}

# Three distinct accounts and not one: the account that runs the pipeline has no reason to trigger
# Jobs, the one that triggers has no reason to read the database, and the one that builds has no
# raison de faire l'un ou l'autre.
resource "google_service_account" "run" {
  project      = var.project_id
  account_id   = "vigie-run"
  display_name = "VIGIE-01 execution"
}

resource "google_service_account" "scheduler" {
  project      = var.project_id
  account_id   = "vigie-scheduler"
  display_name = "VIGIE-01 ordonnanceur"
}

resource "google_service_account" "build" {
  project      = var.project_id
  account_id   = "vigie-build"
  display_name = "VIGIE-01 build"
}

resource "google_project_iam_member" "run_roles" {
  for_each = toset(["roles/secretmanager.secretAccessor", "roles/datastore.user"])

  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.run.email}"
}

resource "google_project_iam_member" "build_roles" {
  for_each = toset([
    "roles/artifactregistry.writer",
    "roles/run.developer",
    "roles/logging.logWriter",
  ])

  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.build.email}"
}

# The role everyone forgets: deploying a revision that runs under vigie-run requires the right to act
# on its behalf. Set on that account, not at project level.
resource "google_service_account_iam_member" "build_act_as_run" {
  service_account_id = google_service_account.run.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.build.email}"
}

resource "google_artifact_registry_repository" "vigie" {
  project       = var.project_id
  location      = var.region
  repository_id = "vigie"
  format        = "DOCKER"
}

resource "google_secret_manager_secret" "secrets" {
  for_each = toset(local.secrets)

  project   = var.project_id
  secret_id = each.key

  replication {
    auto {}
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_cloud_run_v2_service" "api" {
  project  = var.project_id
  name     = "vigie-api"
  location = var.region

  deletion_protection = true
  ingress             = "INGRESS_TRAFFIC_ALL"

  # Scaling at service level, distinct from the template's just below. Set by gcloud at creation:
  # declaring it is what makes the difference between adopting the service
  # et le modifier au premier apply.
  scaling {
    min_instance_count = 0
  }

  template {
    service_account = google_service_account.run.email
    timeout         = "900s"

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      image = var.image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }

        # Defaults set by gcloud. Omitting them would send them to null on the first apply, which is
        # a behaviour change dressed up as adoption.
        cpu_idle          = true
        startup_cpu_boost = true
      }

      dynamic "env" {
        for_each = merge(local.env_common, {
          ALLOWED_ORIGINS = "https://${var.project_id}.web.app"
        })

        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = {
          ANTHROPIC_API_KEY = "anthropic-api-key"
          LANGCHAIN_API_KEY = "langchain-api-key"
          RUN_TOKEN         = "run-token"
        }

        content {
          name = env.key

          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.secrets[env.value].secret_id
              version = "latest"
            }
          }
        }
      }

      # The TCP default says the port is listening, not that the application has imported its
      # configuration — yet the import is what fails when a budget cap is missing.
      startup_probe {
        initial_delay_seconds = 5
        period_seconds        = 5
        failure_threshold     = 6

        http_get {
          path = "/health"
        }
      }
    }
  }

  # Terraform tient la configuration, Cloud Build tient l'image. Sans cette ligne les deux se
  # fight on every push: one wants the last apply's image, the other the last commit's.
  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }
}

# GET /events is read by a browser, which presents no Google identity. It is RUN_TOKEN that closes
# POST /run, the one expensive endpoint.
resource "google_cloud_run_v2_service_iam_member" "public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_job" "daily" {
  project  = var.project_id
  name     = "vigie-daily"
  location = var.region

  deletion_protection = true

  template {
    template {
      service_account = google_service_account.run.email
      timeout         = "3600s"

      # Cloud Run Jobs retries a task that errors. Yet a truncated run has exhausted the daily call
      # cap: retrying it would produce nothing and would bury the work paid for under a pile of failed
      # attempts. The code already exits 0 on a truncation; this covers the real failure, which we want
      # to see and diagnose rather than blindly retry.
      max_retries = 0

      containers {
        image   = var.image
        command = ["python"]
        args    = ["-m", "backend.job"]

        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }

        dynamic "env" {
          for_each = local.env_common

          content {
            name  = env.key
            value = env.value
          }
        }

        dynamic "env" {
          for_each = {
            ANTHROPIC_API_KEY = "anthropic-api-key"
            LANGCHAIN_API_KEY = "langchain-api-key"
          }

          content {
            name = env.key

            value_source {
              secret_key_ref {
                secret  = google_secret_manager_secret.secrets[env.value].secret_id
                version = "latest"
              }
            }
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image, client, client_version]
  }
}

# --- What does not exist yet, and that Terraform will create ------------------------------------

resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker" {
  count = var.enable_scheduler ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.daily.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

# OAuth and not OIDC: the Cloud Run Admin API expects a Google access token, not an identity token.
# The scheduler only triggers — it does not wait for the Job to finish, so its 30 min limit does not
# apply to the run's duration.
resource "google_cloud_scheduler_job" "daily" {
  count = var.enable_scheduler ? 1 : 0

  project   = var.project_id
  region    = var.region
  name      = "vigie-daily-trigger"
  schedule  = "30 6 * * *"
  time_zone = "Europe/Paris"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.daily.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }
}

data "google_project" "this" {
  project_id = var.project_id
}

locals {
  # The GitHub connection is deliberately outside Terraform, for the same reason as the state bucket:
  # it is born of an interactive OAuth authorisation and deposits a GitHub token in Secret Manager.
  # Declaring it here would bring that token into the state's perimeter. Created by runbook §6 bis.
  #
  # Nom court et non chemin complet : l'API renvoie `vigie-github`, et `parent_connection` force le
  # replacement of the resource as soon as it differs — giving the full path would destroy the link
  # lieu de l'adopter.
  build_connection = "vigie-github"

  # Cloud Build's internal service account, derived from the project number rather than hard-coded.
  cloudbuild_p4sa = "service-${data.google_project.this.number}@gcp-sa-cloudbuild.iam.gserviceaccount.com"
}

# A prerequisite of 2nd-generation connections, and not a convenience: this account is the one that
# writes the GitHub token into Secret Manager. Without it, creating the connection fails on
# `could not assert Secret Manager permissions`. The role is broad for want of a predefined role
# covering both secrets.create and secrets.setIamPolicy.
resource "google_project_iam_member" "cloudbuild_p4sa_secrets" {
  project = var.project_id
  role    = "roles/secretmanager.admin"
  member  = "serviceAccount:${local.cloudbuild_p4sa}"
}

# The pointer to the GitHub repository, by contrast, holds nothing secret: it can be managed here.
resource "google_cloudbuildv2_repository" "vigie" {
  project           = var.project_id
  location          = var.region
  name              = var.github_repo
  parent_connection = local.build_connection
  remote_uri        = "https://github.com/${var.github_owner}/${var.github_repo}.git"
}

# 2nd generation: `repository_event_config` and not the `github` block, which only applies to
# connexions historiques.
resource "google_cloudbuild_trigger" "deploy" {
  count = var.enable_build_trigger ? 1 : 0

  project         = var.project_id
  location        = var.region
  name            = "vigie-deploy"
  filename        = "cloudbuild.yaml"
  service_account = google_service_account.build.id

  # A commit that touches documentation only produces an identical image and an identical deployment.
  # The build only fires if at least one modified file falls outside this list — a mixed commit
  # mixte code + doc construit donc normalement.
  #
  # `docs/**` on top of the `.md` files: the slide deck is an `.html` and the screenshots are
  # `.png`, tous documentaires, aucun n'atteignant l'image (le Dockerfile ne copie que `backend/`).
  # We stop there deliberately, without adding `infra/**` which does not reach the image either: the
  # asymmetry of risk leans one way. Wrongly ignoring a change that mattered costs a silently missing
  # deployment; wrongly building costs two minutes of compute.
  ignored_files = ["**/*.md", "docs/**"]

  repository_event_config {
    repository = google_cloudbuildv2_repository.vigie.id

    push {
      branch = var.branch_pattern
    }
  }
}
