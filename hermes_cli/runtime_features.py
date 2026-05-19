"""Local runtime feature toggles for experimental Hermes capabilities."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from hermes_state import SessionDB


MAX_REASON_LENGTH = 240
_GLOBAL_SCOPE = "_global"
_STATE_PREFIX = "runtime_feature:"

_SECRET_PATTERNS = [
    re.compile(r"(?i)\b(sk-[A-Za-z0-9_-]{8,})\b"),
    re.compile(r"(?i)\b((?:api[_-]?key|token|secret|password)\s*=\s*)\S+"),
]


@dataclass(frozen=True)
class RuntimeFeatureDefinition:
    feature_id: str
    title: str
    description: str
    default_enabled: bool
    category: str
    runtime_affecting: bool
    experimental: bool
    safety_notes: str
    enforcement_allowed_default: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "default_enabled": self.default_enabled,
            "runtime_affecting": self.runtime_affecting,
            "experimental": self.experimental,
            "safety": {
                "enforcement_allowed_default": self.enforcement_allowed_default,
                "requires_explicit_enable": not self.default_enabled,
                "notes": self.safety_notes,
            },
        }


FEATURE_DEFINITIONS: Dict[str, RuntimeFeatureDefinition] = {
    "runtime.benchmark_harness": RuntimeFeatureDefinition(
        feature_id="runtime.benchmark_harness",
        title="Production evaluation harness",
        description="Run isolated upstream-vs-branch runtime benchmark surfaces.",
        default_enabled=False,
        category="evaluation",
        runtime_affecting=True,
        experimental=True,
        safety_notes="Local/dev only; must not change memory approval or enforcement state.",
    ),
    "runtime.health_sidecar": RuntimeFeatureDefinition(
        feature_id="runtime.health_sidecar",
        title="Runtime health sidecar",
        description="Scan durable runtime state for stale or degraded worker activity.",
        default_enabled=False,
        category="orchestration",
        runtime_affecting=True,
        experimental=True,
        safety_notes="Audit/recovery metadata only; foreground execution must remain non-blocking.",
    ),
    "runtime.restart_recovery": RuntimeFeatureDefinition(
        feature_id="runtime.restart_recovery",
        title="Restart recovery loader",
        description="Reload safe-to-resume runtime state after process restart.",
        default_enabled=False,
        category="orchestration",
        runtime_affecting=True,
        experimental=True,
        safety_notes="Must preserve allocator, tenant, repo, and approved-memory boundaries.",
    ),
    "runtime.task_graph": RuntimeFeatureDefinition(
        feature_id="runtime.task_graph",
        title="Supervisor task graph",
        description="Create supervisor-owned parallel task graph state helpers.",
        default_enabled=False,
        category="orchestration",
        runtime_affecting=True,
        experimental=True,
        safety_notes="Supervisor validation remains authoritative; no worker auto-completion.",
    ),
}

FEATURE_IDS = tuple(sorted(FEATURE_DEFINITIONS))


def _now_iso(now: Optional[float] = None) -> str:
    timestamp = time.time() if now is None else float(now)
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _scope_value(value: Optional[str]) -> str:
    value = (value or "").strip()
    return value or _GLOBAL_SCOPE


def _scope_dict(tenant_id: Optional[str] = None, repo_id: Optional[str] = None) -> Dict[str, Optional[str]]:
    return {
        "tenant_id": tenant_id or None,
        "repo_id": repo_id or None,
    }


def _state_key(feature_id: str, *, tenant_id: Optional[str] = None, repo_id: Optional[str] = None) -> str:
    return f"{_STATE_PREFIX}{_scope_value(tenant_id)}:{_scope_value(repo_id)}:{feature_id}"


def _require_feature(feature_id: str) -> RuntimeFeatureDefinition:
    try:
        return FEATURE_DEFINITIONS[feature_id]
    except KeyError as exc:
        raise ValueError(f"unknown runtime feature: {feature_id}") from exc


def _redact_reason(reason: str) -> str:
    redacted = " ".join(str(reason).split())
    for pattern in _SECRET_PATTERNS:
        def _replace(match: re.Match[str]) -> str:
            if match.lastindex:
                return f"{match.group(1)}[REDACTED]"
            return "[REDACTED]"

        redacted = pattern.sub(_replace, redacted)
    if len(redacted) > MAX_REASON_LENGTH:
        redacted = redacted[: MAX_REASON_LENGTH - 3].rstrip() + "..."
    return redacted


def _load_override(
    db: SessionDB,
    feature_id: str,
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    raw = db.get_meta(_state_key(feature_id, tenant_id=tenant_id, repo_id=repo_id))
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except Exception:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("enabled"), bool):
        return None
    return value


def _state_payload(
    definition: RuntimeFeatureDefinition,
    *,
    scope: Dict[str, Optional[str]],
    override: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    enabled = bool(override["enabled"]) if override is not None else bool(definition.default_enabled)
    payload = {
        "feature_id": definition.feature_id,
        "enabled": enabled,
        "effective": enabled,
        "source": "override" if override is not None else "default",
        "default_enabled": bool(definition.default_enabled),
        "override": override,
        "scope": scope,
        "reason": None,
        "updated_at": None,
        "safety": definition.to_dict()["safety"],
        "enforcement_allowed": False,
    }
    if override is not None:
        payload["reason"] = override.get("reason")
        payload["updated_at"] = override.get("updated_at")
    return payload


def list_runtime_features(
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return deterministic feature metadata without reading or writing state."""

    return {
        "schema_version": 1,
        "scope": _scope_dict(tenant_id, repo_id),
        "features": [FEATURE_DEFINITIONS[feature_id].to_dict() for feature_id in FEATURE_IDS],
    }


def resolve_runtime_feature(
    db: SessionDB,
    feature_id: str,
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
) -> Dict[str, Any]:
    definition = _require_feature(feature_id)
    override = _load_override(db, feature_id, tenant_id=tenant_id, repo_id=repo_id)
    return _state_payload(definition, scope=_scope_dict(tenant_id, repo_id), override=override)


def status_runtime_features(
    db: SessionDB,
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "scope": _scope_dict(tenant_id, repo_id),
        "features": [
            resolve_runtime_feature(db, feature_id, tenant_id=tenant_id, repo_id=repo_id)
            for feature_id in FEATURE_IDS
        ],
    }


def set_runtime_feature_override(
    db: SessionDB,
    feature_id: str,
    *,
    enabled: bool,
    reason: str,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    definition = _require_feature(feature_id)
    clean_reason = _redact_reason(reason)
    if not clean_reason:
        raise ValueError("reason is required for runtime feature changes")

    override = {
        "feature_id": feature_id,
        "enabled": bool(enabled),
        "scope": _scope_dict(tenant_id, repo_id),
        "reason": clean_reason,
        "updated_at": _now_iso(now),
        "source": "override",
        "enforcement_allowed": False,
    }
    db.set_meta(
        _state_key(feature_id, tenant_id=tenant_id, repo_id=repo_id),
        json.dumps(override, sort_keys=True, ensure_ascii=True),
    )
    return _state_payload(definition, scope=_scope_dict(tenant_id, repo_id), override=override)


def parse_feature_enabled(value: str) -> bool:
    normalized = str(value).strip().lower()
    if normalized == "on":
        return True
    if normalized == "off":
        return False
    raise ValueError("feature state must be 'on' or 'off'")
