"""Tenant onboarding DTO helpers for local/dev platform tests.

These helpers define stable packet shapes for the first tenant-platform slice.
They intentionally do not perform network calls, cloud provisioning, connector
verification, or policy enforcement.
"""

from __future__ import annotations

import copy
import json
import re
from hashlib import sha256
from typing import Any, Dict, Iterable, List, Mapping, Optional


SCHEMA_VERSION = 1
MAX_BODY_SUMMARY_CHARS = 96
SUPPORTED_CONNECTOR_PLATFORMS = ("slack", "telegram", "whatsapp", "dashboard", "api", "email", "webhook")
SUPPORTED_CICD_TASK_KINDS = (
    "workflow_create",
    "workflow_repair",
    "workflow_run",
    "workflow_validate",
    "workflow_report",
)

_STANDALONE_SECRET_PATTERNS = (
    re.compile(r"(?i)\bsk-[A-Za-z0-9_-]{6,}\b"),
)
_PREFIXED_SECRET_PATTERNS = (
    re.compile(r"(?i)\b((?:api[_-]?key|token|secret|password|bot_token)\s*[:=]\s*)\S+"),
)


def stable_json(payload: Mapping[str, Any]) -> str:
    """Serialize packet dictionaries deterministically for state/tests."""

    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _clean_list(value: Optional[Iterable[Any]]) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [item for item in value if item not in (None, "")]


def _copy_dict(value: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if value is None:
        return {}
    return copy.deepcopy(dict(value))


def _base_packet(kind: str, tenant_id: str) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "tenant_id": tenant_id,
        "enforcement_allowed": False,
    }


def _redact_text(value: str) -> str:
    redacted = " ".join(str(value or "").split())
    for pattern in _STANDALONE_SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    for pattern in _PREFIXED_SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]", redacted)
    return redacted


def _bounded_summary(value: str, *, limit: int = MAX_BODY_SUMMARY_CHARS) -> str:
    redacted = _redact_text(value)
    if len(redacted) <= limit:
        return redacted
    return redacted[: limit - 3].rstrip() + "..."


def _require_supported(value: str, supported: Iterable[str], field_name: str) -> None:
    if value not in set(supported):
        raise ValueError(f"unsupported {field_name}: {value}")


def _hash_ref(*parts: str) -> str:
    digest = sha256(":".join(parts).encode("utf-8")).hexdigest()[:12]
    return digest


def build_tenant_registry(
    *,
    tenant_id: str,
    name: str,
    users: Iterable[Mapping[str, Any]],
    budgets: Mapping[str, Any],
    feature_profile: Mapping[str, Any],
    runtime_cell_id: str,
    audit: Mapping[str, Any],
    status: str = "onboarding",
    isolation_mode: str = "dedicated",
) -> Dict[str, Any]:
    payload = _base_packet("tenant_registry", tenant_id)
    payload.update(
        {
            "name": name,
            "status": status,
            "isolation_mode": isolation_mode,
            "users": [_copy_dict(user) for user in users],
            "roles": sorted({str(user.get("role")) for user in users if user.get("role")}),
            "budgets": _copy_dict(budgets),
            "feature_profile": _copy_dict(feature_profile),
            "runtime_cell_assignment": {"runtime_cell_id": runtime_cell_id, "status": "assigned"},
            "audit": _copy_dict(audit),
        }
    )
    return payload


def build_repo_registration(
    *,
    tenant_id: str,
    repo_id: str,
    provider_ref: Mapping[str, Any],
    clone_url: str,
    branch_policy: Mapping[str, Any],
    protected_paths: Iterable[str],
    validation_commands: Iterable[str],
    deployment_mapping: Mapping[str, Any],
    secret_refs: Iterable[str],
    speckit_policy: Mapping[str, Any],
    memory_sharing_policy: Mapping[str, Any],
    status: str = "registered",
) -> Dict[str, Any]:
    payload = _base_packet("repo_registration", tenant_id)
    payload.update(
        {
            "repo_id": repo_id,
            "status": status,
            "provider_ref": _copy_dict(provider_ref),
            "clone_url": clone_url,
            "branch_policy": _copy_dict(branch_policy),
            "protected_paths": _clean_list(protected_paths),
            "validation_commands": _clean_list(validation_commands),
            "deployment_mapping": _copy_dict(deployment_mapping),
            "secret_refs": _clean_list(secret_refs),
            "speckit_policy": _copy_dict(speckit_policy),
            "memory_sharing_policy": _copy_dict(memory_sharing_policy),
            "preflight": {"required": True, "status": "pending", "read_only": True},
        }
    )
    return payload


