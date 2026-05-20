import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

import pytest


TERRAFORM_SCAFFOLD = "infra/azure/terraform/hermes-platform"
_ENVIRONMENTS = {"dev", "staging", "production"}
_RUNTIME_MODES = {"container_apps", "vm", "aks"}
_BUS_BACKENDS = {"sqlite", "eventhubs_kafka", "redpanda", "kafka"}
_OBJECT_STORES = {"azure_blob", "adls_gen2"}
_STATE_STORES = {"sqlite", "postgres", "cosmos"}
_OBSERVABILITY_BACKENDS = {"hermes_local", "azure_monitor", "application_insights"}
_APPROVAL_FIELDS = {
    "apply": "required_for_apply",
    "promote": "required_for_promote",
    "destroy": "required_for_destroy",
    "dns": "required_for_dns",
    "secret_rotation": "required_for_secret_rotation",
}
_PREFLIGHT_CHECKS = (
    "subscription_visibility",
    "quota",
    "resource_providers",
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
)
_PROMOTION_REQUIREMENTS = (
    "staging_apply",
    "health",
    "event_bus",
    "sidecar",
    "memory_retrieval",
    "urgent_alert",
    "cost_latency",
    "no_foreground_blocking",
    "soak",
)
_SECRET_PATTERNS = (
    re.compile(r"\b[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|API_KEY)[A-Z0-9_]*=[^\s]+"),
    re.compile(r"secret://[^\s]+"),
)


def _copy_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(value or {})


@dataclass(frozen=True)
class AzureDeploymentProfile:
    profile_id: str
    environment: str
    subscription_id_ref: str
    tenant_id: str
    region: str
    resource_group: str
    runtime_cells: dict[str, Any]
    event_bus: dict[str, Any]
    storage: dict[str, Any]
    observability: dict[str, Any]
    network: dict[str, Any]
    iac: dict[str, Any]
    approval: dict[str, Any]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "AzureDeploymentProfile":
        return cls(
            profile_id=str(data.get("profile_id", "")),
            environment=str(data.get("environment", "")),
            subscription_id_ref=str(data.get("subscription_id_ref", "")),
            tenant_id=str(data.get("tenant_id", "")),
            region=str(data.get("region", "")),
            resource_group=str(data.get("resource_group", "")),
            runtime_cells=_copy_mapping(data.get("runtime_cells")),
            event_bus=_copy_mapping(data.get("event_bus")),
            storage=_copy_mapping(data.get("storage")),
            observability=_copy_mapping(data.get("observability")),
            network=_copy_mapping(data.get("network")),
            iac=_copy_mapping(data.get("iac")),
            approval=_copy_mapping(data.get("approval")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "environment": self.environment,
            "subscription_id_ref": self.subscription_id_ref,
            "tenant_id": self.tenant_id,
            "region": self.region,
            "resource_group": self.resource_group,
            "runtime_cells": dict(self.runtime_cells),
            "event_bus": dict(self.event_bus),
            "storage": dict(self.storage),
            "observability": dict(self.observability),
            "network": dict(self.network),
            "iac": dict(self.iac),
            "approval": dict(self.approval),
        }


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: list[str]
    normalized: dict[str, Any]


@dataclass(frozen=True)
class FakeAzureAdapter:
    subscription_visible: bool = True
    quota_ok: bool = True
    resource_providers_registered: bool = True
    key_vault_accessible: bool = True
    object_storage_accessible: bool = True
    state_store_ready: bool = True
    bus_ready: bool = True
    observability_workspace_ready: bool = True
    dns_network_ready: bool = True
    broker_health: bool = True
    topics: dict[str, bool] = field(default_factory=dict)
    lag_metrics: dict[str, int] = field(default_factory=dict)
    quota: dict[str, int] = field(default_factory=dict)
    cost_estimate: dict[str, int] = field(default_factory=dict)

    @classmethod
    def all_ready(cls, **overrides: Any) -> "FakeAzureAdapter":
        return cls(**overrides)


@dataclass(frozen=True)
class DeploymentPlan:
    profile_id: str
    read_only: bool
    resources: list[dict[str, Any]]
    unmanaged_resources: list[dict[str, Any]]
    iac_artifacts: list[dict[str, Any]]
    cost_estimate: dict[str, int]
    required_secret_refs: list[str]
    risks: list[str]
    smoke_tests: list[str]
    soak_tests: list[str]
    rollback_plan: dict[str, Any]
    approval_requirements: dict[str, Any]


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    checks: list[PreflightCheck]
    sqlite_fallback: str


@dataclass(frozen=True)
class ApprovalGateResult:
    allowed: bool
    fail_closed: bool
    reason: str
    approval_ref: str | None = None


@dataclass(frozen=True)
class BusReadinessReport:
    backend: str
    kafka_protocol: bool
    helper_template_ref: str
    broker_healthy: bool
    topics_verified: dict[str, bool]
    dead_letter_replay_ready: bool
    lag_metrics: dict[str, int]
    max_lag: int
    tls_sasl: dict[str, str]
    sqlite_spool_fallback: str
    ready: bool


@dataclass(frozen=True)
class PromotionGateResult:
    allowed: bool
    blockers: list[str]
    approval_ref: str | None = None


@dataclass(frozen=True)
class DeploymentStatus:
    run_id: str
    profile_id: str
    state: str
    sanitized_logs: list[str]
    rollback_refs: list[str]
    operator_actions: list[str]
    logs_sanitized: bool = True
    raw_logs_included: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "profile_id": self.profile_id,
            "state": self.state,
            "logs": list(self.sanitized_logs),
            "logs_sanitized": self.logs_sanitized,
            "raw_logs_included": self.raw_logs_included,
            "rollback_refs": list(self.rollback_refs),
            "operator_actions": list(self.operator_actions),
        }


