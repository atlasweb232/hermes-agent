import json
import sys
from pathlib import Path

import pytest

from hermes_cli.tenant_platform import (
    TenantPlatformStore,
    activate_connector_onboarding,
    build_admin_dashboard_snapshot,
    build_cicd_pipeline_packet,
    build_cicd_toolset_profile,
    build_cicd_worker_packet,
    build_connector_onboarding,
    build_connector_registration,
    build_connector_route_packet,
    build_repo_preflight,
    build_repo_registration,
    build_runtime_cell_assignment,
    build_tenant_registry,
    build_tenant_smoke_fixture,
    build_tenant_supervisor_job_packet,
    build_toolset_profile,
    evaluate_tenant_budget,
    merge_toolset_profile,
    normalize_connector_message,
    stable_json,
)


def _roundtrip(payload):
    return json.loads(stable_json(payload))


def test_tenant_registry_schema_defaults_are_safe_and_deterministic():
    registry = build_tenant_registry(
        tenant_id="tenant-acme",
        name="Acme",
        users=[{"user_id": "u-admin", "role": "tenant_admin"}],
        budgets={"tokens": {"limit": 1000, "used": 100}, "models": {"limit": 20, "used": 1}},
        feature_profile={"profile_id": "features-basic", "enabled": ["runtime.task_graph"]},
        runtime_cell_id="cell-acme",
        audit={"created_by": "operator", "created_at": "2026-05-20T00:00:00Z"},
    )

    assert registry["schema_version"] == 1
    assert registry["status"] == "onboarding"
    assert registry["isolation_mode"] == "dedicated"
    assert registry["users"][0] == {"user_id": "u-admin", "role": "tenant_admin"}
    assert registry["budgets"]["tokens"]["limit"] == 1000
    assert registry["feature_profile"]["profile_id"] == "features-basic"
    assert registry["runtime_cell_assignment"]["runtime_cell_id"] == "cell-acme"
    assert registry["audit"]["created_by"] == "operator"
    assert registry["enforcement_allowed"] is False
    assert _roundtrip(registry)["tenant_id"] == "tenant-acme"


def test_repo_onboarding_schema_uses_secret_refs_and_policy_metadata_only():
    repo = build_repo_registration(
        tenant_id="tenant-acme",
        repo_id="repo-web",
        provider_ref={"provider": "github", "installation_ref": "gh-install-1"},
        clone_url="https://github.com/acme/web.git",
        branch_policy={"default_branch": "main", "allowed_branches": ["main", "release/*"]},
        protected_paths=[".github/workflows/*", "infra/prod/*"],
        validation_commands=["pytest -q", "npm test"],
        deployment_mapping={"production": {"environment": "prod", "approval_required": True}},
        secret_refs=["secret://tenant-acme/github/deploy-key"],
        speckit_policy={"required": True, "root": "specs/"},
        memory_sharing_policy={"tenant_private": True, "cross_tenant_shareable": False},
    )

    serialized = stable_json(repo)
    assert repo["provider_ref"]["provider"] == "github"
    assert repo["branch_policy"]["allowed_branches"] == ["main", "release/*"]
    assert repo["deployment_mapping"]["production"]["approval_required"] is True
    assert repo["secret_refs"] == ["secret://tenant-acme/github/deploy-key"]
    assert repo["speckit_policy"]["required"] is True
    assert repo["memory_sharing_policy"]["cross_tenant_shareable"] is False
    assert repo["enforcement_allowed"] is False
    assert "deploy-key-value" not in serialized


