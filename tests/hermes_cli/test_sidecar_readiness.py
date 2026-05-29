import json
import sys
from unittest.mock import patch

from hermes_cli.sidecar_readiness import run_sidecar_readiness
from hermes_state import SessionDB


def _db(tmp_path):
    return SessionDB(db_path=tmp_path / "state.db")


def test_t349_sidecar_readiness_covers_required_service_roles(tmp_path):
    db = _db(tmp_path)
    try:
        result = run_sidecar_readiness(db, now=100.0, lease_owner="test-owner")
        data = result.to_dict()

        assert data["status"] == "ready"
        assert data["foreground_blocking"] is False
        names = {item["name"] for item in data["items"]}
        assert {
            "curator",
            "learning_judge",
            "dreaming",
            "wiki",
            "bus_consumer",
            "sync",
            "progress_summarizer",
            "housekeeping",
        } <= names
        assert all(item["deadline_seconds"] > 0 for item in data["items"])
        assert all(item["interval_seconds"] > 0 for item in data["items"])
        assert all(item["lock_acquired"] is True for item in data["items"])
    finally:
        db.close()


def test_t349_sidecar_readiness_lock_blocks_duplicate_active_runner(tmp_path):
    db = _db(tmp_path)
    try:
        first = run_sidecar_readiness(db, sidecars=["curator"], now=100.0, lease_owner="owner-a")
        second = run_sidecar_readiness(db, sidecars=["curator"], now=101.0, lease_owner="owner-b")
        expired = run_sidecar_readiness(db, sidecars=["curator"], now=1000.0, lease_owner="owner-c")

        assert first.items[0].lock_acquired is True
        assert second.items[0].status == "degraded"
        assert second.items[0].lock_acquired is False
        assert "lock_held" in second.items[0].degraded_reason
        assert expired.items[0].lock_acquired is True
        assert expired.items[0].lease_owner == "owner-c"
    finally:
        db.close()


def test_t349_sidecar_readiness_budget_and_backlog_degrade_without_foreground_blocking(tmp_path):
    db = _db(tmp_path)
    config = {
        "supervisor": {
            "sidecar_budget": {
                "limits": {"tenant_cost": 1, "task_cost": 1, "daily_cost": 1, "tenant_tokens": 10, "task_tokens": 10},
                "usage": {"tenant_cost": 0.9, "task_cost": 0.9, "daily_cost": 0.9, "tenant_tokens": 9, "task_tokens": 9},
            },
            "sidecar_services": {
                "progress_summarizer": {
                    "estimated_cost": 1.0,
                    "estimated_tokens": 100,
                    "backlog_count": 99,
                    "backlog_limit": 10,
                }
            },
        }
    }
    try:
        result = run_sidecar_readiness(
            db,
            config=config,
            sidecars=["progress_summarizer"],
            now=100.0,
            lease_owner="owner-a",
        )

        item = result.items[0]
        assert result.status == "degraded"
        assert item.status == "degraded"
        assert item.foreground_blocking is False
        assert "backlog_limit_exceeded" in item.degraded_reason
        assert "budget_" in item.degraded_reason
    finally:
        db.close()


def test_t357_service_equivalent_one_shot_runner_is_bounded_and_selective(tmp_path):
    db = _db(tmp_path)
    calls = []

    def runner(name, payload):
        calls.append((name, payload))
        return {"status": "completed", "ref": f"job://{name}/1"}

    try:
        result = run_sidecar_readiness(
            db,
            sidecars=["curator", "housekeeping"],
            mode="timer",
            run_once=True,
            now=100.0,
            lease_owner="owner-a",
            runners={"curator": runner, "housekeeping": runner},
        )

        assert result.status == "ready"
        assert result.foreground_blocking is False
        assert [name for name, _payload in calls] == ["curator", "housekeeping"]
        assert all(item.runner_status == "completed" for item in result.items)
        assert all(item.runner_ref.startswith("job://") for item in result.items)
    finally:
        db.close()


def test_t357_run_once_releases_service_equivalent_leases(tmp_path):
    db = _db(tmp_path)
    try:
        first = run_sidecar_readiness(
            db,
            sidecars=["curator"],
            run_once=True,
            now=100.0,
            lease_owner="owner-a",
        )
        second = run_sidecar_readiness(
            db,
            sidecars=["curator"],
            run_once=True,
            now=101.0,
            lease_owner="owner-b",
        )

        assert first.items[0].lock_acquired is True
        assert first.items[0].status == "ready"
        assert second.items[0].lock_acquired is True
        assert second.items[0].status == "ready"
        assert second.items[0].lease_owner == "owner-b"
    finally:
        db.close()


def test_t357_sidecar_readiness_cli_json_smoke(tmp_path, monkeypatch, capsys):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    import hermes_state
    from hermes_cli import main as hermes_main

    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", home / "state.db")
    with patch.object(
        sys,
        "argv",
        [
            "hermes",
            "runtime",
            "sidecars",
            "readiness",
            "--sidecar",
            "curator",
            "--sidecar",
            "bus_consumer",
            "--run-once",
            "--json",
        ],
    ):
        hermes_main.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["checked"] == 2
    assert payload["run_once"] is True
    assert payload["foreground_blocking"] is False
    assert {item["name"] for item in payload["items"]} == {"curator", "bus_consumer"}
