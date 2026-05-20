import json
import subprocess
import sys
from pathlib import Path

import pytest

from hermes_cli.azure_deployment import (
    TERRAFORM_SCAFFOLD,
    AzureDeploymentProfile,
    FakeAzureAdapter,
    azure_deploy_json,
    build_bus_readiness_report,
    build_deployment_plan,
    build_deployment_status,
    decide_deployment_action,
    deployment_helper_templates,
    evaluate_approval_gate,
    evaluate_promotion_gate,
    generate_smoke_checklist,
    generate_soak_checklist,
    load_deployment_profile,
    orchestrate_fake_staging_flow,
    run_preflight,
    validate_deployment_profile,
)


def _profile(environment: str = "staging", **overrides) -> AzureDeploymentProfile:
    data = {
        "profile_id": f"azure-{environment}-eastus",
        "environment": environment,
        "subscription_id_ref": "config://azure/subscription_id",
        "tenant_id": "tenant-atlas",
        "region": "eastus",
        "resource_group": f"rg-hermes-{environment}",
        "runtime_cells": {
            "mode": "container_apps",
            "isolation": "dedicated" if environment == "production" else "pooled",
            "min_instances": 1,
            "max_instances": 10,
        },
        "event_bus": {
            "backend": "eventhubs_kafka",
            "fallback_spool": "sqlite",
            "topics": [
                "learning.events",
                "runtime.events",
                "memory.sync",
                "deadletter.events",
            ],
        },
        "storage": {
            "object_store": "adls_gen2",
            "state_store": "postgres" if environment != "dev" else "sqlite",
            "key_vault": f"kv-hermes-{environment}",
            "containers": {
                "artifacts": "hermes-artifacts",
                "memory": "hermes-memory",
                "corpus": "hermes-corpus",
                "audit": "hermes-audit",
            },
        },
        "observability": {
            "backend": "application_insights",
            "log_retention_days": 30,
        },
        "network": {
            "private_ingress": environment == "production",
            "public_gateway": "frontdoor" if environment == "production" else "none",
            "dns_zone_ref": "config://dns/hermes-zone",
        },
        "iac": {
            "format": "terraform",
            "artifact_store": "azure_blob",
            "artifact_root": TERRAFORM_SCAFFOLD,
            "apply_requires_approval": True,
        },
        "approval": {
            "required_for_apply": True,
            "required_for_promote": True,
            "required_for_destroy": True,
            "required_for_dns": True,
            "required_for_secret_rotation": True,
        },
    }
    data.update(overrides)
    return AzureDeploymentProfile.from_mapping(data)


def test_deployment_profile_schema_covers_azure_resource_classes():
    for env in ("dev", "staging", "production"):
        result = validate_deployment_profile(_profile(env))
        assert result.ok, result.errors
        normalized = result.normalized
        assert normalized["environment"] == env
        assert normalized["runtime_cells"]["mode"] == "container_apps"
        assert normalized["event_bus"]["backend"] == "eventhubs_kafka"
        assert normalized["event_bus"]["fallback_spool"] == "sqlite"
        assert set(normalized["storage"]["containers"]) == {
            "artifacts",
            "memory",
            "corpus",
            "audit",
        }
        assert normalized["storage"]["object_store"] in {"azure_blob", "adls_gen2"}
        assert normalized["storage"]["state_store"] in {"sqlite", "postgres", "cosmos"}
        assert normalized["storage"]["key_vault"].startswith("kv-hermes-")
        assert normalized["observability"]["backend"] in {
            "azure_monitor",
            "application_insights",
        }
        assert normalized["network"]["dns_zone_ref"].startswith("config://")
        assert normalized["iac"]["format"] == "terraform"
        assert normalized["iac"]["artifact_root"] == TERRAFORM_SCAFFOLD
        assert normalized["approval"]["required_for_apply"] is True
        assert normalized["approval"]["required_for_promote"] is True

    alternate = _profile("production").to_dict()
    alternate["storage"] = {
        **alternate["storage"],
        "object_store": "azure_blob",
        "state_store": "cosmos",
    }
    alternate["observability"] = {
        **alternate["observability"],
        "backend": "azure_monitor",
    }
    result = validate_deployment_profile(AzureDeploymentProfile.from_mapping(alternate))
    assert result.ok, result.errors
    assert result.normalized["storage"]["object_store"] == "azure_blob"
    assert result.normalized["storage"]["state_store"] == "cosmos"
    assert result.normalized["observability"]["backend"] == "azure_monitor"


