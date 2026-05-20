import json
import subprocess
import sys
from pathlib import Path

import pytest

from hermes_cli.mlops_corpus import (
    ApprovalProvenance,
    DestinationLayoutPlanner,
    ExternalTrainingHint,
    FailureRepairRecord,
    LocalCorpusBundleWriter,
    PreferencePairRecord,
    RedactionReport,
    RemittanceReceiptWriter,
    SFTMessageRecord,
    build_gemma_codex_e2e_fixture,
    corpus_boundary_capabilities,
    validate_handoff,
)


def _failure_record(dataset_family: str = "failure_repair", tenant_id: str = "tenant-a") -> FailureRepairRecord:
    return FailureRepairRecord(
        tenant_id=tenant_id,
        scope="tenant",
        dataset_family=dataset_family,
        task={
            "task_type": "coding",
            "repo_ref": "hermes-agent@71aedb4",
            "spec_ref": "specs/001-learning-memory-runtime/tasks.md#T275",
            "summary": "Implement local corpus export records with validation.",
        },
        lesser_attempt={
            "model_family": "gemma",
            "model": "gemma-4-26b",
            "summary": "Claimed completion before running the required focused tests.",
            "failure_type": "hallucinated_completion",
            "evidence_refs": ["memory://runtime/failure-1", "test://red/focused-pytest"],
        },
        teacher_repair={
            "model_family": "codex",
            "model": "codex",
            "diagnosis": "The attempt skipped validation and overstated completion.",
            "correction_summary": "Added bounded DTOs, local bundle writing, and focused tests.",
            "repair_refs": ["git://working-tree", "spec://T282", "test://green/focused-pytest"],
        },
        validation={
            "status": "passed",
            "evidence_refs": ["test://green/focused-pytest"],
            "false_completion_checked": True,
            "tool_misuse_checked": True,
        },
        lesson={
            "distilled_behavior": "Run the declared focused validation before reporting completion.",
            "forbidden_behavior": "Do not export raw transcripts or claim validation without evidence.",
        },
        safety={
            "redaction_state": "safe",
            "contains_raw_transcript": False,
            "contains_secret": False,
            "tenant_shareability": "tenant_only",
        },
        approval={
            "candidate_id": "metacand-1",
            "judge_decision_id": "judge-1",
            "operator_approval_id": "approval-1",
        },
    )


def _sft_record() -> SFTMessageRecord:
    return SFTMessageRecord(
        dataset_family="failure_repair",
        messages=[
            {"role": "system", "content": "You are a coding agent. Validate before final response."},
            {"role": "user", "content": "Task packet summary and bounded repo context."},
            {"role": "assistant", "content": "Corrected plan, patch summary, and validation evidence."},
        ],
        metadata={
            "tenant_id": "tenant-a",
            "repo_ref": "hermes-agent@71aedb4",
            "task_type": "coding",
            "failed_model": "gemma-4-26b",
            "teacher_model": "codex",
            "failure_type": "hallucinated_completion",
            "validation_passed": True,
            "redaction_state": "safe",
            "approval_state": "approved",
        },
    )


def _preference_pair() -> PreferencePairRecord:
    return PreferencePairRecord(
        dataset_family="failure_repair",
        prompt_summary="Task packet plus compact repo, memory, and tool context.",
        chosen="Teacher-corrected response summary with validation evidence.",
        rejected="Lesser-model response summary that failed validation.",
        metadata={
            "failure_type": "hallucinated_completion",
            "chosen_validation": "passed",
            "rejected_validation": "failed",
            "approval_state": "approved",
        },
    )


def test_failure_repair_record_schema_covers_repair_redaction_and_approval():
    record = _failure_record()
    data = record.to_dict()

    assert data["schema_version"] == "mlops.corpus.failure_repair.v1"
    assert data["record_id"].startswith("fr_")
    assert data["lesser_attempt"]["model_family"] == "gemma"
    assert data["lesser_attempt"]["failure_type"] == "hallucinated_completion"
    assert data["lesser_attempt"]["evidence_refs"] == ["memory://runtime/failure-1", "test://red/focused-pytest"]
    assert data["teacher_repair"]["model_family"] == "codex"
    assert data["teacher_repair"]["diagnosis"]
    assert data["teacher_repair"]["repair_refs"] == ["git://working-tree", "spec://T282", "test://green/focused-pytest"]
    assert data["validation"]["false_completion_checked"] is True
    assert data["validation"]["tool_misuse_checked"] is True
    assert data["lesson"]["distilled_behavior"]
    assert data["lesson"]["forbidden_behavior"]
    assert data["safety"] == {
        "redaction_state": "safe",
        "contains_raw_transcript": False,
        "contains_secret": False,
        "tenant_shareability": "tenant_only",
    }
    assert data["approval"] == {
        "candidate_id": "metacand-1",
        "judge_decision_id": "judge-1",
        "operator_approval_id": "approval-1",
    }
    assert "full raw transcript" not in json.dumps(data)
    assert "sk-live-secret" not in json.dumps(data)


