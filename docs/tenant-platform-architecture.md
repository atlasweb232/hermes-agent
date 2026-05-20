# Tenant Platform Architecture

## Purpose

Hermes must evolve from a single-user agent runtime into a tenant-aware
platform where organizations can onboard repositories, connect communication
channels, assign work, provision toolsets, observe faults/costs, and run
end-to-end production workflows with human approval points.

This document defines the first architecture for tenant onboarding and scaling.
It is intentionally a platform architecture, not only a code refactor.

The concrete local/dev DTO contract for this phase is
[`specs/001-learning-memory-runtime/contracts/tenant-onboarding.md`](../specs/001-learning-memory-runtime/contracts/tenant-onboarding.md).
That contract is the source of truth for registry, repo, connector, toolset,
runtime cell, budget, smoke, normalized message, connector verification, and
CI/CD packet shapes.

Azure production deployment orchestration is specified separately in
[`contracts/azure-production-deployment.md`](../specs/001-learning-memory-runtime/contracts/azure-production-deployment.md)
and
[`docs/azure-production-deployment-architecture.md`](azure-production-deployment-architecture.md).
Tenant runtime cell fields remain the compatibility boundary; Azure profiles
map them to Container Apps, Event Hubs Kafka, ADLS/Blob containers,
PostgreSQL/Cosmos state, Key Vault, Azure Monitor/Application Insights, and
network/DNS resources through the gated plan/preflight/approval workflow.

## Goals

- Onboard enterprise tenants and power users safely.
- Let tenants connect repositories and create jobs for backend agents.
- Isolate tenant runtime state, secrets, memory, worktrees, and communication
  channels.
- Support tenant communication through Slack, Telegram, WhatsApp, email, and
  future adapters.
- Provision platform toolsets such as planning, Spec Kit creation, code workers,
  QA/browser testing, TinyFish browser/API agent, deployment, and reporting.
- Run tenant workloads through the refactored Hermes supervisor, allocator,
  memory, sidecars, judge, and observability framework.
- Expose a global admin dashboard for tenant activity, faults, cost, latency,
  sidecar health, and operator interventions.
- Preserve traceability across new repos, new apps, code refactors, tests,
  deployments, and memory learning.

## Non-Goals For First Slice

- Do not build a full marketplace.
- Do not enable cross-tenant memory sharing by default.
- Do not auto-provision enforcement policies for tenants.
- Do not require Kafka, Delta Lake, vector DB, or graph DB for the first
  implementation. Start with interfaces and a local/dev adapter.
- Do not require one expensive supervisor model per tenant at idle.

## Core Architecture

### Control Plane

The shared control plane owns tenant metadata and routing:

- tenant registry
- user and role bindings
- repo registrations
- communication channel registrations
- toolset profiles
- runtime cell assignments
- job queue metadata
- cost/usage budgets
- feature toggle policies
- global admin observability

The control plane does not run arbitrary tenant code directly. It assigns work
to isolated runtime cells.

### Tenant Runtime Cell

A runtime cell is the execution boundary for a tenant or tenant workspace. It
contains:

- Hermes runtime home
- tenant-scoped `state.db` or configured database schema
- tenant memory and hot/warm cache
- worktree root
- allowed repo credentials
- communication adapter bindings
- toolset credentials
- worker allocation state
- sidecar leases
- audit/event spool

Initial deployment can use one container per tenant workspace. Later, small
tenants can share a pool if state, worktrees, secrets, and process execution are
strictly isolated.

### Global Services

Global services are shared but must enforce tenant boundaries:

- admin dashboard
- tenant registry API
- billing/cost telemetry
- global memory wiki service
- approved global lesson distribution
- model/provider credential broker
- object storage for redacted artifacts
- optional event bus
- optional vector/graph indexes

Global memory is opt-in and redacted. Tenant-private memory remains private.

## Per-Tenant Hermes Agent Strategy

Use a hybrid strategy:

1. **Dedicated runtime cell for enterprise tenants**
   - stronger isolation
   - easier audit
   - clearer cost attribution
   - better secret boundaries

