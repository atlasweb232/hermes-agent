import json
import sys
from unittest.mock import patch

from hermes_cli.production_runtime_smoke import run_production_runtime_smoke
from hermes_state import SessionDB


def _db(tmp_path):
    return SessionDB(db_path=tmp_path / "state.db")


def test_t353_t361_production_runtime_smoke_exercises_learning_loop(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_URGENT_CHANNEL", "C123456")
    db = _db(tmp_path)
    try:
        result = run_production_runtime_smoke(
            db,
            tenant_id="tenant-a",
            repo_id="repo-a",
            artifact_root=tmp_path / "artifacts",
            env={"PATH": "", "HERMES_SSH_PATH": "", "HERMES_GATEWAY_PATH": "", "HERMES_SIDECAR_PATH": ""},
        )

        assert result["status"] == "passed"
        assert result["execution_mode"] == "deterministic_local"
        assert result["enforcement_enabled"] is False
        assert result["foreground_blocking"] is False
        assert result["curator"]["candidates_created"] >= 1
        assert result["judge"]["approved"] >= 1
        assert result["worker_fallback"]["primary_worker"] == "claude-code"
        assert result["worker_fallback"]["fallback_worker"] == "codex"
        assert result["worker_fallback"]["passed"] is True
        assert result["skill_evolution"]["publication"]["status"] == "published"
        assert result["skill_evolution"]["packet"]["status"] == "ok"
        assert result["skill_evolution"]["repair_candidates"]
        assert result["notification"]["status"] == "dry_run"
        assert result["runtime_impact"]["raw_logs_loaded"] is False
        assert result["runtime_impact"]["raw_transcripts_loaded"] is False
        assert result["safety"]["secret_sentinel_detected"] is False
        assert set(gate["status"] for gate in result["gates"]) == {"passed"}
        assert result["artifact_ref"]
        assert json.loads(open(result["artifact_ref"], encoding="utf-8").read())["run_id"] == result["run_id"]
    finally:
        db.close()


def test_t361_production_runtime_smoke_can_fail_closed_on_missing_urgent_channel(tmp_path, monkeypatch):
    monkeypatch.delenv("SLACK_URGENT_CHANNEL", raising=False)
    monkeypatch.delenv("HERMES_URGENT_CHANNEL", raising=False)
    db = _db(tmp_path)
    try:
        result = run_production_runtime_smoke(
            db,
            tenant_id="tenant-a",
            repo_id="repo-a",
            require_urgent_channel=True,
            env={"PATH": "", "HERMES_SSH_PATH": "", "HERMES_GATEWAY_PATH": "", "HERMES_SIDECAR_PATH": ""},
        )

        gates = {gate["name"]: gate for gate in result["gates"]}
        assert result["status"] == "failed"
        assert result["notification"]["status"] == "skipped"
        assert gates["notification_route"]["status"] == "failed"
        assert result["foreground_blocking"] is False
    finally:
        db.close()


def test_t361_production_runtime_smoke_cli_json(tmp_path, monkeypatch, capsys):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("SLACK_URGENT_CHANNEL", "C123456")
    import hermes_state
    from hermes_cli import main as hermes_main

    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", home / "state.db")
    with patch.object(
        sys,
        "argv",
        [
            "hermes",
            "runtime",
            "production-smoke",
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

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "passed"
    assert payload["artifact_ref"]
    assert payload["safety"]["live_provider_calls"] is False