def test_plan_and_preflight_use_fake_adapter_and_cover_required_checks():
    profile = _profile("staging")
    adapter = FakeAzureAdapter.all_ready(
        quota={"container_apps": 20, "eventhubs": 2},
        cost_estimate={"monthly_min_usd": 120, "monthly_max_usd": 240},
    )

    plan = build_deployment_plan(profile, adapter)
    assert plan.read_only is True
    assert plan.iac_artifacts[0]["path"] == TERRAFORM_SCAFFOLD
    assert plan.iac_artifacts[0]["format"] == "terraform"
    assert plan.cost_estimate == {"monthly_min_usd": 120, "monthly_max_usd": 240}
    assert "secret://azure/key-vault/kv-hermes-staging" in plan.required_secret_refs
    assert plan.rollback_plan["rollback_ref"].startswith("rollback://")

    preflight = run_preflight(profile, adapter, plan)
    assert preflight.ok is True
    assert {check.name for check in preflight.checks} == {
        "subscription_visibility",
        "quota",
        "resource_providers",
        "account_identity",
        "resource_group",
        "key_vault",
        "object_storage",
        "state_store",
        "bus",
        "observability_workspace",
        "dns_network",
        "required_secret_refs",
        "cost_estimate",
        "iac_artifact_refs",
        "rollback_path",
    }
    assert all(check.status == "passed" for check in preflight.checks)
    assert "sqlite" in preflight.sqlite_fallback


@pytest.mark.parametrize(
    "operation",
    ["apply", "promote", "destroy", "dns", "secret_rotation"],
)
def test_approval_gates_fail_closed_without_explicit_operator_approval(operation):
    denied = evaluate_approval_gate(
        _profile("production"),
        operation=operation,
        approval={"approved": False, "operator": "alice"},
    )
    assert denied.allowed is False
    assert denied.fail_closed is True
    assert denied.reason == "explicit_operator_approval_required"

    missing = evaluate_approval_gate(_profile("production"), operation=operation, approval=None)
    assert missing.allowed is False
    assert missing.fail_closed is True

    allowed = evaluate_approval_gate(
        _profile("production"),
        operation=operation,
        approval={"approved": True, "approval_id": "approval-1", "operator": "alice"},
    )
    assert allowed.allowed is True
    assert allowed.approval_ref == "approval://approval-1"


def test_bus_deployment_readiness_covers_managed_and_helper_templates():
    adapter = FakeAzureAdapter.all_ready(
        broker_health=True,
        topics={
            "learning.events": True,
            "runtime.events": True,
            "memory.sync": True,
            "deadletter.events": True,
        },
        lag_metrics={"learning.events": 0, "runtime.events": 3},
    )

    eventhubs = build_bus_readiness_report(_profile("staging"), adapter)
    assert eventhubs.backend == "eventhubs_kafka"
    assert eventhubs.kafka_protocol is True
    assert eventhubs.broker_healthy is True
    assert eventhubs.topics_verified["deadletter.events"] is True
    assert eventhubs.dead_letter_replay_ready is True
    assert eventhubs.max_lag == 3
    assert eventhubs.tls_sasl["tls"] == "required"
    assert eventhubs.tls_sasl["sasl"] == "required"
    assert eventhubs.sqlite_spool_fallback == "sqlite"

    redpanda_profile = _profile(
        "staging",
        event_bus={
            "backend": "redpanda",
            "fallback_spool": "sqlite",
            "topics": ["learning.events", "runtime.events", "memory.sync", "deadletter.events"],
        },
    )
    redpanda = build_bus_readiness_report(redpanda_profile, adapter)
    assert redpanda.helper_template_ref.endswith("redpanda-kafka-helper")
    assert redpanda.kafka_protocol is True