2. **Pooled runtime cells for power users or low-risk tenants**
   - lower cost
   - shared warm workers
   - still separate tenant IDs, homes, worktrees, and secrets

3. **Ephemeral worker containers for jobs**
   - implementation workers run in short-lived worktrees/containers
   - supervisor state remains in the tenant runtime cell
   - large jobs can allocate multiple workers

The supervisor should be tenant-scoped. Sidecars may be tenant-local or global,
depending on the data they consume.

## Tenant Onboarding Flow

1. Create tenant.
2. Configure users, roles, and operator approval policy.
3. Connect communication channels.
4. Connect repositories.
5. Configure secrets and deploy keys.
6. Select toolset profile.
7. Select model profile and cost budget.
8. Select feature profile.
9. Provision runtime cell.
10. Run onboarding smoke tests.
11. Enable job submission.

## Repository Onboarding

Each repository registration records:

- `tenant_id`
- `repo_id`
- provider: GitHub, GitLab, Azure DevOps, local, other
- clone URL
- default branch
- allowed branches
- deployment environment mapping
- required secrets
- allowed toolsets
- Spec Kit path policy
- CI/CD policy
- code ownership and protected paths
- validation commands
- data sensitivity
- memory sharing policy

Repo onboarding must run a read-only preflight before any write-capable job.

## Job Assignment Flow

Jobs can originate from:

- dashboard
- Slack
- Telegram
- WhatsApp
- API
- scheduled trigger
- repository event

Every job becomes a supervisor task packet:

- tenant
- repo
- requester
- objective
- constraints
- expected artifacts
- approval requirements
- toolset profile
- model budget
- validation policy
- communication reply target
- memory policy

Non-trivial work must create or update Spec Kit artifacts before implementation
workers run.

## User-Agent Communication Model

Tenant users communicate with Hermes through a tenant front door, not by
directly controlling raw implementation workers.

Default message path:

```text
user -> connector -> tenant supervisor -> workers/tools -> supervisor -> connector -> user
```

Supported front doors:

- Slack channel, thread, or DM
- Telegram DM, group, or topic mode
- WhatsApp conversation
- dashboard chat
- API
- email/webhook

The connector is responsible for:

- authenticating the sender
- mapping the message to `tenant_id`, `user_id`, `channel_id`, and optional
  `repo_id` or `session_id`
- enforcing tenant allowlists and role permissions
- creating or resuming a supervisor session
- routing approval prompts
- routing progress summaries and final reports
- routing urgent/blocker notifications

The supervisor is responsible for:

- preserving master instructions
- creating task packets
- deciding whether Spec Kit is required
- delegating to workers
- validating outputs
- deciding what summary returns to the user

Raw worker streams are not sent to users by default. Users receive bounded
progress summaries, blocker notices, approval requests, and final reports.

Optional expert mode may expose a direct worker session, but it must be
tenant-scoped, audited, disabled by default, and unable to bypass supervisor
validation, repo ownership, secret policy, memory policy, or approval gates.

## Communication Adapters

Communication adapters are tenant connectors, not trusted supervisors.

Initial adapters:

- Slack
- Telegram
- WhatsApp
- email/webhook

Responsibilities:

- authenticate sender
- map channel/thread to tenant/user/session
- create task packet or append user message
- deliver summaries, blockers, approvals, and urgent alerts
- keep raw channel history out of supervisor context unless summarized

Each adapter must support:

- tenant allowlist
- channel allowlist
- urgent channel route
- approval route
- audit logging
- rate limits
- onboarding verification
- connector health checks
- message retry/dead-letter handling
- thread/session binding

Connector onboarding should be seamless from the operator perspective:

1. Operator provides connector credentials and target channels.
2. Hermes stores secret references, not raw values.
3. Hermes verifies bot/app identity and channel access.
4. Hermes sends a test message to the configured channel.
5. Hermes records the connector as active only after verification passes.
6. Tenant users can submit jobs from the configured channel/thread.

Connector implementations may differ, but they must normalize inbound messages
into the same tenant-scoped task/message envelope.