def test_sft_and_preference_pair_records_are_bounded_and_validated():
    sft = _sft_record().to_dict()
    pair = _preference_pair().to_dict()

    assert sft["schema_version"] == "mlops.corpus.sft_message.v1"
    assert sft["record_type"] == "sft"
    assert [msg["role"] for msg in sft["messages"]] == ["system", "user", "assistant"]
    assert sft["metadata"]["validation_passed"] is True
    assert sft["metadata"]["approval_state"] == "approved"
    assert pair["schema_version"] == "mlops.corpus.preference_pair.v1"
    assert pair["chosen"] != pair["rejected"]
    assert pair["metadata"] == {
        "failure_type": "hallucinated_completion",
        "chosen_validation": "passed",
        "rejected_validation": "failed",
        "approval_state": "approved",
    }


def test_records_redact_forbidden_keys_and_sensitive_string_values():
    record = FailureRepairRecord(
        tenant_id="tenant-a",
        scope="tenant",
        dataset_family="failure_repair",
        task={
            "summary": "Use api_key=fake-api-key-value and sk-fakeSecret123 only as fixture text.",
            "Raw_Transcript": "full raw transcript with fake secret",
        },
        lesser_attempt={
            "model_family": "gemma",
            "raw_log": "raw log field should not export",
            "nested": {"TOKEN": "fake-token-value", "keep": "diagnostic summary"},
        },
        teacher_repair={
            "model_family": "codex",
            "diagnosis": "password=fake-password-value credential=fake-credential-value",
        },
        validation={"status": "passed"},
        lesson={"distilled_behavior": "Do not leak token=fake-token-value."},
        safety={
            "redaction_state": "safe",
            "contains_raw_transcript": False,
            "contains_secret": False,
            "tenant_shareability": "tenant_only",
        },
        approval={"operator_approval_id": "approval-1"},
    )
    pair = PreferencePairRecord(
        dataset_family="failure_repair",
        prompt_summary="Prompt with api-key=fake-api-key-value.",
        chosen="Chosen sk-fakeSecret123 should be redacted.",
        rejected="Rejected token=fake-token-value should be redacted.",
        metadata={"apiKey": "fake-api-key-value", "approval_state": "approved"},
    )

    exported = json.dumps({"record": record.to_dict(), "pair": pair.to_dict()}, sort_keys=True)

    assert "[REDACTED]" in exported
    for forbidden in [
        "Raw_Transcript",
        "raw_log",
        "TOKEN",
        "apiKey",
        "sk-fakeSecret123",
        "fake-api-key-value",
        "fake-token-value",
        "fake-password-value",
        "fake-credential-value",
    ]:
        assert forbidden not in exported


def test_local_jsonl_bundle_is_deterministic_redacted_and_filterable(tmp_path):
    records = [_failure_record(dataset_family="tool_misuse_repair"), _failure_record()]
    pairs = [_preference_pair()]
    approval = ApprovalProvenance.from_records(records)
    redaction = RedactionReport.from_records(records, pairs)
    hints = ExternalTrainingHint.build(
        target_model_family="gemma",
        target_base_models=["gemma-4-26b"],
        recommended_methods=["sft", "dpo", "lora", "qlora"],
        corpus_refs=["bundle://pending"],
        eval_refs=["benchmark://heldout-hermes-runtime"],
        approval_refs=approval.approval_refs,
    )

    first = LocalCorpusBundleWriter(tmp_path / "a").write_bundle(
        records=records,
        preference_pairs=pairs,
        redaction_report=redaction,
        approval_provenance=approval,
        external_training_hints=hints,
        dataset_families=["failure_repair"],
        created_at="2026-05-20T00:00:00Z",
    )
    second = LocalCorpusBundleWriter(tmp_path / "b").write_bundle(
        records=list(reversed(records)),
        preference_pairs=pairs,
        redaction_report=redaction,
        approval_provenance=approval,
        external_training_hints=hints,
        dataset_families=["failure_repair"],
        created_at="2026-05-20T00:00:00Z",
    )

    assert first.manifest["schema_version"] == "mlops.corpus.bundle.v1"
    assert first.manifest["record_count"] == 1
    assert first.manifest == second.manifest
    assert first.hashes == second.hashes
    assert first.manifest["tenant_id"] == "tenant-a"
    assert first.manifest["scope"] == "tenant"
    assert first.manifest["dataset_family"] == "failure_repair"
    for name in [
        "records.jsonl",
        "preference_pairs.jsonl",
        "manifest.json",
        "redaction_report.json",
        "approval_provenance.json",
        "external_training_hints.json",
        "hashes.json",
    ]:
        assert (first.path / name).exists()
    exported = "\n".join(path.read_text(encoding="utf-8") for path in first.path.iterdir() if path.is_file())
    assert "full raw transcript" not in exported
    assert "sk-live-secret" not in exported
    assert "tenant-b" not in exported