def test_connector_registration_and_normalized_envelopes_reject_unauthorized_senders():
    connector = build_connector_registration(
        tenant_id="tenant-acme",
        connector_id="slack-main",
        platform="slack",
        route_ref={"team_ref": "T1", "bot_ref": "B1"},
        allowed_users=["U123"],
        allowed_channels=["C123"],
        urgent_route={"channel_ref": "C-urgent"},
        approval_route={"channel_ref": "C-approvals"},
    )

    envelope = normalize_connector_message(
        connector,
        sender_ref="U123",
        channel_ref="C123",
        thread_ref="1700000000.0001",
        body=(
            "Please repair the deploy workflow. token=sk-test-secret raw transcript omitted. "
            "Include only a bounded operational summary for the tenant supervisor and do not store channel logs."
        ),
        repo_id="repo-web",
        message_kind="job_request",
        urgent=True,
        approval_context={"approval_id": "appr-1", "required": True},
    )

    assert envelope["tenant_id"] == "tenant-acme"
    assert envelope["connector_id"] == "slack-main"
    assert envelope["platform"] == "slack"
    assert envelope["repo_id"] == "repo-web"
    assert envelope["body_summary"].endswith("...")
    assert "sk-test-secret" not in stable_json(envelope)
    assert envelope["raw_transcript_stored"] is False
    assert envelope["approval_context"]["required"] is True
    assert envelope["urgent"] is True
    assert connector["enforcement_allowed"] is False

    rejected = normalize_connector_message(
        connector,
        sender_ref="U999",
        channel_ref="C123",
        thread_ref="1700000000.0002",
        body="hello",
        message_kind="chat",
    )
    assert rejected["status"] == "rejected"
    assert rejected["rejection_reason"] == "unauthorized_sender"
    assert rejected["raw_transcript_stored"] is False


def test_normalized_envelope_redacts_standalone_sk_secret_tokens():
    connector = build_connector_registration(
        tenant_id="tenant-acme",
        connector_id="slack-main",
        platform="slack",
        route_ref={"team_ref": "T1", "bot_ref": "B1"},
        allowed_users=["U123"],
        allowed_channels=["C123"],
        urgent_route={"channel_ref": "C-urgent"},
        approval_route={"channel_ref": "C-approvals"},
    )

    envelope = normalize_connector_message(
        connector,
        sender_ref="U123",
        channel_ref="C123",
        thread_ref="1700000000.0003",
        body="Tenant provided sk-secret-tenant-platform-token for setup verification.",
        message_kind="job_request",
    )

    serialized = stable_json(envelope)
    assert "sk-secret-tenant-platform-token" not in serialized
    assert "sk-secret" not in serialized
    assert "[REDACTED]" in envelope["body_summary"]


@pytest.mark.parametrize("platform", ["slack", "telegram", "whatsapp", "dashboard", "api", "email", "webhook"])
def test_connector_schemas_cover_supported_platforms(platform):
    connector = build_connector_registration(
        tenant_id="tenant-acme",
        connector_id=f"{platform}-main",
        platform=platform,
        route_ref={"route": f"{platform}-route"},
        allowed_users=["user-1"],
        allowed_channels=["channel-1"],
        urgent_route={"route": "urgent"},
        approval_route={"route": "approval"},
    )

    assert connector["platform"] == platform
    assert connector["status"] == "registered"
    assert connector["verification"]["status"] == "pending"
    assert connector["allowlists"]["tenant_ids"] == ["tenant-acme"]
    assert connector["routes"]["urgent"]["route"] == "urgent"
    assert connector["routes"]["approval"]["route"] == "approval"


def test_toolset_profile_covers_worker_roles_scopes_budgets_and_approvals():
    profile = build_toolset_profile(
        tenant_id="tenant-acme",
        profile_id="toolset-prod",
        roles={
            "planner": {"enabled": True},
            "speckit_creator": {"enabled": True},
            "code_worker": {"enabled": True},
            "qa_browser": {"enabled": True},
            "tinyfish_api": {"enabled": True},
            "tinyfish_browser": {"enabled": True},
            "cicd": {"enabled": True},
            "deployment": {"enabled": True},
            "cloud": {"enabled": False},
            "repo": {"enabled": True},
            "voice": {"enabled": False},
            "image": {"enabled": False},
        },
        scopes={"repos": ["repo-web"], "environments": ["staging"]},
        budgets={"tokens": 200000, "tool_calls": 200, "sidecars": 20},
        approval_requirements={"deployment": True, "protected_environment": True},
        feature_toggle_deps=["runtime.task_graph"],
    )

    assert set(profile["roles"]) >= {
        "planner",
        "speckit_creator",
        "code_worker",
        "qa_browser",
        "tinyfish_api",
        "tinyfish_browser",
        "cicd",
        "deployment",
        "cloud",
        "repo",
        "voice",
        "image",
    }
    assert profile["approval_requirements"]["protected_environment"] is True
    assert profile["feature_toggle_deps"] == ["runtime.task_graph"]
    assert profile["enforcement_allowed"] is False


