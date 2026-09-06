# Terraform — adopting the infrastructure

This module does not create the infrastructure: it **adopts** what is running. That was created by
hand on 2026-09-05 following [`../README.md`](../README.md), before this module existed. Starting
from a blank `apply` would have meant destroying what exists — and on the Firestore database that
would be irreparable, its region not being revisable after creation.

Hence the form: `import` blocks (Terraform ≥ 1.5) versioned in [`imports.tf`](imports.tf), rather
than a series of imperative `terraform import` commands of which the repository would keep no trace.

The runbook remains the reference for the **bootstrap** and the reasoning; this module is the
reference for the **current state**.

## What is managed here

25 resources: the 7 APIs, the Firestore database, the three service accounts and their roles, the
Artifact Registry repository, the three secrets, the Cloud Run service, its public exposure, the
Job, the daily scheduler and its invoker binding, and the two alert policies.

One resource is written but **disabled by default**:

- `enable_build_trigger` — the trigger requires the GitHub repository to be connected to Cloud Build
  through an OAuth authorisation, which is only done in the console. True since 2026-09-05, that
  prerequisite being satisfied; set it back to false to replay this module on a fresh project.

Two were disabled until 2026-09-06 and are now on by default:

- `enable_scheduler` — creating the scheduler before the first manual run had validated Firestore
  would have scheduled an unattended execution on a path never exercised. That run happened on
  2026-09-05, so the reason lapsed. **Arming it commits the daily budget**: from the first firing the
  200 calls are spent by 06:30 every day, so a measurement day means pausing the scheduler
  (`gcloud scheduler jobs pause vigie-daily-trigger`) and not flipping this variable, which would
  destroy the resource and its invoker binding.
- `enable_alerts` — an unattended run with no alert is the one configuration that must not persist,
  so the alerts are declared in the same pass as the scheduler. `alert_email` is empty by default and
  deliberately uncommitted: left empty the policies still fire and still show as incidents, they
  simply notify nobody.

## What is deliberately not managed here

- **The secret values.** Only the envelopes are adopted. A value set by Terraform would end up in
  clear in the state, and therefore in the bucket. The versions come from runbook §3.
- **The image.** `ignore_changes` neutralises it on the service and on the Job: Terraform holds the
  configuration, Cloud Build holds the image. Without that the two fight on every push — one wants
  the last `apply`'s, the other the last commit's.
- **The state bucket.** It contains Terraform's state: having Terraform manage it would create a
  cycle. Bootstrapped by hand, versioned.
- **The project, billing, the GitHub connection.** Outside the repository by nature.

## Guardrails

`prevent_destroy` on the Firestore database and on the three secrets; `deletion_protection` on the
service and the Job. A `terraform destroy` therefore fails as long as those protections have not been
explicitly lifted — that is intended, and it beats a badly aimed `-target`.

## Usage

```bash
cd infra/terraform
terraform init
terraform plan      # must say "No changes" on a converged infrastructure
terraform apply
```

**The credentials are not gcloud's.** Terraform uses Application Default Credentials, distinct from
the CLI's session. Experienced on 2026-09-05: the ADC still carried an old quota project, deleted in
the meantime, and `terraform init` answered `bucket doesn't exist` — a permission refusal dressed up
as a missing resource, while `gcloud` saw the bucket without difficulty. The fix:

```bash
gcloud auth application-default set-quota-project vigie-507713
```

The state lives in `gs://vigie-507713-tfstate` and is not in the repository. The
`.terraform.lock.hcl` file is, like the pinned versions in the `requirements*.txt` files: same rule,
same reason.