def test_delta_iceberg_destination_layout_metadata_is_stable_without_services(tmp_path):
    layout = DestinationLayoutPlanner(tmp_path / "training_corpus").plan(
        tenant_id="tenant-a",
        scope="tenant",
        dataset_family="failure_repair",
        model_family="gemma",
        date="2026-05-20",
    )

    assert layout["schema_version"] == "mlops.destination_layout.v1"
    assert layout["format_compatibility"] == ["delta", "iceberg"]
    assert layout["partition_fields"] == ["tenant_id", "scope", "dataset_family", "model_family", "date"]
    assert layout["destination_uri"].startswith("file://")
    assert "tenant_id=tenant-a/scope=tenant/dataset_family=failure_repair/model_family=gemma/date=2026-05-20" in layout["relative_path"]
    assert "kafka" not in json.dumps(layout).lower()
    assert "spark" not in json.dumps(layout).lower()


def test_external_training_hints_are_advisory_and_never_jobs():
    hint = ExternalTrainingHint.build(
        target_model_family="gemma",
        target_base_models=["gemma-4-26b"],
        recommended_methods=["sft", "dpo", "orpo", "lora", "qlora", "full_finetune"],
        corpus_refs=["bundle://bundle-1"],
        eval_refs=["benchmark://heldout-hermes-runtime"],
        approval_refs=["approval://approval-1"],
        approval_state="approved",
    ).to_dict()

    assert hint["schema_version"] == "mlops.training_hints.v1"
    assert hint["target_model_family"] == "gemma"
    assert "full_finetune" in hint["recommended_methods"]
    assert hint["approval_state"] == "approved"
    assert "job_id" not in hint
    assert "training_job" not in hint
    assert hint["schedules_training"] is False


def test_remittance_receipt_is_immutable_audit_record(tmp_path):
    record = _failure_record()
    bundle = LocalCorpusBundleWriter(tmp_path / "bundle").write_bundle(
        records=[record],
        preference_pairs=[_preference_pair()],
        redaction_report=RedactionReport.from_records([record], [_preference_pair()]),
        approval_provenance=ApprovalProvenance.from_records([record]),
        external_training_hints=ExternalTrainingHint.build(
            target_model_family="gemma",
            target_base_models=["gemma-4-26b"],
            recommended_methods=["sft"],
            corpus_refs=["bundle://pending"],
            eval_refs=["benchmark://heldout-hermes-runtime"],
            approval_refs=["approval://approval-1"],
        ),
        created_at="2026-05-20T00:00:00Z",
    )
    writer = RemittanceReceiptWriter(bundle.path)
    receipt = writer.write_receipt(
        bundle=bundle,
        destination_uri="file:///tmp/hermes/training_corpus",
        external_pipeline_id="external-pipeline-123",
        submitted_at="2026-05-20T00:00:00Z",
        status="submitted",
    )

    assert receipt["schema_version"] == "mlops.remittance_receipt.v1"
    assert receipt["destination_uri"] == "file:///tmp/hermes/training_corpus"
    assert receipt["bundle_sha256"] == bundle.hashes["bundle_sha256"]
    assert receipt["approval_refs"] == ["approval://approval-1"]
    assert receipt["external_pipeline_id"] == "external-pipeline-123"
    assert receipt["submitted_at"] == "2026-05-20T00:00:00Z"
    assert receipt["audit_status"] == "immutable"
    with pytest.raises(FileExistsError):
        writer.write_receipt(
            bundle=bundle,
            destination_uri="file:///tmp/hermes/training_corpus",
            external_pipeline_id="external-pipeline-123",
            submitted_at="2026-05-20T00:00:00Z",
            receipt_id=receipt["receipt_id"],
        )