def test_promotion_gate_requires_staging_smoke_soak_and_operational_evidence():
    evidence = {
        "staging_apply": "passed",
        "health": "passed",
        "event_bus": "passed",
        "sidecar": "passed",
        "memory_retrieval": "passed",
        "urgent_alert": "passed",
        "cost_latency": "passed",
        "no_foreground_blocking": "passed",
        "soak": "passed",
    }
    result = evaluate_promotion_gate(_profile("production"), evidence, approval=None)
    assert result.allowed is False
    assert result.blockers == ["operator_approval_required"]

    result = evaluate_promotion_gate(
        _profile("production"),
        {**evidence, "event_bus": "failed"},
        approval={"approved": True, "approval_id": "approval-1"},
    )
    assert result.allowed is False
    assert "event_bus" in result.blockers

    result = evaluate_promotion_gate(
        _profile("production"),
        evidence,
        approval={"approved": True, "approval_id": "approval-1"},
    )
    assert result.allowed is True


def test_failed_deployment_status_is_sanitized_and_includes_rollback_refs():
    status = build_deployment_status(
        run_id="deploy-1",
        profile=_profile("staging"),
        state="failed",
        logs=[
            "terraform failed while reading an operator-provided credential",
            "see secret://azure/key-vault/kv-hermes-staging/runtime",
        ],
        rollback_refs=["rollback://deploy-1/previous-known-good"],
        operator_actions=[
            "Review quota request evidence",
            "Re-run preflight after provider registration completes",
        ],
    )

    payload = status.to_dict()
    encoded = json.dumps(payload)
    assert "secret://azure/key-vault/kv-hermes-staging/runtime" not in encoded
    assert payload["logs_sanitized"] is True
    assert payload["rollback_refs"] == ["rollback://deploy-1/previous-known-good"]
    assert payload["operator_actions"] == [
        "Review quota request evidence",
        "Re-run preflight after provider registration completes",
    ]
    assert payload["raw_logs_included"] is False


def test_profile_loader_supports_explicit_sections_and_redacted_json(tmp_path):
    profile_path = tmp_path / "azure-profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "profile_id": "azure-staging-eastus",
                "environment": "staging",
                "subscription_id_ref": "config://azure/subscription_id",
                "tenant_id": "tenant-atlas",
                "region": "eastus",
                "resource_group": "rg-hermes-staging",
                "compute": {"mode": "container_apps", "min_instances": 1, "max_instances": 3},
                "bus": {
                    "backend": "eventhubs_kafka",
                    "fallback_spool": "sqlite",
                    "topics": ["learning.events", "deadletter.events"],
                },
                "object_storage": {
                    "backend": "adls_gen2",
                    "containers": {
                        "artifacts": "hermes-artifacts",
                        "memory": "hermes-memory",
                        "corpus": "hermes-corpus",
                        "audit": "hermes-audit",
                    },
                },
                "state_store": {"backend": "postgres"},
                "secrets": {"key_vault": "kv-hermes-staging", "client_secret": "inline-value"},
                "observability": {"backend": "application_insights"},
                "network": {"public_gateway": "none", "dns_zone_ref": "config://dns/hermes-zone"},
                "iac": {
                    "format": "terraform",
                    "artifact_root": TERRAFORM_SCAFFOLD,
                    "apply_requires_approval": True,
                },
                "approval": {
                    "required_for_apply": True,
                    "required_for_promote": True,
                    "required_for_destroy": True,
                    "required_for_dns": True,
                    "required_for_secret_rotation": True,
                },
            }
        ),
        encoding="utf-8",
    )

    profile = load_deployment_profile(profile_path)
    result = validate_deployment_profile(profile)
    assert result.ok, result.errors
    assert profile.compute["mode"] == "container_apps"
    assert profile.object_storage["backend"] == "adls_gen2"
    redacted = profile.to_redacted_json()
    assert "inline-value" not in redacted
    assert "[REDACTED]" in redacted


