# Tenant Onboarding Contract

This contract defines the local/dev DTO shapes for Phase 16 tenant platform
onboarding. These schemas describe control-plane records and worker packets;
they do not imply external connector calls, cloud provisioning, Kafka, vector
databases, graph databases, or enforcement.

All records include:

- `schema_version`: integer, currently `1`
- `tenant_id`: tenant boundary for the record
- `kind`: packet or record kind
- `enforcement_allowed`: always `false` in this phase

State must store secret references, bounded summaries, evidence refs, and route
refs only. It must not store raw transcripts, channel logs, credentials, tokens,
or unbounded logs.

## Tenant Registry

Records the tenant status, users, roles, budgets, feature profile, runtime cell
assignment, and audit metadata.

```json
{
  "schema_version": 1,
  "kind": "tenant_registry",
  "tenant_id": "tenant-acme",
  "name": "Acme",
  "status": "onboarding",
  "isolation_mode": "dedicated",
  "users": [{"user_id": "u-admin", "role": "tenant_admin"}],
  "roles": ["tenant_admin"],
  "budgets": {
    "tokens": {"limit": 1000000, "used": 0},
    "models": {"limit": 100, "used": 0},
    "tools": {"limit": 500, "used": 0},
    "sidecars": {"limit": 50, "used": 0}
  },
  "feature_profile": {
    "profile_id": "features-basic",
    "enabled": ["runtime.task_graph"],
    "expert_mode": false
  },
  "runtime_cell_assignment": {
    "runtime_cell_id": "cell-acme",
    "status": "assigned"
  },
  "audit": {
    "created_by": "operator",
    "created_at": "2026-05-20T00:00:00Z"
  },
  "enforcement_allowed": false
}
```

## Repository Registration

Repository onboarding records provider refs, clone refs, branch policy,
protected paths, validation commands, deployment mapping, secret refs, Spec Kit
policy, and memory sharing policy. Preflight is read-only before write-capable
work is allowed.

```json
{
  "schema_version": 1,
  "kind": "repo_registration",
  "tenant_id": "tenant-acme",
  "repo_id": "repo-web",
  "status": "registered",
  "provider_ref": {"provider": "github", "installation_ref": "gh-install-1"},
  "clone_url": "https://github.com/acme/web.git",
  "branch_policy": {
    "default_branch": "main",
    "allowed_branches": ["main", "release/*"]
  },
  "protected_paths": [".github/workflows/*", "infra/prod/*"],
  "validation_commands": ["pytest -q", "npm test"],
  "deployment_mapping": {
    "production": {"environment": "prod", "approval_required": true}
  },
  "secret_refs": ["secret://tenant-acme/github/deploy-key"],
  "speckit_policy": {"required": true, "root": "specs/"},
  "memory_sharing_policy": {
    "tenant_private": true,
    "cross_tenant_shareable": false
  },
  "preflight": {"required": true, "status": "pending", "read_only": true},
  "enforcement_allowed": false
}
```

## Communication Connector

Connectors normalize Slack, Telegram, WhatsApp, dashboard, API, email, and
webhook traffic into one tenant message envelope. Registrations store route
metadata, allowlists, urgent routes, approval routes, and verification status.

```json
{
  "schema_version": 1,
  "kind": "connector_registration",
  "tenant_id": "tenant-acme",
  "connector_id": "slack-main",
  "platform": "slack",
  "status": "registered",
  "route_ref": {"team_ref": "T1", "bot_ref": "B1"},
  "allowlists": {
    "tenant_ids": ["tenant-acme"],
    "user_refs": ["U123"],
    "channel_refs": ["C123"]
  },
  "routes": {
    "urgent": {"channel_ref": "C-urgent"},
    "approval": {"channel_ref": "C-approvals"}
  },
  "verification": {
    "status": "pending",
    "external_call_performed": false
  },
  "raw_transcript_stored": false,
  "enforcement_allowed": false
}
```

### Tenant Message Envelope

Inbound connector messages become bounded, redacted envelopes. Unauthorized
senders or channels are rejected without storing raw message content.

```json
{
  "schema_version": 1,
  "kind": "tenant_message_envelope",
  "tenant_id": "tenant-acme",
  "connector_id": "slack-main",
  "platform": "slack",
  "sender_ref": "U123",
  "channel_ref": "C123",
  "thread_ref": "1700000000.0001",
  "repo_id": "repo-web",
  "session_id": null,
  "message_kind": "job_request",
  "body_summary": "Repair the deploy workflow using the registered repo policy.",
  "approval_context": {"approval_id": "appr-1", "required": true},
  "urgent": true,
  "status": "accepted",
  "rejection_reason": null,
  "raw_transcript_stored": false,
  "enforcement_allowed": false
}
```

## Connector Verification

Connector onboarding accepts credential secret refs only. Activation requires a
successful verification packet with an evidence ref.

```json
{
  "schema_version": 1,
  "kind": "connector_onboarding",
  "tenant_id": "tenant-acme",
  "connector_id": "telegram-main",
  "platform": "telegram",
  "status": "verification_pending",
  "credential_secret_refs": ["secret://tenant-acme/telegram/bot-token"],
  "provided_credentials_stored": false,
  "test_route": {"chat_ref": "tenant-admin-chat"},
  "verification": {
    "status": "pending",
    "access_succeeded": null,
    "test_message_required": true,
    "external_call_performed": false,
    "evidence_ref": null
  },
  "enforcement_allowed": false
}
```

After access succeeds:

```json
{
  "status": "active",
  "verification": {
    "status": "succeeded",
    "access_succeeded": true,
    "evidence_ref": "evidence://connector/telegram-main/smoke-1",
    "external_call_performed": false
  }
}
```

