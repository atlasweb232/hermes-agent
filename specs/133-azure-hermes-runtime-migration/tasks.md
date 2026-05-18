# Tasks: Azure Hermes Runtime Migration

## Phase 1: Preservation

- [x] T001 Record parent branch `132-learning-memory-runtime` and latest preserved commit.
- [x] T002 Create Azure migration Spec Kit branch `133-azure-hermes-runtime-migration`.
- [x] T003 Create service map, VM recovery, production topology, and smoke validation contracts.
- [ ] T004 Create a signed/tagged backup bundle or release marker for `132-learning-memory-runtime`.

## Phase 2: Azure Readiness

- [ ] T005 Register required Azure providers: `Microsoft.App`, `Microsoft.DBforPostgreSQL`, `Microsoft.ContainerRegistry`, and `Microsoft.KeyVault`.
- [ ] T006 Create resource group naming convention and region decision.
- [ ] T007 Add read-only Azure readiness command/script that reports account, quota, provider state, and blockers.
- [ ] T008 Decide initial VM SKU based on quota and expected workload.

## Phase 3: Azure VM Recovery

- [ ] T009 Create Azure VM deployment script or runbook with explicit approval gate.
- [ ] T010 Add VM bootstrap script for git, Python venv, Hermes install, Docker, ripgrep, TinyFish SDK, and smoke tools.
- [ ] T011 Add Claude Code settings copy/runbook without committing local settings file.
- [ ] T012 Add Codex manual auth runbook.
- [ ] T013 Add Key Vault or temporary secure env runbook for secret references.
- [ ] T014 Run VM recovery smoke and save report.

## Phase 4: Production Managed Services

- [ ] T015 Add Container Apps architecture implementation plan after VM smoke passes.
- [ ] T016 Add ACR image build plan for supervisor, workers, and sidecars.
- [ ] T017 Add Key Vault secret reference plan.
- [ ] T018 Add PostgreSQL state migration plan.
- [ ] T019 Add Blob Storage artifact/memory-bundle plan.
- [ ] T020 Add Service Bus queue/bus plan.
- [ ] T021 Add Azure Monitor/Log Analytics plan.
- [ ] T022 Add Cloudflare/Azure Front Door CDN/WAF decision.

## Phase 5: Production Smoke And Cutover

- [ ] T023 Add end-to-end smoke report template.
- [ ] T024 Run allocator fallback smoke in Azure.
- [ ] T025 Run TinyFish/IMAP smoke using secret references only.
- [ ] T026 Run dashboard/API health smoke.
- [ ] T027 Produce cutover checklist and rollback plan.

## Dependencies

- Phase 1 must be complete before any resource deployment.
- Phase 2 must be complete before Container Apps/PostgreSQL work.
- Phase 3 can proceed immediately with Compute provider.
- Phase 4 must wait for provider registration and VM smoke success.
- Phase 5 must wait for production topology implementation.
