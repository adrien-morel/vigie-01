terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # Le bucket est amorcé à la main, hors Terraform : il contient l'état de Terraform, donc le lui
  # faire gérer poserait un cycle — détruire le bucket détruirait la trace de son existence.
  # Versionné, pour qu'un `apply` malheureux se rattrape.
  backend "gcs" {
    bucket = "vigie-507713-tfstate"
    prefix = "vigie-01"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
