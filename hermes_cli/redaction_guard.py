"""Central pre-persistence redaction guard for runtime learning surfaces.

This module is intentionally deterministic and dependency-free. Persistence
paths should call it before writing evidence, events, dashboard DTOs, Slack
messages, or corpus records. It redacts values instead of deleting whole
records so operators keep useful structure without leaking credentials.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import json
import re
from typing import Any, Mapping


REDACTED = "[REDACTED]"

SAFE_TOKEN_METRIC_KEYS = {
    "admitted_tokens",
    "completion_tokens",
    "context_admitted_tokens",
    "estimated_tokens",
    "input_tokens",
    "memory_packet_tokens",
    "memory_tokens",
    "output_tokens",
    "prompt_tokens",
    "token_budget",
    "token_estimate",
    "tokens",
    "total_tokens",
}

SAFE_RAW_STATE_KEYS = {
    "raw_logs_loaded",
    "raw_transcripts_included",
    "raw_transcripts_loaded",
}

SENSITIVE_KEY_PARTS = (
    "access_token",
    "api_key",
    "apikey",
    "auth_token",
    "authorization",
    "bearer",
    "client_secret",
    "connector_credential",
    "credential",
    "password",
    "private_api_key",
    "provider_log",
    "raw_log",
    "raw_logs",
    "raw_stderr",
    "raw_stdout",
    "raw_transcript",
    "refresh_token",
    "secret",
    "signing_secret",
)

SECRET_VALUE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{7,}\b"),
    re.compile(r"\bcsk-[A-Za-z0-9][A-Za-z0-9_-]{7,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9_]{12,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{12,}\b"),
    re.compile(r"\bxapp-[A-Za-z0-9-]{12,}\b"),
    re.compile(r"\bAPIM[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b\d{5,12}:[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(
        r"(?i)\b(api[_-]?key|apikey|auth[_-]?token|access[_-]?token|refresh[_-]?token|"
        r"token|secret|password|authorization|client[_-]?secret|credential)\s*[:=]\s*"
        r"['\"]?[^'\"\s,;}\]]+"
    ),
)


@dataclass(frozen=True)
class RedactionReport:
    status: str
    redacted_fields: int = 0
    redacted_values: int = 0
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_sensitive_key(key: str) -> bool:
    lowered = str(key or "").casefold()
    if lowered in SAFE_TOKEN_METRIC_KEYS or lowered in SAFE_RAW_STATE_KEYS:
        return False
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def redact_text(text: Any, *, max_chars: int | None = None) -> str:
    safe = str(text or "")
    for pattern in SECRET_VALUE_PATTERNS:
        safe = pattern.sub(_redaction_replacement, safe)
    if max_chars is not None and len(safe) > max_chars:
        safe = safe[: max(0, max_chars - 3)].rstrip() + "..."
    return safe


def _redaction_replacement(match: re.Match[str]) -> str:
    text = match.group(0)
    if text.lower().startswith("bearer "):
        return f"Bearer {REDACTED}"
    return REDACTED


def redact_value(value: Any, *, key: str | None = None, max_string_chars: int | None = None) -> Any:
    if is_sensitive_key(key or ""):
        if isinstance(value, (dict, list, tuple)):
            return REDACTED
        return REDACTED if value not in (None, "") else value
    if isinstance(value, Mapping):
        return {str(k): redact_value(v, key=str(k), max_string_chars=max_string_chars) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(item, max_string_chars=max_string_chars) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item, max_string_chars=max_string_chars) for item in value]
    if isinstance(value, str):
        return redact_text(value, max_chars=max_string_chars)
    return value


def redaction_report(value: Any) -> RedactionReport:
    original = _canonical(value)
    redacted = _canonical(redact_value(value))
    findings = find_secret_like_fragments(redacted)
    return RedactionReport(
        status="clean" if not findings else "warning",
        redacted_fields=_count_sensitive_keys(value),
        redacted_values=original.count(REDACTED) + sum(1 for pattern in SECRET_VALUE_PATTERNS if pattern.search(original)),
        warnings=tuple(findings),
    )


def find_secret_like_fragments(value: Any) -> list[str]:
    text = _canonical(value)
    findings: list[str] = []
    for pattern in SECRET_VALUE_PATTERNS:
        matches = list(pattern.finditer(text))
        if any("REDACTED" not in match.group(0) for match in matches):
            findings.append("secret_like_value")
            break
    return findings


def assert_redacted(value: Any) -> None:
    findings = find_secret_like_fragments(value)
    if findings:
        raise ValueError(f"redaction guard found secret-like content: {', '.join(findings)}")


def _count_sensitive_keys(value: Any) -> int:
    if isinstance(value, Mapping):
        count = 0
        for key, item in value.items():
            count += 1 if is_sensitive_key(str(key)) else 0
            count += _count_sensitive_keys(item)
        return count
    if isinstance(value, (list, tuple)):
        return sum(_count_sensitive_keys(item) for item in value)
    return 0


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=True)
    except Exception:
        return str(value)
