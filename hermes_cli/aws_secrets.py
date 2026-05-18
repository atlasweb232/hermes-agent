"""AWS Secrets Manager reference helpers.

This module intentionally checks secret metadata with ``describe-secret`` only.
It never fetches or prints secret values.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


DEFAULT_PRODUCTION_SECRET_NAMES = [
    "hermes/atlasweb/tinyfish/api_key",
    "hermes/atlasweb/imap/host",
    "hermes/atlasweb/imap/port",
    "hermes/atlasweb/imap/username",
    "hermes/atlasweb/imap/password",
    "hermes/atlasweb/ionos/credentials",
]


@dataclass
class SecretReferenceCheck:
    name: str
    exists: bool
    status: str
    arn: Optional[str] = None
    last_changed_date: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def describe_secret_reference(
    name: str,
    *,
    profile: str = "",
    region: str = "",
    timeout_seconds: float = 20.0,
) -> SecretReferenceCheck:
    command = ["aws"]
    if profile:
        command += ["--profile", profile]
    if region:
        command += ["--region", region]
    command += ["secretsmanager", "describe-secret", "--secret-id", name, "--output", "json"]
    try:
        proc = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError:
        return SecretReferenceCheck(name=name, exists=False, status="aws_cli_missing", error="aws CLI not found")
    except subprocess.TimeoutExpired:
        return SecretReferenceCheck(name=name, exists=False, status="timeout", error="describe-secret timed out")

    if proc.returncode != 0:
        error = (proc.stderr or proc.stdout or "").strip()
        status = "missing" if "ResourceNotFoundException" in error else "error"
        return SecretReferenceCheck(name=name, exists=False, status=status, error=error[:500])

    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        return SecretReferenceCheck(name=name, exists=False, status="invalid_json", error=str(exc))

    return SecretReferenceCheck(
        name=name,
        exists=True,
        status="ok",
        arn=payload.get("ARN"),
        last_changed_date=str(payload.get("LastChangedDate")) if payload.get("LastChangedDate") is not None else None,
    )


def check_secret_references(
    names: Optional[List[str]] = None,
    *,
    profile: str = "",
    region: str = "",
    timeout_seconds: float = 20.0,
) -> Dict[str, Any]:
    names = names or DEFAULT_PRODUCTION_SECRET_NAMES
    checks = [
        describe_secret_reference(
            name,
            profile=profile,
            region=region,
            timeout_seconds=timeout_seconds,
        )
        for name in names
    ]
    return {
        "status": "ok" if all(item.exists for item in checks) else "incomplete",
        "profile": profile or None,
        "region": region or None,
        "secrets": [item.to_dict() for item in checks],
    }
