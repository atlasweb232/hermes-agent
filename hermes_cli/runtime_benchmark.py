"""Production benchmark schemas and fail-closed gate helpers.

This module intentionally stops at deterministic schema and validation logic.
The runner, provider execution, telemetry persistence, and report generation are
separate Phase 14 tasks.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


REQUIRED_WORKLOAD_CLASSES = frozenset(
    {
        "review",
        "implementation",
        "qa",
        "deployment",
        "long_running_goal",
        "fallback",
        "stale_worker",
        "repeated_failure",
        "multi_repo_decomposition",
        "hallucinated_completion",
    }
)

REQUIRED_TELEMETRY_ROLES = (
    "supervisor",
    "planner",
    "worker",
    "judge",
    "curator",
    "dreaming",
    "progress_summarizer",
    "qa",
    "deployment",
    "memory_retrieval",
    "slack_analysis",
    "dashboard_analysis",
)

_REDACTED_EXCERPT_LIMIT = 2048


def _clean_list(value: Optional[Iterable[Any]]) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    return [str(item) for item in value if str(item or "").strip()]


def _as_path(value: Any) -> Path:
    return value if isinstance(value, Path) else Path(str(value))


def _missing_required(data: Mapping[str, Any], fields: Iterable[str]) -> List[str]:
    missing: List[str] = []
    for field_name in fields:
        value = data.get(field_name)
        if value is None or value == "" or value == [] or value == {}:
            missing.append(field_name)
    return missing


def _path_contains(parent: Path, child: Path) -> bool:
    try:
        child.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError:
        return False
    return True


def _coerce_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


@dataclass
class BenchmarkValidationResult:
    valid: bool
    missing: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RepoRef:
    repo_id: str
    snapshot_ref: str
    branch_ref: str
    worktree_path: Optional[str] = None

    required_fields = ("repo_id", "snapshot_ref", "branch_ref")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RepoRef":
        return cls(
            repo_id=str(data.get("repo_id", "")),
            snapshot_ref=str(data.get("snapshot_ref", "")),
            branch_ref=str(data.get("branch_ref", "")),
            worktree_path=data.get("worktree_path"),
        )

    def validate(self) -> BenchmarkValidationResult:
        missing = _missing_required(self.to_dict(), self.required_fields)
        return BenchmarkValidationResult(valid=not missing, missing=missing)


@dataclass(frozen=True)
class ValidationCommand:
    command: str
    timeout_seconds: int = 300
    expected_status: int = 0

    required_fields = ("command",)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ValidationCommand":
        return cls(
            command=str(data.get("command", "")),
            timeout_seconds=int(data.get("timeout_seconds", 300)),
            expected_status=int(data.get("expected_status", 0)),
        )

    def validate(self) -> BenchmarkValidationResult:
        missing = _missing_required(self.to_dict(), self.required_fields)
        errors: List[str] = []
        if self.timeout_seconds <= 0:
            errors.append("timeout_seconds must be positive")
        return BenchmarkValidationResult(valid=not missing and not errors, missing=missing, errors=errors)


@dataclass(frozen=True)
class ModelToolProfile:
    provider: str
    model: str
    allowed_workers: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)
    max_prompt_tokens: Optional[int] = None
    max_cost_usd: Optional[float] = None
    sidecars_advisory_only: bool = True

    required_fields = ("provider", "model", "allowed_workers", "allowed_tools")

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_workers", _clean_list(self.allowed_workers))
        object.__setattr__(self, "allowed_tools", _clean_list(self.allowed_tools))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModelToolProfile":
        return cls(
            provider=str(data.get("provider", "")),
            model=str(data.get("model", "")),
            allowed_workers=_clean_list(data.get("allowed_workers")),
            allowed_tools=_clean_list(data.get("allowed_tools")),
            max_prompt_tokens=data.get("max_prompt_tokens"),
            max_cost_usd=data.get("max_cost_usd"),
            sidecars_advisory_only=bool(data.get("sidecars_advisory_only", True)),
        )

    def validate(self) -> BenchmarkValidationResult:
        missing = _missing_required(self.to_dict(), self.required_fields)
        errors: List[str] = []
        if self.max_prompt_tokens is not None and int(self.max_prompt_tokens) <= 0:
            errors.append("max_prompt_tokens must be positive")
        if self.max_cost_usd is not None and float(self.max_cost_usd) < 0:
            errors.append("max_cost_usd must be non-negative")
        if self.sidecars_advisory_only is not True:
            errors.append("sidecars must remain advisory-only in benchmark schema")
        return BenchmarkValidationResult(valid=not missing and not errors, missing=missing, errors=errors)


@dataclass
class BenchmarkWorkload:
    workload_id: str
    workload_class: str
    repo_refs: List[RepoRef]
    prompt: str
    model_profile: ModelToolProfile
    expected_artifacts: List[str]
    validation_commands: List[ValidationCommand]
    pass_fail_rubric: Dict[str, List[str]]
    expected_validation_commands: List[ValidationCommand] = field(default_factory=list)
    branch_refs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    required_fields = (
        "workload_id",
        "workload_class",
        "repo_refs",
        "prompt",
        "model_profile",
        "expected_artifacts",
        "validation_commands",
        "pass_fail_rubric",
    )

    def __post_init__(self) -> None:
        self.repo_refs = [ref if isinstance(ref, RepoRef) else RepoRef.from_dict(ref) for ref in self.repo_refs]
        self.expected_artifacts = _clean_list(self.expected_artifacts)
        self.validation_commands = [
            cmd if isinstance(cmd, ValidationCommand) else ValidationCommand.from_dict(cmd)
            for cmd in self.validation_commands
        ]
        self.expected_validation_commands = [
            cmd if isinstance(cmd, ValidationCommand) else ValidationCommand.from_dict(cmd)
            for cmd in self.expected_validation_commands
        ]
        self.branch_refs = _clean_list(self.branch_refs)
        if not isinstance(self.model_profile, ModelToolProfile):
            self.model_profile = ModelToolProfile.from_dict(self.model_profile)
        self.pass_fail_rubric = {
            str(key): _clean_list(value) for key, value in _coerce_mapping(self.pass_fail_rubric).items()
        }

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BenchmarkWorkload":
        validation_commands = data.get("validation_commands") or data.get("expected_validation_commands") or []
        expected_validation_commands = data.get("expected_validation_commands") or validation_commands
        return cls(
            workload_id=str(data.get("workload_id", "")),
            workload_class=str(data.get("workload_class", "")),
            repo_refs=[RepoRef.from_dict(item) for item in data.get("repo_refs", [])],
            prompt=str(data.get("prompt", "")),
            model_profile=ModelToolProfile.from_dict(_coerce_mapping(data.get("model_profile"))),
            expected_artifacts=_clean_list(data.get("expected_artifacts")),
            validation_commands=[
                ValidationCommand.from_dict(item) for item in validation_commands
            ],
            expected_validation_commands=[
                ValidationCommand.from_dict(item) for item in expected_validation_commands
            ],
            pass_fail_rubric=_coerce_mapping(data.get("pass_fail_rubric")),
            branch_refs=_clean_list(data.get("branch_refs")),
            metadata=_coerce_mapping(data.get("metadata")),
        )

    def validate(self) -> BenchmarkValidationResult:
        data = self.to_dict()
        missing = _missing_required(data, self.required_fields)
        errors: List[str] = []
        if self.workload_class not in REQUIRED_WORKLOAD_CLASSES:
            errors.append(f"unsupported workload_class: {self.workload_class}")
        for idx, repo_ref in enumerate(self.repo_refs):
            child = repo_ref.validate()
            errors.extend(f"repo_refs[{idx}].{err}" for err in child.errors)
            missing.extend(f"repo_refs[{idx}].{item}" for item in child.missing)
        profile = self.model_profile.validate()
        missing.extend(f"model_profile.{item}" for item in profile.missing)
        errors.extend(f"model_profile.{item}" for item in profile.errors)
        for idx, command in enumerate(self.validation_commands):
            result = command.validate()
            missing.extend(f"validation_commands[{idx}].{item}" for item in result.missing)
            errors.extend(f"validation_commands[{idx}].{item}" for item in result.errors)
        if not self.pass_fail_rubric.get("pass") or not self.pass_fail_rubric.get("fail"):
            missing.append("pass_fail_rubric")
        return BenchmarkValidationResult(valid=not missing and not errors, missing=missing, errors=errors)


@dataclass
class WorkloadPack:
    pack_id: str
    version: str
    workloads: List[BenchmarkWorkload]
    immutable: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    required_fields = ("pack_id", "version", "workloads")

    def __post_init__(self) -> None:
        self.workloads = [
            workload if isinstance(workload, BenchmarkWorkload) else BenchmarkWorkload.from_dict(workload)
            for workload in self.workloads
        ]
        self.metadata = _coerce_mapping(self.metadata)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorkloadPack":
        return cls(
            pack_id=str(data.get("pack_id", "")),
            version=str(data.get("version", "")),
            workloads=[BenchmarkWorkload.from_dict(item) for item in data.get("workloads", [])],
            immutable=bool(data.get("immutable", True)),
            metadata=_coerce_mapping(data.get("metadata")),
        )

    def validate(self) -> BenchmarkValidationResult:
        missing = _missing_required(self.to_dict(), self.required_fields)
        errors: List[str] = []
        if not self.immutable:
            errors.append("workload packs must be immutable for upstream/branch comparison")
        seen_ids: set[str] = set()
        seen_classes: set[str] = set()
        for idx, workload in enumerate(self.workloads):
            if workload.workload_id in seen_ids:
                errors.append(f"duplicate workload_id: {workload.workload_id}")
            seen_ids.add(workload.workload_id)
            seen_classes.add(workload.workload_class)
            result = workload.validate()
            missing.extend(f"workloads[{idx}].{item}" for item in result.missing)
            errors.extend(f"workloads[{idx}].{item}" for item in result.errors)
        return BenchmarkValidationResult(valid=not missing and not errors, missing=missing, errors=errors)

    def missing_required_classes(self) -> List[str]:
        present = {workload.workload_class for workload in self.workloads}
        return sorted(REQUIRED_WORKLOAD_CLASSES - present)


def _load_yaml(path: Path) -> Mapping[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on optional environment
        raise ValueError("YAML workload packs require PyYAML") from exc
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, Mapping):
        raise ValueError("workload pack must be a mapping")
    return loaded


def load_workload_pack(path: str | Path) -> WorkloadPack:
    pack_path = _as_path(path)
    suffix = pack_path.suffix.lower()
    if suffix == ".json":
        loaded = json.loads(pack_path.read_text(encoding="utf-8"))
    elif suffix in {".yaml", ".yml"}:
        loaded = _load_yaml(pack_path)
    else:
        raise ValueError(f"unsupported workload pack format: {pack_path.suffix}")
    if not isinstance(loaded, Mapping):
        raise ValueError("workload pack must be a mapping")
    return WorkloadPack.from_dict(loaded)


@dataclass(frozen=True)
class BenchmarkEnvironment:
    name: str
    hermes_home: Path
    artifact_root: Path
    checkout_path: Path
    workload_definition: Path
    env_file: Optional[Path] = None
    learning_enabled: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "hermes_home", _as_path(self.hermes_home))
        object.__setattr__(self, "artifact_root", _as_path(self.artifact_root))
        object.__setattr__(self, "checkout_path", _as_path(self.checkout_path))
        object.__setattr__(self, "workload_definition", _as_path(self.workload_definition))
        if self.env_file is not None:
            object.__setattr__(self, "env_file", _as_path(self.env_file))

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        for key in ("hermes_home", "artifact_root", "checkout_path", "workload_definition", "env_file"):
            if data.get(key) is not None:
                data[key] = str(data[key])
        return data


@dataclass(frozen=True)
class BenchmarkEnvironmentPair:
    upstream: BenchmarkEnvironment
    branch: BenchmarkEnvironment

    def to_dict(self) -> Dict[str, Any]:
        return {"upstream": self.upstream.to_dict(), "branch": self.branch.to_dict()}


def validate_environment_pair(pair: BenchmarkEnvironmentPair) -> BenchmarkValidationResult:
    missing: List[str] = []
    errors: List[str] = []
    upstream = pair.upstream
    branch = pair.branch
    if upstream.name != "upstream":
        errors.append("upstream environment name must be 'upstream'")
    if branch.name != "branch":
        errors.append("branch environment name must be 'branch'")
    for env_name, env in (("upstream", upstream), ("branch", branch)):
        data = env.to_dict()
        missing.extend(f"{env_name}.{field_name}" for field_name in _missing_required(data, ("hermes_home", "artifact_root", "checkout_path", "workload_definition")))
        if _path_contains(env.hermes_home, env.artifact_root) or _path_contains(env.artifact_root, env.hermes_home):
            errors.append(f"{env_name}.hermes_home and artifact_root must not be nested")
    if upstream.hermes_home.resolve(strict=False) == branch.hermes_home.resolve(strict=False):
        errors.append("hermes_home must be separate for upstream and branch")
    if upstream.artifact_root.resolve(strict=False) == branch.artifact_root.resolve(strict=False):
        errors.append("artifact_root must be separate for upstream and branch")
    if upstream.workload_definition.resolve(strict=False) != branch.workload_definition.resolve(strict=False):
        errors.append("workload_definition must be shared and immutable")
    if _path_contains(upstream.hermes_home, branch.hermes_home) or _path_contains(branch.hermes_home, upstream.hermes_home):
        errors.append("hermes_home paths must not be nested")
    if _path_contains(upstream.artifact_root, branch.artifact_root) or _path_contains(branch.artifact_root, upstream.artifact_root):
        errors.append("artifact_root paths must not be nested")
    return BenchmarkValidationResult(valid=not missing and not errors, missing=missing, errors=errors)


@dataclass
class TelemetryRecord:
    environment: str
    session_id: str
    task_id: str
    workload_id: str
    tenant_id: str
    repo_id: str
    role: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    wall_latency_ms: int
    queue_latency_ms: int
    context_tokens_admitted: int
    context_bytes_admitted: int
    raw_bytes_stored_out_of_context: int
    validation_result: str
    token_usage_estimated: bool = False
    cached_tokens: int = 0
    worker_id: Optional[str] = None
    memory_packet_ids: List[str] = field(default_factory=list)
    sidecars_triggered: List[str] = field(default_factory=list)
    sidecars_skipped: List[str] = field(default_factory=list)
    judge_decisions: List[str] = field(default_factory=list)
    worker_attempts: int = 0
    fallback_reasons: List[str] = field(default_factory=list)
    notification_counts: Dict[str, int] = field(default_factory=dict)
    operator_intervention_count: int = 0
    path_attribution: Dict[str, Any] = field(default_factory=dict)
    evidence_refs: List[str] = field(default_factory=list)
    evidence_excerpt: Optional[str] = None
    raw_transcript: Optional[str] = None
    raw_secrets: Optional[str] = None
    unbounded_log: Optional[str] = None

    required_fields = (
        "environment",
        "session_id",
        "task_id",
        "workload_id",
        "tenant_id",
        "repo_id",
        "role",
        "provider",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "input_tokens",
        "output_tokens",
        "estimated_cost_usd",
        "wall_latency_ms",
        "queue_latency_ms",
        "context_tokens_admitted",
        "context_bytes_admitted",
        "raw_bytes_stored_out_of_context",
        "validation_result",
        "path_attribution",
        "evidence_refs",
    )

    def __post_init__(self) -> None:
        self.memory_packet_ids = _clean_list(self.memory_packet_ids)
        self.sidecars_triggered = _clean_list(self.sidecars_triggered)
        self.sidecars_skipped = _clean_list(self.sidecars_skipped)
        self.judge_decisions = _clean_list(self.judge_decisions)
        self.fallback_reasons = _clean_list(self.fallback_reasons)
        self.evidence_refs = _clean_list(self.evidence_refs)
        self.notification_counts = {str(k): int(v) for k, v in _coerce_mapping(self.notification_counts).items()}
        self.path_attribution = _coerce_mapping(self.path_attribution)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("raw_transcript", None)
        data.pop("raw_secrets", None)
        data.pop("unbounded_log", None)
        return data

    def validate(self) -> BenchmarkValidationResult:
        missing = _missing_required(self.to_dict(), self.required_fields)
        errors: List[str] = []
        if self.environment not in {"upstream", "branch"}:
            errors.append("environment must be upstream or branch")
        if self.role not in REQUIRED_TELEMETRY_ROLES:
            errors.append(f"unsupported telemetry role: {self.role}")
        for field_name in (
            "prompt_tokens",
            "completion_tokens",
            "input_tokens",
            "output_tokens",
            "cached_tokens",
            "wall_latency_ms",
            "queue_latency_ms",
            "context_tokens_admitted",
            "context_bytes_admitted",
            "raw_bytes_stored_out_of_context",
            "worker_attempts",
            "operator_intervention_count",
        ):
            if int(getattr(self, field_name)) < 0:
                errors.append(f"{field_name} must be non-negative")
        if float(self.estimated_cost_usd) < 0:
            errors.append("estimated_cost_usd must be non-negative")
        if self.raw_transcript:
            errors.append("raw_transcript is not allowed in telemetry records")
        if self.raw_secrets:
            errors.append("raw_secrets is not allowed in telemetry records")
        if self.unbounded_log:
            errors.append("unbounded_log is not allowed in telemetry records")
        if self.evidence_excerpt and len(self.evidence_excerpt.encode("utf-8")) > _REDACTED_EXCERPT_LIMIT:
            errors.append("evidence_excerpt exceeds bounded redacted excerpt limit")
        return BenchmarkValidationResult(valid=not missing and not errors, missing=missing, errors=errors)


@dataclass(frozen=True)
class GateThresholds:
    max_cost_regression_ratio: float = 1.2
    max_latency_regression_ratio: float = 1.25


@dataclass(frozen=True)
class ProductionGateInput:
    upstream_success_rate: float
    branch_success_rate: float
    upstream_false_completion_rate: float
    branch_false_completion_rate: float
    upstream_repeated_error_rate: float
    branch_repeated_error_rate: float
    cost_per_success_ratio: float
    foreground_latency_ratio: float
    sidecar_blocked_foreground: bool
    urgent_alerts_expected: int
    urgent_alerts_sent: int
    memory_approval_boundary_preserved: bool
    judge_operator_boundary_preserved: bool
    operator_overrode_failed_validation: bool = False


@dataclass(frozen=True)
class ProductionGateResult:
    allowed: bool
    blockers: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def validate_production_gate(
    gate_input: ProductionGateInput,
    thresholds: Optional[GateThresholds] = None,
) -> ProductionGateResult:
    thresholds = thresholds or GateThresholds()
    blockers: List[str] = []
    if gate_input.branch_success_rate < gate_input.upstream_success_rate:
        blockers.append("branch_success_rate_regressed")
    if gate_input.branch_false_completion_rate >= gate_input.upstream_false_completion_rate:
        blockers.append("false_completion_rate_not_improved")
    if gate_input.branch_repeated_error_rate >= gate_input.upstream_repeated_error_rate:
        blockers.append("repeated_error_rate_not_improved")
    if gate_input.cost_per_success_ratio > thresholds.max_cost_regression_ratio:
        blockers.append("cost_threshold_exceeded")
    if gate_input.foreground_latency_ratio > thresholds.max_latency_regression_ratio:
        blockers.append("latency_threshold_exceeded")
    if gate_input.sidecar_blocked_foreground:
        blockers.append("sidecar_blocked_foreground")
    if gate_input.urgent_alerts_sent < gate_input.urgent_alerts_expected:
        blockers.append("urgent_alerts_missing")
    if not gate_input.memory_approval_boundary_preserved:
        blockers.append("memory_approval_boundary_violated")
    if not gate_input.judge_operator_boundary_preserved:
        blockers.append("judge_operator_boundary_violated")
    if gate_input.operator_overrode_failed_validation:
        blockers.append("operator_overrode_failed_validation")
    return ProductionGateResult(allowed=not blockers, blockers=blockers)
