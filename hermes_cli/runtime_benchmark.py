"""Production benchmark schemas, runner, telemetry, and reports.

The default runner is deterministic fixture execution. Live/provider execution
is opt-in through explicit commands so local tests never contact providers.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional


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
_NOTIFICATION_TEXT_LIMIT = 3000
_NOTIFICATION_FIELD_LIMIT = 500
_TELEMETRY_JSONL = "telemetry.jsonl"
_RUN_JSON = "run.json"
_REPORT_JSON = "report.json"

_SECRET_PATTERNS = (
    re.compile(r"(?i)(sk-[a-z0-9][a-z0-9_\-]{8,})"),
    re.compile(r"(?i)(xox[baprs]-[a-z0-9\-]{8,})"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)(authorization:\s*bearer\s+)([^\s,;]+)"),
)


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


def _safe_ratio(numerator: float, denominator: float, *, default: float = 0.0) -> float:
    return numerator / denominator if denominator else default


def _round_money(value: float) -> float:
    return round(float(value), 6)


def _redact_text(value: Any, *, limit: int = _NOTIFICATION_FIELD_LIMIT) -> str:
    text = str(value or "")
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 2:
            text = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    text = text.replace("\x00", "")
    if len(text) > limit:
        return text[: max(0, limit - 16)].rstrip() + " ... [truncated]"
    return text


def _artifact_root_default() -> Path:
    from hermes_constants import get_hermes_home

    return get_hermes_home() / "runtime-benchmark"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _read_json(path: Path) -> Dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return loaded


def _load_env_file(path: Optional[Path]) -> Dict[str, str]:
    if path is None or not path.exists():
        return {}
    env: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key:
            env[key] = value.strip().strip("\"'")
    return env


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


@dataclass(frozen=True)
class BenchmarkUrgentAlert:
    """Bounded benchmark alert ready for Slack/runtime urgent routing."""

    alert_id: str
    severity: str
    title: str
    message: str
    run_id: str
    workload_id: Optional[str] = None
    repo_id: Optional[str] = None
    blockers: List[str] = field(default_factory=list)
    source: str = "runtime-benchmark"

    def __post_init__(self) -> None:
        object.__setattr__(self, "severity", _redact_text(self.severity, limit=64))
        object.__setattr__(self, "title", _redact_text(self.title, limit=180))
        object.__setattr__(self, "message", _redact_text(self.message, limit=1000))
        object.__setattr__(self, "run_id", _redact_text(self.run_id, limit=120))
        object.__setattr__(self, "workload_id", _redact_text(self.workload_id, limit=160) if self.workload_id else None)
        object.__setattr__(self, "repo_id", _redact_text(self.repo_id, limit=160) if self.repo_id else None)
        object.__setattr__(self, "blockers", [_redact_text(item, limit=160) for item in self.blockers[:12]])

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_slack_payload(self) -> Dict[str, Any]:
        lines = [
            f"[Hermes benchmark] {self.title}",
            f"severity: {self.severity}",
            f"run: {self.run_id}",
        ]
        if self.workload_id:
            lines.append(f"workload: {self.workload_id}")
        if self.repo_id:
            lines.append(f"repo: {self.repo_id}")
        if self.blockers:
            lines.append("blockers: " + ", ".join(self.blockers))
        if self.message:
            lines.extend(["", self.message])
        text = "\n".join(lines).strip()
        if len(text) > _NOTIFICATION_TEXT_LIMIT:
            text = text[: _NOTIFICATION_TEXT_LIMIT - 16].rstrip() + " ... [truncated]"
        return {
            "text": text,
            "metadata": {
                "event_type": "hermes_runtime_benchmark_alert",
                "event_payload": {
                    "alert_id": self.alert_id,
                    "run_id": self.run_id,
                    "workload_id": self.workload_id,
                    "severity": self.severity,
                    "source": self.source,
                },
            },
        }


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


@dataclass
class RuntimeBenchmarkConfig:
    suite_path: Path
    artifact_root: Optional[Path] = None
    upstream_checkout: Optional[Path] = None
    branch_checkout: Optional[Path] = None
    upstream_env_file: Optional[Path] = None
    branch_env_file: Optional[Path] = None
    upstream_command: Optional[str] = None
    branch_command: Optional[str] = None
    run_id: Optional[str] = None
    tenant_id: str = "benchmark-tenant"
    execution_mode: str = "fixture"
    thresholds: GateThresholds = field(default_factory=GateThresholds)
    urgent_notifications: bool = False
    urgent_notification_platform: str = "slack"
    urgent_notification_dry_run: bool = False

    def __post_init__(self) -> None:
        self.suite_path = _as_path(self.suite_path)
        self.artifact_root = _as_path(self.artifact_root) if self.artifact_root else _artifact_root_default()
        if self.upstream_checkout is not None:
            self.upstream_checkout = _as_path(self.upstream_checkout)
        if self.branch_checkout is not None:
            self.branch_checkout = _as_path(self.branch_checkout)
        if self.upstream_env_file is not None:
            self.upstream_env_file = _as_path(self.upstream_env_file)
        if self.branch_env_file is not None:
            self.branch_env_file = _as_path(self.branch_env_file)
        if self.execution_mode not in {"fixture", "command"}:
            raise ValueError("execution_mode must be fixture or command")
        if self.execution_mode == "command" and (not self.upstream_command or not self.branch_command):
            raise ValueError("command execution requires upstream_command and branch_command")


class TelemetryCollector:
    """Bounded structured telemetry writer for benchmark runs."""

    def __init__(self, path: str | Path) -> None:
        self.path = _as_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records: List[TelemetryRecord] = []

    def record(self, record: TelemetryRecord) -> None:
        validation = record.validate()
        if not validation.valid:
            details = ", ".join(validation.missing + validation.errors)
            raise ValueError(f"invalid telemetry record: {details}")
        self._records.append(record)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")

    @property
    def records(self) -> List[TelemetryRecord]:
        return list(self._records)

    def summary(self) -> Dict[str, Any]:
        records = self._records
        return {
            "records": len(records),
            "estimated_cost_usd": _round_money(sum(record.estimated_cost_usd for record in records)),
            "prompt_tokens": sum(record.prompt_tokens for record in records),
            "completion_tokens": sum(record.completion_tokens for record in records),
            "context_tokens_admitted": sum(record.context_tokens_admitted for record in records),
            "raw_bytes_stored_out_of_context": sum(record.raw_bytes_stored_out_of_context for record in records),
            "worker_attempts": sum(record.worker_attempts for record in records),
            "sidecar_runs": sum(len(record.sidecars_triggered) for record in records),
            "judge_decisions": sum(len(record.judge_decisions) for record in records),
            "memory_hits": sum(1 for record in records if record.memory_packet_ids),
            "operator_interventions": sum(record.operator_intervention_count for record in records),
        }


def _run_dir(artifact_root: Path, run_id: str) -> Path:
    return artifact_root / "runs" / run_id


def _build_environment_pair(config: RuntimeBenchmarkConfig, run_dir: Path) -> BenchmarkEnvironmentPair:
    suite_path = config.suite_path.resolve(strict=False)
    return BenchmarkEnvironmentPair(
        upstream=BenchmarkEnvironment(
            name="upstream",
            hermes_home=run_dir / "homes" / "upstream",
            artifact_root=run_dir / "artifacts" / "upstream",
            checkout_path=config.upstream_checkout or (run_dir / "worktrees" / "upstream"),
            workload_definition=suite_path,
            env_file=config.upstream_env_file,
            learning_enabled=False,
        ),
        branch=BenchmarkEnvironment(
            name="branch",
            hermes_home=run_dir / "homes" / "branch",
            artifact_root=run_dir / "artifacts" / "branch",
            checkout_path=config.branch_checkout or (run_dir / "worktrees" / "branch"),
            workload_definition=suite_path,
            env_file=config.branch_env_file,
            learning_enabled=True,
        ),
    )


def _prepare_environment(env: BenchmarkEnvironment) -> None:
    env.hermes_home.mkdir(parents=True, exist_ok=True)
    env.artifact_root.mkdir(parents=True, exist_ok=True)
    env.checkout_path.mkdir(parents=True, exist_ok=True)


def _fixture_value(workload: BenchmarkWorkload, environment: str, key: str, default: Any) -> Any:
    fixture = _coerce_mapping(workload.metadata.get("fixture"))
    env_fixture = _coerce_mapping(fixture.get(environment))
    if key in env_fixture:
        return env_fixture[key]
    shared = _coerce_mapping(fixture.get("shared"))
    return shared.get(key, default)


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _record_fixture_telemetry(
    *,
    collector: TelemetryCollector,
    env: BenchmarkEnvironment,
    workload: BenchmarkWorkload,
    outcome: Mapping[str, Any],
) -> None:
    environment = env.name
    roles = ("supervisor", "worker", "judge")
    if environment == "branch":
        roles = ("supervisor", "memory_retrieval", "worker", "progress_summarizer", "judge", "curator")
    prompt_tokens = _estimate_tokens(workload.prompt)
    repo_id = workload.repo_refs[0].repo_id if workload.repo_refs else "unknown"
    for idx, role in enumerate(roles):
        sidecars = []
        if role in {"progress_summarizer", "curator"}:
            sidecars = [role]
        memory_ids = ["mempkt-fixture"] if environment == "branch" and role in {"memory_retrieval", "worker"} else []
        judge_decisions = ["approved"] if role == "judge" else []
        record = TelemetryRecord(
            environment=environment,
            session_id=f"{environment}-{workload.workload_id}",
            task_id=f"task-{workload.workload_id}",
            workload_id=workload.workload_id,
            tenant_id=str(outcome.get("tenant_id") or "benchmark-tenant"),
            repo_id=repo_id,
            role=role,
            provider=workload.model_profile.provider,
            model=workload.model_profile.model,
            worker_id=f"{environment}-{role}" if role in {"worker", "qa", "deployment"} else None,
            prompt_tokens=prompt_tokens + idx,
            completion_tokens=20 + idx,
            cached_tokens=5 if environment == "branch" else 0,
            input_tokens=prompt_tokens + idx,
            output_tokens=20 + idx,
            token_usage_estimated=True,
            estimated_cost_usd=float(outcome.get("cost_usd", 0.0)) / max(1, len(roles)),
            wall_latency_ms=int(float(outcome.get("latency_ms", 0)) / max(1, len(roles))),
            queue_latency_ms=idx,
            context_tokens_admitted=int(outcome.get("context_tokens", 0)) // max(1, len(roles)),
            context_bytes_admitted=int(outcome.get("context_bytes", 0)) // max(1, len(roles)),
            raw_bytes_stored_out_of_context=int(outcome.get("raw_bytes", 0)) // max(1, len(roles)),
            memory_packet_ids=memory_ids,
            sidecars_triggered=sidecars,
            sidecars_skipped=[],
            judge_decisions=judge_decisions,
            worker_attempts=1 if role == "worker" else 0,
            fallback_reasons=_clean_list(outcome.get("fallback_reasons")) if role == "worker" else [],
            validation_result="passed" if outcome.get("validation_passed") else "failed",
            notification_counts={
                "slack": int(outcome.get("urgent_alerts_sent", 0)),
                "dashboard": int(outcome.get("urgent_alerts_sent", 0)),
            } if role == "supervisor" else {},
            operator_intervention_count=int(outcome.get("operator_interventions", 0)) if role == "supervisor" else 0,
            path_attribution={"surface": "runtime-benchmark", "role": role, "mode": "fixture"},
            evidence_refs=[f"artifact://{environment}/{workload.workload_id}/{role}.json"],
            evidence_excerpt=f"{environment} {role} fixture telemetry",
        )
        collector.record(record)


def _fixture_outcome(workload: BenchmarkWorkload, environment: str, tenant_id: str) -> Dict[str, Any]:
    branch = environment == "branch"
    default = {
        "environment": environment,
        "workload_id": workload.workload_id,
        "tenant_id": tenant_id,
        "success": True,
        "validation_passed": True,
        "false_completion": False if branch else True,
        "repeated_errors": 0 if branch else 1,
        "worker_reallocations": 1 if branch and workload.workload_class in {"fallback", "stale_worker"} else 0,
        "operator_interventions": 0,
        "cost_usd": 0.018 if branch else 0.02,
        "latency_ms": 900 if branch else 1000,
        "time_to_first_artifact_ms": 250 if branch else 320,
        "context_tokens": 180 if branch else 260,
        "context_bytes": 900 if branch else 1300,
        "raw_bytes": 4096 if branch else 2048,
        "memory_hits": 1 if branch else 0,
        "memory_helpful": 1 if branch else 0,
        "memory_ignored": 0,
        "memory_harmful": 0,
        "sidecar_wall_ms": 40 if branch else 0,
        "sidecar_cost_usd": 0.002 if branch else 0.0,
        "sidecar_blocked_foreground": False,
        "urgent_alerts_expected": 1 if workload.workload_class in {"fallback", "stale_worker", "repeated_failure"} else 0,
        "urgent_alerts_sent": 1 if branch and workload.workload_class in {"fallback", "stale_worker", "repeated_failure"} else 0,
        "memory_boundary_preserved": True,
        "judge_operator_boundary_preserved": True,
        "operator_overrode_failed_validation": False,
        "fallback_reasons": ["fixture-fallback"] if workload.workload_class == "fallback" else [],
        "message": "",
    }
    for key in list(default):
        default[key] = _fixture_value(workload, environment, key, default[key])
    return default


def _run_command_environment(
    *,
    command: str,
    env: BenchmarkEnvironment,
    workload: BenchmarkWorkload,
    tenant_id: str,
) -> Dict[str, Any]:
    start = time.monotonic()
    process_env = os.environ.copy()
    process_env.update(_load_env_file(env.env_file))
    process_env.update(
        {
            "HERMES_HOME": str(env.hermes_home),
            "HERMES_BENCHMARK_ARTIFACT_ROOT": str(env.artifact_root),
            "HERMES_BENCHMARK_WORKLOAD_ID": workload.workload_id,
            "HERMES_BENCHMARK_TENANT_ID": tenant_id,
        }
    )
    completed = subprocess.run(
        command,
        cwd=str(env.checkout_path),
        env=process_env,
        shell=True,
        text=True,
        capture_output=True,
        timeout=600,
        check=False,
    )
    latency_ms = int((time.monotonic() - start) * 1000)
    evidence_path = env.artifact_root / workload.workload_id / "command-result.json"
    evidence = {
        "status_code": completed.returncode,
        "stdout_excerpt": completed.stdout[:1000],
        "stderr_excerpt": completed.stderr[:1000],
    }
    _write_json(evidence_path, evidence)
    return {
        **_fixture_outcome(workload, env.name, tenant_id),
        "success": completed.returncode == 0,
        "validation_passed": completed.returncode == 0,
        "latency_ms": latency_ms,
        "evidence_ref": f"artifact://{env.name}/{workload.workload_id}/command-result.json",
    }


class BenchmarkRunner:
    def __init__(self, config: RuntimeBenchmarkConfig) -> None:
        self.config = config

    def run(self) -> Dict[str, Any]:
        pack = load_workload_pack(self.config.suite_path)
        validation = pack.validate()
        if not validation.valid:
            details = ", ".join(validation.missing + validation.errors)
            raise ValueError(f"invalid workload pack: {details}")
        run_id = self.config.run_id or f"bench_{uuid.uuid4().hex[:16]}"
        artifact_root = _as_path(self.config.artifact_root)
        run_dir = _run_dir(artifact_root, run_id)
        pair = _build_environment_pair(self.config, run_dir)
        env_validation = validate_environment_pair(pair)
        if not env_validation.valid:
            details = ", ".join(env_validation.missing + env_validation.errors)
            raise ValueError(f"invalid benchmark environments: {details}")
        _prepare_environment(pair.upstream)
        _prepare_environment(pair.branch)
        telemetry = TelemetryCollector(run_dir / _TELEMETRY_JSONL)
        environment_results: Dict[str, List[Dict[str, Any]]] = {"upstream": [], "branch": []}
        commands = {"upstream": self.config.upstream_command, "branch": self.config.branch_command}
        for workload in pack.workloads:
            for env in (pair.upstream, pair.branch):
                command = commands[env.name]
                if self.config.execution_mode == "command":
                    outcome = _run_command_environment(
                        command=command,
                        env=env,
                        workload=workload,
                        tenant_id=self.config.tenant_id,
                    )
                else:
                    outcome = _fixture_outcome(workload, env.name, self.config.tenant_id)
                environment_results[env.name].append(outcome)
                _record_fixture_telemetry(
                    collector=telemetry,
                    env=env,
                    workload=workload,
                    outcome=outcome,
                )
        result = {
            "run_id": run_id,
            "status": "completed",
            "suite": str(self.config.suite_path),
            "pack_id": pack.pack_id,
            "version": pack.version,
            "execution_mode": self.config.execution_mode,
            "environment_pair": pair.to_dict(),
            "workload_count": len(pack.workloads),
            "results": environment_results,
            "telemetry_summary": telemetry.summary(),
            "artifacts": {
                "run_dir": str(run_dir),
                "run_json": str(run_dir / _RUN_JSON),
                "telemetry_jsonl": str(telemetry.path),
                "report_json": str(run_dir / _REPORT_JSON),
            },
            "thresholds": asdict(self.config.thresholds),
        }
        _write_json(run_dir / _RUN_JSON, result)
        report = generate_comparison_report(run_id, artifact_root=artifact_root, persist=True)
        if self.config.urgent_notifications:
            send_benchmark_notifications_for_run(
                run_id,
                artifact_root=artifact_root,
                platform=self.config.urgent_notification_platform,
                dry_run=self.config.urgent_notification_dry_run,
            )
            report = generate_comparison_report(run_id, artifact_root=artifact_root, persist=True)
        result["production_gate"] = report["production_gate"]
        result["notification_requirements"] = report["notification_requirements"]
        if report.get("benchmark_notifications"):
            result["benchmark_notifications"] = report["benchmark_notifications"]
        _write_json(run_dir / _RUN_JSON, result)
        return result


def run_benchmark_suite(config: RuntimeBenchmarkConfig) -> Dict[str, Any]:
    return BenchmarkRunner(config).run()


def get_benchmark_run(run_id: str, *, artifact_root: Optional[str | Path] = None) -> Dict[str, Any]:
    root = _as_path(artifact_root) if artifact_root else _artifact_root_default()
    run_path = _run_dir(root, run_id) / _RUN_JSON
    if not run_path.exists():
        raise ValueError(f"unknown benchmark run: {run_id}")
    return _read_json(run_path)


def _aggregate_outcomes(outcomes: List[Mapping[str, Any]]) -> Dict[str, Any]:
    count = len(outcomes)
    successes = sum(1 for item in outcomes if item.get("success"))
    validation_passes = sum(1 for item in outcomes if item.get("validation_passed"))
    total_cost = sum(float(item.get("cost_usd") or 0.0) for item in outcomes)
    total_latency = sum(float(item.get("latency_ms") or 0.0) for item in outcomes)
    return {
        "task_count": count,
        "successes": successes,
        "success_rate": _safe_ratio(successes, count),
        "validation_pass_rate": _safe_ratio(validation_passes, count),
        "false_completion_rate": _safe_ratio(sum(1 for item in outcomes if item.get("false_completion")), count),
        "repeated_error_rate": _safe_ratio(sum(float(item.get("repeated_errors") or 0.0) for item in outcomes), count),
        "worker_reallocations": sum(int(item.get("worker_reallocations") or 0) for item in outcomes),
        "operator_interventions": sum(int(item.get("operator_interventions") or 0) for item in outcomes),
        "estimated_cost_usd": _round_money(total_cost),
        "cost_per_success_usd": _round_money(_safe_ratio(total_cost, successes, default=total_cost)),
        "avg_latency_ms": _safe_ratio(total_latency, count),
        "avg_time_to_first_artifact_ms": _safe_ratio(sum(float(item.get("time_to_first_artifact_ms") or 0.0) for item in outcomes), count),
        "context_tokens_per_task": _safe_ratio(sum(float(item.get("context_tokens") or 0.0) for item in outcomes), count),
        "context_bytes_per_task": _safe_ratio(sum(float(item.get("context_bytes") or 0.0) for item in outcomes), count),
        "raw_bytes_stored_out_of_context": sum(int(item.get("raw_bytes") or 0) for item in outcomes),
        "memory_hit_rate": _safe_ratio(sum(1 for item in outcomes if int(item.get("memory_hits") or 0) > 0), count),
        "memory_helpful": sum(int(item.get("memory_helpful") or 0) for item in outcomes),
        "memory_ignored": sum(int(item.get("memory_ignored") or 0) for item in outcomes),
        "memory_harmful": sum(int(item.get("memory_harmful") or 0) for item in outcomes),
        "sidecar_wall_ms": sum(float(item.get("sidecar_wall_ms") or 0.0) for item in outcomes),
        "sidecar_cost_usd": _round_money(sum(float(item.get("sidecar_cost_usd") or 0.0) for item in outcomes)),
        "sidecar_blocked_foreground": any(bool(item.get("sidecar_blocked_foreground")) for item in outcomes),
        "urgent_alerts_expected": sum(int(item.get("urgent_alerts_expected") or 0) for item in outcomes),
        "urgent_alerts_sent": sum(int(item.get("urgent_alerts_sent") or 0) for item in outcomes),
        "memory_boundary_preserved": all(bool(item.get("memory_boundary_preserved", True)) for item in outcomes),
        "judge_operator_boundary_preserved": all(bool(item.get("judge_operator_boundary_preserved", True)) for item in outcomes),
        "operator_overrode_failed_validation": any(bool(item.get("operator_overrode_failed_validation")) for item in outcomes),
    }


def _successful_benchmark_notifications(run: Mapping[str, Any]) -> int:
    notifications = _coerce_mapping(run.get("benchmark_notifications"))
    deliveries = notifications.get("deliveries")
    if not isinstance(deliveries, list):
        return 0
    return sum(1 for item in deliveries if isinstance(item, Mapping) and item.get("status") == "sent")


def _benchmark_failure_outcomes(run: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    failures: List[Mapping[str, Any]] = []
    branch_results = list(_coerce_mapping(run.get("results")).get("branch", []))
    for item in branch_results:
        if not isinstance(item, Mapping):
            continue
        if not bool(item.get("success")) or not bool(item.get("validation_passed")):
            failures.append(item)
    return failures


def _notification_requirements(
    *,
    run: Mapping[str, Any],
    branch: Mapping[str, Any],
    preliminary_gate: ProductionGateResult,
) -> Dict[str, Any]:
    failures = _benchmark_failure_outcomes(run)
    non_notification_gate_blockers = [item for item in preliminary_gate.blockers if item != "urgent_alerts_missing"]
    gate_block_alerts_expected = 1 if non_notification_gate_blockers else 0
    benchmark_notifications_sent = _successful_benchmark_notifications(run)
    base_expected = int(branch["urgent_alerts_expected"])
    base_sent = int(branch["urgent_alerts_sent"])
    return {
        "workload_urgent_alerts_expected": base_expected,
        "workload_urgent_alerts_sent": base_sent,
        "benchmark_failures_expected": len(failures),
        "production_gate_block_alerts_expected": gate_block_alerts_expected,
        "benchmark_notifications_sent": benchmark_notifications_sent,
        "total_urgent_alerts_expected": base_expected + len(failures) + gate_block_alerts_expected,
        "total_urgent_alerts_sent": base_sent + benchmark_notifications_sent,
        "gate_blockers_requiring_alert": non_notification_gate_blockers,
    }


def _gate_for_aggregates(
    *,
    upstream: Mapping[str, Any],
    branch: Mapping[str, Any],
    cost_ratio: float,
    latency_ratio: float,
    thresholds: GateThresholds,
    urgent_alerts_expected: Optional[int] = None,
    urgent_alerts_sent: Optional[int] = None,
) -> ProductionGateResult:
    return validate_production_gate(
        ProductionGateInput(
            upstream_success_rate=float(upstream["success_rate"]),
            branch_success_rate=float(branch["success_rate"]),
            upstream_false_completion_rate=float(upstream["false_completion_rate"]),
            branch_false_completion_rate=float(branch["false_completion_rate"]),
            upstream_repeated_error_rate=float(upstream["repeated_error_rate"]),
            branch_repeated_error_rate=float(branch["repeated_error_rate"]),
            cost_per_success_ratio=cost_ratio,
            foreground_latency_ratio=latency_ratio,
            sidecar_blocked_foreground=bool(branch["sidecar_blocked_foreground"]),
            urgent_alerts_expected=int(branch["urgent_alerts_expected"] if urgent_alerts_expected is None else urgent_alerts_expected),
            urgent_alerts_sent=int(branch["urgent_alerts_sent"] if urgent_alerts_sent is None else urgent_alerts_sent),
            memory_approval_boundary_preserved=bool(branch["memory_boundary_preserved"]),
            judge_operator_boundary_preserved=bool(branch["judge_operator_boundary_preserved"]),
            operator_overrode_failed_validation=bool(branch["operator_overrode_failed_validation"]),
        ),
        thresholds=thresholds,
    )


def generate_comparison_report(
    run_id: str,
    *,
    artifact_root: Optional[str | Path] = None,
    persist: bool = True,
) -> Dict[str, Any]:
    root = _as_path(artifact_root) if artifact_root else _artifact_root_default()
    run = get_benchmark_run(run_id, artifact_root=root)
    upstream = _aggregate_outcomes(list(run.get("results", {}).get("upstream", [])))
    branch = _aggregate_outcomes(list(run.get("results", {}).get("branch", [])))
    cost_ratio = _safe_ratio(branch["cost_per_success_usd"], upstream["cost_per_success_usd"], default=1.0)
    latency_ratio = _safe_ratio(branch["avg_latency_ms"], upstream["avg_latency_ms"], default=1.0)
    thresholds = GateThresholds(**_coerce_mapping(run.get("thresholds")))
    preliminary_gate = _gate_for_aggregates(
        upstream=upstream,
        branch=branch,
        cost_ratio=cost_ratio,
        latency_ratio=latency_ratio,
        thresholds=thresholds,
    )
    notification_requirements = _notification_requirements(
        run=run,
        branch=branch,
        preliminary_gate=preliminary_gate,
    )
    gate = _gate_for_aggregates(
        upstream=upstream,
        branch=branch,
        cost_ratio=cost_ratio,
        latency_ratio=latency_ratio,
        thresholds=thresholds,
        urgent_alerts_expected=int(notification_requirements["total_urgent_alerts_expected"]),
        urgent_alerts_sent=int(notification_requirements["total_urgent_alerts_sent"]),
    )
    report = {
        "run_id": run_id,
        "status": "reported",
        "comparison": {
            "quality": {
                "upstream": {
                    "success_rate": upstream["success_rate"],
                    "validation_pass_rate": upstream["validation_pass_rate"],
                    "false_completion_rate": upstream["false_completion_rate"],
                    "repeated_error_rate": upstream["repeated_error_rate"],
                    "worker_reallocations": upstream["worker_reallocations"],
                    "operator_interventions": upstream["operator_interventions"],
                },
                "branch": {
                    "success_rate": branch["success_rate"],
                    "validation_pass_rate": branch["validation_pass_rate"],
                    "false_completion_rate": branch["false_completion_rate"],
                    "repeated_error_rate": branch["repeated_error_rate"],
                    "worker_reallocations": branch["worker_reallocations"],
                    "operator_interventions": branch["operator_interventions"],
                },
            },
            "cost": {
                "upstream": {
                    "estimated_cost_usd": upstream["estimated_cost_usd"],
                    "cost_per_success_usd": upstream["cost_per_success_usd"],
                },
                "branch": {
                    "estimated_cost_usd": branch["estimated_cost_usd"],
                    "cost_per_success_usd": branch["cost_per_success_usd"],
                },
                "cost_per_success_ratio": cost_ratio,
            },
            "latency": {
                "upstream": {
                    "avg_latency_ms": upstream["avg_latency_ms"],
                    "avg_time_to_first_artifact_ms": upstream["avg_time_to_first_artifact_ms"],
                },
                "branch": {
                    "avg_latency_ms": branch["avg_latency_ms"],
                    "avg_time_to_first_artifact_ms": branch["avg_time_to_first_artifact_ms"],
                    "sidecar_wall_ms": branch["sidecar_wall_ms"],
                },
                "foreground_latency_ratio": latency_ratio,
            },
            "context": {
                "upstream": {
                    "context_tokens_per_task": upstream["context_tokens_per_task"],
                    "context_bytes_per_task": upstream["context_bytes_per_task"],
                    "raw_bytes_stored_out_of_context": upstream["raw_bytes_stored_out_of_context"],
                },
                "branch": {
                    "context_tokens_per_task": branch["context_tokens_per_task"],
                    "context_bytes_per_task": branch["context_bytes_per_task"],
                    "raw_bytes_stored_out_of_context": branch["raw_bytes_stored_out_of_context"],
                },
            },
            "self_learning": {
                "upstream": {
                    "memory_hit_rate": upstream["memory_hit_rate"],
                    "memory_helpful": upstream["memory_helpful"],
                    "memory_ignored": upstream["memory_ignored"],
                    "memory_harmful": upstream["memory_harmful"],
                    "sidecar_cost_usd": upstream["sidecar_cost_usd"],
                },
                "branch": {
                    "memory_hit_rate": branch["memory_hit_rate"],
                    "memory_helpful": branch["memory_helpful"],
                    "memory_ignored": branch["memory_ignored"],
                    "memory_harmful": branch["memory_harmful"],
                    "sidecar_cost_usd": branch["sidecar_cost_usd"],
                    "sidecar_blocked_foreground": branch["sidecar_blocked_foreground"],
                    "urgent_alerts_expected": branch["urgent_alerts_expected"],
                    "urgent_alerts_sent": branch["urgent_alerts_sent"],
                },
            },
        },
        "production_gate": gate.to_dict(),
        "notification_requirements": notification_requirements,
        "benchmark_notifications": _coerce_mapping(run.get("benchmark_notifications")),
        "artifacts": {
            "run_json": str(_run_dir(root, run_id) / _RUN_JSON),
            "telemetry_jsonl": str(_run_dir(root, run_id) / _TELEMETRY_JSONL),
            "report_json": str(_run_dir(root, run_id) / _REPORT_JSON),
        },
    }
    report["pending_urgent_alerts"] = [alert.to_dict() for alert in build_benchmark_urgent_alerts(run, report)]
    if persist:
        _write_json(_run_dir(root, run_id) / _REPORT_JSON, report)
    return report


def build_benchmark_urgent_alerts(
    run: Mapping[str, Any],
    report: Mapping[str, Any],
) -> List[BenchmarkUrgentAlert]:
    """Build bounded urgent alerts for benchmark failures and gate blocks."""
    run_id = str(run.get("run_id") or report.get("run_id") or "unknown")
    alerts: List[BenchmarkUrgentAlert] = []
    for idx, outcome in enumerate(_benchmark_failure_outcomes(run), start=1):
        repo_id = ""
        workload_id = str(outcome.get("workload_id") or "")
        message = (
            "Benchmark workload failed or did not pass validation. "
            f"status success={bool(outcome.get('success'))} validation_passed={bool(outcome.get('validation_passed'))}. "
            f"reason={outcome.get('message') or outcome.get('error') or outcome.get('fallback_reasons') or 'not provided'}"
        )
        alerts.append(
            BenchmarkUrgentAlert(
                alert_id=f"{run_id}:failure:{idx}",
                severity="failed",
                title="runtime benchmark workload failed",
                message=message,
                run_id=run_id,
                workload_id=workload_id or None,
                repo_id=repo_id or None,
                blockers=["benchmark_failure"],
            )
        )
    gate = _coerce_mapping(report.get("production_gate"))
    blockers = [str(item) for item in gate.get("blockers", []) if str(item) != "urgent_alerts_missing"]
    if gate and gate.get("allowed") is False and blockers:
        alerts.append(
            BenchmarkUrgentAlert(
                alert_id=f"{run_id}:production_gate",
                severity="blocked",
                title="runtime benchmark production gate blocked",
                message="Production readiness gate blocked rollout for this benchmark run.",
                run_id=run_id,
                blockers=blockers,
            )
        )
    return alerts


def send_benchmark_urgent_alerts(
    alerts: Iterable[BenchmarkUrgentAlert],
    *,
    platform: str = "slack",
    dry_run: bool = False,
    sender: Optional[Callable[[dict[str, Any]], str]] = None,
) -> Dict[str, Any]:
    """Send benchmark alerts through the urgent notification route.

    The sender is injectable for tests and dry runs. Only actual successful
    deliveries count as sent for production-gate accounting.
    """
    from hermes_cli.runtime_urgent_notify import UrgentNotification, send_urgent_notification

    deliveries: List[Dict[str, Any]] = []
    for alert in alerts:
        payload = alert.to_slack_payload()
        notification = UrgentNotification(
            severity=alert.severity,
            title=alert.title,
            message=payload["text"],
            repo_id=alert.repo_id,
            event_kind="runtime_benchmark",
            source=alert.source,
        )
        delivery = send_urgent_notification(
            notification,
            platform=platform,
            dry_run=dry_run,
            sender=sender,
        )
        deliveries.append({
            "alert": alert.to_dict(),
            "status": delivery.get("status"),
            "target": _redact_text(delivery.get("target"), limit=160) if delivery.get("target") else None,
            "dry_run": dry_run,
            "delivery": {
                key: _redact_text(value, limit=240)
                for key, value in _coerce_mapping(delivery.get("delivery")).items()
                if key in {"success", "error", "message", "message_ts", "raw"}
            },
        })
    return {
        "status": "completed",
        "platform": platform,
        "dry_run": dry_run,
        "attempted": len(deliveries),
        "sent": sum(1 for item in deliveries if item.get("status") == "sent"),
        "failed": sum(1 for item in deliveries if item.get("status") == "failed"),
        "skipped": sum(1 for item in deliveries if item.get("status") == "skipped"),
        "deliveries": deliveries,
    }


def send_benchmark_notifications_for_run(
    run_id: str,
    *,
    artifact_root: Optional[str | Path] = None,
    platform: str = "slack",
    dry_run: bool = False,
    sender: Optional[Callable[[dict[str, Any]], str]] = None,
) -> Dict[str, Any]:
    root = _as_path(artifact_root) if artifact_root else _artifact_root_default()
    run = get_benchmark_run(run_id, artifact_root=root)
    report = generate_comparison_report(run_id, artifact_root=root, persist=False)
    alerts = build_benchmark_urgent_alerts(run, report)
    delivery = send_benchmark_urgent_alerts(alerts, platform=platform, dry_run=dry_run, sender=sender)
    run["benchmark_notifications"] = delivery
    _write_json(_run_dir(root, run_id) / _RUN_JSON, run)
    final_report = generate_comparison_report(run_id, artifact_root=root, persist=True)
    return {
        **delivery,
        "run_id": run_id,
        "production_gate": final_report["production_gate"],
        "notification_requirements": final_report["notification_requirements"],
    }


def build_azure_side_by_side_smoke_fixture(*, live: bool = False, env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Return deterministic Azure smoke status without running live providers."""
    source_env = env or os.environ
    required = ("AZURE_SUBSCRIPTION_ID", "AZURE_RESOURCE_GROUP", "AZURE_VM_NAME")
    missing = [name for name in required if not str(source_env.get(name, "")).strip()]
    live_enabled = live or str(source_env.get("HERMES_AZURE_LIVE_SMOKE", "")).strip().lower() in {"1", "true", "yes"}
    blockers: List[str] = []
    if missing:
        blockers.append("missing_azure_live_smoke_configuration")
    if not live_enabled:
        blockers.append("live_azure_smoke_not_opted_in")
    deterministic_fixture = {
        "status": "passed",
        "scenario": "azure-side-by-side-local-fixture",
        "upstream": {
            "execution_mode": "fixture",
            "learning_enabled": False,
            "quality_signal": "comparison-baseline",
        },
        "branch": {
            "execution_mode": "fixture",
            "learning_enabled": True,
            "sidecars_advisory_only": True,
            "enforcement_enabled": False,
            "quality_signal": "memory-wrapper-smoke",
        },
        "metrics": {
            "token_cost_latency_quality_recorded": True,
            "self_learning_results_recorded": True,
            "transcript_storage": "none",
            "secrets_stored": False,
        },
    }
    if live_enabled and not missing:
        status = "blocked"
        blockers.append("live_azure_provider_execution_not_run_by_local_harness")
    else:
        status = "skipped"
    return {
        "status": status,
        "task": "T189",
        "live_smoke": {
            "enabled": live_enabled,
            "required_configuration": list(required),
            "missing_configuration": missing,
            "blockers": blockers,
            "note": "Live Azure/provider smoke is opt-in and was not executed by the deterministic local fixture.",
        },
        "deterministic_fixture": deterministic_fixture,
    }


