variable "project_id" {
  description = "ID réel du projet, pas son nom affiché. Le domaine Firebase Hosting en dérive."
  type        = string
  default     = "vigie-507713"
}

variable "region" {
  description = "Région du service, du Job et du dépôt d'images. Égale à celle de Firestore, dont l'historique est relu plusieurs fois par run."
  type        = string
  default     = "europe-west1"
}

variable "image" {
  description = "Image du service et du Job. Sa valeur ici ne vaut qu'à la création : Cloud Build la fait ensuite avancer à chaque push, et ignore_changes empêche Terraform de la ramener en arrière."
  type        = string
  default     = "europe-west1-docker.pkg.dev/vigie-507713/vigie/vigie-01:latest"
}

variable "fetch_full_article" {
  description = "Interrupteur du module de récupération d'articles. Le code vaut true par défaut ; on le pose ici explicitement pour que ce soit une décision et non un défaut hérité. À false le temps que le premier run valide Firestore sans confondre deux variables."
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
  description = "Branche par défaut du dépôt : master, pas main — c'est aussi celle que couvre .github/workflows/ci.yml."
  type        = string
  default     = "^master$"
}

# Les deux ressources qui ne doivent pas naître avec le reste, chacune pour sa raison.

variable "enable_scheduler" {
  description = "Faux par défaut : créer l'ordonnanceur avant que le premier run manuel ait validé Firestore programmerait une exécution non surveillée sur un chemin jamais exercé."
  type        = bool
  default     = false
}

variable "enable_build_trigger" {
  description = "Suppose que la connexion GitHub existe et que l'application est installée sur le dépôt (runbook §6 bis). Vrai depuis le 2026-09-05, ce prérequis étant satisfait ; à repasser à faux pour rejouer ce module sur un projet neuf, où l'autorisation OAuth n'existe pas encore."
  type        = bool
  default     = true
}
