"""Named model-role configuration for supervisor sidecars.

These roles are operationally distinct even when they all use the Codex
provider. The curator proposes, judges approve/reject, and workers execute.
This module centralizes the config paths so CLI, backend, and docs do not
drift.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, Optional


DEFAULT_SIDECAR_MODEL_TIERS: Dict[str, Dict[str, Any]] = {
    "programmatic": {
        "description": "No LLM call; deterministic/indexing work only.",
        "provider": "",
        "model": "",
        "base_url": "",
        "allow_llm": False,
        "timeout_seconds": 60,
    },
    "low_cost_reasoning": {
        "description": "Cheap hosted reasoning for bounded capture and extraction sidecars.",
        "provider": "deepseek",
        "model": "deepseek-reasoner",
        "base_url": "https://api.deepseek.com",
        "allow_llm": True,
        "timeout_seconds": 180,
    },
    "balanced_reasoning": {
        "description": "Moderate-cost reasoning for synthesis sidecars.",
        "provider": "codex",
        "model": "codex",
        "base_url": "",
        "allow_llm": True,
        "timeout_seconds": 300,
    },
    "strong_reasoning": {
        "description": "Strong reasoning for judges, approval gates, and high-impact curation.",
        "provider": "codex",
        "model": "codex",
        "base_url": "",
        "allow_llm": True,
        "timeout_seconds": 300,
    },
}


ROLE_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "curator": {
        "path": ("supervisor", "curator"),
        "description": "Offline learning curator that synthesizes advisory candidates from evidence.",
        "tier": "strong_reasoning",
        "defaults": {
            "enabled": True,
            "provider": "codex",
            "model": "codex",
            "base_url": "",
            "mode": "advisory",
            "approval_required": True,
            "timeout_seconds": 300,
        },
    },
    "learning_judge": {
        "path": ("supervisor", "learning_judge"),
        "description": "Approval gate for proposed memory, policy, wiki, and training candidates.",
        "tier": "strong_reasoning",
        "defaults": {
            "enabled": True,
            "provider": "codex",
            "model": "codex",
            "base_url": "",
            "timeout_seconds": 300,
            "fail_closed": True,
            "allow_enforcement_approval": False,
        },
    },
    "goal_judge": {
        "path": ("auxiliary", "goal_judge"),
        "description": "Continuation judge for native /goal and supervisor-owned task goals.",
        "tier": "strong_reasoning",
        "defaults": {
            "enabled": True,
            "provider": "codex",
            "model": "codex",
            "base_url": "",
            "api_key": "",
            "timeout": 300,
            "max_tokens": 4096,
            "extra_body": {},
        },
    },
    "discussion_capture": {
        "path": ("supervisor", "sidecar_models", "discussion_capture"),
        "description": "Summarizes conversations into discussion memory candidates.",
        "tier": "low_cost_reasoning",
        "defaults": {"enabled": True, "tier": "low_cost_reasoning", "timeout_seconds": 120},
    },
    "claim_extractor": {
        "path": ("supervisor", "sidecar_models", "claim_extractor"),
        "description": "Extracts scoped claims, assumptions, decisions, and open questions from discussion summaries.",
        "tier": "low_cost_reasoning",
        "defaults": {"enabled": True, "tier": "low_cost_reasoning", "timeout_seconds": 300},
    },
    "wiki_compiler": {
        "path": ("supervisor", "sidecar_models", "wiki_compiler"),
        "description": "Compiles approved discussion claims into durable wiki pages and index payloads.",
        "tier": "balanced_reasoning",
        "defaults": {"enabled": True, "tier": "balanced_reasoning", "timeout_seconds": 300},
    },
    "dreaming": {
        "path": ("supervisor", "sidecar_models", "dreaming"),
        "description": "Tenant/repo-scoped offline proposal synthesis over approved local wiki/memory evidence.",
        "tier": "strong_reasoning",
        "defaults": {"enabled": True, "tier": "strong_reasoning", "timeout_seconds": 300},
    },
    "global_dreaming": {
        "path": ("supervisor", "sidecar_models", "global_dreaming"),
        "description": "Global offline proposal synthesis over approved redacted canonical memory only.",
        "tier": "strong_reasoning",
        "defaults": {"enabled": True, "tier": "strong_reasoning", "timeout_seconds": 300},
    },
    "citation_validator": {
        "path": ("supervisor", "sidecar_models", "citation_validator"),
        "description": "Deterministic-first citation/evidence validator with optional LLM classification.",
        "tier": "low_cost_reasoning",
        "defaults": {"enabled": True, "mode": "deterministic_first", "tier": "low_cost_reasoning", "timeout_seconds": 120},
    },
}


def role_names() -> list[str]:
    return list(ROLE_DEFINITIONS)


def _get_role_container(config: Dict[str, Any], role: str, *, create: bool = False) -> Dict[str, Any]:
    if role not in ROLE_DEFINITIONS:
        raise ValueError(f"unknown model role: {role}")
    current: Any = config
    path = ROLE_DEFINITIONS[role]["path"]
    for key in path:
        if not isinstance(current, dict):
            raise ValueError(f"invalid config shape at {'.'.join(path)}")
        if create:
            node = current.get(key)
            if not isinstance(node, dict):
                node = {}
                current[key] = node
            current = node
        else:
            current = current.get(key, {})
    return current if isinstance(current, dict) else {}


def list_model_tiers(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    tiers = deepcopy(DEFAULT_SIDECAR_MODEL_TIERS)
    configured = config.get("supervisor", {}).get("sidecar_model_tiers", {})
    if isinstance(configured, dict):
        for name, value in configured.items():
            if isinstance(value, dict):
                tier = tiers.setdefault(str(name), {})
                tier.update(value)
    return tiers


def get_model_tier(config: Dict[str, Any], tier: str) -> Dict[str, Any]:
    tiers = list_model_tiers(config)
    if tier not in tiers:
        raise ValueError(f"unknown model tier: {tier}")
    result = deepcopy(tiers[tier])
    result["tier"] = tier
    return result


def get_model_role(config: Dict[str, Any], role: str) -> Dict[str, Any]:
    definition = ROLE_DEFINITIONS[role]
    role_config = _get_role_container(config, role, create=False)
    tier_name = str(
        role_config.get("tier")
        or definition.get("tier")
        or definition.get("defaults", {}).get("tier")
        or "balanced_reasoning"
    )
    tier_config = get_model_tier(config, tier_name)
    data = {
        key: value
        for key, value in tier_config.items()
        if key not in {"description", "tier"}
    }
    data.update(deepcopy(definition["defaults"]))
    data.update(role_config)
    data["tier"] = tier_name
    return {
        "role": role,
        "path": ".".join(definition["path"]),
        "description": definition["description"],
        "tier": tier_name,
        "tier_config": tier_config,
        "config": data,
    }


def list_model_roles(config: Dict[str, Any]) -> list[Dict[str, Any]]:
    return [get_model_role(config, role) for role in role_names()]


def update_model_role(
    config: Dict[str, Any],
    role: str,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    enabled: Optional[bool] = None,
    timeout: Optional[float] = None,
    tier: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    container = _get_role_container(config, role, create=True)
    if tier is not None:
        get_model_tier(config, str(tier))
        container["tier"] = str(tier)
    if provider is not None:
        container["provider"] = str(provider)
    if model is not None:
        container["model"] = str(model)
    if base_url is not None:
        container["base_url"] = str(base_url)
    if enabled is not None:
        container["enabled"] = bool(enabled)
    if timeout is not None:
        timeout_key = "timeout" if role == "goal_judge" else "timeout_seconds"
        container[timeout_key] = float(timeout)
    if extra:
        for key, value in extra.items():
            if value is not None:
                container[str(key)] = value
    return get_model_role(config, role)


def update_model_tier(
    config: Dict[str, Any],
    tier: str,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    allow_llm: Optional[bool] = None,
    timeout: Optional[float] = None,
    description: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    tier_name = str(tier)
    get_model_tier(config, tier_name)
    supervisor = config.setdefault("supervisor", {})
    if not isinstance(supervisor, dict):
        raise ValueError("invalid config shape at supervisor")
    tiers = supervisor.setdefault("sidecar_model_tiers", {})
    if not isinstance(tiers, dict):
        raise ValueError("invalid config shape at supervisor.sidecar_model_tiers")
    container = tiers.setdefault(tier_name, {})
    if not isinstance(container, dict):
        container = {}
        tiers[tier_name] = container
    if provider is not None:
        container["provider"] = str(provider)
    if model is not None:
        container["model"] = str(model)
    if base_url is not None:
        container["base_url"] = str(base_url)
    if allow_llm is not None:
        container["allow_llm"] = bool(allow_llm)
    if timeout is not None:
        container["timeout_seconds"] = float(timeout)
    if description is not None:
        container["description"] = str(description)
    if extra:
        for key, value in extra.items():
            if value is not None:
                container[str(key)] = value
    return get_model_tier(config, tier_name)


def validate_roles(roles: Iterable[str]) -> list[str]:
    names = role_names()
    invalid = [role for role in roles if role not in names]
    if invalid:
        raise ValueError(f"unknown model role(s): {', '.join(invalid)}")
    return list(roles)
