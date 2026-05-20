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
from pathlib import Path
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
_TENANT_STATE_PREFIX = "tenant_platform"
_RECORD_ID_FIELDS = {
    "tenant_registry": "tenant_id",
    "repo_registration": "repo_id",
    "connector_registration": "connector_id",
    "toolset_profile": "profile_id",
    "runtime_cell_assignment": "runtime_cell_id",
    "tenant_job_submission": "job_id",
}

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


def _state_key(tenant_id: str, kind: str, record_id: Optional[str] = None) -> str:
    record_id = record_id or tenant_id
    return f"{_TENANT_STATE_PREFIX}:{tenant_id}:{kind}:{record_id}"


def _record_id(payload: Mapping[str, Any]) -> str:
    kind = str(payload.get("kind", ""))
    field = _RECORD_ID_FIELDS.get(kind)
    if field and payload.get(field):
        return str(payload[field])
    return str(payload.get("id") or payload.get("tenant_id") or kind)


class TenantPlatformStore:
    """Local/dev SQLite-backed state adapter for tenant onboarding records."""

    def __init__(self, db_path: Optional[Path | str] = None, db: Any = None):
        if db is not None:
            self._db = db
            self._owns_db = False
        else:
            from hermes_state import SessionDB

            self._db = SessionDB(Path(db_path) if db_path is not None else None)
            self._owns_db = True

    def close(self) -> None:
        if self._owns_db and hasattr(self._db, "close"):
            self._db.close()

    def save_record(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        record = copy.deepcopy(dict(payload))
        tenant_id = str(record.get("tenant_id") or "")
        kind = str(record.get("kind") or "")
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if not kind:
            raise ValueError("kind is required")
        record["enforcement_allowed"] = False
        self._db.set_meta(_state_key(tenant_id, kind, _record_id(record)), stable_json(record))
        return record

    def get_record(self, tenant_id: str, kind: str, record_id: Optional[str] = None) -> Dict[str, Any]:
        value = self._db.get_meta(_state_key(tenant_id, kind, record_id))
        if value is None:
            raise KeyError(f"missing tenant platform record: {tenant_id}/{kind}/{record_id or tenant_id}")
        return json.loads(value)

    def list_records(self, kind: str, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        prefix = f"{_TENANT_STATE_PREFIX}:{tenant_id or '%'}:{kind}:"
        if tenant_id is None:
            like = f"{_TENANT_STATE_PREFIX}:%:{kind}:%"
        else:
            like = prefix + "%"
        with self._db._lock:
            rows = self._db._conn.execute(
                "SELECT value FROM state_meta WHERE key LIKE ? ORDER BY key",
                (like,),
            ).fetchall()
        return [json.loads(row["value"] if hasattr(row, "keys") else row[0]) for row in rows]


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
            "isolation": {
                "mode": isolation_mode,
                "pooled": isolation_mode == "pooled",
                "tenant_namespace": tenant_id,
                "runtime_namespace": f"{tenant_id}:{runtime_cell_id}",
                "state_scope": "tenant",
            },
        }
    )
    return payload


def build_repo_preflight(repo: Mapping[str, Any]) -> Dict[str, Any]:
    checks = {
        "clone_url_present": bool(repo.get("clone_url")),
        "branch_policy_present": bool(repo.get("branch_policy")),
        "validation_commands_present": bool(repo.get("validation_commands")),
        "speckit_policy_present": bool(repo.get("speckit_policy")),
        "secret_refs_only": all(str(ref).startswith("secret://") for ref in repo.get("secret_refs", [])),
    }
    payload = _base_packet("repo_preflight", str(repo["tenant_id"]))
    payload.update(
        {
            "repo_id": repo["repo_id"],
            "read_only": True,
            "mutation_performed": False,
            "external_call_performed": False,
            "checks": checks,
            "status": "passed" if all(checks.values()) else "blocked",
            "evidence_refs": [f"evidence://tenant/{repo['tenant_id']}/repo/{repo['repo_id']}/preflight/local"],
        }
    )
    return payload