def validate_deployment_profile(profile: AzureDeploymentProfile) -> ValidationResult:
    errors: list[str] = []
    data = profile.to_dict()

    if profile.environment not in _ENVIRONMENTS:
        errors.append("environment must be dev, staging, or production")
    if profile.runtime_cells.get("mode") not in _RUNTIME_MODES:
        errors.append("runtime_cells.mode must be container_apps, vm, or aks")
    if profile.event_bus.get("backend") not in _BUS_BACKENDS:
        errors.append("event_bus.backend must be sqlite, eventhubs_kafka, redpanda, or kafka")
    if profile.event_bus.get("fallback_spool") != "sqlite":
        errors.append("event_bus.fallback_spool must be sqlite")
    containers = profile.storage.get("containers") or {}
    for name in ("artifacts", "memory", "corpus", "audit"):
        if name not in containers:
            errors.append(f"storage.containers.{name} is required")
    if profile.storage.get("object_store") not in _OBJECT_STORES:
        errors.append("storage.object_store must be azure_blob or adls_gen2")
    if profile.storage.get("state_store") not in _STATE_STORES:
        errors.append("storage.state_store must be sqlite, postgres, or cosmos")
    if not profile.storage.get("key_vault"):
        errors.append("storage.key_vault is required")
    if profile.observability.get("backend") not in _OBSERVABILITY_BACKENDS:
        errors.append("observability.backend is invalid")
    if not profile.network.get("dns_zone_ref"):
        errors.append("network.dns_zone_ref is required")
    if profile.iac.get("format") not in {"terraform", "bicep"}:
        errors.append("iac.format must be terraform or bicep")
    if profile.iac.get("format") == "terraform" and profile.iac.get("artifact_root") != TERRAFORM_SCAFFOLD:
        errors.append("terraform profiles must target infra/azure/terraform/hermes-platform")
    for field_name in _APPROVAL_FIELDS.values():
        if profile.approval.get(field_name) is not True:
            errors.append(f"approval.{field_name} must be true")
    if profile.iac.get("apply_requires_approval") is not True:
        errors.append("iac.apply_requires_approval must be true")

    return ValidationResult(ok=not errors, errors=errors, normalized=data)