def test_runtime_cell_isolation_namespaces_do_not_overlap_between_tenants():
    a = build_runtime_cell_assignment("tenant-a", "cell-a", root="/srv/hermes", isolation_mode="dedicated")
    b = build_runtime_cell_assignment("tenant-b", "cell-b", root="/srv/hermes", isolation_mode="pooled")

    keys = [
        "hermes_home",
        "worktree_root",
        "secret_namespace",
        "memory_namespace",
        "connector_namespace",
        "sidecar_namespace",
        "cost_ledger_namespace",
    ]
    assert all(a[key] != b[key] for key in keys)
    assert a["tenant_id"] == "tenant-a"
    assert b["tenant_id"] == "tenant-b"
    assert a["enforcement_allowed"] is False
    assert b["enforcement_allowed"] is False


def test_tenant_budget_exhaustion_pauses_or_degrades_without_looping():
    exhausted = evaluate_tenant_budget(
        tenant_id="tenant-acme",
        usage={
            "tokens": {"used": 1001, "limit": 1000},
            "models": {"used": 4, "limit": 10},
            "tools": {"used": 8, "limit": 10},
            "sidecars": {"used": 1, "limit": 2},
        },
    )
    degraded = evaluate_tenant_budget(
        tenant_id="tenant-acme",
        usage={
            "tokens": {"used": 900, "limit": 1000},
            "models": {"used": 10, "limit": 10},
            "tools": {"used": 8, "limit": 10},
            "sidecars": {"used": 1, "limit": 2},
        },
    )

    assert exhausted["decision"] == "pause"
    assert exhausted["loop_allowed"] is False
    assert "tokens" in exhausted["exhausted"]
    assert degraded["decision"] == "degrade"
    assert degraded["loop_allowed"] is False
    assert degraded["degraded_capabilities"] == ["models"]


def test_connector_onboarding_stores_secret_refs_and_activates_after_verified_access():
    onboarding = build_connector_onboarding(
        tenant_id="tenant-acme",
        connector_id="telegram-main",
        platform="telegram",
        credential_secret_refs=["secret://tenant-acme/telegram/bot-token"],
        test_route={"chat_ref": "tenant-admin-chat"},
        provided_credentials={"bot_token": "123456:raw-token-value", "api_key": "raw-api-key-value"},
    )
    serialized = stable_json(onboarding)

    assert onboarding["status"] == "verification_pending"
    assert onboarding["credential_secret_refs"] == ["secret://tenant-acme/telegram/bot-token"]
    assert onboarding["provided_credentials_stored"] is False
    assert onboarding["provided_credentials_received"] is True
    assert onboarding["provided_credentials_count"] == 2
    assert "provided_credentials_digest" not in onboarding
    assert "raw-token-value" not in serialized
    assert "raw-api-key-value" not in serialized

    failed = activate_connector_onboarding(onboarding, access_succeeded=False, evidence_ref="evidence://conn/fail")
    activated = activate_connector_onboarding(onboarding, access_succeeded=True, evidence_ref="evidence://conn/success")
    assert failed["status"] == "blocked"
    assert failed["verification"]["access_succeeded"] is False
    assert activated["status"] == "active"
    assert activated["verification"]["evidence_ref"] == "evidence://conn/success"