def test_plan_includes_resource_diff_and_no_live_artifact_generation():
    adapter = FakeAzureAdapter.all_ready(
        quota={"container_apps": 20},
        existing_resources=[
            {"class": "compute", "target": "vm"},
            {"class": "operator_owned", "target": "existing-vnet"},
        ],
    )

    plan = build_deployment_plan(_profile("staging"), adapter)
    compute = next(item for item in plan.resources if item["class"] == "compute")
    assert compute["action"] == "update"
    assert plan.unmanaged_resources == [{"class": "operator_owned", "target": "existing-vnet"}]
    assert plan.iac_artifacts[0]["terraform_first"] is True
    assert "dns_cutover_requires_separate_approval" in plan.risks


def test_apply_decision_records_are_immutable_and_plan_only():
    blocked = decide_deployment_action(_profile("staging"), action="apply", approval=None)
    assert blocked.allowed is False
    assert blocked.status == "blocked"
    assert blocked.run_record.action == "apply"

    approved = decide_deployment_action(
        _profile("staging"),
        action="apply",
        approval={"approved": True, "approval_id": "approval-1"},
    )
    assert approved.allowed is True
    assert approved.status == "approved_plan_only"
    assert approved.run_record.approval_ref == "approval://approval-1"

    live = decide_deployment_action(
        _profile("staging"),
        action="apply",
        approval={"approved": True, "approval_id": "approval-1"},
        live=True,
    )
    assert live.allowed is False
    assert live.reason == "live_apply_not_implemented"
    with pytest.raises(Exception):
        live.run_record.evidence_refs += ("evidence://new",)


def test_helper_templates_cover_required_azure_surfaces_without_live_creation():
    templates = deployment_helper_templates(_profile("production"))
    assert set(templates) == {
        "eventhubs_kafka",
        "redpanda_kafka",
        "kafka",
        "object_storage",
        "state_store",
        "key_vault",
        "observability",
        "network",
        "sqlite_spool",
    }
    assert all(template["creates_live_resources"] is False for template in templates.values())
    assert templates["sqlite_spool"]["fallback"] is True


def test_smoke_soak_checklists_feed_promotion_gate():
    smoke = generate_smoke_checklist(_profile("staging"))
    soak = generate_soak_checklist(_profile("staging"))
    assert {item["name"] for item in smoke["checks"]} == {
        "health",
        "event_bus",
        "sidecar",
        "memory_retrieval",
        "urgent_alert",
    }
    assert {item["name"] for item in soak["checks"]} == {
        "cost_latency",
        "no_foreground_blocking",
        "soak",
    }

    promotion = azure_deploy_json(
        "promote",
        profile=_profile("production"),
        evidence={item["name"]: "passed" for item in smoke["checks"] + soak["checks"]},
    )
    assert promotion["allowed"] is False
    assert "operator_approval_required" in promotion["blockers"]


def test_fake_adapter_e2e_staging_flow_blocks_production_promotion_without_approval():
    flow = orchestrate_fake_staging_flow(approval_id="approval-1")
    assert flow["plan"]["read_only"] is True
    assert flow["preflight"]["ok"] is True
    assert flow["apply"]["allowed"] is True
    assert flow["apply"]["run_record"]["approval_ref"] == "approval://approval-1"
    assert flow["smoke"]["checks"]
    assert flow["soak"]["checks"]
    assert flow["promote"]["allowed"] is False
    assert "operator_approval_required" in flow["promote"]["blockers"]


def test_cli_deploy_json_surfaces_default_to_fake_plan_only():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hermes_cli.main",
            "deploy",
            "apply",
            "--target",
            "azure",
        ],
        cwd=str(Path(__file__).resolve().parents[2]),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["allowed"] is False
    assert payload["status"] == "blocked"
    assert payload["reason"] == "explicit_operator_approval_required"