## Toolset Profiles

Toolsets are provisioned per tenant/repo/job:

- planner LLM
- Spec Kit creator
- Codex worker
- Claude Code worker
- DeepSeek/Cursor/other code workers
- QA/test worker
- TinyFish API agent
- TinyFish browser agent
- browser automation
- deployment tools
- CI/CD tools
- cloud provider tools
- repo tools such as git, gh, exa, ripgrep
- voice/image tools where configured

Toolset profiles define:

- enabled tools
- credential source
- allowed scopes
- network permissions
- cost tier
- approval requirements
- fallback workers

Skills are part of the toolset boundary. Tenant toolset profiles should declare
which skill scopes are available to each role, and should follow the skill
retrieval and bounded-injection rules in
[`skill-memory-pipeline-architecture.md`](./skill-memory-pipeline-architecture.md).

## CI/CD And Deployment Automation

CI/CD is a first-class toolset, not an afterthought. Hermes must be able to
create, inspect, repair, and run deployment pipelines when the tenant toolset
allows it.

Supported CI/CD targets:

- GitHub Actions
- GitLab CI
- Azure DevOps Pipelines
- Jenkins
- Buildkite
- container registry build pipelines
- cloud-native deployment pipelines

CI/CD tasks may include:

- create workflow files
- update build/test/deploy stages
- add manual dispatch workflows
- add artifact publishing
- add environment-specific secrets references
- add smoke-test jobs
- add rollback jobs
- add deployment approval gates
- diagnose failed pipeline runs
- compare local validation with CI failures
- produce release notes and deployment reports

CI/CD automation rules:

- non-trivial pipeline changes require Spec Kit artifacts
- secrets are referenced through the tenant secret backend, never committed
- protected branch and environment rules must be respected
- deployment jobs require tenant approval unless policy allows auto-deploy
- failed deployments create runtime failure records and urgent notifications
- pipeline creation must include a smoke-test or validation path

CI/CD worker packets must include:

- repository registration
- target branch
- CI/CD provider
- intended environments
- required secrets by reference
- artifact expectations
- validation commands
- rollback expectations
- approval requirements

The platform should treat CI/CD pipeline work as a production-grade workload
fixture in the E2E suite.

## Tenant Isolation

Minimum isolation requirements:

- separate tenant ID on every state row
- separate Hermes home or schema namespace
- separate worktree root
- separate secret namespace
- separate communication bindings
- separate cost ledger
- separate feature toggle policy
- separate memory visibility policy
- no raw cross-tenant retrieval

Enterprise mode should use separate containers and separate persistent volumes.

## Secrets

Secrets must not live in memory packets, wiki claims, dreaming proposals, or raw
chat transcripts.

Preferred secret backends:

- Azure Key Vault
- AWS Secrets Manager
- HashiCorp Vault
- Kubernetes secrets for short-lived dev
- encrypted local dev store only for single-user development

Tenant onboarding stores references, not values, in Hermes state.

## Memory And Learning

Tenant-local learning:

- raw events
- runtime failures
- candidates
- judge decisions
- approved memory
- memory wiki claims
- dreaming proposals
- policy audits

Dreaming proposals follow the tenant/local and global role boundaries in
[`dreaming-integration-architecture.md`](./dreaming-integration-architecture.md)
and the
[`dreaming-integration.md`](../specs/001-learning-memory-runtime/contracts/dreaming-integration.md)
contract.

Global learning:

- only redacted, approved, shareable lessons
- explicit tenant/operator approval
- global deduplication and conflict checks
- distributed back into tenant hot/warm memory only after relevance and
  sensitivity gates pass

The platform must maintain separation between:

- raw events
- curator candidates
- judge decisions
- approved memory
- wiki claims
- dreaming proposals
- training corpus records
- enforcement policies

Training corpus records are scoped by the MLOps corpus boundary in
[`lesser-model-mlops-architecture.md`](lesser-model-mlops-architecture.md)
and
[`mlops-corpus-remittance.md`](../specs/001-learning-memory-runtime/contracts/mlops-corpus-remittance.md).
Tenant runtime cells may produce only approved, redacted, shareable records for
Hermes corpus bundles and remittance receipts. External MLOps owns fine-tuning,
model registry, evaluation gates, serving, and rollout; tenant onboarding does
not grant Hermes authority to train, register, deploy, promote, or route to
fine-tuned models.