## Toolset Profile

Toolset profiles define worker roles, scopes, budgets, approval requirements,
and feature-toggle dependencies for planner, Spec Kit creator, code workers,
QA/browser, TinyFish API/browser, CI/CD, deployment, cloud, repo, voice, and
image tools.

```json
{
  "schema_version": 1,
  "kind": "toolset_profile",
  "tenant_id": "tenant-acme",
  "profile_id": "toolset-prod",
  "status": "active",
  "roles": {
    "planner": {"enabled": true},
    "speckit_creator": {"enabled": true},
    "code_worker": {"enabled": true},
    "qa_browser": {"enabled": true},
    "tinyfish_api": {"enabled": true},
    "tinyfish_browser": {"enabled": true},
    "cicd": {"enabled": true},
    "deployment": {"enabled": true},
    "cloud": {"enabled": false},
    "repo": {"enabled": true},
    "voice": {"enabled": false},
    "image": {"enabled": false}
  },
  "scopes": {"repos": ["repo-web"], "environments": ["staging"]},
  "budgets": {"tokens": 200000, "tool_calls": 200, "sidecars": 20},
  "approval_requirements": {
    "deployment": true,
    "protected_environment": true
  },
  "feature_toggle_deps": ["runtime.task_graph"],
  "enforcement_allowed": false
}
```

## Runtime Cell

Runtime cells isolate tenant homes, worktrees, secrets, memory, connectors,
sidecars, and cost ledgers. Pooled mode still requires separate namespaces.

```json
{
  "schema_version": 1,
  "kind": "runtime_cell_assignment",
  "tenant_id": "tenant-acme",
  "runtime_cell_id": "cell-acme",
  "status": "assigned",
  "isolation_mode": "dedicated",
  "hermes_home": "/srv/hermes/tenant-acme/cell-acme/home",
  "worktree_root": "/srv/hermes/tenant-acme/cell-acme/worktrees",
  "secret_namespace": "secret://tenant-acme/cell-acme",
  "memory_namespace": "memory://tenant-acme/cell-acme",
  "connector_namespace": "connector://tenant-acme/cell-acme",
  "sidecar_namespace": "sidecar://tenant-acme/cell-acme",
  "cost_ledger_namespace": "cost://tenant-acme/cell-acme",
  "state_ref": "/srv/hermes/tenant-acme/cell-acme/state.db",
  "enforcement_allowed": false
}
```

## Budget Decision

Budget helpers evaluate token, model, tool, and sidecar usage once and return a
pause/degrade/allow decision. They must not foreground sleep-loop.

```json
{
  "schema_version": 1,
  "kind": "tenant_budget_decision",
  "tenant_id": "tenant-acme",
  "usage": {
    "tokens": {"used": 1001, "limit": 1000, "remaining": 0}
  },
  "decision": "pause",
  "exhausted": ["tokens"],
  "degraded_capabilities": [],
  "loop_allowed": false,
  "next_action": "operator_review",
  "enforcement_allowed": false
}
```

## Feature Profile

Feature profiles reference runtime feature toggles and product capabilities. All
runtime-affecting features remain unavailable or disabled by default until an
operator explicitly enables them for a tenant/repo scope.

```json
{
  "profile_id": "features-basic",
  "enabled": ["runtime.task_graph"],
  "unavailable": ["direct_worker_chat", "policy_enforcement"],
  "expert_mode": false,
  "enforcement_allowed": false
}
```

## Smoke Schema

Tenant smoke tests should record only status and evidence refs.

```json
{
  "schema_version": 1,
  "kind": "tenant_onboarding_smoke",
  "tenant_id": "tenant-acme",
  "repo_id": "repo-web",
  "checks": {
    "repo_preflight": {"status": "passed", "evidence_ref": "evidence://repo/preflight-1"},
    "connector_reply_route": {"status": "passed", "evidence_ref": "evidence://connector/reply-1"},
    "toolset_available": {"status": "passed", "evidence_ref": "evidence://toolset/status-1"},
    "budget_policy": {"status": "passed", "evidence_ref": "evidence://budget/status-1"},
    "feature_profile": {"status": "passed", "evidence_ref": "evidence://features/status-1"},
    "runtime_cell_isolation": {"status": "passed", "evidence_ref": "evidence://cell/isolation-1"}
  },
  "raw_transcript_stored": false,
  "enforcement_allowed": false
}
```

## CI/CD Pipeline Packets

CI/CD task packets support workflow create, repair, run, validate, and report
operations. Packets must include Spec Kit refs, secret refs, protected
environment approvals, validation evidence refs, rollback expectations, and an
urgent failure notification route.

```json
{
  "schema_version": 1,
  "kind": "cicd_pipeline_task",
  "tenant_id": "tenant-acme",
  "repo_id": "repo-web",
  "task_kind": "workflow_repair",
  "speckit_refs": {
    "spec": "specs/001/spec.md",
    "plan": "specs/001/plan.md",
    "tasks": "specs/001/tasks.md"
  },
  "secret_refs": ["secret://tenant-acme/github/actions-token"],
  "protected_environment_approvals": [
    {"environment": "production", "required": true}
  ],
  "validation_evidence_refs": ["evidence://ci/run-1"],
  "rollback_expectations": {
    "strategy": "revert_workflow_change",
    "required": true
  },
  "urgent_failure_notification": {
    "connector_id": "slack-main",
    "route_ref": "C-urgent"
  },
  "worker_packet_shape": {
    "create": false,
    "repair": true,
    "run": false,
    "validate": false,
    "report": false
  },
  "raw_logs_stored": false,
  "enforcement_allowed": false
}
```
