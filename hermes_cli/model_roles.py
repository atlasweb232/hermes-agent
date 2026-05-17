"""Named model-role configuration for supervisor sidecars.

These roles are operationally distinct even when they all use the Codex
provider. The curator proposes, judges approve/reject, and workers execute.
This module centralizes the config paths so CLI, backend, and docs do not
drift.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, Optional


ROLE_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "curator": {
        "path": ("supervisor", "curator"),
        "description": "Offline learning curator that synthesizes advisory candidates from evidence.",
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


def get_model_role(config: Dict[str, Any], role: str) -> Dict[str, Any]:
    definition = ROLE_DEFINITIONS[role]
    data = deepcopy(definition["defaults"])
    data.update(_get_role_container(config, role, create=False))
    return {
        "role": role,
        "path": ".".join(definition["path"]),
        "description": definition["description"],
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
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    container = _get_role_container(config, role, create=True)
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


def validate_roles(roles: Iterable[str]) -> list[str]:
    names = role_names()
    invalid = [role for role in roles if role not in names]
    if invalid:
        raise ValueError(f"unknown model role(s): {', '.join(invalid)}")
    return list(roles)
