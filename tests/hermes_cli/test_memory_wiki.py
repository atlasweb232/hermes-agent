import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import hermes_cli.memory_wiki as memory_wiki
from hermes_cli.mlops_corpus import validate_handoff
from hermes_cli.memory_wiki import (
    compile_memory_wiki,
    export_wiki_training_corpus_bundle,
    export_training_corpus,
    list_memory_wiki_claims,
    list_training_corpus_records,
    validate_training_export,
)
from hermes_state import SessionDB


def _make_db(tmp_path: Path) -> SessionDB:
    return SessionDB(db_path=tmp_path / "state.db")


def _seed_candidate(db: SessionDB, candidate_id: str = "metacand_migration") -> None:
    db.upsert_meta_candidate(
        candidate_id=candidate_id,
        kind="playbook",
        claim="For Rails to FastAPI migration, preserve validation commands before changing routes",
        evidence_json={
            "record_id": "memrec_1",
            "evidence_uri": "git://atlas/legacy@abc123..def456",
            "evidence_sha256": "sha256:abc",
            "dataset_family": "before_after_diff",
            "legacy_repo_ref": {
                "repo_id": "legacy-rails",
                "branch": "main",
                "commit": "abc123",
                "frameworks": ["rails"],
            },
            "target_repo_ref": {
                "repo_id": "new-fastapi",
                "branch": "migration/forms",
                "commit": "def456",
                "runtime": "python",
            },
            "spec_refs": ["specs/132/spec.md", "specs/132/tasks.md"],
            "diff_refs": {
                "before_commit": "abc123",
                "after_commit": "def456",
                "changed_files": ["routes.py", "forms.py"],
                "redacted_diff_sha256": "sha256:def",
            },
            "failure_signature": "route validation skipped",
            "bad_action": "changed route without validation recipe",
            "successful_action": "run route tests before and after migration",
            "validation_evidence": {
                "commands": ["pytest tests/test_routes.py"],
                "output_sha256": "sha256:validation",
            },
            "drift_eval": {
                "regression_prompt": "migrate rails form routes to fastapi",
                "forbidden_bad_fix": "skip route validation",
                "required_evidence": ["pytest route tests"],
            },
            "redaction_status": "redacted",
        },
        score=0.92,
        status="approved",
        tenant_id="atlas",
        repo_id="migration-suite",
    )


def test_compile_memory_wiki_creates_scoped_claim_index_and_training_payload(tmp_path):
    db = _make_db(tmp_path)
    try:
        _seed_candidate(db)

        result = compile_memory_wiki(
            db,
            tenant_id="atlas",
            repo_id="migration-suite",
        )

        assert result.status == "completed"
        assert result.scanned == 1
        assert result.claims_created == 1
        claim = result.claims[0]
        assert claim.scope_json["tenant_id"] == "atlas"
        assert claim.scope_json["repo_id"] == "migration-suite"
        assert claim.safety_json["secret_safe"] is True
        assert claim.training_payload_json["dataset_family"] == "before_after_diff"
        assert claim.training_payload_json["legacy_repo_ref"]["repo_id"] == "legacy-rails"
        assert claim.training_payload_json["target_repo_ref"]["repo_id"] == "new-fastapi"
        assert claim.training_payload_json["diff_refs"]["before_commit"] == "abc123"
        assert claim.training_payload_json["validation_evidence"]["output_sha256"] == "sha256:validation"
        assert claim.training_payload_json["drift_eval"]["forbidden_bad_fix"] == "skip route validation"

        indexed = db._conn.execute(
            "SELECT memory_id FROM hermes_memory_index WHERE memory_id = ?",
            (claim.id,),
        ).fetchone()
        assert indexed is not None
    finally:
        db.close()


