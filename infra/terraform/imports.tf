# Adopting what exists, rather than recreating it.
#
# The infrastructure was created by hand on 2026-09-05 following infra/README.md, before this module
# existed. Starting from a blank `apply` would mean destroying what is running — and on the Firestore
# database that would be irreparable, its region not being revisable after creation. The `import`
# blocks therefore bring those resources into the state without touching them: `terraform plan` must
# announce "will be imported" and, on those resources, no change at all.
#
# Native blocks (Terraform >= 1.5) and not `terraform import`: they are versioned, readable, and
# replayable on a fresh state — an imperative command leaves no trace in the repository.
#
# Once the first apply has gone through, this file can be deleted: the imports are idempotent but no
# longer serve a purpose. Keep it until the state has been rebuilt at least once.
#
# Two resources are not here, because this module creates them rather than adopting them: the
# scheduler and the Cloud Build trigger. Nor a third, for a reason worth noting: the build account
# and its three
# project roles already existed, created by a command interrupted before its last line. Only the
# `actAs` was missing. That is exactly the case adoption handles and that a module written from
# scratch would have hit head-on.

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

import {
  to = google_cloudbuildv2_repository.vigie
  id = "projects/${var.project_id}/locations/${var.region}/connections/vigie-github/repositories/${var.github_repo}"
}

import {
  to = google_project_iam_member.cloudbuild_p4sa_secrets
  id = "${var.project_id} roles/secretmanager.admin serviceAccount:${local.cloudbuild_p4sa}"
}
