"""Supervisor runtime orchestration gates.

This module intentionally does not dispatch workers yet. It creates and
validates the packets that future planner/worker dispatch must pass through.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from hermes_cli.config import load_config
from hermes_cli.runtime_packets import (
    PacketValidationResult,
    PlannerPacket,
    SessionSummary,
    SpecKitArtifactSet,
    SupervisorTaskPacket,
    ValidationReport,
    WorkerDelegationPacket,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _as_list(value: Optional[Iterable[str]]) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    return [str(item) for item in value if str(item or "").strip()]


def _runtime_config(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = config or load_config()
    supervisor = cfg.get("supervisor") if isinstance(cfg, dict) else {}
    runtime = supervisor.get("runtime_orchestration") if isinstance(supervisor, dict) else {}
    return runtime if isinstance(runtime, dict) else {}


def infer_complexity(request: str, *, explicit: str = "") -> str:
    if explicit:
        return explicit
    lowered = request.lower()
    if any(marker in lowered for marker in ("implement", "add ", "create ", "refactor", "fix ", "deploy", "build")):
        return "standard"
    if any(marker in lowered for marker in ("inspect", "check", "summarize", "explain", "read")):
        return "trivial"
    return "standard"


def infer_task_type(request: str, *, explicit: str = "") -> str:
    if explicit:
        return explicit
    lowered = request.lower()
    if "spec kit" in lowered or "speckit" in lowered:
        return "speckit_planning"
    if any(marker in lowered for marker in ("implement", "feature", "code", "refactor")):
        return "implementation"
    if any(marker in lowered for marker in ("inspect", "summarize", "review")):
        return "read_only_investigation"
    return "general"


def requires_speckit_for_task(
    *,
    request: str,
    complexity: str,
    task_type: str,
    opt_out: bool = False,
    config: Optional[Dict[str, Any]] = None,
) -> bool:
    runtime = _runtime_config(config)
    if not runtime.get("require_speckit_for_non_trivial", True):
        return False
    if opt_out and runtime.get("allow_user_opt_out", True):
        return False
    trivial_types = set(_as_list(runtime.get("trivial_task_types")))
    if complexity == "trivial" or task_type in trivial_types:
        return False
    return True


def clarification_questions(
    *,
    source: str,
    requires_speckit: bool,
    repo_id: Optional[str],
    cwd: Optional[str],
    success_criteria: Iterable[str],
) -> List[str]:
    questions: List[str] = []
    if requires_speckit and not (repo_id or cwd):
        questions.append("Which repository or working directory should Hermes use?")
    if source == "dashboard" and requires_speckit and not _as_list(success_criteria):
        questions.append("What outcome should count as done from the user's point of view?")
    return questions


@dataclass
class TaskInitializationResult:
    task_packet: SupervisorTaskPacket
    validation: PacketValidationResult
    memory_packet: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": "created" if self.validation.valid else "invalid",
            "task_packet": self.task_packet.to_dict(),
            "validation": self.validation.to_dict(),
            "needs_clarification": self.task_packet.status == "needs_clarification",
            "requires_speckit": self.task_packet.requires_speckit,
            "memory_packet_id": self.task_packet.memory_packet_id,
            "memory_packet": self.memory_packet,
        }


def initialize_task(
    *,
    request: str,
    source: str = "cli",
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    cwd: Optional[str] = None,
    task_type: str = "",
    complexity: str = "",
    success_criteria: Optional[Iterable[str]] = None,
    constraints: Optional[Iterable[str]] = None,
    memory_packet_id: Optional[str] = None,
    skip_speckit: bool = False,
    skip_reason: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    db: Any = None,
    auto_memory_packet: bool = True,
    memory_required: bool = False,
) -> TaskInitializationResult:
    inferred_type = infer_task_type(request, explicit=task_type)
    inferred_complexity = infer_complexity(request, explicit=complexity)
    requires_speckit = requires_speckit_for_task(
        request=request,
        complexity=inferred_complexity,
        task_type=inferred_type,
        opt_out=skip_speckit,
        config=config,
    )
    clarifications = clarification_questions(
        source=source,
        requires_speckit=requires_speckit,
        repo_id=repo_id,
        cwd=cwd,
        success_criteria=success_criteria or [],
    )
    status = "needs_clarification" if clarifications else "planned"
    if skip_speckit and not skip_reason:
        skip_reason = "explicit user opt-out"
    task_packet_id = _new_id("taskpkt")
    memory_packet: Optional[Dict[str, Any]] = None
    if auto_memory_packet and db is not None and not memory_packet_id:
        from hermes_cli.supervisor_memory import create_memory_packet

        packet_result = create_memory_packet(
            db,
            query=request,
            tenant_id=tenant_id,
            repo_id=repo_id,
            task_id=task_packet_id,
            scopes=[
                "runtime.task_initialization",
                f"task_type:{inferred_type}",
                f"complexity:{inferred_complexity}",
            ],
            required=memory_required,
            config=config,
        )
        memory_packet_id = packet_result.packet_id
        memory_packet = packet_result.to_dict()
    packet = SupervisorTaskPacket(
        id=task_packet_id,
        source=source,
        tenant_id=tenant_id,
        repo_id=repo_id,
        cwd=cwd,
        raw_request_summary=request.strip()[:1000],
        task_type=inferred_type,
        complexity=inferred_complexity,
        requires_speckit=requires_speckit,
        clarifications=clarifications,
        memory_packet_id=memory_packet_id,
        success_criteria=_as_list(success_criteria),
        constraints=_as_list(constraints),
        status=status,
        skip_reason=skip_reason if not requires_speckit else None,
    )
    return TaskInitializationResult(task_packet=packet, validation=packet.validate(), memory_packet=memory_packet)


def create_planner_packet(
    task_packet: SupervisorTaskPacket,
    *,
    branch_name: str,
    worktree_path: Optional[str] = None,
    memory_packet_id: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> PlannerPacket:
    task_validation = task_packet.validate()
    if not task_validation.valid:
        raise ValueError(f"invalid task packet: {task_validation.to_dict()}")
    if task_packet.status == "needs_clarification":
        raise ValueError("cannot create planner packet while clarification is required")
    if not task_packet.requires_speckit:
        raise ValueError("planner packet requires a Spec Kit task")
    runtime = _runtime_config(config)
    planner = runtime.get("planner") if isinstance(runtime.get("planner"), dict) else {}
    model = str(planner.get("model") or "gpt-5.5")
    return PlannerPacket(
        id=_new_id("planner"),
        task_packet_id=task_packet.id,
        planner_role=str(planner.get("role") or "planner"),
        preferred_model=model,
        branch_name=branch_name,
        worktree_path=worktree_path,
        required_artifacts=["spec.md", "plan.md", "tasks.md"],
        memory_packet_id=memory_packet_id or task_packet.memory_packet_id,
        return_schema={
            "spec_path": "string",
            "plan_path": "string",
            "tasks_path": "string",
            "assumptions": "list[string]",
            "validation_strategy": "string",
        },
    )


def validate_worker_delegation(packet: WorkerDelegationPacket) -> PacketValidationResult:
    return packet.validate()


def validate_completion(
    *,
    artifact_set: SpecKitArtifactSet,
    validation_report: ValidationReport,
    session_summary: SessionSummary,
) -> PacketValidationResult:
    missing: List[str] = []
    errors: List[str] = []
    for name, packet in (
        ("artifact_set", artifact_set),
        ("validation_report", validation_report),
        ("session_summary", session_summary),
    ):
        result = packet.validate()
        missing.extend([f"{name}.{field}" for field in result.missing])
        errors.extend([f"{name}.{error}" for error in result.errors])
    if artifact_set.artifact_status not in {"validated", "committed"}:
        errors.append("artifact_set must be validated or committed")
    if validation_report.status not in {"passed", "blocked"}:
        errors.append("validation_report status must be passed or blocked")
    return PacketValidationResult(valid=not missing and not errors, missing=missing, errors=errors)


def discover_speckit_artifacts(feature_dir: Path, *, task_packet_id: str, branch_name: str) -> SpecKitArtifactSet:
    spec = feature_dir / "spec.md"
    plan = feature_dir / "plan.md"
    tasks = feature_dir / "tasks.md"
    status = "validated" if spec.exists() and plan.exists() and tasks.exists() else "missing"
    return SpecKitArtifactSet(
        id=_new_id("specart"),
        task_packet_id=task_packet_id,
        branch_name=branch_name,
        spec_path=str(spec),
        plan_path=str(plan),
        tasks_path=str(tasks),
        artifact_status=status,
    )
