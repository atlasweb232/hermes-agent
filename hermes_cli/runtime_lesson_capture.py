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
_SAFE_HERMES_EVIDENCE_REF_RE = re.compile(
    r"^hermes:(?:delegate|allocation|runtime-lesson):[A-Za-z0-9_.:-]{1,260}$"
)

WORKER_COMMAND_FAMILIES = {
    "worker-router",
    "delegate_task",
    "delegate-task",
    "claude",
    "codex",
    "deepseek",
    "cursor",
    "gemini",
    "qwen",
    "minimax",
}


@dataclass
class ToolOutcome:
    tool_name: str
    command: str
    failed: bool
    result_excerpt: str = ""
    session_id: Optional[str] = None
    cwd: Optional[str] = None
    duration_seconds: float = 0.0
    status: str = ""


@dataclass
class RuntimeLesson:
    record_id: str
    kind: str
    claim: str
    title: str
    body: str
    score: float
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeFailureGate:
    status: str
    reason: str = ""
    last_failed_family: str = ""
    last_failed_command: str = ""
    last_failed_status: str = ""
    last_successful_worker_family: str = ""
    failure_count: int = 0
    requires_disclosure: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DelegatedWorkerRuntimeFailure:
    record_id: str
    task_id: str
    worker_id: str
    route: str
    command_family: str
    status: str
    evidence_refs: list[str] = field(default_factory=list)
    validation_mismatch: dict[str, Any] = field(default_factory=dict)
    output_excerpt: str = ""
    error_excerpt: str = ""
    session_id: Optional[str] = None
    allocation_id: Optional[str] = None
    attempt_id: Optional[str] = None
    secret_safe: bool = True
    requires_judge: bool = True
    operator_approval_required: bool = True

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


def _progress_only_worker_router_output(output: str) -> bool:
    lines = [line.strip() for line in str(output or "").splitlines() if line.strip()]
    if not lines:
        return True
    progress_pattern = re.compile(
        r"^\d{4}-\d{2}-\d{2}T\S+\s+worker=\S+\s+phase=\S+"
    )
    return all(progress_pattern.match(line) for line in lines)


def classify_terminal_status(
    result: Any,
    *,
    failed: bool,
    duration_seconds: float = 0.0,
    command: str = "",
) -> str:
    data: dict[str, Any] = {}
    if isinstance(result, dict):
        data = result
    else:
        try:
            parsed = json.loads(str(result or ""))
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            data = {}

    text = str(result or "")
    lowered = text.lower()
    exit_code = data.get("exit_code", data.get("returncode"))
    error = str(data.get("error") or "")
    output = str(data.get("output", data.get("stdout", "")) or "")
    if exit_code == 124 or "timed out" in lowered or "timeout" in error.lower():
        return "timed_out"
    if failed or (isinstance(exit_code, int) and exit_code != 0) or error:
        return "failed"
    if _worker_command_family(command) == "worker-router" and _progress_only_worker_router_output(output):
        return "empty_output"
    if isinstance(exit_code, int) and exit_code == 0 and not output.strip():
        return "empty_output"
    if float(duration_seconds or 0.0) >= 60.0 and not output.strip():
        return "empty_output"
    return "success"


def _command_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return str(command or "").split()


def _is_failed_claude_router(command: str) -> bool:
    tokens = _command_tokens(command)
    if len(tokens) >= 2 and tokens[0] == "worker-router" and tokens[1] == "claude":
        return True
    return (
        len(tokens) >= 3
        and tokens[0] == "hermes"
        and tokens[1] == "worker-router"
        and tokens[2] == "claude"
    )


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