def test_verification_block_carries_into_training_validation_evidence(tmp_path):
    """The model-independent completion-gate proof must reach the training artifact.

    A candidate carrying a passing ``verification`` block (attached by the harness via
    capture_verification_for_task) should surface in the training payload's
    ``validation_evidence`` as model-independent, held-out-flagged proof — without
    losing any explicitly-recorded validation commands.
    """
    from hermes_cli.verification_evidence import capture_verification_for_task

    db = _make_db(tmp_path)
    try:
        _seed_candidate(db, "metacand_verified")
        gate = {
            "enabled": True,
            "status": "passed",
            "repo_path": "/repo",
            "passed": True,
            "checks": [
                {"name": "build_command", "passed": True, "skipped": False,
                 "command": ["pytest"], "returncode": 0},
            ],
        }
        record = capture_verification_for_task(
            db, gate, task_id="t-verified",
            tenant_id="atlas", repo_id="migration-suite",
            held_out=True, candidate_id="metacand_verified",
        )

        result = compile_memory_wiki(db, tenant_id="atlas", repo_id="migration-suite")
        claim = result.claims[0]
        ve = claim.training_payload_json["validation_evidence"]

        # the harness proof is folded in, and is model-independent + held-out
        assert ve["verification"]["passed"] is True
        assert ve["model_independent"] is True
        assert ve["held_out"] is True
        assert ve["verification_sha256"] == record.evidence_sha256
        # the explicitly-recorded validation commands are preserved alongside it
        assert "pytest tests/test_routes.py" in ve["evidence_refs"]
        assert record.evidence_uri in ve["evidence_refs"]

        # and it survives into the exported training-corpus record (the artifact)
        export = export_training_corpus(db, tenant_id="atlas", repo_id="migration-suite")
        exported = export.records[0].payload_json["validation_evidence"]
        assert exported["verification"]["passed"] is True
        assert exported["held_out"] is True
    finally:
        db.close()


def test_validation_evidence_unchanged_without_verification_block(tmp_path):
    """Back-compat: candidates with no verification block behave exactly as before."""
    db = _make_db(tmp_path)
    try:
        _seed_candidate(db, "metacand_legacy")
        result = compile_memory_wiki(db, tenant_id="atlas", repo_id="migration-suite")
        ve = result.claims[0].training_payload_json["validation_evidence"]
        assert ve == {
            "commands": ["pytest tests/test_routes.py"],
            "output_sha256": "sha256:validation",
        }
        assert "verification" not in ve
    finally:
        db.close()


def test_compile_memory_wiki_deduplicates_by_claim_scope(tmp_path):
    db = _make_db(tmp_path)
    try:
        _seed_candidate(db, "metacand_first")
        first = compile_memory_wiki(db, tenant_id="atlas", repo_id="migration-suite")
        second = compile_memory_wiki(db, tenant_id="atlas", repo_id="migration-suite")

        assert first.claims_created == 1
        assert second.claims_created == 0
        assert second.claims_updated == 1
        assert len(list_memory_wiki_claims(db, tenant_id="atlas", repo_id="migration-suite")) == 1
    finally:
        db.close()


def test_training_corpus_export_preserves_migration_refs_and_requires_curated_claim(tmp_path):
    db = _make_db(tmp_path)
    try:
        _seed_candidate(db)
        compile_memory_wiki(db, tenant_id="atlas", repo_id="migration-suite")

        result = export_training_corpus(
            db,
            tenant_id="atlas",
            repo_id="migration-suite",
            dataset_family="before_after_diff",
        )

        assert result.status == "completed"
        assert result.records_created == 1
        record = result.records[0]
        assert record.export_status == "candidate"
        assert record.dataset_family == "before_after_diff"
        assert record.payload_json["legacy_repo_ref"]["repo_id"] == "legacy-rails"
        assert record.payload_json["target_repo_ref"]["repo_id"] == "new-fastapi"
        assert record.payload_json["diff_refs"]["after_commit"] == "def456"
        assert record.payload_json["validation_evidence"]["commands"] == ["pytest tests/test_routes.py"]
        assert record.payload_json["drift_eval"]["required_evidence"] == ["pytest route tests"]
        assert record.approval_provenance_json["operator_approved"] is False
    finally:
        db.close()


