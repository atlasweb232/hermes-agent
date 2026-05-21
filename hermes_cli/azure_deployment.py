"""Safe Azure deployment orchestration helpers.

This module is intentionally local/fake by default. It builds plans,
preflight reports, gated decisions, and append-safe run records without
creating Azure resources or requiring Azure login.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


TERRAFORM_SCAFFOLD = "infra/azure/terraform/hermes-platform"

ENVIRONMENTS = {"dev", "staging", "production"}
RUNTIME_MODES = {"container_apps", "vm", "aks"}
BUS_BACKENDS = {"sqlite", "eventhubs_kafka", "redpanda", "kafka"}
OBJECT_STORES = {"azure_blob", "adls_gen2"}
STATE_STORES = {"sqlite", "postgres", "cosmos"}
OBSERVABILITY_BACKENDS = {"hermes_local", "azure_monitor", "application_insights"}
APPROVAL_FIELDS = {
    "apply": "required_for_apply",
    "promote": "required_for_promote",
    "destroy": "required_for_destroy",
    "dns": "required_for_dns",
    "secret_rotation": "required_for_secret_rotation",
}
PREFLIGHT_CHECKS = (
    "account_identity",
    "subscription_visibility",
    "quota",
    "resource_providers",
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
)
PROMOTION_REQUIREMENTS = (
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
SMOKE_CHECKS = ("health", "event_bus", "sidecar", "memory_retrieval", "urgent_alert")
SOAK_CHECKS = ("cost_latency", "no_foreground_blocking", "soak")

_SECRET_PATTERNS = (
    re.compile(r"\b[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|API_KEY)[A-Z0-9_]*=[^\s]+"),
    re.compile(r"secret://[^\s\"']+"),
    re.compile(r"\b(?:ARM|AZURE)_[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|API_KEY)[A-Z0-9_]*\b"),
)
_SENSITIVE_KEY_PARTS = ("secret", "token", "password", "api_key", "client_secret")


def _copy_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(value or {})


def _redact_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if isinstance(value, Mapping):
        return {str(k): _redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(key, item) for item in value]
    if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
        if isinstance(value, str) and value.startswith(("config://", "secret://")):
            return value
        if isinstance(value, str):
            return "[REDACTED]"
        return value
    if isinstance(value, str):
        return _sanitize_text(value)
    return value


def _sanitize_text(value: str) -> str:
    sanitized = value
    for pattern in _SECRET_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    return sanitized


def sanitize_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    return value


@dataclass(frozen=True)
class AzureDeploymentProfile:
    profile_id: str
    environment: str
    subscription_id_ref: str
    tenant_id: str
    region: str
    resource_group: str
    compute: dict[str, Any]
    bus: dict[str, Any]
    object_storage: dict[str, Any]
    state_store: dict[str, Any]
    secrets: dict[str, Any]
    observability: dict[str, Any]
    network: dict[str, Any]
    iac: dict[str, Any]
    approval: dict[str, Any]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "AzureDeploymentProfile":
        storage = _copy_mapping(data.get("storage"))
        object_storage = _copy_mapping(data.get("object_storage"))
        state_store = _copy_mapping(data.get("state_store"))
        secrets = _copy_mapping(data.get("secrets"))

        if storage:
            if "object_store" in storage:
                object_storage["backend"] = storage.get("object_store")
            if "containers" in storage:
                object_storage["containers"] = _copy_mapping(storage.get("containers"))
            if "state_store" in storage:
                state_store["backend"] = storage.get("state_store")
            if "key_vault" in storage:
                secrets["key_vault"] = storage.get("key_vault")

        return cls(
            profile_id=str(data.get("profile_id", "")),
            environment=str(data.get("environment", "")),
            subscription_id_ref=str(data.get("subscription_id_ref", "")),
            tenant_id=str(data.get("tenant_id", "")),
            region=str(data.get("region", "")),
            resource_group=str(data.get("resource_group", "")),
            compute=_copy_mapping(data.get("compute") or data.get("runtime_cells")),
            bus=_copy_mapping(data.get("bus") or data.get("event_bus")),
            object_storage=object_storage,
            state_store=state_store,
            secrets=secrets,
            observability=_copy_mapping(data.get("observability")),
            network=_copy_mapping(data.get("network")),
            iac=_copy_mapping(data.get("iac")),
            approval=_copy_mapping(data.get("approval")),
        )

    @property
    def runtime_cells(self) -> dict[str, Any]:
        return dict(self.compute)

    @property
    def event_bus(self) -> dict[str, Any]:
        return dict(self.bus)

    @property
    def storage(self) -> dict[str, Any]:
        return {
            "object_store": self.object_storage.get("backend"),
            "state_store": self.state_store.get("backend"),
            "key_vault": self.secrets.get("key_vault"),
            "containers": dict(self.object_storage.get("containers") or {}),
        }

    def to_dict(self, *, include_legacy_aliases: bool = True, redacted: bool = False) -> dict[str, Any]:
        data = {
            "profile_id": self.profile_id,
            "environment": self.environment,
            "subscription_id_ref": self.subscription_id_ref,
            "tenant_id": self.tenant_id,
            "region": self.region,
            "resource_group": self.resource_group,
            "compute": dict(self.compute),
            "bus": dict(self.bus),
            "object_storage": dict(self.object_storage),
            "state_store": dict(self.state_store),
            "secrets": dict(self.secrets),
            "observability": dict(self.observability),
            "network": dict(self.network),
            "iac": dict(self.iac),
            "approval": dict(self.approval),
        }
        if include_legacy_aliases:
            data["runtime_cells"] = dict(self.compute)
            data["event_bus"] = dict(self.bus)
            data["storage"] = self.storage
        return sanitize_payload(data) if redacted else data

    def to_redacted_json(self) -> str:
        return json.dumps(self.to_dict(redacted=True), sort_keys=True)


def load_deployment_profile(path: str | Path) -> AzureDeploymentProfile:
    profile_path = Path(path)
    raw = profile_path.read_text(encoding="utf-8")
    if profile_path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ValueError("YAML profiles require PyYAML; use JSON profile input") from exc
        data = yaml.safe_load(raw) or {}
    else:
        data = json.loads(raw)
    if not isinstance(data, Mapping):
        raise ValueError("deployment profile must be a JSON/YAML object")
    return AzureDeploymentProfile.from_mapping(data)


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: list[str]
    normalized: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "errors": list(self.errors), "normalized": self.normalized}


@dataclass(frozen=True)
class FakeAzureAdapter:
    account_identity_visible: bool = True
    subscription_visible: bool = True
    quota_ok: bool = True
    resource_providers_registered: bool = True
    resource_group_ready: bool = True
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
    existing_resources: list[dict[str, Any]] = field(default_factory=list)
    cost_estimate: dict[str, int] = field(default_factory=dict)

    @classmethod
    def all_ready(cls, **overrides: Any) -> "FakeAzureAdapter":
        return cls(**overrides)

    def inspect(self) -> dict[str, Any]:
        return {
            "account_identity": self.account_identity_visible,
            "subscription": self.subscription_visible,
            "quota": self.quota,
            "existing_resources": list(self.existing_resources),
        }


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

    def to_dict(self) -> dict[str, Any]:
        return sanitize_payload(
            {
                "profile_id": self.profile_id,
                "read_only": self.read_only,
                "resources": list(self.resources),
                "unmanaged_resources": list(self.unmanaged_resources),
                "iac_artifacts": list(self.iac_artifacts),
                "cost_estimate": dict(self.cost_estimate),
                "required_secret_refs": list(self.required_secret_refs),
                "risks": list(self.risks),
                "smoke_tests": list(self.smoke_tests),
                "soak_tests": list(self.soak_tests),
                "rollback_plan": dict(self.rollback_plan),
                "approval_requirements": dict(self.approval_requirements),
            }
        )


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    checks: list[PreflightCheck]
    sqlite_fallback: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": [check.to_dict() for check in self.checks],
            "sqlite_fallback": self.sqlite_fallback,
        }


@dataclass(frozen=True)
class ApprovalGateResult:
    allowed: bool
    fail_closed: bool
    reason: str
    approval_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "fail_closed": self.fail_closed,
            "reason": self.reason,
            "approval_ref": self.approval_ref,
        }


@dataclass(frozen=True)
class DeploymentRunRecord:
    run_id: str
    profile_id: str
    status: str
    action: str
    approval_ref: str | None
    evidence_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    rollback_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return sanitize_payload(
            {
                "run_id": self.run_id,
                "profile_id": self.profile_id,
                "status": self.status,
                "action": self.action,
                "approval_ref": self.approval_ref,
                "evidence_refs": list(self.evidence_refs),
                "artifact_refs": list(self.artifact_refs),
                "rollback_refs": list(self.rollback_refs),
            }
        )


@dataclass(frozen=True)
class DeploymentDecision:
    action: str
    allowed: bool
    status: str
    reason: str
    run_record: DeploymentRunRecord
    live: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "allowed": self.allowed,
            "status": self.status,
            "reason": self.reason,
            "live": self.live,
            "run_record": self.run_record.to_dict(),
        }


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "kafka_protocol": self.kafka_protocol,
            "helper_template_ref": self.helper_template_ref,
            "broker_healthy": self.broker_healthy,
            "topics_verified": dict(self.topics_verified),
            "dead_letter_replay_ready": self.dead_letter_replay_ready,
            "lag_metrics": dict(self.lag_metrics),
            "max_lag": self.max_lag,
            "tls_sasl": dict(self.tls_sasl),
            "sqlite_spool_fallback": self.sqlite_spool_fallback,
            "ready": self.ready,
        }


@dataclass(frozen=True)
class PromotionGateResult:
    allowed: bool
    blockers: list[str]
    approval_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "blockers": list(self.blockers),
            "approval_ref": self.approval_ref,
        }


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
        return sanitize_payload(
            {
                "run_id": self.run_id,
                "profile_id": self.profile_id,
                "state": self.state,
                "logs": list(self.sanitized_logs),
                "logs_sanitized": self.logs_sanitized,
                "raw_logs_included": self.raw_logs_included,
                "rollback_refs": list(self.rollback_refs),
                "operator_actions": list(self.operator_actions),
            }
        )


def default_azure_profile(environment: str = "staging") -> AzureDeploymentProfile:
    data = {
        "profile_id": f"azure-{environment}-eastus",
        "environment": environment,
        "subscription_id_ref": "config://azure/subscription_id",
        "tenant_id": "tenant-atlas",
        "region": "eastus",
        "resource_group": f"rg-hermes-{environment}",
        "compute": {
            "mode": "container_apps",
            "isolation": "dedicated" if environment == "production" else "pooled",
            "min_instances": 1,
            "max_instances": 10,
        },
        "bus": {
            "backend": "eventhubs_kafka",
            "fallback_spool": "sqlite",
            "topics": [
                "learning.events",
                "runtime.events",
                "memory.sync",
                "deadletter.events",
            ],
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
        "state_store": {"backend": "postgres" if environment != "dev" else "sqlite"},
        "secrets": {"key_vault": f"kv-hermes-{environment}"},
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
    return AzureDeploymentProfile.from_mapping(data)


def validate_deployment_profile(profile: AzureDeploymentProfile) -> ValidationResult:
    errors: list[str] = []
    data = profile.to_dict()

    if profile.environment not in ENVIRONMENTS:
        errors.append("environment must be dev, staging, or production")
    if profile.compute.get("mode") not in RUNTIME_MODES:
        errors.append("compute.mode must be container_apps, vm, or aks")
    if profile.bus.get("backend") not in BUS_BACKENDS:
        errors.append("bus.backend must be sqlite, eventhubs_kafka, redpanda, or kafka")
    if profile.bus.get("fallback_spool") != "sqlite":
        errors.append("bus.fallback_spool must be sqlite")
    containers = profile.object_storage.get("containers") or {}
    for name in ("artifacts", "memory", "corpus", "audit"):
        if name not in containers:
            errors.append(f"object_storage.containers.{name} is required")
    if profile.object_storage.get("backend") not in OBJECT_STORES:
        errors.append("object_storage.backend must be azure_blob or adls_gen2")
    if profile.state_store.get("backend") not in STATE_STORES:
        errors.append("state_store.backend must be sqlite, postgres, or cosmos")
    if not profile.secrets.get("key_vault"):
        errors.append("secrets.key_vault is required")
    if profile.observability.get("backend") not in OBSERVABILITY_BACKENDS:
        errors.append("observability.backend is invalid")
    if not profile.network.get("dns_zone_ref"):
        errors.append("network.dns_zone_ref is required")
    if profile.iac.get("format") not in {"terraform", "bicep"}:
        errors.append("iac.format must be terraform or bicep")
    if profile.iac.get("format") == "terraform" and profile.iac.get("artifact_root") != TERRAFORM_SCAFFOLD:
        errors.append("terraform profiles must target infra/azure/terraform/hermes-platform")
    for field_name in APPROVAL_FIELDS.values():
        if profile.approval.get(field_name) is not True:
            errors.append(f"approval.{field_name} must be true")
    if profile.iac.get("apply_requires_approval") is not True:
        errors.append("iac.apply_requires_approval must be true")

    return ValidationResult(ok=not errors, errors=errors, normalized=data)


def _resource_id(profile: AzureDeploymentProfile, resource_class: str) -> str:
    return f"azure://{profile.profile_id}/{resource_class}"


def build_deployment_plan(
    profile: AzureDeploymentProfile,
    adapter: FakeAzureAdapter | None = None,
) -> DeploymentPlan:
    adapter = adapter or FakeAzureAdapter.all_ready()
    validation = validate_deployment_profile(profile)
    if not validation.ok:
        raise ValueError("; ".join(validation.errors))

    desired = [
        {"class": "compute", "target": profile.compute["mode"]},
        {"class": "bus", "target": profile.bus["backend"]},
        {"class": "object_storage", "target": profile.object_storage["backend"]},
        {"class": "state_store", "target": profile.state_store["backend"]},
        {"class": "secrets", "target": "azure_key_vault"},
        {"class": "observability", "target": profile.observability["backend"]},
        {"class": "network", "target": profile.network["public_gateway"]},
    ]
    existing_by_class = {
        item.get("class"): item for item in adapter.existing_resources if item.get("class")
    }
    resources = []
    for item in desired:
        current = existing_by_class.get(item["class"])
        action = "create"
        if current and current.get("target") == item["target"]:
            action = "no_change"
        elif current:
            action = "update"
        resources.append(
            {
                **item,
                "id": _resource_id(profile, item["class"]),
                "action": action,
            }
        )
    managed_classes = {item["class"] for item in desired}
    unmanaged = [
        dict(item)
        for item in adapter.existing_resources
        if item.get("class") not in managed_classes
    ]
    artifact_root = profile.iac.get("artifact_root", TERRAFORM_SCAFFOLD)
    return DeploymentPlan(
        profile_id=profile.profile_id,
        read_only=True,
        resources=resources,
        unmanaged_resources=unmanaged,
        iac_artifacts=[
            {
                "format": profile.iac["format"],
                "path": artifact_root,
                "ref": f"iac://{profile.profile_id}/{profile.iac['format']}",
                "terraform_first": profile.iac["format"] == "terraform",
            }
        ],
        cost_estimate=adapter.cost_estimate or {"monthly_min_usd": 0, "monthly_max_usd": 0},
        required_secret_refs=[
            f"secret://azure/key-vault/{profile.secrets['key_vault']}",
            profile.subscription_id_ref,
        ],
        risks=[
            "live_apply_requires_operator_approval",
            "dns_cutover_requires_separate_approval",
            "sqlite_spool_is_fallback_not_primary_bus",
        ],
        smoke_tests=list(SMOKE_CHECKS),
        soak_tests=list(SOAK_CHECKS),
        rollback_plan={
            "rollback_ref": f"rollback://{profile.profile_id}/previous-known-good",
            "artifact_ref": f"iac://{profile.profile_id}/{profile.iac['format']}",
            "strategy": "restore_previous_known_good_or_block_for_operator",
        },
        approval_requirements=dict(profile.approval),
    )


def run_preflight(
    profile: AzureDeploymentProfile,
    adapter: FakeAzureAdapter | None = None,
    plan: DeploymentPlan | None = None,
) -> PreflightResult:
    adapter = adapter or FakeAzureAdapter.all_ready()
    plan = plan or build_deployment_plan(profile, adapter)
    status_by_check = {
        "account_identity": adapter.account_identity_visible,
        "subscription_visibility": adapter.subscription_visible,
        "quota": adapter.quota_ok and bool(adapter.quota or profile.environment == "dev"),
        "resource_providers": adapter.resource_providers_registered,
        "resource_group": adapter.resource_group_ready,
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
        for name in PREFLIGHT_CHECKS
    ]
    return PreflightResult(
        ok=all(check.status == "passed" for check in checks),
        checks=checks,
        sqlite_fallback=str(profile.bus.get("fallback_spool", "sqlite")),
    )


def evaluate_approval_gate(
    profile: AzureDeploymentProfile,
    *,
    operation: str,
    approval: Mapping[str, Any] | None,
) -> ApprovalGateResult:
    field_name = APPROVAL_FIELDS.get(operation)
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


def decide_deployment_action(
    profile: AzureDeploymentProfile,
    *,
    action: str,
    approval: Mapping[str, Any] | None = None,
    evidence_refs: list[str] | None = None,
    live: bool = False,
    hardening_evidence: Mapping[str, Any] | None = None,
) -> DeploymentDecision:
    gate_action = "destroy" if action == "rollback_destroy" else action
    gate = evaluate_approval_gate(profile, operation=gate_action, approval=approval)
    run_id = f"{action}-{uuid.uuid4().hex[:12]}"
    status = "approved_plan_only" if gate.allowed else "blocked"
    reason = gate.reason
    if gate.allowed and live:
        status = "blocked"
        if profile.environment == "production" and action in {"apply", "promote"}:
            from hermes_cli.platform_hardening import evaluate_azure_production_hardening

            hardening = evaluate_azure_production_hardening(hardening_evidence)
            if not hardening.allowed:
                reason = "azure_production_hardening_blocked"
            else:
                reason = f"live_{action}_not_implemented"
        else:
            reason = f"live_{action}_not_implemented"
    record = DeploymentRunRecord(
        run_id=run_id,
        profile_id=profile.profile_id,
        status=status,
        action=action,
        approval_ref=gate.approval_ref,
        evidence_refs=tuple(evidence_refs or ()),
        artifact_refs=(f"iac://{profile.profile_id}/{profile.iac.get('format', 'terraform')}",),
        rollback_refs=(f"rollback://{profile.profile_id}/previous-known-good",),
    )
    return DeploymentDecision(
        action=action,
        allowed=gate.allowed and not live,
        status=status,
        reason=reason,
        run_record=record,
        live=live,
    )


def deployment_helper_templates(profile: AzureDeploymentProfile) -> dict[str, dict[str, Any]]:
    backend = str(profile.bus.get("backend", "sqlite"))
    return {
        "eventhubs_kafka": {
            "ref": "template://azure/eventhubs-kafka-helper",
            "enabled": backend == "eventhubs_kafka",
            "protocol": "kafka",
            "creates_live_resources": False,
        },
        "redpanda_kafka": {
            "ref": "template://azure/redpanda-kafka-helper",
            "enabled": backend == "redpanda",
            "protocol": "kafka",
            "creates_live_resources": False,
        },
        "kafka": {
            "ref": "template://azure/kafka-helper",
            "enabled": backend == "kafka",
            "protocol": "kafka",
            "creates_live_resources": False,
        },
        "object_storage": {
            "ref": f"template://azure/{profile.object_storage.get('backend')}-object-storage",
            "containers": dict(profile.object_storage.get("containers") or {}),
            "creates_live_resources": False,
        },
        "state_store": {
            "ref": f"template://azure/{profile.state_store.get('backend')}-state-store",
            "creates_live_resources": False,
        },
        "key_vault": {
            "ref": "template://azure/key-vault",
            "vault_ref": f"secret://azure/key-vault/{profile.secrets.get('key_vault')}",
            "creates_live_resources": False,
        },
        "observability": {
            "ref": f"template://azure/{profile.observability.get('backend')}",
            "creates_live_resources": False,
        },
        "network": {
            "ref": f"template://azure/network/{profile.network.get('public_gateway')}",
            "dns_zone_ref": profile.network.get("dns_zone_ref"),
            "creates_live_resources": False,
        },
        "sqlite_spool": {
            "ref": "template://local/sqlite-spool-fallback",
            "fallback": True,
            "creates_live_resources": False,
        },
    }


def build_bus_readiness_report(
    profile: AzureDeploymentProfile,
    adapter: FakeAzureAdapter | None = None,
) -> BusReadinessReport:
    adapter = adapter or FakeAzureAdapter.all_ready()
    backend = str(profile.bus.get("backend", "sqlite"))
    topics = list(profile.bus.get("topics") or [])
    topics_verified = {topic: bool(adapter.topics.get(topic, False)) for topic in topics}
    deadletter_ready = topics_verified.get("deadletter.events", False)
    max_lag = max(adapter.lag_metrics.values()) if adapter.lag_metrics else 0
    templates = deployment_helper_templates(profile)
    if backend == "eventhubs_kafka":
        helper = templates["eventhubs_kafka"]["ref"]
    elif backend == "redpanda":
        helper = templates["redpanda_kafka"]["ref"]
    else:
        helper = templates["kafka"]["ref"] if backend == "kafka" else templates["sqlite_spool"]["ref"]
    kafka_protocol = backend in {"eventhubs_kafka", "redpanda", "kafka"}
    tls_sasl = {
        "tls": "required" if backend != "sqlite" else "local",
        "sasl": "required" if kafka_protocol else "local",
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
        sqlite_spool_fallback=str(profile.bus.get("fallback_spool", "sqlite")),
        ready=adapter.broker_health and all(topics_verified.values()) and deadletter_ready,
    )


def generate_smoke_checklist(profile: AzureDeploymentProfile) -> dict[str, Any]:
    return {
        "profile_id": profile.profile_id,
        "environment": profile.environment,
        "checks": [
            {"name": name, "required": True, "evidence_ref_prefix": f"evidence://{profile.profile_id}/{name}"}
            for name in SMOKE_CHECKS
        ],
    }


def generate_soak_checklist(profile: AzureDeploymentProfile) -> dict[str, Any]:
    return {
        "profile_id": profile.profile_id,
        "environment": profile.environment,
        "checks": [
            {"name": name, "required": True, "evidence_ref_prefix": f"evidence://{profile.profile_id}/{name}"}
            for name in SOAK_CHECKS
        ],
    }


def evaluate_promotion_gate(
    profile: AzureDeploymentProfile,
    evidence: Mapping[str, str],
    approval: Mapping[str, Any] | None,
) -> PromotionGateResult:
    blockers = [name for name in PROMOTION_REQUIREMENTS if evidence.get(name) != "passed"]
    approval_result = evaluate_approval_gate(profile, operation="promote", approval=approval)
    if not approval_result.allowed:
        blockers.append("operator_approval_required")
    return PromotionGateResult(
        allowed=not blockers,
        blockers=blockers,
        approval_ref=approval_result.approval_ref,
    )


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
        sanitized_logs=[_sanitize_text(line) for line in logs],
        rollback_refs=list(rollback_refs),
        operator_actions=list(operator_actions),
    )


def orchestrate_fake_staging_flow(
    *,
    staging_profile: AzureDeploymentProfile | None = None,
    production_profile: AzureDeploymentProfile | None = None,
    approval_id: str = "approval-staging",
) -> dict[str, Any]:
    staging = staging_profile or default_azure_profile("staging")
    production = production_profile or default_azure_profile("production")
    adapter = FakeAzureAdapter.all_ready(
        quota={"container_apps": 20, "eventhubs": 2},
        cost_estimate={"monthly_min_usd": 120, "monthly_max_usd": 240},
        topics={topic: True for topic in staging.bus.get("topics", [])},
        lag_metrics={"learning.events": 0, "runtime.events": 1},
    )
    plan = build_deployment_plan(staging, adapter)
    preflight = run_preflight(staging, adapter, plan)
    apply_decision = decide_deployment_action(
        staging,
        action="apply",
        approval={"approved": True, "approval_id": approval_id},
        evidence_refs=["evidence://staging/preflight"],
    )
    evidence = {name: "passed" for name in PROMOTION_REQUIREMENTS}
    promotion = evaluate_promotion_gate(production, evidence, approval=None)
    return {
        "plan": plan.to_dict(),
        "preflight": preflight.to_dict(),
        "apply": apply_decision.to_dict(),
        "smoke": generate_smoke_checklist(staging),
        "soak": generate_soak_checklist(staging),
        "promote": promotion.to_dict(),
    }


def azure_deploy_json(
    command: str,
    *,
    profile: AzureDeploymentProfile | None = None,
    approval_id: str | None = None,
    evidence: Mapping[str, str] | None = None,
    run_id: str | None = None,
    live: bool = False,
) -> dict[str, Any]:
    profile = profile or default_azure_profile("staging")
    adapter = FakeAzureAdapter.all_ready(
        quota={"container_apps": 20, "eventhubs": 2},
        cost_estimate={"monthly_min_usd": 0, "monthly_max_usd": 0},
        topics={topic: True for topic in profile.bus.get("topics", [])},
    )
    approval = (
        {"approved": True, "approval_id": approval_id}
        if approval_id
        else None
    )
    if command == "plan":
        return build_deployment_plan(profile, adapter).to_dict()
    if command == "preflight":
        return run_preflight(profile, adapter).to_dict()
    if command == "apply":
        return decide_deployment_action(profile, action="apply", approval=approval, live=live).to_dict()
    if command == "status":
        status = build_deployment_status(
            run_id=run_id or "deploy-local",
            profile=profile,
            state="plan_only",
            logs=["fake adapter status: no live Azure resources created"],
            rollback_refs=[f"rollback://{profile.profile_id}/previous-known-good"],
            operator_actions=["Provide approval ref before any live apply"],
        )
        return status.to_dict()
    if command == "smoke":
        return generate_smoke_checklist(profile)
    if command == "soak":
        return generate_soak_checklist(profile)
    if command == "promote":
        return evaluate_promotion_gate(profile, evidence or {}, approval).to_dict()
    if command == "rollback":
        return decide_deployment_action(
            profile,
            action="rollback_destroy",
            approval=approval,
            evidence_refs=[f"rollback://{run_id or profile.profile_id}/previous-known-good"],
            live=live,
        ).to_dict()
    raise ValueError(f"unknown azure deploy command: {command}")