def _command_family(command: str) -> str:
    """Return a coarse command family for generic supervisor telemetry.

    The family deliberately avoids provider-specific rules. It groups wrapper
    invocations by the first executable so repeated attempts through any router
    or CLI can be detected without hardcoding every possible failure mode.
    """
    tokens = _command_tokens(command)
    if not tokens:
        return "unknown"
    executable = tokens[0]
    if executable in {"delegate_task", "delegate-task"}:
        return "delegate_task"
    if executable in {"sudo", "env", "timeout", "time"} and len(tokens) > 1:
        executable = tokens[1]
    if executable == "hermes" and len(tokens) > 1:
        return "hermes"
    return executable


def _route_family(route: str) -> str:
    route_text = str(route or "").strip()
    if not route_text:
        return "unknown"
    if route_text.startswith("delegate_task") or route_text.startswith("delegate-task"):
        return "delegate_task"
    return _worker_command_family(route_text) or _command_family(route_text)


def _worker_command_family(command: str) -> str:
    tokens = _command_tokens(command)
    if not tokens:
        return ""
    if tokens[0] in WORKER_COMMAND_FAMILIES:
        return tokens[0]
    if tokens[0] == "hermes" and len(tokens) > 1 and tokens[1] in WORKER_COMMAND_FAMILIES:
        return tokens[1]
    if len(tokens) > 1 and tokens[0] in {"sudo", "env", "timeout", "time"} and tokens[1] in WORKER_COMMAND_FAMILIES:
        return tokens[1]
    return ""


