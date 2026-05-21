"""Local MLOps corpus export and remittance helpers.

This module intentionally stops at deterministic corpus artifacts and audit
receipts. It does not schedule training, write model registries, deploy models,
or affect runtime routing.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


FAILURE_REPAIR_SCHEMA = "mlops.corpus.failure_repair.v1"
SFT_MESSAGE_SCHEMA = "mlops.corpus.sft_message.v1"
PREFERENCE_PAIR_SCHEMA = "mlops.corpus.preference_pair.v1"
BUNDLE_SCHEMA = "mlops.corpus.bundle.v1"
REDACTION_REPORT_SCHEMA = "mlops.corpus.redaction_report.v1"
APPROVAL_PROVENANCE_SCHEMA = "mlops.corpus.approval_provenance.v1"
TRAINING_HINTS_SCHEMA = "mlops.training_hints.v1"
DESTINATION_LAYOUT_SCHEMA = "mlops.destination_layout.v1"
REMITTANCE_RECEIPT_SCHEMA = "mlops.remittance_receipt.v1"

FORBIDDEN_EXPORT_KEYS = {
    "raw_transcript",
    "raw_log",
    "raw_logs",
    "secret",
    "secrets",
    "api_key",
    "apikey",
    "token",
    "password",
    "credential",
    "credentials",
}
SENSITIVE_VALUE_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(
        r"(?i)\b(api[_-]?key|token|password|secret|credential)\s*=\s*"
        r"([^\s,;\"'}\]]+)"
    ),
]
HANDOFF_SCAN_FILES = [
    "records.jsonl",
    "preference_pairs.jsonl",
    "manifest.json",
    "redaction_report.json",
    "approval_provenance.json",
    "external_training_hints.json",
    "hashes.json",
]
ALLOWED_METHODS = {"sft", "dpo", "orpo", "lora", "qlora", "full_finetune"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stable_id(prefix: str, data: dict[str, Any]) -> str:
    payload = {k: v for k, v in data.items() if k not in {"record_id", "bundle_id", "receipt_id"}}
    return f"{prefix}_{_sha256_text(_canonical_json(payload))[:24]}"


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            lower = str(key).lower()
            if lower in FORBIDDEN_EXPORT_KEYS:
                continue
            safe[str(key)] = _json_safe(item)
        return safe
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, str):
        return _redact_sensitive_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _redact_sensitive_text(str(value))


def _redact_sensitive_text(text: str) -> str:
    redacted = text
    for pattern in SENSITIVE_VALUE_PATTERNS:
        redacted = pattern.sub(lambda match: f"{match.group(1)}=[REDACTED]" if match.lastindex else "[REDACTED]", redacted)
    return redacted


def _sensitive_text_findings(text: str) -> list[str]:
    findings: list[str] = []
    for pattern in SENSITIVE_VALUE_PATTERNS:
        if pattern.search(text):
            findings.append("sensitive_value")
    return findings


def _scan_forbidden_export_content(value: Any, *, source: str, location: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            child_location = f"{location}.{key_text}"
            if key_text.lower() in FORBIDDEN_EXPORT_KEYS:
                errors.append(f"forbidden_key:{source}:{child_location}")
            errors.extend(_scan_forbidden_export_content(item, source=source, location=child_location))
        return errors
    if isinstance(value, list):
        for index, item in enumerate(value):
            errors.extend(_scan_forbidden_export_content(item, source=source, location=f"{location}[{index}]"))
        return errors
    if isinstance(value, str):
        if _sensitive_text_findings(value):
            errors.append(f"forbidden_value:{source}:{location}")
    return errors


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.write_text(
        "".join(_canonical_json(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class FailureRepairRecord:
    tenant_id: str
    scope: str
    dataset_family: str
    task: dict[str, Any]
    lesser_attempt: dict[str, Any]
    teacher_repair: dict[str, Any]
    validation: dict[str, Any]
    lesson: dict[str, Any]
    safety: dict[str, Any]
    approval: dict[str, Any]
    record_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "schema_version": FAILURE_REPAIR_SCHEMA,
            "tenant_id": self.tenant_id,
            "scope": self.scope,
            "dataset_family": self.dataset_family,
            "task": _json_safe(self.task),
            "lesser_attempt": _json_safe(self.lesser_attempt),
            "teacher_repair": _json_safe(self.teacher_repair),
            "validation": _json_safe(self.validation),
            "lesson": _json_safe(self.lesson),
            "safety": _json_safe(self.safety),
            "approval": _json_safe(self.approval),
        }
        data["record_id"] = self.record_id or _stable_id("fr", data)
        return data


@dataclass(frozen=True)
class SFTMessageRecord:
    dataset_family: str
    messages: list[dict[str, str]]
    metadata: dict[str, Any]
    record_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "schema_version": SFT_MESSAGE_SCHEMA,
            "record_type": "sft",
            "dataset_family": self.dataset_family,
            "messages": _json_safe(self.messages),
            "metadata": _json_safe(self.metadata),
        }
        data["record_id"] = self.record_id or _stable_id("sft", data)
        return data


@dataclass(frozen=True)
class PreferencePairRecord:
    dataset_family: str
    prompt_summary: str
    chosen: str
    rejected: str
    metadata: dict[str, Any]
    record_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "schema_version": PREFERENCE_PAIR_SCHEMA,
            "record_type": "preference_pair",
            "dataset_family": self.dataset_family,
            "prompt_summary": _json_safe(self.prompt_summary),
            "chosen": _json_safe(self.chosen),
            "rejected": _json_safe(self.rejected),
            "metadata": _json_safe(self.metadata),
        }
        data["record_id"] = self.record_id or _stable_id("pp", data)
        return data


@dataclass(frozen=True)
class ApprovalProvenance:
    approval_refs: list[str]
    candidate_refs: list[str]
    judge_refs: list[str]
    operator_refs: list[str]

    @classmethod
    def from_records(cls, records: Iterable[FailureRepairRecord]) -> "ApprovalProvenance":
        candidate_refs: set[str] = set()
        judge_refs: set[str] = set()
        operator_refs: set[str] = set()
        for record in records:
            approval = record.to_dict().get("approval", {})
            if approval.get("candidate_id"):
                candidate_refs.add(f"candidate://{approval['candidate_id']}")
            if approval.get("judge_decision_id"):
                judge_refs.add(f"judge://{approval['judge_decision_id']}")
            if approval.get("operator_approval_id"):
                operator_refs.add(f"approval://{approval['operator_approval_id']}")
        return cls(
            approval_refs=sorted(operator_refs),
            candidate_refs=sorted(candidate_refs),
            judge_refs=sorted(judge_refs),
            operator_refs=sorted(operator_refs),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": APPROVAL_PROVENANCE_SCHEMA,
            "approval_refs": self.approval_refs,
            "candidate_refs": self.candidate_refs,
            "judge_refs": self.judge_refs,
            "operator_refs": self.operator_refs,
            "approval_state": "approved" if self.approval_refs else "missing",
        }


@dataclass(frozen=True)
class RedactionReport:
    redaction_state: str
    contains_raw_transcript: bool
    contains_secret: bool
    tenant_shareability: list[str]
    checked_record_count: int

    @classmethod
    def from_records(
        cls,
        records: Iterable[FailureRepairRecord],
        preference_pairs: Iterable[PreferencePairRecord] = (),
    ) -> "RedactionReport":
        record_dicts = [record.to_dict() for record in records]
        pair_dicts = [pair.to_dict() for pair in preference_pairs]
        contains_raw = any(
            item.get("safety", {}).get("contains_raw_transcript") is True for item in record_dicts
        )
        contains_secret = any(item.get("safety", {}).get("contains_secret") is True for item in record_dicts)
        shareability = sorted(
            {
                item.get("safety", {}).get("tenant_shareability", "tenant_only")
                for item in record_dicts
            }
        )
        return cls(
            redaction_state="unsafe" if contains_raw or contains_secret else "safe",
            contains_raw_transcript=contains_raw,
            contains_secret=contains_secret,
            tenant_shareability=shareability,
            checked_record_count=len(record_dicts) + len(pair_dicts),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": REDACTION_REPORT_SCHEMA,
            "redaction_state": self.redaction_state,
            "contains_raw_transcript": self.contains_raw_transcript,
            "contains_secret": self.contains_secret,
            "tenant_shareability": self.tenant_shareability,
            "checked_record_count": self.checked_record_count,
        }


@dataclass(frozen=True)
class ExternalTrainingHint:
    target_model_family: str
    target_base_models: list[str]
    recommended_methods: list[str]
    corpus_refs: list[str]
    eval_refs: list[str]
    approval_refs: list[str]
    approval_state: str = "approved"
    notes: str = "External MLOps may train end-of-day or streaming batches."

    @classmethod
    def build(
        cls,
        *,
        target_model_family: str,
        target_base_models: list[str],
        recommended_methods: list[str],
        corpus_refs: list[str],
        eval_refs: list[str],
        approval_refs: list[str],
        approval_state: str = "approved",
        notes: str = "External MLOps may train end-of-day or streaming batches.",
    ) -> "ExternalTrainingHint":
        methods = [method for method in recommended_methods if method in ALLOWED_METHODS]
        return cls(
            target_model_family=target_model_family,
            target_base_models=target_base_models,
            recommended_methods=methods,
            corpus_refs=corpus_refs,
            eval_refs=eval_refs,
            approval_refs=approval_refs,
            approval_state=approval_state,
            notes=notes,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TRAINING_HINTS_SCHEMA,
            "target_model_family": self.target_model_family,
            "target_base_models": self.target_base_models,
            "recommended_methods": self.recommended_methods,
            "corpus_refs": self.corpus_refs,
            "eval_refs": self.eval_refs,
            "approval_refs": self.approval_refs,
            "approval_state": self.approval_state,
            "notes": self.notes,
            "schedules_training": False,
        }


@dataclass(frozen=True)
class BundleResult:
    path: Path
    manifest: dict[str, Any]
    hashes: dict[str, str]


class LocalCorpusBundleWriter:
    def __init__(self, root: Path):
        self.root = Path(root)

    def write_bundle(
        self,
        *,
        records: list[FailureRepairRecord],
        preference_pairs: list[PreferencePairRecord],
        redaction_report: RedactionReport,
        approval_provenance: ApprovalProvenance,
        external_training_hints: ExternalTrainingHint,
        dataset_families: list[str] | None = None,
        created_at: str | None = None,
    ) -> BundleResult:
        families = set(dataset_families or [])
        record_rows = [record.to_dict() for record in records]
        if families:
            record_rows = [row for row in record_rows if row.get("dataset_family") in families]
        record_rows = sorted(record_rows, key=lambda row: row["record_id"])

        pair_rows = [pair.to_dict() for pair in preference_pairs]
        if families:
            pair_rows = [row for row in pair_rows if row.get("dataset_family") in families]
        pair_rows = sorted(pair_rows, key=lambda row: row["record_id"])

        if not record_rows:
            raise ValueError("at least one approved failure/repair record is required")
        tenant_ids = sorted({row["tenant_id"] for row in record_rows})
        scopes = sorted({row["scope"] for row in record_rows})
        dataset_values = sorted({row["dataset_family"] for row in record_rows})
        if len(tenant_ids) != 1 or len(scopes) != 1 or len(dataset_values) != 1:
            raise ValueError("bundle records must share tenant_id, scope, and dataset_family")

        created = created_at or _now_iso()
        manifest_seed = {
            "created_at": created,
            "tenant_id": tenant_ids[0],
            "scope": scopes[0],
            "dataset_family": dataset_values[0],
            "record_ids": [row["record_id"] for row in record_rows],
            "preference_pair_ids": [row["record_id"] for row in pair_rows],
        }
        bundle_id = f"bundle_{_sha256_text(_canonical_json(manifest_seed))[:24]}"
        bundle_path = self.root / bundle_id
        bundle_path.mkdir(parents=True, exist_ok=True)

        _write_jsonl(bundle_path / "records.jsonl", record_rows)
        _write_jsonl(bundle_path / "preference_pairs.jsonl", pair_rows)
        redaction_data = redaction_report.to_dict()
        approval_data = approval_provenance.to_dict()
        hints_data = external_training_hints.to_dict()
        if hints_data.get("corpus_refs") == ["bundle://pending"]:
            hints_data["corpus_refs"] = [f"bundle://{bundle_id}"]
        _write_json(bundle_path / "redaction_report.json", redaction_data)
        _write_json(bundle_path / "approval_provenance.json", approval_data)
        _write_json(bundle_path / "external_training_hints.json", hints_data)

        records_sha = _file_sha(bundle_path / "records.jsonl")
        pairs_sha = _file_sha(bundle_path / "preference_pairs.jsonl")
        manifest = {
            "schema_version": BUNDLE_SCHEMA,
            "bundle_id": bundle_id,
            "created_at": created,
            "tenant_id": tenant_ids[0],
            "scope": scopes[0],
            "dataset_family": dataset_values[0],
            "record_count": len(record_rows),
            "preference_pair_count": len(pair_rows),
            "artifact_formats": ["jsonl"],
            "format_compatibility": ["jsonl", "parquet"],
            "parquet_compatibility": {
                "status": "manifest_metadata_only",
                "row_groups": ["records.jsonl", "preference_pairs.jsonl"],
                "schema_hint": "mlops.corpus.failure_repair.v1",
            },
            "hash_algorithm": "sha256",
            "records_sha256": records_sha,
            "preference_pairs_sha256": pairs_sha,
            "redaction_report_ref": "redaction_report.json",
            "approval_provenance_ref": "approval_provenance.json",
            "external_training_hints_ref": "external_training_hints.json",
            "reproducibility": {
                "ordering": "record_id_ascending",
                "json": "canonical_sort_keys_compact_jsonl",
                "created_by": "hermes-local-corpus-writer",
            },
        }
        _write_json(bundle_path / "manifest.json", manifest)

        file_hashes = {
            "records.jsonl": records_sha,
            "preference_pairs.jsonl": pairs_sha,
            "manifest.json": _file_sha(bundle_path / "manifest.json"),
            "redaction_report.json": _file_sha(bundle_path / "redaction_report.json"),
            "approval_provenance.json": _file_sha(bundle_path / "approval_provenance.json"),
            "external_training_hints.json": _file_sha(bundle_path / "external_training_hints.json"),
        }
        hashes = dict(file_hashes)
        hashes["bundle_sha256"] = _sha256_text(_canonical_json(file_hashes))
        _write_json(bundle_path / "hashes.json", hashes)
        return BundleResult(path=bundle_path, manifest=manifest, hashes=hashes)


class DestinationLayoutPlanner:
    def __init__(self, root: Path):
        self.root = Path(root)

    def plan(
        self,
        *,
        tenant_id: str,
        scope: str,
        dataset_family: str,
        model_family: str,
        date: str,
    ) -> dict[str, Any]:
        relative = (
            Path(f"tenant_id={tenant_id}")
            / f"scope={scope}"
            / f"dataset_family={dataset_family}"
            / f"model_family={model_family}"
            / f"date={date}"
        )
        destination = (self.root / relative).resolve()
        return {
            "schema_version": DESTINATION_LAYOUT_SCHEMA,
            "format_compatibility": ["delta", "iceberg"],
            "partition_fields": ["tenant_id", "scope", "dataset_family", "model_family", "date"],
            "tenant_id": tenant_id,
            "scope": scope,
            "dataset_family": dataset_family,
            "model_family": model_family,
            "date": date,
            "relative_path": relative.as_posix(),
            "destination_uri": destination.as_uri(),
            "planned_files": [
                "records.jsonl",
                "preference_pairs.jsonl",
                "manifest.json",
                "redaction_report.json",
                "approval_provenance.json",
                "external_training_hints.json",
                "remittance_receipt.json",
            ],
        }


class RemittanceReceiptWriter:
    def __init__(self, bundle_path: Path):
        self.bundle_path = Path(bundle_path)

    def write_receipt(
        self,
        *,
        bundle: BundleResult | None = None,
        destination_uri: str,
        external_pipeline_id: str = "",
        submitted_at: str | None = None,
        status: str = "submitted",
        receipt_id: str | None = None,
    ) -> dict[str, Any]:
        manifest = _read_json(self.bundle_path / "manifest.json")
        hashes = _read_json(self.bundle_path / "hashes.json")
        approval = _read_json(self.bundle_path / "approval_provenance.json")
        submitted = submitted_at or _now_iso()
        seed = {
            "bundle_id": manifest["bundle_id"],
            "destination_uri": destination_uri,
            "bundle_sha256": hashes["bundle_sha256"],
            "submitted_at": submitted,
            "external_pipeline_id": external_pipeline_id,
        }
        rid = receipt_id or f"receipt_{_sha256_text(_canonical_json(seed))[:24]}"
        receipt_path = self.bundle_path / "remittance_receipt.json"
        if receipt_path.exists():
            existing = _read_json(receipt_path)
            if existing.get("receipt_id") == rid:
                raise FileExistsError(f"immutable remittance receipt already exists: {rid}")
            raise FileExistsError("immutable remittance receipt already exists")
        receipt = {
            "schema_version": REMITTANCE_RECEIPT_SCHEMA,
            "receipt_id": rid,
            "bundle_id": manifest["bundle_id"],
            "destination_uri": destination_uri,
            "bundle_sha256": hashes["bundle_sha256"],
            "submitted_at": submitted,
            "external_pipeline_id": external_pipeline_id,
            "status": status,
            "audit_refs": [f"audit://{rid}"],
            "approval_refs": approval.get("approval_refs", []),
            "schema_ref": manifest["schema_version"],
            "audit_status": "immutable",
        }
        _write_json(receipt_path, receipt)
        return receipt


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _scan_handoff_artifacts(path: Path) -> list[str]:
    errors: list[str] = []
    for name in HANDOFF_SCAN_FILES:
        artifact = path / name
        if not artifact.exists():
            continue
        if name.endswith(".jsonl"):
            for line_number, line in enumerate(artifact.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    errors.append(f"invalid_json:{name}:{line_number}")
                    continue
                errors.extend(
                    _scan_forbidden_export_content(row, source=f"{name}:{line_number}")
                )
            continue
        try:
            data = _read_json(artifact)
        except json.JSONDecodeError:
            errors.append(f"invalid_json:{name}")
            continue
        errors.extend(_scan_forbidden_export_content(data, source=name))
    return errors


def validate_handoff(bundle_path: str | Path) -> dict[str, Any]:
    path = Path(bundle_path)
    errors: list[str] = []
    required = HANDOFF_SCAN_FILES
    for name in required:
        if not (path / name).exists():
            errors.append(f"missing:{name}")
    if errors:
        return {"valid": False, "errors": errors, "bundle_path": str(path)}

    manifest = _read_json(path / "manifest.json")
    redaction = _read_json(path / "redaction_report.json")
    approval = _read_json(path / "approval_provenance.json")
    hints = _read_json(path / "external_training_hints.json")
    hashes = _read_json(path / "hashes.json")
    errors.extend(_scan_handoff_artifacts(path))
    if manifest.get("schema_version") != BUNDLE_SCHEMA:
        errors.append("invalid:manifest_schema_version")
    if redaction.get("redaction_state") != "safe":
        errors.append("invalid:redaction_state")
    if redaction.get("contains_raw_transcript") or redaction.get("contains_secret"):
        errors.append("invalid:redaction_report")
    if not redaction.get("tenant_shareability"):
        errors.append("missing:tenant_shareability")
    if not approval.get("approval_refs"):
        errors.append("missing:approval_refs")
    if hints.get("schema_version") != TRAINING_HINTS_SCHEMA:
        errors.append("invalid:training_hints_schema_version")
    if hints.get("schedules_training") is not False:
        errors.append("invalid:training_hints_schedule_training")
    for key in ("records_sha256", "preference_pairs_sha256"):
        if not manifest.get(key):
            errors.append(f"missing:{key}")
    if not hashes.get("bundle_sha256"):
        errors.append("missing:bundle_sha256")
    if _file_sha(path / "records.jsonl") != manifest.get("records_sha256"):
        errors.append("hash_mismatch:records.jsonl")
    if _file_sha(path / "preference_pairs.jsonl") != manifest.get("preference_pairs_sha256"):
        errors.append("hash_mismatch:preference_pairs.jsonl")
    return {
        "valid": not errors,
        "errors": errors,
        "bundle_path": str(path),
        "bundle_id": manifest.get("bundle_id"),
        "hashes": hashes,
    }


def corpus_boundary_capabilities(_: dict[str, Any] | None = None) -> dict[str, bool]:
    return {
        "can_train": False,
        "can_register": False,
        "can_deploy": False,
        "can_promote": False,
        "can_route": False,
    }


def _fixture_record() -> FailureRepairRecord:
    return FailureRepairRecord(
        tenant_id="tenant-a",
        scope="tenant",
        dataset_family="failure_repair",
        task={
            "task_type": "coding",
            "repo_ref": "hermes-agent@71aedb4",
            "spec_ref": "specs/001-learning-memory-runtime/tasks.md#T289",
            "summary": "Produce approved local training records from a lesser-model failure.",
        },
        lesser_attempt={
            "model_family": "gemma",
            "model": "gemma-4-26b",
            "summary": "Claimed the implementation was complete before validation.",
            "failure_type": "hallucinated_completion",
            "evidence_refs": ["memory://fixture/gemma-failure", "test://fixture/red"],
        },
        teacher_repair={
            "model_family": "codex",
            "model": "codex",
            "diagnosis": "Validation evidence was missing.",
            "correction_summary": "Generated bounded records, deterministic bundle artifacts, and a receipt.",
            "repair_refs": ["spec://T289", "test://fixture/green"],
        },
        validation={
            "status": "passed",
            "evidence_refs": ["test://fixture/green"],
            "false_completion_checked": True,
            "tool_misuse_checked": True,
        },
        lesson={
            "distilled_behavior": "Preserve validation evidence in bounded summaries.",
            "forbidden_behavior": "Do not export raw transcripts, secrets, or unapproved tenant data.",
        },
        safety={
            "redaction_state": "safe",
            "contains_raw_transcript": False,
            "contains_secret": False,
            "tenant_shareability": "tenant_only",
        },
        approval={
            "candidate_id": "metacand-gemma-codex",
            "judge_decision_id": "judge-gemma-codex",
            "operator_approval_id": "approval-gemma-codex",
        },
    )


def _fixture_pair() -> PreferencePairRecord:
    return PreferencePairRecord(
        dataset_family="failure_repair",
        prompt_summary="Gemma-class coding task with compact repo and validation context.",
        chosen="Codex repair summary that includes validation evidence.",
        rejected="Gemma failure summary that claimed completion without evidence.",
        metadata={
            "failure_type": "hallucinated_completion",
            "chosen_validation": "passed",
            "rejected_validation": "failed",
            "approval_state": "approved",
        },
    )


def build_gemma_codex_e2e_fixture(root: Path, submitted_at: str | None = None) -> dict[str, Any]:
    record = _fixture_record()
    pair = _fixture_pair()
    approval = ApprovalProvenance.from_records([record])
    redaction = RedactionReport.from_records([record], [pair])
    hints = ExternalTrainingHint.build(
        target_model_family="gemma",
        target_base_models=["gemma-4-26b"],
        recommended_methods=["sft", "dpo", "orpo", "lora", "qlora"],
        corpus_refs=["bundle://pending"],
        eval_refs=["benchmark://heldout-hermes-runtime"],
        approval_refs=approval.approval_refs,
    )
    bundle = LocalCorpusBundleWriter(Path(root)).write_bundle(
        records=[record],
        preference_pairs=[pair],
        redaction_report=redaction,
        approval_provenance=approval,
        external_training_hints=hints,
        created_at="2026-05-20T00:00:00Z",
    )
    receipt = RemittanceReceiptWriter(bundle.path).write_receipt(
        bundle=bundle,
        destination_uri=(bundle.path / "remitted").resolve().as_uri(),
        external_pipeline_id="external-fixture-pipeline",
        submitted_at=submitted_at or "2026-05-20T00:00:00Z",
    )
    return {
        "bundle_path": str(bundle.path),
        "bundle": bundle.manifest,
        "hashes": bundle.hashes,
        "receipt": receipt,
        "record": record.to_dict(),
        "preference_pair": pair.to_dict(),
        "boundary_flags": corpus_boundary_capabilities(receipt),
    }


def export_fixture_bundle(artifact_root: Path) -> dict[str, Any]:
    fixture = build_gemma_codex_e2e_fixture(Path(artifact_root), submitted_at="2026-05-20T00:00:00Z")
    receipt_path = Path(fixture["bundle_path"]) / "remittance_receipt.json"
    if receipt_path.exists():
        receipt_path.unlink()
    manifest = _read_json(Path(fixture["bundle_path"]) / "manifest.json")
    hashes = _read_json(Path(fixture["bundle_path"]) / "hashes.json")
    return {
        "status": "exported",
        "bundle_id": manifest["bundle_id"],
        "bundle_path": fixture["bundle_path"],
        "manifest": manifest,
        "hashes": hashes,
        "boundary_flags": corpus_boundary_capabilities(manifest),
    }


def remit_bundle(
    bundle_path: Path,
    *,
    destination_uri: str,
    external_pipeline_id: str = "",
    submitted_at: str | None = None,
) -> dict[str, Any]:
    validation = validate_handoff(bundle_path)
    if not validation["valid"]:
        raise ValueError(f"bundle failed handoff validation: {validation['errors']}")
    receipt = RemittanceReceiptWriter(bundle_path).write_receipt(
        destination_uri=destination_uri,
        external_pipeline_id=external_pipeline_id,
        submitted_at=submitted_at,
    )
    return {**receipt, "boundary_flags": corpus_boundary_capabilities(receipt)}


def list_receipts(artifact_root: Path) -> dict[str, Any]:
    root = Path(artifact_root)
    receipts = [
        _read_json(path)
        for path in sorted(root.glob("**/remittance_receipt.json"))
    ]
    return {
        "schema_version": "mlops.remittance_receipts.v1",
        "receipt_count": len(receipts),
        "receipts": receipts,
    }
