# Adoption de l'existant, et non recréation.
#
# L'infrastructure a été posée à la main le 2026-09-05 en suivant infra/README.md, avant que ce
# module existe. Repartir d'un `apply` vierge supposerait de détruire ce qui tourne — et sur la base
# Firestore ce serait irréparable, sa région n'étant pas révisable après création. Les blocs `import`
# font donc entrer ces ressources dans l'état sans y toucher : `terraform plan` doit annoncer
# « will be imported » et, sur ces ressources-là, aucun changement.
#
# Blocs natifs (Terraform >= 1.5) et non `terraform import` : ils sont versionnés, relisibles, et
# rejouables sur un état neuf — une commande impérative ne laisse aucune trace dans le dépôt.
#
# Une fois le premier apply passé, ce fichier peut être supprimé : les imports sont idempotents mais
# n'ont plus d'objet. Le garder tant que l'état n'a pas été reconstruit au moins une fois.
#
# Deux ressources ne sont pas ici, parce qu'elles n'existent pas encore : l'ordonnanceur et le
# déclencheur Cloud Build. Une troisième non plus, et pour une raison qui vaut d'être notée : le
# compte de build et ses trois rôles de projet existaient déjà, créés par une commande interrompue
# avant sa dernière ligne. Seul l'`actAs` manquait. C'est exactement le cas que l'adoption sait
# traiter et qu'un module écrit « à blanc » aurait heurté de front.

import {
  for_each = toset(local.apis)
  to       = google_project_service.apis[each.key]
  id       = "${var.project_id}/${each.key}"
}

import {
  to = google_firestore_database.default
  id = "projects/${var.project_id}/databases/(default)"
}

import {
  to = google_service_account.run
  id = "projects/${var.project_id}/serviceAccounts/vigie-run@${var.project_id}.iam.gserviceaccount.com"
}

import {
  to = google_service_account.scheduler
  id = "projects/${var.project_id}/serviceAccounts/vigie-scheduler@${var.project_id}.iam.gserviceaccount.com"
}

import {
  for_each = toset(["roles/secretmanager.secretAccessor", "roles/datastore.user"])
  to       = google_project_iam_member.run_roles[each.key]
  id       = "${var.project_id} ${each.key} serviceAccount:vigie-run@${var.project_id}.iam.gserviceaccount.com"
}

import {
  to = google_service_account.build
  id = "projects/${var.project_id}/serviceAccounts/vigie-build@${var.project_id}.iam.gserviceaccount.com"
}

import {
  for_each = toset([
    "roles/artifactregistry.writer",
    "roles/run.developer",
    "roles/logging.logWriter",
  ])
  to = google_project_iam_member.build_roles[each.key]
  id = "${var.project_id} ${each.key} serviceAccount:vigie-build@${var.project_id}.iam.gserviceaccount.com"
}

import {
  to = google_artifact_registry_repository.vigie
  id = "projects/${var.project_id}/locations/${var.region}/repositories/vigie"
}

import {
  for_each = toset(local.secrets)
  to       = google_secret_manager_secret.secrets[each.key]
  id       = "projects/${var.project_id}/secrets/${each.key}"
}

import {
  to = google_cloud_run_v2_service.api
  id = "projects/${var.project_id}/locations/${var.region}/services/vigie-api"
}

import {
  to = google_cloud_run_v2_service_iam_member.public
  id = "projects/${var.project_id}/locations/${var.region}/services/vigie-api roles/run.invoker allUsers"
}

import {
  to = google_cloud_run_v2_job.daily
  id = "projects/${var.project_id}/locations/${var.region}/jobs/vigie-daily"
}
