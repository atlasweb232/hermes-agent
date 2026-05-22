"""Foreground context admission guard for supervisor prompt construction.

The supervisor context is a latency and token budget. This module keeps raw
worker streams, command output, logs, and repeated status chatter out of the
model prompt. Full details can still be stored through worker_event_store and
shown in the dashboard by reference.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import re
import time
from typing import Any, Mapping, Sequence

from hermes_cli.redaction_guard import find_secret_like_fragments, redact_text


DEFAULT_DIRECT_TOKEN_BUDGET = 180
DEFAULT_SUMMARY_TOKEN_BUDGET = 900
DEFAULT_FOREGROUND_BUDGET_MS = 75

RAW_KIND_MARKERS = {
    "raw_log",
    "raw_stdout",
    "raw_stderr",
    "terminal_output",
    "worker_stream",
    "watch_stream",
    "sidecar_log",
    "slack_mirror",
    "spec_artifact",
    "full_transcript",
}

IMPORTANT_KIND_MARKERS = {
    "user_request",
    "task_state",
    "validation_result",
    "blocker",
    "approval_request",
    "memory_packet",
    "progress_checkpoint",
}

RAW_TEXT_PATTERNS = (
    re.compile(r"(?im)^diff --git "),
    re.compile(r"(?im)^Traceback \(most recent call last\):"),
    re.compile(r"(?im)^\s*(stdout|stderr|raw log|provider log)\s*[:=]"),
    re.compile(r"(?im)\b(worker-router watch|tail -f|Preparing terminal|preparing terminal)\b"),
    re.compile(r"(?im)\b(Passed: \d+|Failed: \d+|pytest|npm test|dotnet test)\b.*\n", re.M),
)


@dataclass(frozen=True)
class ContextAdmissionPolicy:
    direct_token_budget: int = DEFAULT_DIRECT_TOKEN_BUDGET
    summary_token_budget: int = DEFAULT_SUMMARY_TOKEN_BUDGET
    foreground_budget_ms: int = DEFAULT_FOREGROUND_BUDGET_MS
    repeated_status_threshold: int = 3
    max_direct_chars: int = 1200


@dataclass(frozen=True)
class ContextItem:
    kind: str
    text: str
    source: str = ""
    task_id: str | None = None
    tenant_id: str | None = None
    repo_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContextAdmissionDecision:
    action: str
    reason: str
    estimated_tokens: int
    foreground_budget_ms: int
    elapsed_ms: int
    ref_recommended: bool
    summary_budget_tokens: int
    redaction_required: bool
    item_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_tokens(text: str) -> int:
    """Cheap deterministic estimate suitable for admission gating."""

    stripped = str(text or "").strip()
    if not stripped:
        return 0
    return max(1, len(stripped) // 4)


def text_hash(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:16]


def sanitize_for_context(text: str, *, max_chars: int = 1200) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    return redact_text(compact, max_chars=max_chars)


def _has_raw_marker(item: ContextItem) -> bool:
    kind = str(item.kind or "").casefold()
    source = str(item.source or "").casefold()
    if kind in RAW_KIND_MARKERS or any(marker in kind for marker in RAW_KIND_MARKERS):
        return True
    if any(marker in source for marker in ("terminal", "worker", "watch", "slack", "sidecar")):
        return True
    return any(pattern.search(item.text or "") for pattern in RAW_TEXT_PATTERNS)


def _is_important(item: ContextItem) -> bool:
    kind = str(item.kind or "").casefold()
    return kind in IMPORTANT_KIND_MARKERS or any(marker in kind for marker in IMPORTANT_KIND_MARKERS)


def _repetition_count(item: ContextItem, recent_hashes: Sequence[str] | None) -> int:
    if not recent_hashes:
        return 0
    item_digest = text_hash(item.text)
    return sum(1 for digest in recent_hashes if digest == item_digest)


def decide_context_admission(
    item: ContextItem | Mapping[str, Any],
    *,
    policy: ContextAdmissionPolicy | None = None,
    recent_hashes: Sequence[str] | None = None,
    now: float | None = None,
) -> ContextAdmissionDecision:
    """Return a deterministic context admission decision.

    Actions:
    - admit: safe to include directly in supervisor prompt
    - summarize: summarize/checkpoint before prompt use
    - store_only: preserve outside prompt and reference by id
    - reject: do not use in prompt or storage path
    """

    start = time.monotonic()
    policy = policy or ContextAdmissionPolicy()
    if not isinstance(item, ContextItem):
        item = ContextItem(
            kind=str(item.get("kind") or ""),
            text=str(item.get("text") or item.get("content") or ""),
            source=str(item.get("source") or ""),
            task_id=item.get("task_id"),
            tenant_id=item.get("tenant_id"),
            repo_id=item.get("repo_id"),
            metadata=item.get("metadata") or {},
        )
    tokens = estimate_tokens(item.text)
    digest = text_hash(item.text)
    redaction_required = bool(find_secret_like_fragments(item.text or ""))
    repeats = _repetition_count(item, recent_hashes)
    raw_marker = _has_raw_marker(item)

    if repeats >= policy.repeated_status_threshold:
        action = "store_only"
        reason = "repeated_status"
    elif redaction_required and raw_marker:
        action = "store_only"
        reason = "secret_bearing_raw_content"
    elif raw_marker and tokens > policy.direct_token_budget:
        action = "store_only"
        reason = "raw_or_stream_content"
    elif tokens > policy.summary_token_budget:
        action = "store_only"
        reason = "over_summary_budget"
    elif tokens > policy.direct_token_budget:
        action = "summarize"
        reason = "over_direct_budget"
    elif _is_important(item):
        action = "admit"
        reason = "decision_critical"
    elif raw_marker:
        action = "summarize"
        reason = "raw_marker_requires_summary"
    else:
        action = "admit"
        reason = "within_budget"

    elapsed_ms = int((time.monotonic() - start) * 1000)
    return ContextAdmissionDecision(
        action=action,
        reason=reason,
        estimated_tokens=tokens,
        foreground_budget_ms=int(policy.foreground_budget_ms),
        elapsed_ms=elapsed_ms,
        ref_recommended=action in {"summarize", "store_only"},
        summary_budget_tokens=int(policy.summary_token_budget),
        redaction_required=redaction_required,
        item_hash=digest,
    )
