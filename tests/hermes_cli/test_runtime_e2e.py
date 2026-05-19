import json
import sys
from unittest.mock import patch

from hermes_cli.runtime_features import set_runtime_feature_override
from hermes_cli.runtime_e2e import (
    E2E_SMOKE_FEATURE_IDS,
    get_e2e_run,
    list_e2e_suites,
    run_e2e_suite,
)
from hermes_state import SessionDB


def _db(tmp_path):
    return SessionDB(db_path=tmp_path / "state.db")


def test_e2e_suite_schema_has_stable_dashboard_fields(tmp_path):
    suites = list_e2e_suites()

    assert suites["schema_version"] == 1
    suite = suites["suites"][0]
    assert suite["suite_id"] == "runtime.local_smoke"
    assert suite["workload_id"] == "runtime-local-dev-smoke"
    assert suite["artifact_policy"]["isolated_hermes_home"] is True
    assert suite["artifact_policy"]["bounded_evidence_only"] is True
    assert suite["repo_snapshot"]["ref_kind"] == "local_git"
    assert suite["validation_commands"] == ["runtime-e2e:deterministic-local-smoke"]
    assert {case["feature_id"] for case in suite["cases"]} == set(E2E_SMOKE_FEATURE_IDS)


def test_e2e_run_records_isolated_home_artifacts_and_feature_snapshot(tmp_path):
    db = _db(tmp_path)
    try:
        result = run_e2e_suite(
            db,
            suite_id="runtime.local_smoke",
            tenant_id="tenant-a",
            repo_id="repo-a",
            artifact_root=tmp_path / "artifacts",
            repo_path=tmp_path,
        )

        assert result["schema_version"] == 1
        assert result["suite_id"] == "runtime.local_smoke"
        assert result["workload_id"] == "runtime-local-dev-smoke"
        assert result["scope"] == {"tenant_id": "tenant-a", "repo_id": "repo-a"}
        assert result["isolated"]["hermes_home"].startswith(str(tmp_path / "artifacts"))
        assert result["isolated"]["hermes_home"] != str(tmp_path)
        assert result["artifacts"]["root"].startswith(str(tmp_path / "artifacts"))
        assert result["repo_snapshot"]["repo_id"] == "repo-a"
        assert result["repo_snapshot"]["head_ref"]
        assert all(item["enforcement_allowed"] is False for item in result["feature_snapshot"]["features"])
        assert result["validation_refs"][0]["command"] == "runtime-e2e:deterministic-local-smoke"

        persisted = get_e2e_run(db, result["run_id"])
        assert persisted == result
    finally:
        db.close()


def test_e2e_safety_no_enforcement_raw_transcripts_cross_tenant_or_sidecars(tmp_path):
    db = _db(tmp_path)
    try:
        set_runtime_feature_override(
            db,
            "runtime.health_sidecar",
            enabled=True,
            reason="tenant-a smoke token=sk-test123456789",
            tenant_id="tenant-a",
            repo_id="repo-a",
        )

        tenant_a = run_e2e_suite(
            db,
            suite_id="runtime.local_smoke",
            tenant_id="tenant-a",
            repo_id="repo-a",
            artifact_root=tmp_path / "artifacts-a",
            transcript_excerpt="raw transcript password=hunter2 " + ("x" * 1000),
        )
        tenant_b = run_e2e_suite(
            db,
            suite_id="runtime.local_smoke",
            tenant_id="tenant-b",
            repo_id="repo-a",
            artifact_root=tmp_path / "artifacts-b",
            transcript_excerpt="raw transcript password=hunter2",
        )

        dumped_a = json.dumps(tenant_a)
        assert "hunter2" not in dumped_a
        assert "sk-test" not in dumped_a
        assert len(tenant_a["safety"]["input_summary"]) <= 240
        assert tenant_a["safety"]["raw_transcripts_stored"] is False
        assert tenant_a["safety"]["expensive_sidecars_started"] is False
        assert tenant_a["safety"]["enforcement_allowed"] is False

        cases_a = {case["feature_ids"][0]: case for case in tenant_a["cases"]}
        cases_b = {case["feature_ids"][0]: case for case in tenant_b["cases"]}
        assert cases_a["runtime.health_sidecar"]["status"] == "passed"
        assert cases_b["runtime.health_sidecar"]["status"] == "skipped"
    finally:
        db.close()


def test_e2e_feature_gated_smoke_skips_disabled_and_passes_enabled_scope(tmp_path):
    db = _db(tmp_path)
    try:
        for feature_id in E2E_SMOKE_FEATURE_IDS:
            set_runtime_feature_override(
                db,
                feature_id,
                enabled=True,
                reason=f"enable {feature_id} for scoped smoke",
                tenant_id="tenant-a",
                repo_id="repo-a",
            )

        enabled = run_e2e_suite(db, suite_id="runtime.local_smoke", tenant_id="tenant-a", repo_id="repo-a")
        disabled = run_e2e_suite(db, suite_id="runtime.local_smoke", tenant_id="tenant-a", repo_id="repo-b")

        assert {case["status"] for case in enabled["cases"]} == {"passed"}
        assert {case["status"] for case in disabled["cases"]} == {"skipped"}
        assert enabled["status"] == "passed"
        assert disabled["status"] == "skipped"
    finally:
        db.close()


def test_e2e_state_records_are_idempotent_and_indexed(tmp_path):
    db = _db(tmp_path)
    try:
        first = run_e2e_suite(db, suite_id="runtime.local_smoke", tenant_id="tenant-a", repo_id="repo-a")
        second = run_e2e_suite(db, suite_id="runtime.local_smoke", tenant_id="tenant-a", repo_id="repo-a")

        assert first["run_id"] != second["run_id"]
        assert get_e2e_run(db, first["run_id"])["run_id"] == first["run_id"]
        assert get_e2e_run(db, second["run_id"])["run_id"] == second["run_id"]
        index = json.loads(db.get_meta("runtime_e2e_runs"))
        assert index[-2:] == [first["run_id"], second["run_id"]]
    finally:
        db.close()


def test_runtime_e2e_cli_json_run_and_status(tmp_path, monkeypatch, capsys):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    import hermes_state

    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", home / "state.db")
    from hermes_cli import main as hermes_main

    with patch.object(sys, "argv", ["hermes", "runtime", "e2e", "list", "--json"]):
        hermes_main.main()
    listed = json.loads(capsys.readouterr().out)
    assert listed["suites"][0]["suite_id"] == "runtime.local_smoke"

    with patch.object(
        sys,
        "argv",
        [
            "hermes",
            "runtime",
            "e2e",
            "run",
            "--suite",
            "runtime.local_smoke",
            "--tenant-id",
            "tenant-a",
            "--repo-id",
            "repo-a",
            "--artifact-root",
            str(tmp_path / "artifacts"),
            "--json",
        ],
    ):
        hermes_main.main()
    run_payload = json.loads(capsys.readouterr().out)
    assert run_payload["run_id"]
    assert run_payload["status"] == "skipped"

    with patch.object(
        sys,
        "argv",
        ["hermes", "runtime", "e2e", "status", "--run-id", run_payload["run_id"], "--json"],
    ):
        hermes_main.main()
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["run_id"] == run_payload["run_id"]
    assert status_payload["cases"] == run_payload["cases"]