class RuntimeLessonObserver:
    """Session-local detector for failure-to-success operational lessons."""

    def __init__(
        self,
        *,
        min_failures: int = 3,
        max_events: int = 30,
        generic_min_failures: int = 5,
        long_failure_seconds: float = 60.0,
    ):
        self.min_failures = min_failures
        self.max_events = max_events
        self.generic_min_failures = generic_min_failures
        self.long_failure_seconds = long_failure_seconds
        self._events: list[ToolOutcome] = []
        self._emitted: set[str] = set()

    def runtime_failure_gate(self) -> RuntimeFailureGate:
        worker_events = [event for event in self._events if _worker_command_family(event.command)]
        if not worker_events:
            return RuntimeFailureGate(status="passed")

        failed_events = [
            event
            for event in worker_events
            if event.failed or event.status in {"failed", "timed_out", "empty_output"}
        ]
        if not failed_events:
            return RuntimeFailureGate(status="passed")

        last_failure = failed_events[-1]
        last_failure_index = self._events.index(last_failure)
        last_success = next(
            (
                event
                for event in reversed(worker_events)
                if not event.failed and event.status == "success"
            ),
            None,
        )
        if last_success and self._events.index(last_success) > last_failure_index:
            return RuntimeFailureGate(
                status="passed",
                last_successful_worker_family=_worker_command_family(last_success.command),
            )

        family = _worker_command_family(last_failure.command) or _command_family(last_failure.command)
        return RuntimeFailureGate(
            status="degraded",
            reason="latest worker/agent command did not produce validated successful output",
            last_failed_family=family,
            last_failed_command=redact_sensitive_text(last_failure.command, max_chars=300),
            last_failed_status=last_failure.status or ("failed" if last_failure.failed else "unknown"),
            failure_count=len(failed_events),
            requires_disclosure=True,
        )

    def observe(self, outcome: ToolOutcome) -> Optional[RuntimeLesson]:
        if outcome.tool_name != "terminal" or not outcome.command:
            return None
        if not outcome.status:
            outcome.status = "failed" if outcome.failed else "success"
        self._events.append(outcome)
        if len(self._events) > self.max_events:
            self._events = self._events[-self.max_events :]

        if outcome.failed or not _is_successful_direct_claude(outcome.command):
            generic_lesson = self._observe_generic_supervisor_failure(outcome)
            if generic_lesson is not None:
                return generic_lesson
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
        record_id = _stable_id("memrec", claim)
        if record_id in self._emitted:
            return None
        self._emitted.add(record_id)

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
            record_id=record_id,
            kind="routing_hint",
            claim=claim,
            title="Claude Code direct invocation works after worker-router failures",
            body=body,
            score=0.9,
            evidence=evidence,
        )

    def _observe_generic_supervisor_failure(self, outcome: ToolOutcome) -> Optional[RuntimeLesson]:
        family = _command_family(outcome.command)
        recent = self._events[-self.max_events :]
        recent_failed_family = [
            event
            for event in recent
            if event.failed and _command_family(event.command) == family
        ]
        long_failure = outcome.failed and float(outcome.duration_seconds or 0.0) >= self.long_failure_seconds
        repeated_failure = outcome.failed and len(recent_failed_family) >= self.generic_min_failures
        if long_failure or repeated_failure:
            failure_commands = [
                redact_sensitive_text(event.command, max_chars=300)
                for event in recent_failed_family[-8:]
            ]
            claim = (
                f"Supervisor observed a command-family failure loop for `{family}` "
                "and must change strategy or request operator/judge review before claiming completion."
            )
            record_id = _stable_id("memrec", claim)
            if record_id not in self._emitted:
                self._emitted.add(record_id)
                evidence = {
                    "detector": "runtime_lesson_capture.generic_command_family_failure",
                    "failure_type": "supervisor_tool_loop_failure",
                    "command_family": family,
                    "failure_count": len(recent_failed_family),
                    "duration_seconds": float(outcome.duration_seconds or 0.0),
                    "thresholds": {
                        "generic_min_failures": self.generic_min_failures,
                        "long_failure_seconds": self.long_failure_seconds,
                    },
                    "failed_commands": failure_commands,
                    "last_result_excerpt": redact_sensitive_text(outcome.result_excerpt, max_chars=800),
                    "session_id": outcome.session_id,
                    "cwd": outcome.cwd,
                    "secret_safe": True,
                    "requires_judge": True,
                    "operator_approval_required": True,
                }
                return RuntimeLesson(
                    record_id=record_id,
                    kind="supervisor_tool_loop_failure",
                    claim=claim,
                    title=f"Supervisor command-family loop detected: {family}",
                    body=(
                        "A terminal command family repeatedly failed or exceeded the long-running "
                        "failure threshold. The supervisor must not continue repeating the same "
                        "route or claim success without validated evidence."
                    ),
                    score=0.85 if long_failure else 0.75,
                    evidence=evidence,
                )

        if outcome.failed:
            return None

        prior_failures = [
            event
            for event in recent[:-1]
            if event.failed
            and (
                float(event.duration_seconds or 0.0) >= self.long_failure_seconds
                or sum(
                    1
                    for candidate in recent[:-1]
                    if candidate.failed and _command_family(candidate.command) == _command_family(event.command)
                )
                >= self.generic_min_failures
            )
        ]
        if not prior_failures:
            return None
        failed_family = _command_family(prior_failures[-1].command)
        if failed_family == family:
            return None
        claim = (
            f"Supervisor switched from failed command family `{failed_family}` to `{family}`; "
            "completion requires evidence that the new command satisfies the original task intent."
        )
        record_id = _stable_id("memrec", claim)
        if record_id in self._emitted:
            return None
        self._emitted.add(record_id)
        evidence = {
            "detector": "runtime_lesson_capture.generic_evidence_mismatch",
            "failure_type": "supervisor_evidence_mismatch",
            "failed_command_family": failed_family,
            "substitute_command_family": family,
            "failure_count": sum(1 for event in recent[:-1] if event.failed and _command_family(event.command) == failed_family),
            "failed_commands": [
                redact_sensitive_text(event.command, max_chars=300)
                for event in recent[:-1]
                if event.failed and _command_family(event.command) == failed_family
            ][-8:],
            "substitute_command": redact_sensitive_text(outcome.command, max_chars=300),
            "substitute_result_excerpt": redact_sensitive_text(outcome.result_excerpt, max_chars=800),
            "session_id": outcome.session_id,
            "cwd": outcome.cwd,
            "secret_safe": True,
            "requires_judge": True,
            "operator_approval_required": True,
        }
        return RuntimeLesson(
            record_id=record_id,
            kind="supervisor_evidence_mismatch",
            claim=claim,
            title=f"Supervisor evidence mismatch: {failed_family} -> {family}",
            body=(
                "A supervisor route failed or timed out, then a different command family produced "
                "a result. The result must be treated as unvalidated until an evidence gate proves "
                "it satisfies the original task intent."
            ),
            score=0.9,
            evidence=evidence,
        )


