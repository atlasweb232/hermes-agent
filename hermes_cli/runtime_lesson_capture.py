"""Deterministic runtime lesson capture for repeated tool failures.

This module captures small, evidence-backed operational lessons without
waiting for an LLM or curator pass. The curator can later consolidate or
promote the candidate, but first capture must happen at the moment Hermes
observes a failure pattern and a successful alternative.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
import shlex
from typing import Any, Optional


_SECRET_PATTERNS = [
    re.compile(r"\b(sk-[A-Za-z0-9_-]{12,})\b"),
    re.compile(r"\b([A-Za-z0-9_]{6,}:[A-Za-z0-9_-]{20,})\b"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s]+"),
]


@dataclass
class ToolOutcome:
    tool_name: str
    command: str
    failed: bool
    result_excerpt: str = ""
    session_id: Optional[str] = None
    cwd: Optional[str] = None


@dataclass
class RuntimeLesson:
    candidate_id: str
    record_id: str
    kind: str
    claim: str
    title: str
    body: str
    score: float
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def redact_sensitive_text(text: str, *, max_chars: int = 2000) -> str:
    safe = str(text or "")
    for pattern in _SECRET_PATTERNS:
        safe = pattern.sub("[REDACTED]", safe)
    if len(safe) > max_chars:
        safe = safe[:max_chars] + "...[truncated]"
    return safe


def parse_terminal_failure(result: Any) -> bool:
    if isinstance(result, dict):
        if result.get("error"):
            return True
        exit_code = result.get("exit_code", result.get("returncode"))
        if isinstance(exit_code, int):
            return exit_code != 0
    text = str(result or "")
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parse_terminal_failure(parsed)
    except Exception:
        pass
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "[error]",
            "error executing tool",
            "command failed",
            "exit code",
            "unknown option",
            "usage:",
        )
    )


def _command_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return str(command or "").split()


def _is_failed_claude_router(command: str) -> bool:
    tokens = _command_tokens(command)
    return len(tokens) >= 2 and tokens[0] == "worker-router" and tokens[1] == "claude"


def _is_successful_direct_claude(command: str) -> bool:
    tokens = _command_tokens(command)
    if not tokens or tokens[0] != "claude":
        return False
    if "-p" not in tokens and "--print" not in tokens:
        return False
    for i, token in enumerate(tokens):
        if token == "--model" and i + 1 < len(tokens) and "sonnet" in tokens[i + 1]:
            return True
        if token.startswith("--model=") and "sonnet" in token:
            return True
    return False


def _stable_id(prefix: str, claim: str) -> str:
    digest = hashlib.sha1(claim.strip().lower().encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


class RuntimeLessonObserver:
    """Session-local detector for failure-to-success operational lessons."""

    def __init__(self, *, min_failures: int = 3, max_events: int = 30):
        self.min_failures = min_failures
        self.max_events = max_events
        self._events: list[ToolOutcome] = []
        self._emitted: set[str] = set()

    def observe(self, outcome: ToolOutcome) -> Optional[RuntimeLesson]:
        if outcome.tool_name != "terminal" or not outcome.command:
            return None
        self._events.append(outcome)
        if len(self._events) > self.max_events:
            self._events = self._events[-self.max_events :]
        if outcome.failed or not _is_successful_direct_claude(outcome.command):
            return None

        failures = [
            event
            for event in self._events
            if event.failed and _is_failed_claude_router(event.command)
        ]
        if len(failures) < self.min_failures:
            return None

        claim = (
            'Prefer direct Claude Code invocation `claude --model sonnet -p "<prompt>"` '
            "when `worker-router claude` repeatedly fails on this machine."
        )
        candidate_id = _stable_id("metacand", claim)
        if candidate_id in self._emitted:
            return None
        self._emitted.add(candidate_id)

        failed_commands = [redact_sensitive_text(event.command, max_chars=300) for event in failures[-8:]]
        evidence = {
            "detector": "runtime_lesson_capture.claude_router_fallback",
            "failed_path": "worker-router claude",
            "working_path": "claude --model sonnet -p",
            "failure_count": len(failures),
            "failed_commands": failed_commands,
            "working_command": redact_sensitive_text(outcome.command, max_chars=300),
            "working_result_excerpt": redact_sensitive_text(outcome.result_excerpt, max_chars=800),
            "session_id": outcome.session_id,
            "cwd": outcome.cwd,
            "secret_safe": True,
        }
        body = (
            "Hermes observed repeated `worker-router claude` failures followed by a "
            "successful direct Claude Code invocation. Use the direct command until "
            "the worker-router wrapper is fixed."
        )
        return RuntimeLesson(
            candidate_id=candidate_id,
            record_id=_stable_id("memrec", claim),
            kind="routing_hint",
            claim=claim,
            title="Claude Code direct invocation works after worker-router failures",
            body=body,
            score=0.9,
            evidence=evidence,
        )


def persist_runtime_lesson(db: Any, lesson: RuntimeLesson) -> dict[str, Any]:
    """Persist a lesson as both durable memory and a meta-learning candidate."""
    db.upsert_memory_record(
        record_id=lesson.record_id,
        kind="tool_routing_lesson",
        title=lesson.title,
        body=lesson.body,
        payload_json=lesson.evidence,
        status="active",
        score=lesson.score,
        evidence_uri=f"hermes:runtime-lesson:{lesson.candidate_id}",
    )
    db.upsert_meta_candidate(
        candidate_id=lesson.candidate_id,
        kind=lesson.kind,
        claim=lesson.claim,
        evidence_json=lesson.evidence,
        score=lesson.score,
        status="proposed",
    )
    return {
        "lesson_captured": True,
        "candidate_id": lesson.candidate_id,
        "record_id": lesson.record_id,
        "kind": lesson.kind,
        "claim": lesson.claim,
    }


def append_lesson_capture_note(result: Any, capture: dict[str, Any]) -> Any:
    if not capture or not capture.get("lesson_captured"):
        return result
    note = {
        "runtime_lesson_capture": {
            "status": "captured",
            "candidate_id": capture.get("candidate_id"),
            "record_id": capture.get("record_id"),
            "kind": capture.get("kind"),
            "claim": capture.get("claim"),
        }
    }
    if isinstance(result, dict):
        merged = dict(result)
        merged.update(note)
        return merged
    text = str(result or "")
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            parsed.update(note)
            return json.dumps(parsed, ensure_ascii=False)
    except Exception:
        pass
    return text.rstrip() + "\n\n" + json.dumps(note, ensure_ascii=False)
