# Azure Service Map Contract

## Purpose

Map the AWS/VM-era Hermes services to Azure or edge equivalents.

## Required Mapping

| Capability | Immediate Azure Recovery | Production Azure/Edge |
| --- | --- | --- |
| Hermes supervisor runtime | Azure VM process | Azure Container Apps service |
| Worker-router / agents | Azure VM process | Container Apps worker/jobs |
| Learning/health sidecars | Azure VM systemd/tmux process | Container Apps jobs |
| Secrets | Temporary chmod-600 env, then Key Vault | Azure Key Vault |
| Runtime DB/state | VM SQLite initially | Azure PostgreSQL |
| Artifacts/memory bundles | VM disk initially | Azure Blob Storage |
| Queue/bus | SQLite initially | Azure Service Bus |
| Docker images | VM local Docker | Azure Container Registry |
| Logs/metrics | VM logs initially | Azure Monitor + Log Analytics |
| CDN/WAF | Cloudflare optional | Cloudflare or Azure Front Door |
| Frontend dashboard | VM or Vercel | Vercel/Static Web Apps + API |

## Rules

- VM recovery can use local SQLite and local disk temporarily.
- Production must externalize state, secrets, artifacts, and logs.
- Secrets must be referenced by name only in prompts/specs/tasks.
- Any resource that bills continuously requires explicit operator approval.