def persist_runtime_lesson(db: Any, lesson: RuntimeLesson) -> dict[str, Any]:
    """Persist a lesson as durable memory.

    Curator policy candidates are generated later by `hermes curator policy-run`.
    Runtime capture intentionally does not create ordinary meta-candidates,
    because generic learning reconciliation may auto-promote those before the
    curator validator has run.
    """
    record_kind = "tool_routing_lesson"
    if lesson.kind in {"supervisor_tool_loop_failure", "supervisor_evidence_mismatch"}:
        record_kind = "supervisor_runtime_failure"
    db.upsert_memory_record(
        record_id=lesson.record_id,
        kind=record_kind,
        title=lesson.title,
        body=lesson.body,
        payload_json=lesson.evidence,
        status="active",
        score=lesson.score,
        evidence_uri=f"hermes:runtime-lesson:{lesson.record_id}",
    )
    return {
        "lesson_captured": True,
        "record_id": lesson.record_id,
        "kind": lesson.kind,
        "claim": lesson.claim,
    }


def _clean_evidence_refs(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    for value in values:
        raw = str(value or "").strip()
        text = (
            raw
            if _SAFE_HERMES_EVIDENCE_REF_RE.fullmatch(raw)
            else redact_sensitive_text(raw, max_chars=300).strip()
        )
        if text:
            cleaned.append(text)
    return cleaned[:20]


def _should_capture_delegated_worker_failure(
    *,
    status: str,
    validation_mismatch: Optional[dict[str, Any]],
    route_substitution: bool,
) -> bool:
    normalized = str(status or "").strip().lower()
    if normalized in {
        "failed",
        "failure",
        "error",
        "timeout",
        "timed_out",
        "empty_output",
        "blocked",
        "cancelled",
        "interrupted",
        "quota_exhausted",
        "auth_failed",
        "network_degraded",
    }:
        return True
    if route_substitution:
        return True
    mismatch = validation_mismatch or {}
    if mismatch:
        validation_status = str(mismatch.get("validation_status") or "").strip().lower()
        if validation_status and validation_status not in {"passed", "success", "ok"}:
            return True
        return True
    return False


def capture_delegated_worker_runtime_failure(
    db: Any,
    *,
    task_id: str,
    worker_id: str,
    route: str,
    status: str,
    evidence_refs: Optional[list[str]] = None,
    validation_mismatch: Optional[dict[str, Any]] = None,
    output_excerpt: str = "",
    error_excerpt: str = "",
    session_id: Optional[str] = None,
    allocation_id: Optional[str] = None,
    attempt_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    expected_route: Optional[str] = None,
) -> dict[str, Any]:
    """Persist a structured delegated-worker runtime failure record.

    The payload is intentionally bounded and redacted. Raw worker streams and
    full logs must stay as external artifacts referenced by evidence URIs.
    """
    task = str(task_id or "").strip()
    worker = str(worker_id or "").strip()
    route_text = str(route or "").strip()
    normalized_status = str(status or "unknown").strip().lower() or "unknown"
    route_substitution = bool(expected_route and str(expected_route).strip() != route_text)
    mismatch = dict(validation_mismatch or {})
    if route_substitution:
        mismatch.setdefault("expected_route", str(expected_route or "").strip())
        mismatch.setdefault("actual_route", route_text)
    if not _should_capture_delegated_worker_failure(
        status=normalized_status,
        validation_mismatch=mismatch,
        route_substitution=route_substitution,
    ):
        return {"runtime_failure_captured": False, "reason": "no_failure"}

    family = _route_family(route_text)
    evidence = _clean_evidence_refs(evidence_refs or [])
    if not evidence:
        if allocation_id and attempt_id:
            evidence = [f"hermes:allocation:{allocation_id}:{attempt_id}"]
        elif task and worker:
            evidence = [f"hermes:delegate:{task}:{worker}"]

    claim_parts = [
        task or "unknown-task",
        worker or "unknown-worker",
        route_text or "unknown-route",
        normalized_status,
        json.dumps(mismatch, sort_keys=True),
        "|".join(evidence),
    ]
    record_id = _stable_id("memrec", "delegated_worker_runtime_failure:" + "|".join(claim_parts))
    failure = DelegatedWorkerRuntimeFailure(
        record_id=record_id,
        task_id=task,
        worker_id=worker,
        route=redact_sensitive_text(route_text, max_chars=300),
        command_family=family,
        status=normalized_status,
        evidence_refs=evidence,
        validation_mismatch={
            redact_sensitive_text(str(key), max_chars=120): redact_sensitive_text(str(value), max_chars=500)
            for key, value in mismatch.items()
        },
        output_excerpt=redact_sensitive_text(output_excerpt, max_chars=800),
        error_excerpt=redact_sensitive_text(error_excerpt, max_chars=800),
        session_id=session_id,
        allocation_id=allocation_id,
        attempt_id=attempt_id,
    )
    payload = failure.to_dict()
    payload.update(
        {
            "detector": "runtime_lesson_capture.delegated_worker_runtime_failure",
            "failure_type": "delegated_worker_runtime_failure",
            "route_substitution": route_substitution,
        }
    )
    db.upsert_memory_record(
        record_id=record_id,
        kind="supervisor_runtime_failure",
        title=f"Delegated worker runtime failure: {worker or family}",
        body=(
            "A delegated worker or allocator attempt failed, produced empty output, "
            "timed out, substituted routes, or failed validation. Treat the result "
            "as advisory-only until validated by supervisor evidence."
        ),
        payload_json=payload,
        status="active",
        score=0.9,
        tenant_id=tenant_id,
        repo_id=repo_id,
        task_id=task or None,
        evidence_uri=evidence[0] if evidence else f"hermes:runtime-lesson:{record_id}",
    )
    return {
        "runtime_failure_captured": True,
        "record_id": record_id,
        "kind": "delegated_worker_runtime_failure",
        "status": normalized_status,
    }


def apply_runtime_failure_gate_to_final_response(
    final_response: str,
    gate: RuntimeFailureGate | dict[str, Any] | None,
) -> str:
    if not final_response or gate is None:
        return final_response
    if isinstance(gate, dict):
        gate = RuntimeFailureGate(**{k: v for k, v in gate.items() if k in RuntimeFailureGate.__dataclass_fields__})
    if gate.status != "degraded" or not gate.requires_disclosure:
        return final_response

    response = final_response.strip()
    if "Worker delegation degraded:" in response:
        return final_response
    lines = [
        "Worker delegation degraded: the latest worker/agent command did not produce validated successful output.",
        f"- last_failed_family: {gate.last_failed_family or 'unknown'}",
        f"- last_failed_status: {gate.last_failed_status or 'unknown'}",
    ]
    if gate.last_failed_command:
        lines.append(f"- last_failed_command: `{gate.last_failed_command}`")
    lines.append("The answer below is supervisor fallback unless separately validated.")
    return "\n".join(lines) + "\n\n" + response


def append_lesson_capture_note(result: Any, capture: dict[str, Any]) -> Any:
    if not capture or not capture.get("lesson_captured"):
        return result
    note = {
        "runtime_lesson_capture": {
            "status": "captured",
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
