import json
import sys
from pathlib import Path
from unittest.mock import patch

from hermes_cli.memory_wiki import (
    compile_memory_wiki,
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
