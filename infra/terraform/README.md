# Terraform — adoption de l'infrastructure

Ce module ne crée pas l'infrastructure : il **adopte** celle qui tourne. Elle a été posée à la main
le 2026-09-05 en suivant [`../README.md`](../README.md), avant que ce module existe. Repartir d'un
`apply` vierge aurait supposé de détruire l'existant — et sur la base Firestore ce serait
irréparable, sa région n'étant pas révisable après création.

D'où la forme : des blocs `import` (Terraform ≥ 1.5) versionnés dans [`imports.tf`](imports.tf),
plutôt qu'une série de `terraform import` impératifs dont le dépôt ne garderait aucune trace.

Le runbook reste la référence de l'**amorçage** et du raisonnement ; ce module est la référence de
l'**état courant**.

## Ce qui est géré ici

23 ressources : les 6 APIs, la base Firestore, les trois comptes de service et leurs rôles, le
dépôt Artifact Registry, les trois secrets, le service Cloud Run, son ouverture publique, et le Job.

Deux ressources sont écrites mais **désactivées par défaut**, chacune pour sa raison :

- `enable_scheduler` — créer l'ordonnanceur avant que le premier run manuel ait validé Firestore
  programmerait une exécution non surveillée sur un chemin jamais exercé.
- `enable_build_trigger` — le déclencheur exige que le dépôt GitHub soit connecté à Cloud Build par
  une autorisation OAuth, qui ne se fait qu'en console.

## Ce qui n'est délibérément pas géré ici

- **Les valeurs des secrets.** Seules les enveloppes sont adoptées. Une valeur posée par Terraform
  se retrouverait en clair dans l'état, donc dans le bucket. Les versions viennent du runbook §3.
- **L'image.** `ignore_changes` la neutralise sur le service et sur le Job : Terraform tient la
  configuration, Cloud Build tient l'image. Sans cela les deux se battent à chaque push — l'un veut
  celle du dernier `apply`, l'autre celle du dernier commit.
- **Le bucket d'état.** Il contient l'état de Terraform : le lui faire gérer poserait un cycle.
  Amorcé à la main, versionné.
- **Le projet, la facturation, la connexion GitHub.** Hors dépôt par nature.

## Garde-fous

`prevent_destroy` sur la base Firestore et sur les trois secrets ; `deletion_protection` sur le
service et le Job. Un `terraform destroy` échoue donc tant qu'on n'a pas explicitement levé ces
protections — c'est voulu, et ça vaut mieux qu'un `-target` mal visé.

## Usage

```bash
cd infra/terraform
terraform init
terraform plan      # doit dire « No changes » sur une infrastructure convergée
terraform apply
```

**Les identifiants ne sont pas ceux de `gcloud`.** Terraform utilise les Application Default
Credentials, distinctes de la session du CLI. Vécu le 2026-09-05 : les ADC portaient encore un
ancien projet de quota, supprimé entre-temps, et `terraform init` répondait
`bucket doesn't exist` — un refus d'attribution déguisé en absence de ressource, alors que `gcloud`
voyait le bucket sans difficulté. Le correctif :

```bash
gcloud auth application-default set-quota-project vigie-507713
```

L'état vit dans `gs://vigie-507713-tfstate` et n'est pas dans le dépôt. Le fichier
`.terraform.lock.hcl` l'est, lui, comme les versions épinglées des `requirements*.txt` : même règle,
même raison.