def test_cicd_pipeline_packets_include_safety_refs_for_all_task_kinds():
    for task_kind in ["workflow_create", "workflow_repair", "workflow_run", "workflow_validate", "workflow_report"]:
        packet = build_cicd_pipeline_packet(
            tenant_id="tenant-acme",
            repo_id="repo-web",
            task_kind=task_kind,
            speckit_refs={"spec": "specs/001/spec.md", "plan": "specs/001/plan.md", "tasks": "specs/001/tasks.md"},
            secret_refs=["secret://tenant-acme/github/actions-token"],
            protected_environment_approvals=[{"environment": "production", "required": True}],
            validation_evidence_refs=["evidence://ci/run-1"],
            rollback_expectations={"strategy": "revert_workflow_change", "required": True},
            urgent_failure_notification={"connector_id": "slack-main", "route_ref": "C-urgent"},
        )

        serialized = stable_json(packet)
        assert packet["task_kind"] == task_kind
        assert packet["speckit_refs"]["spec"].endswith("spec.md")
        assert packet["secret_refs"] == ["secret://tenant-acme/github/actions-token"]
        assert packet["protected_environment_approvals"][0]["required"] is True
        assert packet["validation_evidence_refs"] == ["evidence://ci/run-1"]
        assert packet["rollback_expectations"]["required"] is True
        assert packet["urgent_failure_notification"]["connector_id"] == "slack-main"
        assert packet["enforcement_allowed"] is False
        assert "actions-token-value" not in serialized


def test_tenant_platform_store_persists_records_by_tenant_and_kind(tmp_path):
    store = TenantPlatformStore(tmp_path / "state.db")
    tenant = build_tenant_registry(
        tenant_id="tenant-acme",
        name="Acme",
        users=[{"user_id": "u-admin", "role": "tenant_admin"}],
        budgets={"tokens": {"limit": 1000, "used": 0}},
        feature_profile={"profile_id": "features-basic", "enabled": ["runtime.task_graph"]},
        runtime_cell_id="cell-acme",
        audit={"created_by": "operator", "created_at": "2026-05-20T00:00:00Z"},
    )
    other = build_tenant_registry(
        tenant_id="tenant-other",
        name="Other",
        users=[],
        budgets={},
        feature_profile={"profile_id": "features-basic", "enabled": []},
        runtime_cell_id="cell-other",
        audit={"created_by": "operator", "created_at": "2026-05-20T00:00:00Z"},
    )

    store.save_record(tenant)
    store.save_record(other)

    assert store.get_record("tenant-acme", "tenant_registry")["name"] == "Acme"
    assert [row["tenant_id"] for row in store.list_records("tenant_registry")] == [
        "tenant-acme",
        "tenant-other",
    ]
    assert [row["tenant_id"] for row in store.list_records("tenant_registry", tenant_id="tenant-acme")] == [
        "tenant-acme"
    ]
    assert store.get_record("tenant-acme", "tenant_registry")["enforcement_allowed"] is False
    store.close()


def test_repo_preflight_is_read_only_and_uses_registered_repo_metadata(tmp_path):
    store = TenantPlatformStore(tmp_path / "state.db")
    repo = build_repo_registration(
        tenant_id="tenant-acme",
        repo_id="repo-web",
        provider_ref={"provider": "github", "installation_ref": "gh-install-1"},
        clone_url="https://github.com/acme/web.git",
        branch_policy={"default_branch": "main", "allowed_branches": ["main"]},
        protected_paths=[".github/workflows/*"],
        validation_commands=["pytest -q"],
        deployment_mapping={"production": {"environment": "prod", "approval_required": True}},
        secret_refs=["secret://tenant-acme/github/deploy-key"],
        speckit_policy={"required": True, "root": "specs/"},
        memory_sharing_policy={"tenant_private": True, "cross_tenant_shareable": False},
    )
    store.save_record(repo)

    preflight = build_repo_preflight(store.get_record("tenant-acme", "repo_registration", "repo-web"))

    assert preflight["kind"] == "repo_preflight"
    assert preflight["read_only"] is True
    assert preflight["checks"]["clone_url_present"] is True
    assert preflight["checks"]["validation_commands_present"] is True
    assert preflight["mutation_performed"] is False
    assert preflight["status"] == "passed"
    assert preflight["enforcement_allowed"] is False
    store.close()


