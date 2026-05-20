# Hermes Azure Platform Terraform

This Terraform scaffold creates the first production Azure resource shape for
Hermes platform deployment. It is intentionally infrastructure-only and should
be driven through the gated Phase 20 workflow:

```text
plan -> preflight -> approval -> apply staging -> smoke -> soak
  -> approval -> promote production -> monitor -> rollback
```

## Resources

Created resources:

- resource group
- Log Analytics workspace
- Application Insights
- ADLS Gen2 / Blob Storage account
- private containers:
  - `hermes-artifacts`
  - `hermes-memory`
  - `hermes-corpus`
  - `hermes-audit`
- Azure Key Vault
- Event Hubs namespace
- Event Hubs topics:
  - `runtime.events`
  - `learning.events`
  - `memory.sync`
  - `observability.events`
  - `deployment.events`
  - `deadletter.events`
- Azure Container Apps environment
- Hermes runtime Container App
- Hermes sidecar Container App
- optional Azure PostgreSQL Flexible Server

## Defaults

- SQLite remains the local spool/fallback.
- Event Hubs Kafka protocol is the managed production bus target.
- Container Apps are the first runtime/sidecar compute target.
- PostgreSQL is optional in this scaffold because it requires an operator-owned
  password and network decision.
- Public ingress is disabled by default.

## Usage

```bash
cd infra/azure/terraform/hermes-platform
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars; do not commit real tenant ids, image refs, or secrets
terraform init
terraform fmt -check
terraform validate
terraform plan
```

Apply is intentionally not part of the default workflow. Use the Hermes
deployment gate or an explicit operator-approved Terraform apply.

## Secrets

Do not commit secrets in `terraform.tfvars`.

Use environment variables or your deployment runner secret store:

```bash
export TF_VAR_postgres_admin_password='...'
```

Provider API keys, connector tokens, and deployment tokens belong in Azure Key
Vault after creation and should be referenced by name from Hermes config.

## Production Notes

This scaffold does not yet create Azure Front Door, Application Gateway,
private endpoints, managed identities, role assignments, or full network
isolation. Those should be added after the Phase 20 fake-adapter tests and
preflight gates are implemented.