def test_training_export_rejects_raw_logs_or_secret_like_payloads(tmp_path):
    db = _make_db(tmp_path)
    try:
        db.upsert_meta_candidate(
            candidate_id="metacand_secret",
            kind="playbook",
            claim="Use API key sk-thisisnotallowed1234567890 for migration",
            evidence_json={
                "evidence_uri": "artifact://secret",
                "dataset_family": "policy_playbook",
                "raw_log": True,
            },
            score=0.9,
            status="approved",
            tenant_id="atlas",
            repo_id="migration-suite",
        )
        compile_memory_wiki(db, tenant_id="atlas", repo_id="migration-suite")
        claim = list_memory_wiki_claims(db, tenant_id="atlas", repo_id="migration-suite")[0]

        errors = validate_training_export(claim)
        assert "secret_safety_not_confirmed" in errors
        assert "raw_transcript_or_log_not_exportable" in errors

        result = export_training_corpus(db, tenant_id="atlas", repo_id="migration-suite")
        assert result.records_created == 0
        assert result.rejected[0]["wiki_claim_id"] == claim.id
    finally:
        db.close()


def test_memory_wiki_cli_compile_and_export_json_smoke(tmp_path, monkeypatch, capsys):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    import hermes_state

    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", home / "state.db")
    db = SessionDB()
    try:
        _seed_candidate(db)
    finally:
        db.close()

    from hermes_cli import main as hermes_main

    compile_argv = [
        "hermes",
        "memory",
        "wiki",
        "compile",
        "--tenant-id",
        "atlas",
        "--repo-id",
        "migration-suite",
        "--json",
    ]
    with patch.object(sys, "argv", compile_argv):
        hermes_main.main()
    compiled = json.loads(capsys.readouterr().out)
    assert compiled["claims_created"] == 1

    export_argv = [
        "hermes",
        "memory",
        "wiki",
        "export-training",
        "--tenant-id",
        "atlas",
        "--repo-id",
        "migration-suite",
        "--family",
        "before_after_diff",
        "--json",
    ]
    with patch.object(sys, "argv", export_argv):
        hermes_main.main()
    exported = json.loads(capsys.readouterr().out)
    assert exported["records_created"] == 1

    db = SessionDB()
    try:
        records = list_training_corpus_records(db, tenant_id="atlas", repo_id="migration-suite")
        assert len(records) == 1
    finally:
        db.close()


def _approve_training_record_for_bundle(db: SessionDB, record_id: str) -> None:
    approval = {
        "source": "memory_wiki",
        "approval_required": True,
        "operator_approved": True,
        "candidate_id": "metacand_migration",
        "judge_decision_id": "judge_migration",
        "operator_approval_id": "approval_migration",
        "approval_refs": ["approval://approval_migration"],
    }

    def _do(conn):
        conn.execute(
            """
            UPDATE hermes_training_corpus_records
            SET export_status = 'approved',
                approval_provenance_json = ?
            WHERE id = ?
            """,
            (json.dumps(approval, sort_keys=True), record_id),
        )

    db._execute_write(_do)


def test_wiki_training_corpus_bundle_uses_mlops_writer_and_validation_boundary(tmp_path, monkeypatch):
    db = _make_db(tmp_path)
    calls = []
    original_write_bundle = memory_wiki.LocalCorpusBundleWriter.write_bundle

    def spy_write_bundle(self, **kwargs):
        calls.append(kwargs)
        return original_write_bundle(self, **kwargs)

    monkeypatch.setattr(memory_wiki.LocalCorpusBundleWriter, "write_bundle", spy_write_bundle)
    try:
        _seed_candidate(db)
        compile_memory_wiki(db, tenant_id="atlas", repo_id="migration-suite")
        exported = export_training_corpus(
            db,
            tenant_id="atlas",
            repo_id="migration-suite",
            dataset_family="before_after_diff",
            approve=True,
        )
        _approve_training_record_for_bundle(db, exported.records[0].id)

        bundle = export_wiki_training_corpus_bundle(
            db,
            artifact_root=tmp_path / "bundles",
            tenant_id="atlas",
            repo_id="migration-suite",
            dataset_family="before_after_diff",
            created_at="2026-05-21T00:00:00Z",
        )

        assert len(calls) == 1
        assert bundle.status == "exported"
        assert bundle.manifest["schema_version"] == "mlops.corpus.bundle.v1"
        assert bundle.manifest["dataset_family"] == "before_after_diff"
        assert bundle.manifest["record_count"] == 1
        assert bundle.manifest["artifact_formats"] == ["jsonl"]
        assert "parquet" in bundle.manifest["format_compatibility"]
        assert validate_handoff(bundle.bundle_path)["valid"] is True

        record = json.loads((bundle.bundle_path / "records.jsonl").read_text(encoding="utf-8").splitlines()[0])
        assert record["schema_version"] == "mlops.corpus.failure_repair.v1"
        assert record["tenant_id"] == "atlas"
        assert record["task"]["source_refs"]["wiki_claim_id"].startswith("wikiclaim_")
        assert record["task"]["source_refs"]["evidence_refs"]["candidate_id"] == "metacand_migration"
        assert record["approval"]["operator_approval_id"] == "approval_migration"
        assert record["safety"]["tenant_shareability"] == "tenant_only"
        exported_text = "\n".join(path.read_text(encoding="utf-8") for path in bundle.bundle_path.iterdir())
        assert "full raw transcript" not in exported_text
        assert "sk-live-secret" not in exported_text
    finally:
        db.close()


