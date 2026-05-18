# Production Topology Contract

## Purpose

Define the production target after Azure VM recovery is validated.

## Topology

```text
Cloudflare or Azure Front Door
  -> dashboard/frontend
  -> Azure Container Apps supervisor API
  -> Azure Container Apps worker services
  -> Azure Container Apps sidecar jobs
  -> Azure Service Bus
  -> Azure PostgreSQL
  -> Azure Blob Storage
  -> Azure Key Vault
  -> Azure Monitor / Log Analytics
```

## Services

### Supervisor API

- Runs Hermes supervisor runtime.
- Owns task graph, allocation state, runtime memory injection, and final
  validation authority.
- Stateless except external DB/storage references.

### Worker Services

- Run worker-router, Codex, Claude Code compatible dispatch, DeepSeek/Cursor
  adapters where available.
- Emit worker attempt results and heartbeats.
- Do not own completion authority.

### Sidecar Jobs

- Health sidecar
- Learning sidecar
- Curator
- Judge
- Memory wiki compiler
- Dreaming proposal generator
- Housekeeping

Sidecars must be independently scalable and bounded by leases/timeouts.

## Scaling

- Supervisor API scales on HTTP concurrency.
- Worker services scale on queue depth and CPU/memory.
- Sidecar jobs scale on scheduled/event triggers.
- Queue and DB are external managed services.

## Secrets

All secrets must be in Azure Key Vault or approved external secret manager:

- TinyFish API key
- IMAP host/port/user/password
- IONOS credentials
- model provider keys when not using OAuth
- deployment credentials

## CDN/WAF

Use Cloudflare unless Azure-only routing is required. Azure Front Door is
acceptable when tighter Azure-native integration is preferred.

## Production Gate

Do not cut over production until:

- VM recovery smoke passes
- provider registration is complete
- container image builds are reproducible
- Key Vault references are verified
- DB/storage migration path is tested
- worker fallback smoke passes
- dashboard/API health checks pass