class CostStatus:
    def __init__(self, artifact_root: Optional[str | Path] = None) -> None:
        self.artifact_root = _as_path(artifact_root) if artifact_root else _artifact_root_default()

    def to_dict(self) -> Dict[str, Any]:
        runs_root = self.artifact_root / "runs"
        runs: List[Dict[str, Any]] = []
        if runs_root.exists():
            for run_json in sorted(runs_root.glob(f"*/{_RUN_JSON}")):
                try:
                    run = _read_json(run_json)
                except Exception:
                    continue
                summary = _coerce_mapping(run.get("telemetry_summary"))
                runs.append(
                    {
                        "run_id": run.get("run_id"),
                        "pack_id": run.get("pack_id"),
                        "estimated_cost_usd": float(summary.get("estimated_cost_usd") or 0.0),
                        "prompt_tokens": int(summary.get("prompt_tokens") or 0),
                        "completion_tokens": int(summary.get("completion_tokens") or 0),
                        "production_gate": run.get("production_gate", {}),
                    }
                )
        return {
            "artifact_root": str(self.artifact_root),
            "run_count": len(runs),
            "total_estimated_cost_usd": _round_money(sum(item["estimated_cost_usd"] for item in runs)),
            "total_prompt_tokens": sum(item["prompt_tokens"] for item in runs),
            "total_completion_tokens": sum(item["completion_tokens"] for item in runs),
            "runs": runs,
        }