def build_deployment_plan(profile: AzureDeploymentProfile, adapter: FakeAzureAdapter) -> DeploymentPlan:
    validation = validate_deployment_profile(profile)
    if not validation.ok:
        raise ValueError("; ".join(validation.errors))

    resources = [
        {"class": "compute", "target": profile.runtime_cells["mode"]},
        {"class": "bus", "target": profile.event_bus["backend"]},
        {"class": "object_storage", "target": profile.storage["object_store"]},
        {"class": "state_store", "target": profile.storage["state_store"]},
        {"class": "secrets", "target": "azure_key_vault"},
        {"class": "observability", "target": profile.observability["backend"]},
        {"class": "network", "target": profile.network["public_gateway"]},
    ]
    return DeploymentPlan(
        profile_id=profile.profile_id,
        read_only=True,
        resources=resources,
        unmanaged_resources=[],
        iac_artifacts=[
            {
                "format": profile.iac["format"],
                "path": profile.iac.get("artifact_root", TERRAFORM_SCAFFOLD),
                "ref": f"iac://{profile.profile_id}/{profile.iac['format']}",
            }
        ],
        cost_estimate=adapter.cost_estimate or {"monthly_min_usd": 0, "monthly_max_usd": 0},
        required_secret_refs=[
            f"secret://azure/key-vault/{profile.storage['key_vault']}",
            profile.subscription_id_ref,
        ],
        risks=["live_apply_requires_operator_approval"],
        smoke_tests=["health", "event_bus", "sidecar", "memory_retrieval", "urgent_alert"],
        soak_tests=["cost_latency", "no_foreground_blocking"],
        rollback_plan={
            "rollback_ref": f"rollback://{profile.profile_id}/previous-known-good",
            "artifact_ref": f"iac://{profile.profile_id}/{profile.iac['format']}",
        },
        approval_requirements=dict(profile.approval),
    )


def run_preflight(
    profile: AzureDeploymentProfile,
    adapter: FakeAzureAdapter,
    plan: DeploymentPlan | None = None,
) -> PreflightResult:
    plan = plan or build_deployment_plan(profile, adapter)
    status_by_check = {
        "subscription_visibility": adapter.subscription_visible,
        "quota": adapter.quota_ok and bool(adapter.quota or profile.environment == "dev"),
        "resource_providers": adapter.resource_providers_registered,
        "key_vault": adapter.key_vault_accessible,
        "object_storage": adapter.object_storage_accessible,
        "state_store": adapter.state_store_ready,
        "bus": adapter.bus_ready,
        "observability_workspace": adapter.observability_workspace_ready,
        "dns_network": adapter.dns_network_ready,
        "required_secret_refs": all(
            str(ref).startswith(("secret://", "config://")) for ref in plan.required_secret_refs
        ),
        "cost_estimate": bool(plan.cost_estimate),
        "iac_artifact_refs": any(item.get("path") == TERRAFORM_SCAFFOLD for item in plan.iac_artifacts),
        "rollback_path": bool(plan.rollback_plan.get("rollback_ref")),
    }
    checks = [
        PreflightCheck(
            name=name,
            status="passed" if status_by_check[name] else "failed",
            detail="fake_adapter_check",
        )
        for name in _PREFLIGHT_CHECKS
    ]
    return PreflightResult(
        ok=all(check.status == "passed" for check in checks),
        checks=checks,
        sqlite_fallback=str(profile.event_bus.get("fallback_spool", "sqlite")),
    )


def evaluate_approval_gate(
    profile: AzureDeploymentProfile,
    *,
    operation: str,
    approval: Mapping[str, Any] | None,
) -> ApprovalGateResult:
    field_name = _APPROVAL_FIELDS.get(operation)
    if field_name is None:
        return ApprovalGateResult(False, True, "unknown_operation")
    if profile.approval.get(field_name) is not True:
        return ApprovalGateResult(False, True, "profile_approval_requirement_missing")
    if not approval or approval.get("approved") is not True or not approval.get("approval_id"):
        return ApprovalGateResult(False, True, "explicit_operator_approval_required")
    return ApprovalGateResult(
        True,
        False,
        "approved",
        approval_ref=f"approval://{approval['approval_id']}",
    )


