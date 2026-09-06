variable "project_id" {
  description = "The project's real ID, not its display name. The Firebase Hosting domain derives from it."
  type        = string
  default     = "vigie-507713"
}

variable "region" {
  description = "Region of the service, the Job and the image repository. Equal to Firestore's, whose history is re-read several times per run."
  type        = string
  default     = "europe-west1"
}

variable "image" {
  description = "Image of the service and the Job. Its value here only counts at creation: Cloud Build then moves it forward on every push, and ignore_changes stops Terraform from pulling it back."
  type        = string
  default     = "europe-west1-docker.pkg.dev/vigie-507713/vigie/vigie-01:latest"
}

variable "fetch_full_article" {
  description = "Switch for the article-fetching module. The code defaults to true; it is set explicitly here so that it is a decision and not an inherited default. At false while the first run validates Firestore without confounding two variables."
  type        = string
  default     = "false"
}

variable "github_owner" {
  type    = string
  default = "adrien-morel"
}

variable "github_repo" {
  type    = string
  default = "vigie-01"
}

variable "branch_pattern" {
  description = "The repository's default branch: master, not main — it is also the one .github/workflows/ci.yml covers."
  type        = string
  default     = "^master$"
}

# The resources that must not come into being with the rest, each for its own reason.

variable "enable_scheduler" {
  description = <<-EOT
    True since 2026-09-06. It was false until then: creating the scheduler before the first manual run
    had validated Firestore would have scheduled an unattended execution on a path never exercised.
    That run happened on 2026-09-05, so the reason no longer holds.

    Arming it commits the daily budget: from the first firing the 200 calls are spent by 06:30 every
    day. A measurement day therefore means pausing the scheduler the evening before
    (`gcloud scheduler jobs pause vigie-daily-trigger`), not flipping this variable — flipping it
    destroys the resource and its invoker binding.
  EOT
  type        = bool
  default     = true
}

variable "enable_build_trigger" {
  description = "Assumes the GitHub connection exists and the application is installed on the repository (runbook §6 bis). True since 2026-09-05, that prerequisite being satisfied; set back to false to replay this module on a fresh project, where the OAuth authorisation does not exist yet."
  type        = bool
  default     = true
}
