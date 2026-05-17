"""Runtime orchestration packet schemas.

The supervisor protocol uses these packets as deterministic gates around
planning, delegation, validation, and summary persistence. Prompt templates can
guide model behavior, but these schemas define the minimum runtime contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional


def _clean_list(value: Optional[Iterable[str]]) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    return [str(item) for item in value if str(item or "").strip()]


def _missing_required(data: Dict[str, Any], fields: Iterable[str]) -> List[str]:
    missing: List[str] = []
    for field_name in fields:
        value = data.get(field_name)
        if value is None or value == "" or value == [] or value == {}:
            missing.append(field_name)
    return missing


@dataclass
class PacketValidationResult:
    valid: bool
    missing: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RuntimePacket:
    """Base helper for packet dataclasses."""

    required_fields: tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)  # type: ignore[arg-type]

    def validate(self) -> PacketValidationResult:
        data = self.to_dict()
        missing = _missing_required(data, self.required_fields)
        return PacketValidationResult(valid=not missing, missing=missing)


@dataclass
class SupervisorTaskPacket(RuntimePacket):
    id: str
    source: str
    raw_request_summary: str
    task_type: str
    complexity: str
    requires_speckit: bool
    tenant_id: Optional[str] = None
    repo_id: Optional[str] = None
    cwd: Optional[str] = None
    clarifications: List[str] = field(default_factory=list)
    memory_packet_id: Optional[str] = None
    success_criteria: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    status: str = "intake"
    skip_reason: Optional[str] = None

    required_fields = ("id", "source", "raw_request_summary", "task_type", "complexity", "status")

    def __post_init__(self) -> None:
        self.clarifications = _clean_list(self.clarifications)
        self.success_criteria = _clean_list(self.success_criteria)
        self.constraints = _clean_list(self.constraints)

    def validate(self) -> PacketValidationResult:
        result = super().validate()
        errors = list(result.errors)
        if self.requires_speckit is False and not self.skip_reason:
            errors.append("skip_reason is required when requires_speckit is false")
        return PacketValidationResult(
            valid=not result.missing and not errors,
            missing=result.missing,
            errors=errors,
        )


@dataclass
class PlannerPacket(RuntimePacket):
    id: str
    task_packet_id: str
    planner_role: str
    preferred_model: str
    branch_name: str
    required_artifacts: List[str]
    return_schema: Dict[str, Any]
    worktree_path: Optional[str] = None
    memory_packet_id: Optional[str] = None
    status: str = "queued"

    required_fields = (
        "id",
        "task_packet_id",
        "planner_role",
        "preferred_model",
        "branch_name",
        "required_artifacts",
        "return_schema",
        "status",
    )

    def __post_init__(self) -> None:
        self.required_artifacts = _clean_list(self.required_artifacts)


@dataclass
class SpecKitArtifactSet(RuntimePacket):
    id: str
    task_packet_id: str
    branch_name: str
    spec_path: str
    plan_path: str
    tasks_path: str
    artifact_status: str
    worktree_path: Optional[str] = None
    commit_sha: Optional[str] = None

    required_fields = (
        "id",
        "task_packet_id",
        "branch_name",
        "spec_path",
        "plan_path",
        "tasks_path",
        "artifact_status",
    )


@dataclass
class WorkerDelegationPacket(RuntimePacket):
    id: str
    task_packet_id: str
    worker_id: str
    worker_kind: str
    repo_id: str
    branch_name: str
    worktree_path: str
    objective: str
    owned_files: List[str]
    constraints: List[str]
    validation_commands: List[str]
    memory_packet_id: str
    return_schema: Dict[str, Any]
    status: str = "queued"

    required_fields = (
        "id",
        "task_packet_id",
        "worker_id",
        "worker_kind",
        "repo_id",
        "branch_name",
        "worktree_path",
        "objective",
        "owned_files",
        "constraints",
        "validation_commands",
        "memory_packet_id",
        "return_schema",
        "status",
    )

    def __post_init__(self) -> None:
        self.owned_files = _clean_list(self.owned_files)
        self.constraints = _clean_list(self.constraints)
        self.validation_commands = _clean_list(self.validation_commands)


@dataclass
class WorkerResult(RuntimePacket):
    id: str
    delegation_packet_id: str
    summary: str
    changed_files: List[str]
    commands_run: List[Dict[str, Any]]
    validation_status: str
    blockers: List[str] = field(default_factory=list)
    memory_notes: List[str] = field(default_factory=list)

    required_fields = (
        "id",
        "delegation_packet_id",
        "summary",
        "changed_files",
        "commands_run",
        "validation_status",
    )

    def __post_init__(self) -> None:
        self.changed_files = _clean_list(self.changed_files)
        self.blockers = _clean_list(self.blockers)
        self.memory_notes = _clean_list(self.memory_notes)


@dataclass
class ValidationReport(RuntimePacket):
    id: str
    task_packet_id: str
    artifact_set_id: str
    worker_result_ids: List[str]
    git_diff_summary: str
    test_results: Dict[str, Any]
    requirement_coverage: Dict[str, Any]
    status: str

    required_fields = (
        "id",
        "task_packet_id",
        "artifact_set_id",
        "worker_result_ids",
        "git_diff_summary",
        "test_results",
        "requirement_coverage",
        "status",
    )

    def __post_init__(self) -> None:
        self.worker_result_ids = _clean_list(self.worker_result_ids)


@dataclass
class SessionSummary(RuntimePacket):
    id: str
    task_packet_id: str
    master_instructions: str
    decisions: List[str]
    delegations: List[str]
    validation_report_id: str
    memory_outcome: str
    commit_refs: List[str]

    required_fields = (
        "id",
        "task_packet_id",
        "master_instructions",
        "decisions",
        "delegations",
        "validation_report_id",
        "memory_outcome",
        "commit_refs",
    )

    def __post_init__(self) -> None:
        self.decisions = _clean_list(self.decisions)
        self.delegations = _clean_list(self.delegations)
        self.commit_refs = _clean_list(self.commit_refs)


@dataclass
class WorktreeAssignment(RuntimePacket):
    id: str
    task_packet_id: str
    agent_id: str
    branch_name: str
    worktree_path: str
    owned_files: List[str]
    status: str

    required_fields = (
        "id",
        "task_packet_id",
        "agent_id",
        "branch_name",
        "worktree_path",
        "owned_files",
        "status",
    )

    def __post_init__(self) -> None:
        self.owned_files = _clean_list(self.owned_files)