def build_bus_readiness_report(
    profile: AzureDeploymentProfile,
    adapter: FakeAzureAdapter,
) -> BusReadinessReport:
    backend = str(profile.event_bus.get("backend", "sqlite"))
    topics = list(profile.event_bus.get("topics") or [])
    topics_verified = {topic: bool(adapter.topics.get(topic, False)) for topic in topics}
    deadletter_ready = topics_verified.get("deadletter.events", False)
    max_lag = max(adapter.lag_metrics.values()) if adapter.lag_metrics else 0
    helper = (
        "template://azure/eventhubs-kafka-helper"
        if backend == "eventhubs_kafka"
        else f"template://azure/{backend}-kafka-helper"
    )
    kafka_protocol = backend in {"eventhubs_kafka", "redpanda", "kafka"}
    tls_sasl = {
        "tls": "required" if backend != "sqlite" else "local",
        "sasl": "required" if backend in {"eventhubs_kafka", "redpanda", "kafka"} else "local",
    }
    return BusReadinessReport(
        backend=backend,
        kafka_protocol=kafka_protocol,
        helper_template_ref=helper,
        broker_healthy=adapter.broker_health,
        topics_verified=topics_verified,
        dead_letter_replay_ready=deadletter_ready,
        lag_metrics=dict(adapter.lag_metrics),
        max_lag=max_lag,
        tls_sasl=tls_sasl,
        sqlite_spool_fallback=str(profile.event_bus.get("fallback_spool", "sqlite")),
        ready=adapter.broker_health and all(topics_verified.values()) and deadletter_ready,
    )


def evaluate_promotion_gate(
    profile: AzureDeploymentProfile,
    evidence: Mapping[str, str],
    approval: Mapping[str, Any] | None,
) -> PromotionGateResult:
    blockers = [name for name in _PROMOTION_REQUIREMENTS if evidence.get(name) != "passed"]
    approval_result = evaluate_approval_gate(profile, operation="promote", approval=approval)
    if not approval_result.allowed:
        blockers.append("operator_approval_required")
    return PromotionGateResult(
        allowed=not blockers,
        blockers=blockers,
        approval_ref=approval_result.approval_ref,
    )


def _sanitize_log(line: str) -> str:
    sanitized = line
    for pattern in _SECRET_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    return sanitized


def build_deployment_status(
    *,
    run_id: str,
    profile: AzureDeploymentProfile,
    state: str,
    logs: list[str],
    rollback_refs: list[str],
    operator_actions: list[str],
) -> DeploymentStatus:
    return DeploymentStatus(
        run_id=run_id,
        profile_id=profile.profile_id,
        state=state,
        sanitized_logs=[_sanitize_log(line) for line in logs],
        rollback_refs=list(rollback_refs),
        operator_actions=list(operator_actions),
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
    sentinel = "REDACTED_VALUE_SHOULD_NOT_SURVIVE"
    status = build_deployment_status(
        run_id="deploy-1",
        profile=_profile("staging"),
        state="failed",
        logs=[
            f"terraform failed with ARM_CLIENT_SECRET={sentinel}",
            "see secret://azure/key-vault/kv-hermes-staging/HERMES_API_KEY",
        ],
        rollback_refs=["rollback://deploy-1/previous-known-good"],
        operator_actions=[
            "Review quota request evidence",
            "Re-run preflight after provider registration completes",
        ],
    )

    payload = status.to_dict()
    encoded = json.dumps(payload)
    assert sentinel not in encoded
    assert "ARM_CLIENT_SECRET" not in encoded
    assert "secret://azure/key-vault/kv-hermes-staging/HERMES_API_KEY" not in encoded
    assert "HERMES_API_KEY" not in encoded
    assert payload["logs_sanitized"] is True
    assert payload["rollback_refs"] == ["rollback://deploy-1/previous-known-good"]
    assert payload["operator_actions"] == [
        "Review quota request evidence",
        "Re-run preflight after provider registration completes",
    ]
    assert payload["raw_logs_included"] is False
