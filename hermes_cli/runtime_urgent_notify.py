"""Urgent runtime notification routing.

This module is intentionally small and deterministic. It gives runtime
workers, goal loops, and sidecars a non-LLM path for sending stoppage-class
events to an operator channel without manually subscribing every task.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional


URGENT_SEVERITIES = frozenset({
    "blocked",
    "degraded",
    "needs_operator",
    "goal_paused",
    "fallback_exhausted",
    "failed",
    "timed_out",
    "timeout",
    "empty_output",
    "quota_exhausted",
    "network_degraded",
    "auth_failed",
})


@dataclass(frozen=True)
class UrgentNotification:
    severity: str
    title: str
    message: str
    task_id: Optional[str] = None
    repo_id: Optional[str] = None
    worker_id: Optional[str] = None
    event_kind: Optional[str] = None
    source: str = "runtime"
    created_at: float = 0.0

    def to_message(self) -> str:
        lines = [
            f"[Hermes urgent] {self.title}",
            f"severity: {self.severity}",
        ]
        if self.task_id:
            lines.append(f"task: {self.task_id}")
        if self.repo_id:
            lines.append(f"repo: {self.repo_id}")
        if self.worker_id:
            lines.append(f"worker: {self.worker_id}")
        if self.event_kind:
            lines.append(f"event: {self.event_kind}")
        if self.source:
            lines.append(f"source: {self.source}")
        if self.message:
            lines.extend(["", self.message.strip()])
        return "\n".join(lines).strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "task_id": self.task_id,
            "repo_id": self.repo_id,
            "worker_id": self.worker_id,
            "event_kind": self.event_kind,
            "source": self.source,
            "created_at": self.created_at,
        }


def normalize_severity(value: str | None) -> str:
    return (value or "").strip().lower().replace("-", "_")


def is_urgent_severity(value: str | None) -> bool:
    return normalize_severity(value) in URGENT_SEVERITIES


def event_is_urgent(event: Mapping[str, Any]) -> bool:
    """Return True when an event/status should route to urgent notification."""
    for key in ("severity", "status", "state", "reason", "event_kind", "kind"):
        value = event.get(key)
        if isinstance(value, str) and is_urgent_severity(value):
            return True
    payload = event.get("payload")
    if isinstance(payload, Mapping):
        return event_is_urgent(payload)
    return False


def resolve_urgent_channel(platform: str = "slack") -> Optional[str]:
    """Resolve the configured urgent channel for a platform.

    Slack is the first production target. HERMES_URGENT_CHANNEL is the generic
    cross-platform knob; SLACK_URGENT_CHANNEL is the Slack-specific override.
    Both may be either a raw channel id or a full ``slack:C...`` target.
    """
    platform_key = platform.strip().upper() or "SLACK"
    candidates = [
        os.getenv(f"{platform_key}_URGENT_CHANNEL", ""),
        os.getenv("HERMES_URGENT_CHANNEL", ""),
        os.getenv("SLACK_URGENT_CHANNEL", "") if platform_key == "SLACK" else "",
        os.getenv("SLACK_HOME_CHANNEL", "") if platform_key == "SLACK" else "",
    ]
    for raw in candidates:
        channel = (raw or "").strip()
        if channel:
            return channel
    return None


def resolve_urgent_target(platform: str = "slack") -> Optional[str]:
    channel = resolve_urgent_channel(platform)
    if not channel:
        return None
    if ":" in channel:
        return channel
    return f"{platform.strip().lower() or 'slack'}:{channel}"


def notification_from_event(
    event: Mapping[str, Any],
    *,
    default_title: str = "runtime event needs attention",
) -> UrgentNotification:
    payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
    source = str(event.get("source") or payload.get("source") or "runtime")
    severity = normalize_severity(
        str(event.get("severity") or payload.get("severity") or event.get("status") or payload.get("status") or "needs_operator")
    )
    title = str(event.get("title") or payload.get("title") or default_title)
    message = str(event.get("message") or payload.get("message") or payload.get("summary") or "")
    return UrgentNotification(
        severity=severity,
        title=title,
        message=message,
        task_id=str(event.get("task_id") or payload.get("task_id") or "") or None,
        repo_id=str(event.get("repo_id") or payload.get("repo_id") or "") or None,
        worker_id=str(event.get("worker_id") or payload.get("worker_id") or "") or None,
        event_kind=str(event.get("event_kind") or event.get("kind") or payload.get("event_kind") or payload.get("kind") or "") or None,
        source=source,
        created_at=float(event.get("created_at") or payload.get("created_at") or time.time()),
    )


def send_urgent_notification(
    notification: UrgentNotification,
    *,
    platform: str = "slack",
    dry_run: bool = False,
    sender: Optional[Callable[[dict[str, Any]], str]] = None,
) -> dict[str, Any]:
    """Send one urgent notification through the existing messaging tool."""
    target = resolve_urgent_target(platform)
    payload = {
        "status": "skipped",
        "reason": "urgent channel is not configured",
        "target": target,
        "notification": notification.to_dict(),
    }
    if not target:
        return payload

    message = notification.to_message()
    if dry_run:
        return {
            "status": "dry_run",
            "target": target,
            "message": message,
            "notification": notification.to_dict(),
        }

    if sender is None:
        from hermes_cli.send_cmd import _load_hermes_env

        _load_hermes_env()
        from tools.send_message_tool import send_message_tool

        sender = send_message_tool

    result_raw = sender({"action": "send", "target": target, "message": message})
    try:
        result = json.loads(result_raw) if isinstance(result_raw, str) else dict(result_raw)
    except Exception:
        result = {"raw": result_raw}
    ok = bool(result.get("success")) and not result.get("error")
    return {
        "status": "sent" if ok else "failed",
        "target": target,
        "notification": notification.to_dict(),
        "delivery": result,
    }


__all__ = [
    "URGENT_SEVERITIES",
    "UrgentNotification",
    "event_is_urgent",
    "is_urgent_severity",
    "notification_from_event",
    "resolve_urgent_channel",
    "resolve_urgent_target",
    "send_urgent_notification",
]
