"""Named model-role configuration for supervisor sidecars.

These roles are operationally distinct. Programmatic sidecars do not call a
model, cheap sidecars perform bounded extraction/confirmation, strong sidecars
judge or curate only when confidence or approval policy requires it, and Codex
is reserved for code-critical review. This module centralizes the config paths
so CLI, backend, and docs do not drift.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, Optional


DEFAULT_SIDECAR_MODEL_TIERS: Dict[str, Dict[str, Any]] = {
    "programmatic": {
        "description": "No LLM call; deterministic/indexing work only.",
        "provider": "none",
        "model": "none",
        "allow_llm": False,
        "timeout_seconds": 60,
    },
    "cheap_reasoning": {
        "description": "Cheap reasoning for bounded confirmation and extraction sidecars.",
        "provider": "cerebras",
        "model": "gpt-oss-120b",
        "allow_llm": True,
        "timeout_seconds": 60,
        "max_tokens": 2048,
    },
    "strong_reasoning": {
        "description": "Strong reasoning for judges, approval gates, and high-impact curation.",
        "provider": "deepseek",
        "model": "deepseek-reasoner",
        "allow_llm": True,
        "timeout_seconds": 180,
        "max_tokens": 4096,
    },
    "code_critical": {
        "description": "Codex tier reserved for code-critical review and review judges.",
        "provider": "codex",
        "model": "codex",
        "allow_llm": True,
        "timeout_seconds": 300,
    },
}

TIER_ALIASES = {
    "low_cost_reasoning": "cheap_reasoning",
    "balanced_reasoning": "strong_reasoning",
}


ROLE_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "progress_summarizer": {
        "path": ("sidecar_roles", "progress_summarizer"),
        "description": "Summarizes worker progress into compact checkpoints.",
        "tier": "cheap_reasoning",
        "defaults": {"enabled": True, "tier": "cheap_reasoning", "timeout_seconds": 60},
    },
    "classifier": {
        "path": ("sidecar_roles", "classifier"),
        "description": "Classifies task and event metadata programmatically.",
        "tier": "programmatic",
        "defaults": {"enabled": True, "tier": "programmatic", "timeout_seconds": 60},
    },
    "extraction": {
        "path": ("sidecar_roles", "extraction"),
        "description": "Extracts bounded facts or fields from already-scoped inputs.",
        "tier": "cheap_reasoning",
        "defaults": {"enabled": True, "tier": "cheap_reasoning", "timeout_seconds": 60},
    },
    "curator": {
        "path": ("supervisor", "curator"),
        "description": "Offline learning curator that synthesizes advisory candidates from evidence.",
        "tier": "strong_reasoning",
        "defaults": {
            "enabled": True,
            "mode": "advisory",
            "approval_required": True,
            "timeout_seconds": 180,
        },
    },
    "learning_judge": {
        "path": ("supervisor", "learning_judge"),
        "description": "Approval gate for proposed memory, policy, wiki, and training candidates.",
        "tier": "strong_reasoning",
        "defaults": {
            "enabled": True,
            "timeout_seconds": 180,
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
            "api_key": "",
            "timeout": 180,
            "max_tokens": 4096,
            "extra_body": {},
        },
    },
    "discussion_capture": {
        "path": ("supervisor", "sidecar_models", "discussion_capture"),
        "description": "Summarizes conversations into discussion memory candidates.",
        "tier": "cheap_reasoning",
        "defaults": {"enabled": True, "tier": "cheap_reasoning", "timeout_seconds": 60},
    },
    "claim_extractor": {
        "path": ("supervisor", "sidecar_models", "claim_extractor"),
        "description": "Extracts scoped claims, assumptions, decisions, and open questions from discussion summaries.",
        "tier": "cheap_reasoning",
        "defaults": {"enabled": True, "tier": "cheap_reasoning", "timeout_seconds": 60},
    },
    "wiki_compiler": {
        "path": ("supervisor", "sidecar_models", "wiki_compiler"),
        "description": "Compiles approved discussion claims into durable wiki pages and index payloads.",
        "tier": "strong_reasoning",
        "defaults": {"enabled": True, "tier": "strong_reasoning", "timeout_seconds": 180},
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
        "defaults": {"enabled": True, "mode": "deterministic_first", "tier": "cheap_reasoning", "timeout_seconds": 60},
    },
    "policy_review": {
        "path": ("sidecar_roles", "policy_review"),
        "description": "Reviews proposed advisory policies before operator approval.",
        "tier": "strong_reasoning",
        "defaults": {"enabled": True, "tier": "strong_reasoning", "timeout_seconds": 180},
    },
    "code_review_judge": {
        "path": ("sidecar_roles", "code_review_judge"),
        "description": "Reviews code-critical findings with the reserved Codex tier.",
        "tier": "code_critical",
        "defaults": {"enabled": True, "tier": "code_critical", "timeout_seconds": 300},
    },
    "training_corpus_review": {
        "path": ("sidecar_roles", "training_corpus_review"),
        "description": "Reviews approved training corpus export candidates.",
        "tier": "strong_reasoning",
        "defaults": {"enabled": True, "tier": "strong_reasoning", "timeout_seconds": 180},
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


def _canonical_tier_name(tier: str) -> str:
    return TIER_ALIASES.get(str(tier), str(tier))


def _merge_tier(tiers: Dict[str, Dict[str, Any]], name: str, value: Dict[str, Any]) -> None:
    canonical = _canonical_tier_name(name)
    tier = tiers.setdefault(canonical, {})
    tier.update(value)


def list_model_tiers(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    tiers = deepcopy(DEFAULT_SIDECAR_MODEL_TIERS)
    configured = config.get("supervisor", {}).get("sidecar_model_tiers", {})
    if isinstance(configured, dict):
        for name, value in configured.items():
            if isinstance(value, dict):
                _merge_tier(tiers, str(name), value)
    configured = config.get("sidecar_tiers", {})
    if isinstance(configured, dict):
        for name, value in configured.items():
            if isinstance(value, dict):
                _merge_tier(tiers, str(name), value)
    for alias, canonical in TIER_ALIASES.items():
        if canonical in tiers:
            tiers[alias] = deepcopy(tiers[canonical])
    return tiers


def get_model_tier(config: Dict[str, Any], tier: str) -> Dict[str, Any]:
    tiers = list_model_tiers(config)
    tier_name = _canonical_tier_name(tier)
    if tier_name not in tiers:
        raise ValueError(f"unknown model tier: {tier}")
    result = deepcopy(tiers[tier_name])
    result["tier"] = tier_name
    return result


def get_model_role(config: Dict[str, Any], role: str) -> Dict[str, Any]:
    definition = ROLE_DEFINITIONS[role]
    role_config = _get_role_container(config, role, create=False)
    top_level_roles = config.get("sidecar_roles", {})
    top_level_role_tier = None
    if isinstance(top_level_roles, dict):
        value = top_level_roles.get(role)
        if isinstance(value, str):
            top_level_role_tier = value
        elif isinstance(value, dict):
            role_config = {**role_config, **value}
            top_level_role_tier = value.get("tier")
    tier_name = str(
        top_level_role_tier
        or role_config.get("tier")
        or definition.get("tier")
        or definition.get("defaults", {}).get("tier")
        or "strong_reasoning"
    )
    tier_name = _canonical_tier_name(tier_name)
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
    tier_name = _canonical_tier_name(tier_name)
    get_model_tier(config, tier_name)
    tiers = config.setdefault("sidecar_tiers", {})
    if not isinstance(tiers, dict):
        raise ValueError("invalid config shape at sidecar_tiers")
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


def sidecar_role_mapping(config: Dict[str, Any]) -> Dict[str, str]:
    return {role: get_model_role(config, role)["tier"] for role in role_names()}


def plan_sidecar_route(
    config: Dict[str, Any],
    role: str,
    *,
    retrieval_result: str = "miss",
    confidence: Optional[float] = None,
    promotion_requested: bool = False,
    enforcement_requested: bool = False,
) -> Dict[str, Any]:
    """Return the model tier policy decision for one sidecar role.

    The policy is deliberately conservative: exact persisted lesson matches stay
    programmatic, high-confidence non-promotion paths avoid strong models, and
    promotion/enforcement always requires judge plus operator approval.
    """
    retrieval = str(retrieval_result or "miss").lower()
    needs_approval = bool(promotion_requested or enforcement_requested)
    if retrieval in {"exact", "exact_persisted_lesson", "exact_hit"}:
        tier_name = "programmatic"
        reason = "exact_persisted_lesson_match"
        call_llm = False
    elif needs_approval:
        tier_name = "strong_reasoning"
        reason = "promotion_or_enforcement_requested"
        call_llm = True
    elif confidence is not None and float(confidence) >= 0.75 and role in {"curator", "learning_judge", "policy_review"}:
        tier_name = "programmatic"
        reason = "high_confidence_no_promotion"
        call_llm = False
    elif confidence is not None and float(confidence) < 0.75 and role in {"curator", "learning_judge", "policy_review"}:
        tier_name = "strong_reasoning"
        reason = "low_confidence_requires_strong_judge"
        call_llm = True
    else:
        role_info = get_model_role(config, role)
        tier_name = role_info["tier"]
        tier = get_model_tier(config, tier_name)
        call_llm = bool(tier.get("allow_llm", True))
        reason = "role_default"
    tier = get_model_tier(config, tier_name)
    return {
        "role": role,
        "tier": tier["tier"],
        "provider": tier.get("provider", ""),
        "model": tier.get("model", ""),
        "call_llm": call_llm,
        "reason": reason,
        "requires_judge": needs_approval,
        "requires_operator": needs_approval,
        "enforcement_allowed": False,
    }


_OPERATOR_CONTROL_ACTIONS = {
    "approve_export_bundle",
    "enable_realtime_provider",
    "promote_low_end_eval_finding",
}


def evaluate_operator_control(
    action: str,
    *,
    judge_approved: bool = False,
    operator_approved: bool = False,
) -> Dict[str, Any]:
    action_name = str(action)
    if action_name not in _OPERATOR_CONTROL_ACTIONS:
        raise ValueError(f"unknown operator control action: {action}")
    missing = []
    if not judge_approved:
        missing.append("judge_approval")
    if not operator_approved:
        missing.append("operator_approval")
    return {
        "action": action_name,
        "allowed": not missing,
        "mode": "advisory",
        "requires": ["judge_approval", "operator_approval"],
        "missing": missing,
        "enforcement_allowed": False,
    }


def validate_roles(roles: Iterable[str]) -> list[str]:
    names = role_names()
    invalid = [role for role in roles if role not in names]
    if invalid:
        raise ValueError(f"unknown model role(s): {', '.join(invalid)}")
    return list(roles)
