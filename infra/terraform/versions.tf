terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # The bucket is bootstrapped by hand, outside Terraform: it holds Terraform's state, so having
  # Terraform manage it would create a cycle — destroying the bucket would destroy the record of its
  # own existence. Versioned, so that an unfortunate `apply` can be recovered from.
  backend "gcs" {
    bucket = "vigie-507713-tfstate"
    prefix = "vigie-01"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