def build_connector_registration(
    *,
    tenant_id: str,
    connector_id: str,
    platform: str,
    route_ref: Mapping[str, Any],
    allowed_users: Iterable[str],
    allowed_channels: Iterable[str],
    urgent_route: Mapping[str, Any],
    approval_route: Mapping[str, Any],
    status: str = "registered",
) -> Dict[str, Any]:
    _require_supported(platform, SUPPORTED_CONNECTOR_PLATFORMS, "platform")
    payload = _base_packet("connector_registration", tenant_id)
    payload.update(
        {
            "connector_id": connector_id,
            "platform": platform,
            "status": status,
            "route_ref": _copy_dict(route_ref),
            "allowlists": {
                "tenant_ids": [tenant_id],
                "user_refs": _clean_list(allowed_users),
                "channel_refs": _clean_list(allowed_channels),
            },
            "routes": {
                "urgent": _copy_dict(urgent_route),
                "approval": _copy_dict(approval_route),
            },
            "verification": {"status": "pending", "external_call_performed": False},
            "raw_transcript_stored": False,
        }
    )
    return payload


def normalize_connector_message(
    connector: Mapping[str, Any],
    *,
    sender_ref: str,
    channel_ref: str,
    thread_ref: str,
    body: str,
    message_kind: str,
    repo_id: Optional[str] = None,
    session_id: Optional[str] = None,
    urgent: bool = False,
    approval_context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    tenant_id = str(connector["tenant_id"])
    allowed_users = set(connector.get("allowlists", {}).get("user_refs", []))
    allowed_channels = set(connector.get("allowlists", {}).get("channel_refs", []))
    status = "accepted"
    rejection_reason = None
    if allowed_users and sender_ref not in allowed_users:
        status = "rejected"
        rejection_reason = "unauthorized_sender"
    elif allowed_channels and channel_ref not in allowed_channels:
        status = "rejected"
        rejection_reason = "unauthorized_channel"

    payload = _base_packet("tenant_message_envelope", tenant_id)
    payload.update(
        {
            "connector_id": connector["connector_id"],
            "platform": connector["platform"],
            "sender_ref": sender_ref,
            "channel_ref": channel_ref,
            "thread_ref": thread_ref,
            "repo_id": repo_id,
            "session_id": session_id,
            "message_kind": message_kind,
            "body_summary": _bounded_summary(body),
            "approval_context": _copy_dict(approval_context),
            "urgent": bool(urgent),
            "status": status,
            "rejection_reason": rejection_reason,
            "raw_transcript_stored": False,
        }
    )
    return payload


def build_toolset_profile(
    *,
    tenant_id: str,
    profile_id: str,
    roles: Mapping[str, Any],
    scopes: Mapping[str, Any],
    budgets: Mapping[str, Any],
    approval_requirements: Mapping[str, Any],
    feature_toggle_deps: Iterable[str],
    status: str = "active",
) -> Dict[str, Any]:
    payload = _base_packet("toolset_profile", tenant_id)
    payload.update(
        {
            "profile_id": profile_id,
            "status": status,
            "roles": _copy_dict(roles),
            "scopes": _copy_dict(scopes),
            "budgets": _copy_dict(budgets),
            "approval_requirements": _copy_dict(approval_requirements),
            "feature_toggle_deps": _clean_list(feature_toggle_deps),
        }
    )
    return payload


def build_runtime_cell_assignment(
    tenant_id: str,
    runtime_cell_id: str,
    *,
    root: str,
    isolation_mode: str,
    status: str = "assigned",
) -> Dict[str, Any]:
    suffix = _hash_ref(tenant_id, runtime_cell_id)
    base = f"{root.rstrip('/')}/{tenant_id}/{runtime_cell_id}-{suffix}"
    payload = _base_packet("runtime_cell_assignment", tenant_id)
    payload.update(
        {
            "runtime_cell_id": runtime_cell_id,
            "status": status,
            "isolation_mode": isolation_mode,
            "hermes_home": f"{base}/home",
            "worktree_root": f"{base}/worktrees",
            "secret_namespace": f"secret://{tenant_id}/{runtime_cell_id}",
            "memory_namespace": f"memory://{tenant_id}/{runtime_cell_id}",
            "connector_namespace": f"connector://{tenant_id}/{runtime_cell_id}",
            "sidecar_namespace": f"sidecar://{tenant_id}/{runtime_cell_id}",
            "cost_ledger_namespace": f"cost://{tenant_id}/{runtime_cell_id}",
            "state_ref": f"{base}/state.db",
        }
    )
    return payload


def evaluate_tenant_budget(*, tenant_id: str, usage: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    exhausted: List[str] = []
    degraded: List[str] = []
    usage_payload: Dict[str, Dict[str, Any]] = {}
    for budget_name in sorted(usage):
        item = dict(usage[budget_name])
        used = float(item.get("used", 0))
        limit = float(item.get("limit", 0))
        remaining = max(limit - used, 0.0)
        usage_payload[budget_name] = {"used": item.get("used", 0), "limit": item.get("limit", 0), "remaining": remaining}
        if limit > 0 and used > limit:
            exhausted.append(budget_name)
        elif limit > 0 and used >= limit:
            degraded.append(budget_name)

    if exhausted:
        decision = "pause"
    elif degraded:
        decision = "degrade"
    else:
        decision = "allow"

    payload = _base_packet("tenant_budget_decision", tenant_id)
    payload.update(
        {
            "usage": usage_payload,
            "decision": decision,
            "exhausted": exhausted,
            "degraded_capabilities": degraded,
            "loop_allowed": False,
            "next_action": "operator_review" if decision == "pause" else "use_lower_cost_route" if decision == "degrade" else "continue",
        }
    )
    return payload


def build_connector_onboarding(
    *,
    tenant_id: str,
    connector_id: str,
    platform: str,
    credential_secret_refs: Iterable[str],
    test_route: Mapping[str, Any],
    provided_credentials: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    _require_supported(platform, SUPPORTED_CONNECTOR_PLATFORMS, "platform")
    payload = _base_packet("connector_onboarding", tenant_id)
    payload.update(
        {
            "connector_id": connector_id,
            "platform": platform,
            "status": "verification_pending",
            "credential_secret_refs": _clean_list(credential_secret_refs),
            "provided_credentials_stored": False,
            "provided_credentials_received": bool(provided_credentials),
            "provided_credentials_count": len(provided_credentials or {}),
            "test_route": _copy_dict(test_route),
            "verification": {
                "status": "pending",
                "access_succeeded": None,
                "test_message_required": True,
                "external_call_performed": False,
                "evidence_ref": None,
            },
        }
    )
    return payload


def activate_connector_onboarding(
    onboarding: Mapping[str, Any],
    *,
    access_succeeded: bool,
    evidence_ref: str,
) -> Dict[str, Any]:
    payload = copy.deepcopy(dict(onboarding))
    payload["verification"] = _copy_dict(payload.get("verification"))
    payload["verification"].update(
        {
            "status": "succeeded" if access_succeeded else "failed",
            "access_succeeded": bool(access_succeeded),
            "evidence_ref": evidence_ref,
            "external_call_performed": False,
        }
    )
    payload["status"] = "active" if access_succeeded else "blocked"
    payload["enforcement_allowed"] = False
    return payload


def build_cicd_pipeline_packet(
    *,
    tenant_id: str,
    repo_id: str,
    task_kind: str,
    speckit_refs: Mapping[str, Any],
    secret_refs: Iterable[str],
    protected_environment_approvals: Iterable[Mapping[str, Any]],
    validation_evidence_refs: Iterable[str],
    rollback_expectations: Mapping[str, Any],
    urgent_failure_notification: Mapping[str, Any],
) -> Dict[str, Any]:
    _require_supported(task_kind, SUPPORTED_CICD_TASK_KINDS, "task_kind")
    payload = _base_packet("cicd_pipeline_task", tenant_id)
    payload.update(
        {
            "repo_id": repo_id,
            "task_kind": task_kind,
            "speckit_refs": _copy_dict(speckit_refs),
            "secret_refs": _clean_list(secret_refs),
            "protected_environment_approvals": [
                _copy_dict(item) for item in protected_environment_approvals
            ],
            "validation_evidence_refs": _clean_list(validation_evidence_refs),
            "rollback_expectations": _copy_dict(rollback_expectations),
            "urgent_failure_notification": _copy_dict(urgent_failure_notification),
            "worker_packet_shape": {
                "create": task_kind == "workflow_create",
                "repair": task_kind == "workflow_repair",
                "run": task_kind == "workflow_run",
                "validate": task_kind == "workflow_validate",
                "report": task_kind == "workflow_report",
            },
            "raw_logs_stored": False,
        }
    )
    return payload