def test_handoff_validator_and_boundary_guards_prevent_training_or_deployment(tmp_path):
    fixture = build_gemma_codex_e2e_fixture(tmp_path, submitted_at="2026-05-20T00:00:00Z")
    validation = validate_handoff(fixture["bundle_path"])
    flags = corpus_boundary_capabilities(fixture["receipt"])

    assert validation["valid"] is True
    assert validation["errors"] == []
    assert flags == {
        "can_train": False,
        "can_register": False,
        "can_deploy": False,
        "can_promote": False,
        "can_route": False,
    }
    assert fixture["receipt"]["status"] == "submitted"
    assert fixture["record"]["lesser_attempt"]["model_family"] == "gemma"
    assert fixture["record"]["teacher_repair"]["model_family"] == "codex"


@pytest.mark.parametrize(
    "artifact_name",
    [
        "records.jsonl",
        "preference_pairs.jsonl",
        "manifest.json",
        "redaction_report.json",
        "approval_provenance.json",
        "external_training_hints.json",
        "hashes.json",
    ],
)
def test_handoff_validation_fails_closed_on_tampered_secret_or_raw_artifacts(tmp_path, artifact_name):
    fixture = build_gemma_codex_e2e_fixture(tmp_path, submitted_at="2026-05-20T00:00:00Z")
    bundle_path = Path(fixture["bundle_path"])
    artifact_path = bundle_path / artifact_name
    leaked = {
        "raw_transcript": "full raw transcript should fail validation",
        "operator_note": "secret=fake-secret-value api-key=fake-api-key-value token=fake-token-value sk-fakeSecret123",
    }

    if artifact_name.endswith(".jsonl"):
        with artifact_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(leaked, sort_keys=True) + "\n")
    else:
        data = json.loads(artifact_path.read_text(encoding="utf-8"))
        if artifact_name == "redaction_report.json":
            data.update({
                "redaction_state": "safe",
                "contains_raw_transcript": False,
                "contains_secret": False,
            })
        data["tampered_safe_claim"] = leaked
        artifact_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    validation = validate_handoff(bundle_path)

    assert validation["valid"] is False
    assert any(error.startswith("forbidden_key:") for error in validation["errors"])
    assert any(error.startswith("forbidden_value:") for error in validation["errors"])


def test_cli_mlops_corpus_export_validate_remit_and_receipts_json(tmp_path):
    env = {**dict(PYTHONPATH=str(Path.cwd())), **dict(HERMES_HOME=str(tmp_path / "home"))}
    export_cmd = [
        sys.executable,
        "-m",
        "hermes_cli.main",
        "mlops",
        "corpus",
        "export",
        "--artifact-root",
        str(tmp_path / "artifacts"),
        "--json",
    ]
    exported = json.loads(subprocess.check_output(export_cmd, text=True, env=env))

    assert exported["status"] == "exported"
    assert exported["bundle_id"].startswith("bundle_")
    assert exported["boundary_flags"]["can_train"] is False
    assert "raw_transcript" not in json.dumps(exported)
    bundle_path = exported["bundle_path"]

    validated = json.loads(subprocess.check_output([
        sys.executable,
        "-m",
        "hermes_cli.main",
        "mlops",
        "corpus",
        "validate",
        "--bundle-path",
        bundle_path,
        "--json",
    ], text=True, env=env))
    assert validated["valid"] is True

    remitted = json.loads(subprocess.check_output([
        sys.executable,
        "-m",
        "hermes_cli.main",
        "mlops",
        "corpus",
        "remit",
        "--bundle-path",
        bundle_path,
        "--destination-uri",
        "file:///tmp/hermes/dev-remit",
        "--external-pipeline-id",
        "external-pipeline-123",
        "--json",
    ], text=True, env=env))
    assert remitted["status"] == "submitted"
    assert remitted["boundary_flags"]["can_deploy"] is False

    receipts = json.loads(subprocess.check_output([
        sys.executable,
        "-m",
        "hermes_cli.main",
        "mlops",
        "corpus",
        "receipts",
        "--artifact-root",
        str(tmp_path / "artifacts"),
        "--json",
    ], text=True, env=env))
    assert receipts["receipt_count"] == 1
    assert receipts["receipts"][0]["receipt_id"] == remitted["receipt_id"]
