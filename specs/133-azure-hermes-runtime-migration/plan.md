# Implementation Plan: Azure Hermes Runtime Migration

## Summary

Create a safe Azure migration path for the Hermes runtime work currently on
`132-learning-memory-runtime`. The first deliverable is an Azure VM recovery
environment that recreates the lost AWS VM services. The second deliverable is a
production topology using Azure Container Apps and managed services after
provider registration and smoke validation.

## Current Preserved Work

Parent branch:

```text
132-learning-memory-runtime
```

Latest preserved commit at branch creation:

```text
e675e4136 Add runtime allocation observability
```

Key preserved capabilities:

- runtime memory injection
- runtime degradation/final-response disclosure
- empty worker-output degradation classification
- goal allocation spec and primitives
- allocation observability CLI
- AWS secret reference checker
- TinyFish tool readiness
- production smoke supervisor prompt
- self-healing workflow architecture/specs

## Azure Strategy

### Phase A: VM Recovery

Use Azure VM to recover the AWS VM operational shape quickly:

- Ubuntu LTS VM
- Hermes repo branch checkout
- Python venv
- Hermes CLI install
- Codex CLI/auth manually configured by operator
- Claude Code settings copied from known-good local project
- TinyFish SDK
- Docker + Ollama if local curator model is required
- Azure Key Vault or temporary chmod-600 env file for secrets
- runtime smoke tests

### Phase B: Managed Production

After recovery smoke passes and providers are registered:

- Azure Container Registry
- Azure Container Apps for API/supervisor
- Azure Container Apps jobs/workers for sidecars and worker-router
- Azure Database for PostgreSQL Flexible Server
- Azure Blob Storage for artifacts/memory bundles
- Azure Key Vault for secrets
- Azure Service Bus for queues
- Azure Monitor + Log Analytics
- Cloudflare or Azure Front Door for CDN/WAF

## AWS-To-Azure Mapping

| AWS/VM-era Need | Azure / Edge Target |
| --- | --- |
| EC2 VM | Azure VM, then Container Apps |
| AWS Secrets Manager | Azure Key Vault |
| S3 artifacts | Azure Blob Storage or Cloudflare R2 |
| RDS/Postgres | Azure PostgreSQL Flexible Server |
| SQS/EventBridge | Azure Service Bus |
| ECR | Azure Container Registry |
| CloudWatch | Azure Monitor + Log Analytics |
| CloudFront/WAF | Cloudflare or Azure Front Door |
| Lambda/webhooks | Azure Functions or Container Apps |
| Route 53 DNS | Cloudflare DNS or existing registrar DNS |

## Provider Registration

Required for production path:

```bash
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.DBforPostgreSQL
az provider register --namespace Microsoft.ContainerRegistry
az provider register --namespace Microsoft.KeyVault
```

## Project Structure

```text
specs/133-azure-hermes-runtime-migration/
├── spec.md
├── plan.md
├── tasks.md
├── quickstart.md
└── contracts/
    ├── azure-service-map.md
    ├── azure-vm-recovery.md
    ├── production-topology.md
    └── smoke-validation.md
```

## Testing

Test order:

1. Local spec validation.
2. Azure CLI read-only subscription checks.
3. Provider registration status.
4. VM creation dry-run/what-if where possible.
5. VM bootstrap smoke.
6. Hermes runtime smoke.
7. Claude/TinyFish readiness smoke.
8. Secret reference check.
9. Production topology plan review.

## Constraints

- Do not commit raw credentials.
- Do not deploy paid resources without explicit operator approval.
- Prefer idempotent scripts and clear teardown commands.
- Keep VM recovery separate from managed production migration.
- Do not migrate to Container Apps until provider registration and recovery VM
  smoke are complete.
