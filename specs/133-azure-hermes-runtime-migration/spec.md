# Feature Specification: Azure Hermes Runtime Migration

**Branch**: `133-azure-hermes-runtime-migration`

**Parent**: `132-learning-memory-runtime`

**Input**: Preserve the Hermes runtime learning, allocator, memory, TinyFish, and
production smoke work from the AWS VM path, then define a migration plan to
deploy equivalent services on Azure without losing history, secrets discipline,
or runtime observability.

## User Story 1 - Preserve Current Hermes Work (Priority: P1)

As the operator, I want all current Hermes runtime work preserved before any
cloud migration, so the Azure deployment starts from the known branch history
and not from an ad hoc VM copy.

**Acceptance Scenarios**:

1. **Given** the current runtime branch, **When** migration planning starts,
   **Then** the branch parent and latest commits are recorded.
2. **Given** VM-specific setup exists, **When** it is migrated, **Then** all
   reusable pieces become scripts, docs, containers, or config references.
3. **Given** secrets are required, **When** migration artifacts are created,
   **Then** raw secrets are not written to git, memory, logs, or prompts.

## User Story 2 - Recreate AWS VM Capabilities On Azure (Priority: P2)

As the operator, I want the lost AWS VM services mapped to Azure equivalents, so
Hermes can run the same agent workflows with a clearer production path.

**Acceptance Scenarios**:

1. **Given** Hermes requires CLI tools and long-running workers, **When** the
   first Azure environment is created, **Then** an Azure VM can run Hermes,
   Codex, Claude Code, TinyFish SDK, worker-router tooling, and optional Ollama.
2. **Given** production deployment needs scale, **When** container providers are
   registered, **Then** Container Apps, ACR, Key Vault, PostgreSQL, Blob Storage,
   Service Bus, and Monitor are available in the target resource group.
3. **Given** traffic spikes up to at least 1,000 users, **When** the production
   path is selected, **Then** CDN/WAF and autoscaling worker/API services are
   part of the topology.

## User Story 3 - Test Migration Value Before Full Production Cutover (Priority: P3)

As the operator, I want deterministic smoke tests before full migration, so we
prove the Azure environment preserves runtime degradation handling, allocator
fallback, TinyFish readiness, and secret references.

**Acceptance Scenarios**:

1. **Given** an Azure VM or Container App environment, **When** runtime smoke
   runs, **Then** `hermes runtime smoke compare --no-upstream --json` passes.
2. **Given** Claude Code or another primary worker degrades, **When** allocation
   smoke runs, **Then** fallback or pause is recorded through runtime allocation
   observability.
3. **Given** TinyFish/IMAP/deployment secrets are referenced, **When** secret
   checks run, **Then** only secret metadata is checked and values are never
   printed.

## Functional Requirements

- **FR-001**: Migration MUST branch from `132-learning-memory-runtime`.
- **FR-002**: Migration MUST preserve commit history and document parent branch.
- **FR-003**: Azure setup MUST start with a VM recovery path before Container
  Apps productionization.
- **FR-004**: Production topology MUST support API, workers, sidecars, dashboard,
  queue, state DB, object storage, secrets, logs, and CDN/WAF.
- **FR-005**: Secrets MUST move to Azure Key Vault or another approved managed
  secret store; raw secrets MUST NOT be committed.
- **FR-006**: AWS service equivalents MUST be documented.
- **FR-007**: Deployment scripts MUST be idempotent and safe to rerun.
- **FR-008**: Smoke tests MUST validate Hermes commit, runtime allocator,
  Claude/Codex availability, TinyFish readiness, and secret references.
- **FR-009**: Container Apps work MUST wait until providers are registered and VM
  recovery smoke passes.
- **FR-010**: CDN/WAF choice MUST be Cloudflare or Azure Front Door, with
  Cloudflare preferred for DNS/WAF speed unless Azure-only is required.

## Key Entities

- **Azure Recovery VM**: Initial VM replacement for the lost AWS instance.
- **Azure Production Resource Group**: Resource group containing Container Apps,
  ACR, Key Vault, PostgreSQL, Blob Storage, Service Bus, and Monitor.
- **Hermes Runtime Service**: API/supervisor container or VM process.
- **Hermes Worker Service**: Worker-router/Codex/Claude/DeepSeek execution
  container or VM process.
- **Hermes Sidecar Service**: Learning, health, memory, curator, judge, and
  dreaming background processes.
- **Secret Reference**: Key Vault secret name or external secret ref; never raw
  value.
- **Migration Smoke Report**: JSON evidence showing runtime readiness and gaps.

## Success Criteria

- **SC-001**: Current branch commit is pushed and recorded as migration parent.
- **SC-002**: Azure VM plan can recreate the Hermes VM runtime without raw
  secrets in git.
- **SC-003**: Production topology maps every AWS VM-era service to an Azure or
  CDN equivalent.
- **SC-004**: Smoke tests can be run before production cutover.
- **SC-005**: Container Apps production implementation is gated behind provider
  registration and VM smoke success.

## Assumptions

- Current Azure subscription is Pay-As-You-Go and enabled.
- East US currently has 10 regional vCPUs available.
- Microsoft.Compute is registered.
- Microsoft.App and Microsoft.DBforPostgreSQL may require registration before
  Container Apps/PostgreSQL deployment.
- The operator may use Cloudflare, Azure Front Door, Vercel, or Hostinger for
  edge/frontend concerns, but Hermes runtime workers need Azure VM/containers.