def test_toolset_merge_applies_job_overrides_without_mutating_profile():
    profile = build_toolset_profile(
        tenant_id="tenant-acme",
        profile_id="toolset-prod",
        roles={"planner": {"enabled": True}, "cloud": {"enabled": False}},
        scopes={"repos": ["repo-web"], "environments": ["staging"]},
        budgets={"tokens": 200000, "tool_calls": 200},
        approval_requirements={"deployment": True},
        feature_toggle_deps=["runtime.task_graph"],
    )

    merged = merge_toolset_profile(
        profile,
        {
            "roles": {"cloud": {"enabled": False, "reason": "disabled locally"}},
            "scopes": {"environments": ["staging", "preview"]},
            "budgets": {"tokens": 50000},
            "approval_requirements": {"protected_environment": True},
        },
    )

    assert merged["kind"] == "toolset_profile_resolved"
    assert merged["roles"]["cloud"]["reason"] == "disabled locally"
    assert merged["scopes"]["environments"] == ["staging", "preview"]
    assert merged["budgets"]["tokens"] == 50000
    assert merged["approval_requirements"]["deployment"] is True
    assert merged["approval_requirements"]["protected_environment"] is True
    assert profile["budgets"]["tokens"] == 200000


def test_runtime_cell_supports_dedicated_and_pooled_isolation_metadata():
    dedicated = build_runtime_cell_assignment("tenant-acme", "cell-acme", root="/tmp/hermes", isolation_mode="dedicated")
    pooled = build_runtime_cell_assignment("tenant-acme", "pool-a", root="/tmp/hermes", isolation_mode="pooled")

    assert dedicated["isolation"]["mode"] == "dedicated"
    assert dedicated["isolation"]["tenant_namespace"] == "tenant-acme"
    assert pooled["isolation"]["mode"] == "pooled"
    assert pooled["isolation"]["pooled"] is True
    assert pooled["isolation"]["tenant_namespace"] == "tenant-acme"
    assert dedicated["hermes_home"] != pooled["hermes_home"]


def test_tenant_job_packet_feeds_supervisor_task_shape_with_spec_refs():
    packet = build_tenant_supervisor_job_packet(
        tenant_id="tenant-acme",
        repo_id="repo-web",
        connector_id="slack-main",
        request_summary="Repair deploy workflow",
        speckit_refs={"spec": "specs/001/spec.md", "plan": "specs/001/plan.md", "tasks": "specs/001/tasks.md"},
        runtime_cell_id="cell-acme",
        toolset_profile_id="toolset-prod",
        source="connector",
    )

    assert packet["kind"] == "tenant_job_submission"
    assert packet["supervisor_task_packet"]["tenant_id"] == "tenant-acme"
    assert packet["supervisor_task_packet"]["repo_id"] == "repo-web"
    assert packet["supervisor_task_packet"]["requires_speckit"] is True
    assert packet["supervisor_task_packet"]["status"] == "intake"
    assert packet["supervisor_task_path"] == "hermes_cli.runtime_packets.SupervisorTaskPacket"
    assert packet["speckit_refs"]["tasks"].endswith("tasks.md")
    assert packet["raw_transcript_stored"] is False