def merge_toolset_profile(profile: Mapping[str, Any], job_overrides: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    payload = copy.deepcopy(dict(profile))
    overrides = _copy_dict(job_overrides)
    for field in ("roles", "scopes", "budgets", "approval_requirements"):
        merged = _copy_dict(payload.get(field))
        for key, value in _copy_dict(overrides.get(field)).items():
            if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
                nested = _copy_dict(merged[key])
                nested.update(_copy_dict(value))
                merged[key] = nested
            else:
                merged[key] = copy.deepcopy(value)
        payload[field] = merged
    payload["kind"] = "toolset_profile_resolved"
    payload["base_profile_id"] = profile.get("profile_id")
    payload["job_overrides_applied"] = bool(overrides)
    payload["enforcement_allowed"] = False
    return payload


def build_tenant_supervisor_job_packet(
    *,
    tenant_id: str,
    repo_id: str,
    connector_id: str,
    request_summary: str,
    speckit_refs: Mapping[str, Any],
    runtime_cell_id: str,
    toolset_profile_id: str,
    source: str,
    job_id: Optional[str] = None,
    job_overrides: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    bounded_request = _bounded_summary(request_summary, limit=160)
    derived_job_id = job_id or f"job-{_hash_ref(tenant_id, repo_id, connector_id, bounded_request)}"
    task_id = f"task-{_hash_ref(derived_job_id, tenant_id, repo_id)}"
    supervisor_task_packet = {
        "id": task_id,
        "source": source,
        "tenant_id": tenant_id,
        "repo_id": repo_id,
        "cwd": None,
        "raw_request_summary": bounded_request,
        "task_type": "speckit_backed_job",
        "complexity": "standard",
        "requires_speckit": True,
        "clarifications": [],
        "memory_packet_id": None,
        "success_criteria": ["Spec Kit refs are preserved", "Tenant runtime state remains isolated"],
        "constraints": ["local/dev only", "no raw transcripts", "enforcement_allowed=false"],
        "status": "intake",
        "skip_reason": None,
    }
    payload = _base_packet("tenant_job_submission", tenant_id)
    payload.update(
        {
            "job_id": derived_job_id,
            "repo_id": repo_id,
            "connector_id": connector_id,
            "runtime_cell_id": runtime_cell_id,
            "toolset_profile_id": toolset_profile_id,
            "speckit_refs": _copy_dict(speckit_refs),
            "job_overrides": _copy_dict(job_overrides),
            "supervisor_task_path": "hermes_cli.runtime_packets.SupervisorTaskPacket",
            "supervisor_task_packet": supervisor_task_packet,
            "status": "submitted",
            "raw_transcript_stored": False,
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


def build_connector_route_packet(
    connector: Mapping[str, Any],
    *,
    route_kind: str,
    message_ref: str,
    body_summary: str,
    approval_context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    _require_supported(route_kind, ("reply", "approval", "urgent"), "route_kind")
    route_ref = _copy_dict(connector.get("route_ref"))
    if route_kind == "approval":
        route_ref.update(_copy_dict(connector.get("routes", {}).get("approval")))
    elif route_kind == "urgent":
        route_ref.update(_copy_dict(connector.get("routes", {}).get("urgent")))
    payload = _base_packet(f"tenant_{route_kind}_route", str(connector["tenant_id"]))
    payload.update(
        {
            "connector_id": connector["connector_id"],
            "platform": connector["platform"],
            "route_kind": route_kind,
            "route_ref": route_ref,
            "message_ref": message_ref,
            "body_summary": _bounded_summary(body_summary),
            "approval_context": _copy_dict(approval_context),
            "status": "queued",
            "external_call_performed": False,
            "raw_transcript_stored": False,
        }
    )
    return payload


def build_admin_dashboard_snapshot(
    store: TenantPlatformStore,
    *,
    tenant_id: Optional[str] = None,
    jobs: Optional[Iterable[Mapping[str, Any]]] = None,
    faults: Optional[Iterable[Mapping[str, Any]]] = None,
    worker_health: Optional[Iterable[Mapping[str, Any]]] = None,
    sidecar_health: Optional[Iterable[Mapping[str, Any]]] = None,
    cost: Optional[Iterable[Mapping[str, Any]]] = None,
    memory_flow: Optional[Iterable[Mapping[str, Any]]] = None,
    urgent_alerts: Optional[Iterable[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    payload = _base_packet("tenant_admin_dashboard", tenant_id or "all")
    payload.update(
        {
            "tenants": store.list_records("tenant_registry", tenant_id=tenant_id),
            "runtime_cells": store.list_records("runtime_cell_assignment", tenant_id=tenant_id),
            "connectors": store.list_records("connector_registration", tenant_id=tenant_id),
            "repos": store.list_records("repo_registration", tenant_id=tenant_id),
            "jobs": [_copy_dict(item) for item in (jobs or [])],
            "faults": [_copy_dict(item) for item in (faults or [])],
            "worker_health": [_copy_dict(item) for item in (worker_health or [])],
            "sidecar_health": [_copy_dict(item) for item in (sidecar_health or [])],
            "cost": [_copy_dict(item) for item in (cost or [])],
            "memory_flow": [_copy_dict(item) for item in (memory_flow or [])],
            "urgent_alerts": [_copy_dict(item) for item in (urgent_alerts or [])],
            "raw_transcript_stored": False,
        }
    )
    return payload


def build_tenant_smoke_fixture(
    store: TenantPlatformStore,
    *,
    tenant_id: str,
    repo_id: str,
    connector_id: str,
    root: str,
    speckit_refs: Mapping[str, Any],
) -> Dict[str, Any]:
    tenant = build_tenant_registry(
        tenant_id=tenant_id,
        name=tenant_id,
        users=[{"user_id": "local-operator", "role": "tenant_admin"}],
        budgets={"tokens": {"limit": 1000000, "used": 0}, "tools": {"limit": 500, "used": 0}},
        feature_profile={"profile_id": "features-local", "enabled": ["runtime.task_graph"], "expert_mode": False},
        runtime_cell_id=f"cell-{tenant_id}",
        audit={"created_by": "local-dev", "created_at": "local"},
    )
    repo = build_repo_registration(
        tenant_id=tenant_id,
        repo_id=repo_id,
        provider_ref={"provider": "local", "installation_ref": "local-dev"},
        clone_url=f"local://{tenant_id}/{repo_id}",
        branch_policy={"default_branch": "main", "allowed_branches": ["main"]},
        protected_paths=[".github/workflows/*"],
        validation_commands=["python3 -m py_compile hermes_cli/tenant_platform.py"],
        deployment_mapping={},
        secret_refs=[],
        speckit_policy={"required": True, "root": "specs/"},
        memory_sharing_policy={"tenant_private": True, "cross_tenant_shareable": False},
    )
    connector = build_connector_registration(
        tenant_id=tenant_id,
        connector_id=connector_id,
        platform="dashboard",
        route_ref={"route": "local-dashboard"},
        allowed_users=["local-operator"],
        allowed_channels=["local-channel"],
        urgent_route={"route": "local-urgent"},
        approval_route={"route": "local-approval"},
    )
    toolset = build_toolset_profile(
        tenant_id=tenant_id,
        profile_id="toolset-local",
        roles={"planner": {"enabled": True}, "speckit_creator": {"enabled": True}, "code_worker": {"enabled": True}},
        scopes={"repos": [repo_id], "environments": ["local"]},
        budgets={"tokens": 100000, "tool_calls": 100, "sidecars": 5},
        approval_requirements={"deployment": True, "protected_environment": True},
        feature_toggle_deps=["runtime.task_graph"],
    )
    cell = build_runtime_cell_assignment(tenant_id, f"cell-{tenant_id}", root=root, isolation_mode="dedicated")
    envelope = normalize_connector_message(
        connector,
        sender_ref="local-operator",
        channel_ref="local-channel",
        thread_ref="local-smoke",
        body="Submit Spec Kit backed local smoke job",
        message_kind="job_request",
        repo_id=repo_id,
    )
    job = build_tenant_supervisor_job_packet(
        tenant_id=tenant_id,
        repo_id=repo_id,
        connector_id=connector_id,
        request_summary=envelope["body_summary"],
        speckit_refs=speckit_refs,
        runtime_cell_id=cell["runtime_cell_id"],
        toolset_profile_id=toolset["profile_id"],
        source="connector",
    )
    for record in (tenant, repo, connector, toolset, cell, job):
        store.save_record(record)
    payload = _base_packet("tenant_onboarding_smoke", tenant_id)
    payload.update(
        {
            "status": "passed" if envelope["status"] == "accepted" else "blocked",
            "tenant": tenant,
            "repo": repo,
            "connector": connector,
            "toolset": toolset,
            "runtime_cell": cell,
            "connector_envelope": envelope,
            "job_packet": job,
            "isolation": {
                "tenant_scoped_state": True,
                "runtime_cell_id": cell["runtime_cell_id"],
                "state_ref": cell["state_ref"],
            },
            "raw_transcript_stored": False,
        }
    )
    return payload


def build_cicd_toolset_profile(
    *,
    tenant_id: str,
    profile_id: str,
    repo_ids: Iterable[str],
    protected_environments: Iterable[str],
) -> Dict[str, Any]:
    return build_toolset_profile(
        tenant_id=tenant_id,
        profile_id=profile_id,
        roles={
            "planner": {"enabled": True},
            "speckit_creator": {"enabled": True},
            "code_worker": {"enabled": True},
            "qa_browser": {"enabled": False},
            "cicd": {"enabled": True},
            "deployment": {"enabled": False},
            "repo": {"enabled": True},
        },
        scopes={"repos": _clean_list(repo_ids), "environments": _clean_list(protected_environments)},
        budgets={"tokens": 200000, "tool_calls": 200, "sidecars": 10},
        approval_requirements={"deployment": True, "protected_environment": True},
        feature_toggle_deps=["runtime.task_graph"],
    )


def build_cicd_worker_packet(
    *,
    tenant_id: str,
    repo_id: str,
    task_kind: str,
    workflow_ref: str,
    speckit_refs: Mapping[str, Any],
    secret_refs: Iterable[str],
    protected_environment_approvals: Iterable[Mapping[str, Any]],
    validation_evidence_refs: Iterable[str],
    rollback_expectations: Mapping[str, Any],
    urgent_failure_notification: Mapping[str, Any],
) -> Dict[str, Any]:
    pipeline = build_cicd_pipeline_packet(
        tenant_id=tenant_id,
        repo_id=repo_id,
        task_kind=task_kind,
        speckit_refs=speckit_refs,
        secret_refs=secret_refs,
        protected_environment_approvals=protected_environment_approvals,
        validation_evidence_refs=validation_evidence_refs,
        rollback_expectations=rollback_expectations,
        urgent_failure_notification=urgent_failure_notification,
    )
    payload = _base_packet("cicd_worker_packet", tenant_id)
    payload.update(
        {
            "repo_id": repo_id,
            "workflow_ref": workflow_ref,
            "task_kind": task_kind,
            "pipeline_packet": pipeline,
            "speckit_refs": _copy_dict(speckit_refs),
            "secret_refs": _clean_list(secret_refs),
            "protected_environment_approvals": [_copy_dict(item) for item in protected_environment_approvals],
            "validation_evidence_refs": _clean_list(validation_evidence_refs),
            "rollback_expectations": _copy_dict(rollback_expectations),
            "urgent_failure_notification": _copy_dict(urgent_failure_notification),
            "worker_packet_shape": _copy_dict(pipeline["worker_packet_shape"]),
            "raw_logs_stored": False,
        }
    )
    return payload
