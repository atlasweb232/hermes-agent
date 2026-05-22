"""Bounded progress checkpoints for supervisor context."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
import time
from typing import Any, Mapping, Sequence

from hermes_cli.context_admission import estimate_tokens, sanitize_for_context
from hermes_cli.worker_event_store import WorkerEvent


DEFAULT_CHECKPOINT_TOKEN_BUDGET = 750


@dataclass(frozen=True)
class ProgressCheckpoint:
    task_id: str
    status: str
    summary: str
    latest_progress: str
    blocker: str | None = None
    next_action: str | None = None
    validation_refs: list[str] = field(default_factory=list)
    memory_refs: list[str] = field(default_factory=list)
    event_refs: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    estimated_tokens: int = 0
    token_budget: int = DEFAULT_CHECKPOINT_TOKEN_BUDGET
    truncated: bool = False
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean_refs(values: Sequence[Any] | None, *, limit: int = 12) -> list[str]:
    if not values:
        return []
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _infer_blocker(events: Sequence[WorkerEvent | Mapping[str, Any]]) -> str | None:
    for event in events:
        data = event.to_dict() if hasattr(event, "to_dict") else dict(event)
        text = f"{data.get('kind', '')} {data.get('summary', '')}".casefold()
        if any(marker in text for marker in ("blocked", "failed", "timeout", "degraded", "error")):
            return sanitize_for_context(data.get("summary") or data.get("kind") or "blocked", max_chars=180)
    return None


def _event_ref(event: WorkerEvent | Mapping[str, Any]) -> str:
    if hasattr(event, "ref"):
        return str(getattr(event, "ref"))
    return str(event.get("ref") or event.get("event_ref") or event.get("id") or "")


def _event_summary(event: WorkerEvent | Mapping[str, Any]) -> str:
    data = event.to_dict() if hasattr(event, "to_dict") else dict(event)
    text = str(data.get("summary") or data.get("text") or data.get("kind") or "")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 20:
        text = f"{lines[0]}; omitted_stream_lines={len(lines) - 1}"
    elif len(lines) > 1:
        unique: list[str] = []
        for line in lines:
            if line not in unique:
                unique.append(line)
            if len(unique) >= 3:
                break
        omitted = max(0, len(lines) - len(unique))
        text = "; ".join(unique)
        if omitted:
            text = f"{text}; omitted_repeated_lines={omitted}"
    return sanitize_for_context(text, max_chars=220)


def build_progress_checkpoint(
    *,
    task_id: str,
    events: Sequence[WorkerEvent | Mapping[str, Any]],
    task_state: Mapping[str, Any] | None = None,
    validation_refs: Sequence[Any] | None = None,
    memory_refs: Sequence[Any] | None = None,
    artifact_refs: Sequence[Any] | None = None,
    token_budget: int = DEFAULT_CHECKPOINT_TOKEN_BUDGET,
    now: float | None = None,
) -> ProgressCheckpoint:
    task_state = task_state or {}
    budget = max(100, int(token_budget or DEFAULT_CHECKPOINT_TOKEN_BUDGET))
    event_refs = _clean_refs([_event_ref(event) for event in events if _event_ref(event)], limit=12)
    summaries = [_event_summary(event) for event in events[:5]]
    latest_progress = "; ".join(summary for summary in summaries if summary) or "No worker progress events recorded."
    status = str(task_state.get("status") or ("blocked" if _infer_blocker(events) else "running"))
    blocker = task_state.get("blocker") or _infer_blocker(events)
    next_action = task_state.get("next_action") or ("review blocker and decide recovery" if blocker else "continue next validated step")
    headline = sanitize_for_context(task_state.get("summary") or task_state.get("title") or f"Task {task_id}", max_chars=220)

    payload_text = " ".join(
        [
            headline,
            latest_progress,
            str(blocker or ""),
            str(next_action or ""),
            " ".join(event_refs),
            " ".join(_clean_refs(validation_refs)),
            " ".join(_clean_refs(memory_refs)),
        ]
    )
    estimated = estimate_tokens(payload_text)
    truncated = False
    if estimated > budget:
        max_chars = max(300, budget * 4)
        latest_progress = re.sub(r"\s+", " ", latest_progress)[: max_chars // 2].rstrip() + "..."
        headline = headline[: max(80, max_chars // 5)].rstrip()
        estimated = estimate_tokens(" ".join([headline, latest_progress, str(blocker or ""), str(next_action or "")]))
        truncated = True

    return ProgressCheckpoint(
        task_id=str(task_id),
        status=status,
        summary=headline,
        latest_progress=latest_progress,
        blocker=str(blocker) if blocker else None,
        next_action=str(next_action) if next_action else None,
        validation_refs=_clean_refs(validation_refs),
        memory_refs=_clean_refs(memory_refs),
        event_refs=event_refs,
        artifact_refs=_clean_refs(artifact_refs),
        estimated_tokens=estimated,
        token_budget=budget,
        truncated=truncated,
        created_at=time.time() if now is None else float(now),
    )


def build_supervisor_context_packet(
    *,
    checkpoint: ProgressCheckpoint,
    memory_packet: Mapping[str, Any] | None = None,
    max_memory_items: int = 5,
) -> dict[str, Any]:
    """Return prompt-safe supervisor context packet.

    This packet deliberately contains summaries and refs, not raw worker event
    bodies.
    """

    memory_packet = memory_packet or {}
    items = memory_packet.get("items") or memory_packet.get("advisories") or memory_packet.get("claims") or []
    if isinstance(items, list):
        compact_items = items[: max(0, int(max_memory_items))]
    else:
        compact_items = []
    return {
        "context_policy": "checkpoint_and_refs_only",
        "raw_worker_updates_included": False,
        "checkpoint": checkpoint.to_dict(),
        "memory_packet": {
            "packet_id": memory_packet.get("packet_id") or memory_packet.get("id"),
            "items": compact_items,
            "item_count": len(compact_items),
        },
        "evidence_refs": {
            "events": checkpoint.event_refs,
            "validation": checkpoint.validation_refs,
            "memory": checkpoint.memory_refs,
            "artifacts": checkpoint.artifact_refs,
        },
    }