def test_admin_dashboard_snapshot_covers_required_tenant_platform_panels(tmp_path):
    store = TenantPlatformStore(tmp_path / "state.db")
    tenant = build_tenant_registry(
        tenant_id="tenant-acme",
        name="Acme",
        users=[],
        budgets={"tokens": {"limit": 1000, "used": 10}},
        feature_profile={"profile_id": "features-basic", "enabled": []},
        runtime_cell_id="cell-acme",
        audit={"created_by": "operator", "created_at": "2026-05-20T00:00:00Z"},
    )
    cell = build_runtime_cell_assignment("tenant-acme", "cell-acme", root=str(tmp_path), isolation_mode="dedicated")
    connector = build_connector_registration(
        tenant_id="tenant-acme",
        connector_id="slack-main",
        platform="slack",
        route_ref={"team_ref": "T1"},
        allowed_users=["U1"],
        allowed_channels=["C1"],
        urgent_route={"channel_ref": "C-urgent"},
        approval_route={"channel_ref": "C-approval"},
    )
    for record in [tenant, cell, connector]:
        store.save_record(record)

    snapshot = build_admin_dashboard_snapshot(
        store,
        tenant_id="tenant-acme",
        jobs=[{"job_id": "job-1", "status": "intake"}],
        faults=[{"fault_id": "fault-1", "severity": "low"}],
        worker_health=[{"worker_id": "worker-1", "status": "idle"}],
        sidecar_health=[{"sidecar_id": "sidecar-1", "status": "skipped"}],
        cost=[{"ledger": "cost://tenant-acme/cell-acme", "used": 0}],
        memory_flow=[{"stage": "prefetch", "status": "skipped"}],
        urgent_alerts=[{"route": "C-urgent", "status": "not_sent"}],
    )

    assert snapshot["kind"] == "tenant_admin_dashboard"
    for key in [
        "tenants",
        "runtime_cells",
        "connectors",
        "repos",
        "jobs",
        "faults",
        "worker_health",
        "sidecar_health",
        "cost",
        "memory_flow",
        "urgent_alerts",
    ]:
        assert key in snapshot
    assert snapshot["tenants"][0]["tenant_id"] == "tenant-acme"
    assert snapshot["urgent_alerts"][0]["status"] == "not_sent"
    store.close()


def test_e2e_smoke_fixture_submits_connector_job_with_isolated_runtime_state(tmp_path):
    store = TenantPlatformStore(tmp_path / "state.db")
    smoke = build_tenant_smoke_fixture(
        store,
        tenant_id="tenant-acme",
        repo_id="repo-web",
        connector_id="slack-main",
        root=str(tmp_path / "cells"),
        speckit_refs={"spec": "specs/001/spec.md", "plan": "specs/001/plan.md", "tasks": "specs/001/tasks.md"},
    )

    assert smoke["kind"] == "tenant_onboarding_smoke"
    assert smoke["status"] == "passed"
    assert smoke["tenant"]["tenant_id"] == "tenant-acme"
    assert smoke["connector_envelope"]["status"] == "accepted"
    assert smoke["job_packet"]["supervisor_task_packet"]["tenant_id"] == "tenant-acme"
    assert smoke["runtime_cell"]["hermes_home"].startswith(str(tmp_path / "cells"))
    assert smoke["isolation"]["tenant_scoped_state"] is True
    assert smoke["raw_transcript_stored"] is False
    store.close()


def test_connector_route_packets_cover_reply_approval_and_urgent_routes():
    connector = build_connector_registration(
        tenant_id="tenant-acme",
        connector_id="slack-main",
        platform="slack",
        route_ref={"team_ref": "T1"},
        allowed_users=["U1"],
        allowed_channels=["C1"],
        urgent_route={"channel_ref": "C-urgent"},
        approval_route={"channel_ref": "C-approval"},
    )

    reply = build_connector_route_packet(connector, route_kind="reply", message_ref="msg-1", body_summary="Done")
    approval = build_connector_route_packet(connector, route_kind="approval", message_ref="msg-1", body_summary="Approve?")
    urgent = build_connector_route_packet(connector, route_kind="urgent", message_ref="msg-1", body_summary="Failed")

    assert reply["kind"] == "tenant_reply_route"
    assert approval["kind"] == "tenant_approval_route"
    assert urgent["kind"] == "tenant_urgent_route"
    assert approval["route_ref"]["channel_ref"] == "C-approval"
    assert urgent["route_ref"]["channel_ref"] == "C-urgent"
    assert all(packet["raw_transcript_stored"] is False for packet in [reply, approval, urgent])