def test_wiki_bundle_fails_closed_without_approval_refs_and_blocks_tampering(tmp_path):
    db = _make_db(tmp_path)
    try:
        _seed_candidate(db)
        compile_memory_wiki(db, tenant_id="atlas", repo_id="migration-suite")
        export_training_corpus(
            db,
            tenant_id="atlas",
            repo_id="migration-suite",
            dataset_family="before_after_diff",
            approve=True,
        )

        with pytest.raises(ValueError, match="approved records with approval provenance"):
            export_wiki_training_corpus_bundle(
                db,
                artifact_root=tmp_path / "missing-approval",
                tenant_id="atlas",
                repo_id="migration-suite",
                dataset_family="before_after_diff",
            )

        record = list_training_corpus_records(db, tenant_id="atlas", repo_id="migration-suite")[0]
        _approve_training_record_for_bundle(db, record.id)
        bundle = export_wiki_training_corpus_bundle(
            db,
            artifact_root=tmp_path / "bundles",
            tenant_id="atlas",
            repo_id="migration-suite",
            dataset_family="before_after_diff",
            created_at="2026-05-21T00:00:00Z",
        )
        with (bundle.bundle_path / "records.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"raw_log": "must fail", "note": "token=INLINE_REDACTION_SENTINEL"}) + "\n")

        validation = validate_handoff(bundle.bundle_path)
        assert validation["valid"] is False
        assert any(error.startswith("forbidden_key:") for error in validation["errors"])
        assert any(error.startswith("forbidden_value:") for error in validation["errors"])
    finally:
        db.close()


def test_wiki_bundle_honors_tenant_and_dataset_filters(tmp_path):
    db = _make_db(tmp_path)
    try:
        _seed_candidate(db, "metacand_atlas")
        db.upsert_meta_candidate(
            candidate_id="metacand_other",
            kind="playbook",
            claim="Other tenant migration repair stays isolated",
            evidence_json={
                "record_id": "memrec_other",
                "evidence_uri": "git://other/repo@abc..def",
                "dataset_family": "migration_failure_repair",
                "failure_signature": "fixture failure",
                "successful_action": "fixture repair",
                "validation_evidence": {"commands": ["pytest tests/test_fixture.py"]},
                "redaction_status": "redacted",
            },
            score=0.9,
            status="approved",
            tenant_id="other",
            repo_id="migration-suite",
        )
        for tenant in ("atlas", "other"):
            compile_memory_wiki(db, tenant_id=tenant, repo_id="migration-suite")
            exported = export_training_corpus(db, tenant_id=tenant, repo_id="migration-suite", approve=True)
            for record in exported.records:
                _approve_training_record_for_bundle(db, record.id)

        bundle = export_wiki_training_corpus_bundle(
            db,
            artifact_root=tmp_path / "bundles",
            tenant_id="atlas",
            repo_id="migration-suite",
            dataset_family="before_after_diff",
            created_at="2026-05-21T00:00:00Z",
        )

        assert bundle.manifest["tenant_id"] == "atlas"
        assert bundle.manifest["dataset_family"] == "before_after_diff"
        exported_text = "\n".join(path.read_text(encoding="utf-8") for path in bundle.bundle_path.iterdir())
        assert "Other tenant" not in exported_text
        assert '"tenant_id":"other"' not in exported_text
        assert "migration_failure_repair" not in exported_text
    finally:
        db.close()
