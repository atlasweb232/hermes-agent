"""Runtime task-start memory injection helpers.

The supervisor should not need the user to explicitly ask for memory.  This
module builds a compact, advisory-only memory packet for the current turn from
approved global lessons.  It is intentionally deterministic and model-free.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any, Dict, Optional

from hermes_cli.global_memory import (
    GlobalPreCurationEvent,
    HydratedMemoryPacket,
    hydrate_task_memory_from_global,
    stable_hash,
)
from hermes_state import SessionDB


@dataclass
class RuntimeMemoryInjectionResult:
    status: str
    context: str
    event: GlobalPreCurationEvent
    packet: Optional[HydratedMemoryPacket] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "context": self.context,
            "event": self.event.to_dict(),
            "packet": self.packet.to_dict() if self.packet else None,
            "reason": self.reason,
        }


def _normalize_text(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip().casefold()
    text = re.sub(r"[^\w\s:/.-]", "", text)
    return text


def _repo_id_from_cwd(cwd: Optional[str]) -> Optional[str]:
    if not cwd:
        return None
    name = os.path.basename(os.path.abspath(cwd))
    return name or None


def infer_runtime_memory_event(
    user_message: str,
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    cwd: Optional[str] = None,
) -> GlobalPreCurationEvent:
    """Classify a user turn into the retrieval metadata used by memory wiki.

    This is deliberately conservative.  It extracts hard metadata that is safe
    to use for retrieval, while leaving broad semantic interpretation to the
    existing normalized text and simhash paths.
    """

    normalized = _normalize_text(user_message)
    tool = ""
    task_type = "general_task"
    worker_kind = ""
    failure_signature = ""

    if re.search(r"\bclaude(?:\s+code)?\b", normalized):
        tool = "claude"
        worker_kind = "claude-code"
        task_type = "worker_routing"
    elif "codex" in normalized:
        tool = "codex"
        worker_kind = "codex"
        task_type = "worker_routing"
    elif "deepseek" in normalized:
        tool = "deepseek"
        worker_kind = "deepseek"
        task_type = "worker_routing"

    if "worker-router" in normalized and tool:
        failure_signature = f"cmd:worker-router:{tool}:parse-error"

    event_id = f"rtmem_{stable_hash([tenant_id or '', repo_id or '', normalized])[:16]}"
    return GlobalPreCurationEvent(
        event_id=event_id,
        tenant_id=tenant_id,
        repo_id=repo_id or _repo_id_from_cwd(cwd),
        task_type=task_type,
        tool=tool,
        worker_kind=worker_kind,
        failure_signature=failure_signature,
        normalized_text=normalized,
        sensitivity="internal",
        metadata={"source": "runtime_task_start", "cwd": cwd or ""},
    )


def format_runtime_memory_context(packet: HydratedMemoryPacket, *, max_items: int = 3) -> str:
    if packet.status != "ready" or not packet.advisory_items:
        return ""
    lines = [
        "[Hermes runtime memory advisory]",
        "Use only as advisory context. Explicit user instructions, git, tests, and logs are more authoritative.",
    ]
    for item in packet.advisory_items[: max(1, int(max_items))]:
        text = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()
        if not text:
            continue
        source = item.get("source") or "memory"
        confidence = item.get("confidence")
        item_id = item.get("global_lesson_id") or item.get("id") or ""
        suffix = f"source={source}"
        if confidence is not None:
            suffix += f", confidence={confidence}"
        if item_id:
            suffix += f", id={item_id}"
        lines.append(f"- {text} ({suffix})")
    return "\n".join(lines) if len(lines) > 2 else ""


def build_runtime_memory_context(
    db: SessionDB,
    user_message: str,
    *,
    config: Optional[Dict[str, Any]] = None,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    cwd: Optional[str] = None,
    token_budget: int = 600,
) -> RuntimeMemoryInjectionResult:
    cfg = ((config or {}).get("supervisor") or {}).get("runtime_memory_injection") or {}
    if cfg.get("enabled") is False:
        event = infer_runtime_memory_event(user_message, tenant_id=tenant_id, repo_id=repo_id, cwd=cwd)
        return RuntimeMemoryInjectionResult(status="disabled", context="", event=event, reason="disabled")

    event = infer_runtime_memory_event(user_message, tenant_id=tenant_id, repo_id=repo_id, cwd=cwd)
    min_chars = int(cfg.get("min_query_chars") or 8)
    if len(event.normalized_text) < min_chars:
        return RuntimeMemoryInjectionResult(status="empty", context="", event=event, reason="query_too_short")

    packet = hydrate_task_memory_from_global(
        db,
        event,
        config=config,
        hot_limit=int(cfg.get("hot_limit") or 3),
        global_limit=int(cfg.get("global_limit") or 3),
        token_budget=int(token_budget or cfg.get("token_budget") or 600),
        ttl_seconds=int(cfg.get("packet_ttl_seconds") or 3600),
    )
    context = format_runtime_memory_context(packet, max_items=int(cfg.get("max_items") or 3))
    return RuntimeMemoryInjectionResult(
        status="ready" if context else packet.status,
        context=context,
        event=event,
        packet=packet,
        reason="" if context else "no_advisory_items",
    )