def test_cicd_toolset_and_worker_packets_cover_pipeline_worker_shape():
    profile = build_cicd_toolset_profile(
        tenant_id="tenant-acme",
        profile_id="toolset-ci",
        repo_ids=["repo-web"],
        protected_environments=["production"],
    )
    packet = build_cicd_worker_packet(
        tenant_id="tenant-acme",
        repo_id="repo-web",
        task_kind="workflow_repair",
        workflow_ref=".github/workflows/deploy.yml",
        speckit_refs={"spec": "specs/001/spec.md", "plan": "specs/001/plan.md", "tasks": "specs/001/tasks.md"},
        secret_refs=["secret://tenant-acme/github/actions-token"],
        protected_environment_approvals=[{"environment": "production", "required": True, "status": "pending"}],
        validation_evidence_refs=["evidence://ci/preflight"],
        rollback_expectations={"strategy": "revert_workflow_change", "required": True},
        urgent_failure_notification={"connector_id": "slack-main", "route_ref": "C-urgent"},
    )

    assert profile["roles"]["cicd"]["enabled"] is True
    assert profile["approval_requirements"]["protected_environment"] is True
    assert packet["kind"] == "cicd_worker_packet"
    assert packet["pipeline_packet"]["task_kind"] == "workflow_repair"
    assert packet["worker_packet_shape"]["repair"] is True
    assert packet["protected_environment_approvals"][0]["status"] == "pending"
    assert "actions-token-value" not in stable_json(packet)


def test_tenant_cli_json_surfaces_are_local_and_deterministic(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from hermes_cli import main as main_mod

    def run_cli(*argv):
        monkeypatch.setattr(sys, "argv", ["hermes", *argv])
        main_mod.main()
        return json.loads(capsys.readouterr().out)

    created = run_cli("tenant", "create", "tenant-acme", "--name", "Acme", "--json")
    assert created["kind"] == "tenant_registry"
    assert created["tenant_id"] == "tenant-acme"

    status = run_cli("tenant", "status", "tenant-acme", "--json")
    assert status["tenant"]["name"] == "Acme"

    repo = run_cli(
        "tenant",
        "repo",
        "add",
        "tenant-acme",
        "repo-web",
        "--clone-url",
        "https://github.com/acme/web.git",
        "--json",
    )
    assert repo["kind"] == "repo_registration"
    assert repo["repo_id"] == "repo-web"

    preflight = run_cli("tenant", "repo", "preflight", "tenant-acme", "repo-web", "--json")
    assert preflight["read_only"] is True
    assert preflight["mutation_performed"] is False

    connector = run_cli(
        "tenant",
        "connector",
        "add",
        "tenant-acme",
        "slack-main",
        "--platform",
        "slack",
        "--json",
    )
    assert connector["platform"] == "slack"

    connector_status = run_cli("tenant", "connector", "status", "tenant-acme", "slack-main", "--json")
    assert connector_status["connector_id"] == "slack-main"

    toolset = run_cli("tenant", "toolset", "set", "tenant-acme", "toolset-prod", "--json")
    assert toolset["profile_id"] == "toolset-prod"

    toolset_status = run_cli("tenant", "toolset", "status", "tenant-acme", "toolset-prod", "--json")
    assert toolset_status["profile_id"] == "toolset-prod"

    smoke = run_cli("tenant", "smoke", "tenant-acme", "--json")
    assert smoke["status"] == "passed"
    assert smoke["job_packet"]["supervisor_task_packet"]["tenant_id"] == "tenant-acme"
    assert Path(tmp_path / "state.db").exists()