## Admin Dashboard

Global admin dashboard views:

- tenants
- active jobs
- historical jobs
- runtime cells
- worker health
- sidecar health
- communication connectors
- repo registrations
- blocked tasks
- urgent alerts
- cost by tenant/model/tool/job
- token/context usage
- memory candidate flow
- judge decisions
- policy audits
- deployment status

Tenant admins see only their tenant scope.

Dashboard DTOs should consume the tenant onboarding contract directly: tenant
registry rows, runtime cell assignments, connector registrations, repo
registrations, budget decisions, toolset profiles, and CI/CD packet status. The
dashboard must display bounded summaries and evidence refs, not raw connector
transcripts, credentials, worker streams, or unbounded logs.

## Cost And Budgeting

Every model/tool path must emit cost telemetry:

- tenant
- repo
- job
- model/provider
- worker role
- sidecar role
- tokens
- estimated cost
- latency
- retries
- fallback reason

Budgets can be set at:

- tenant
- repo
- project
- job
- sidecar
- model tier

Budget exhaustion should pause or degrade gracefully, not loop.

## Deployment Model

First deployable shape:

- control-plane API
- admin dashboard
- tenant runtime cell container image
- worker container image
- local SQLite/dev adapter
- optional Postgres production adapter
- optional object storage adapter
- communication gateway workers

Deployment surfaces must preserve the runtime cell fields from the onboarding
contract: `hermes_home`, `worktree_root`, `secret_namespace`,
`memory_namespace`, `connector_namespace`, `sidecar_namespace`, and
`cost_ledger_namespace`. Production orchestration can map those fields to
containers, volumes, schemas, and secret managers, but the local/dev contract
remains the compatibility boundary.

For the Azure target, that mapping is driven by the Phase 20 deployment
profile and the Terraform scaffold at
[`infra/azure/terraform/hermes-platform`](../infra/azure/terraform/hermes-platform).
Apply, production promotion, destroy, DNS cutover, and secret rotation remain
operator-approved operations; the tenant platform may request plans and
preflight reports but must not bypass those gates.

Scale-out shape:

- container orchestrator: Azure Container Apps, Kubernetes, ECS, or Cloud Run
- managed database
- object storage
- queue/event bus
- vector/graph services behind interfaces
- per-tenant runtime cell autoscaling
- worker pool autoscaling

## Message Bus

The architecture should support a Kafka-like bus, but not require it for MVP.

Adapters:

- local SQLite/event table
- Redis Streams
- Azure Service Bus
- Kafka/Redpanda
- cloud pub/sub

Use bus topics for:

- job submitted
- worker event
- sidecar event
- memory candidate
- judge decision
- notification
- cost telemetry
- runtime fault
- approval request

The bus is for decoupling and history. Supervisor context still receives only
bounded packets.

## Open Design Decisions

- Whether enterprise tenants always get one dedicated runtime cell or can choose
  pooled mode.
- Whether global admin can invoke tenant-scoped read-only Ask across all
  tenants by default or only with tenant approval.
- Which production event bus to use first.
- Which managed vector/graph stack to use after local interfaces are proven.
- How much onboarding should be self-service versus operator-assisted.
- Whether tenant-created apps/repos should live under tenant-owned orgs or a
  platform-managed org with strict ACLs.

## Recommended First Slice

1. Tenant registry schema and config.
2. Repo registration schema and preflight.
3. Communication connector registration schema.
4. Toolset profile schema.
5. Runtime cell assignment model.
6. Tenant-scoped job submission API/CLI.
7. Admin dashboard line-item DTOs.
8. Feature toggle and budget policy attachment to tenant.
9. E2E onboarding smoke fixture.

This is enough to test the platform shape without committing to Kafka,
Kubernetes, vector DB, or graph DB prematurely.
