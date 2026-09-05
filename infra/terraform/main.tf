locals {
  apis = [
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "firestore.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
  ]

  # Conteneurs seulement : les versions ne sont jamais gérées ici. Une valeur de secret posée par
  # Terraform se retrouve en clair dans l'état, donc dans le bucket. Elles sont créées par le
  # runbook §3 et ce module n'adopte que l'enveloppe.
  secrets = ["anthropic-api-key", "langchain-api-key", "run-token"]

  # Partagé par le service et le Job. ALLOWED_ORIGINS et RUN_TOKEN ne concernent que le service :
  # le Job n'expose aucun endpoint.
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

  # Désactiver une API à la destruction couperait des ressources que ce module ne possède pas.
  disable_on_destroy = false
}

# La région d'une base Firestore ne se change pas après création : tout changement de location_id se
# traduirait par un remplacement, donc par la perte de l'historique. prevent_destroy est ici le
# garde-fou, pas une précaution de style.
resource "google_firestore_database" "default" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  lifecycle {
    prevent_destroy = true
  }
}

# Trois comptes distincts et non un : celui qui exécute le pipeline n'a aucune raison de déclencher
# des Jobs, celui qui déclenche n'a aucune raison de lire la base, et celui qui construit n'a aucune
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

# Le rôle qu'on oublie : déployer une révision qui s'exécute sous vigie-run demande le droit d'agir
# en son nom. Posé sur ce compte-là, pas au niveau du projet.
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

  # Mise à l'échelle au niveau du service, distincte de celle du gabarit juste en dessous. Posée
  # par gcloud à la création : la déclarer est ce qui fait la différence entre adopter le service
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

        # Défauts posés par gcloud. Les omettre les enverrait à null au premier apply, ce qui est
        # un changement de comportement déguisé en adoption.
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

      # Le défaut TCP dit que le port écoute, pas que l'application a importé sa configuration — or
      # c'est l'import qui échoue quand un plafond de budget manque.
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
  # battent à chaque push : l'un veut l'image du dernier apply, l'autre celle du dernier commit.
  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }
}

# GET /events est lu par un navigateur, qui ne présente pas d'identité Google. C'est RUN_TOKEN qui
# ferme POST /run, le seul endpoint coûteux.
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

      # Cloud Run Jobs relance une tâche en erreur. Or un run tronqué a épuisé le plafond quotidien
      # d'appels : le relancer ne produirait rien et enterrerait le travail payé sous une pile de
      # tentatives en échec. Le code sort déjà en 0 sur une troncature ; ceci couvre l'échec réel,
      # qu'on veut voir et diagnostiquer plutôt que réessayer à l'aveugle.
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

# --- Ce qui n'existe pas encore, et que Terraform créera ----------------------------------------

resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker" {
  count = var.enable_scheduler ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.daily.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

# OAuth et non OIDC : l'API Cloud Run Admin attend un jeton d'accès Google, pas un jeton d'identité.
# L'ordonnanceur ne fait que déclencher — il n'attend pas la fin du Job, donc sa limite de 30 min ne
# s'applique pas à la durée du run.
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

resource "google_cloudbuild_trigger" "deploy" {
  count = var.enable_build_trigger ? 1 : 0

  project         = var.project_id
  location        = var.region
  name            = "vigie-deploy"
  filename        = "cloudbuild.yaml"
  service_account = google_service_account.build.id

  github {
    owner = var.github_owner
    name  = var.github_repo

    push {
      branch = var.branch_pattern
    }
  }
}
