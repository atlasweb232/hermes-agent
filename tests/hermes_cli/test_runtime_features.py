import json
import sys
from unittest.mock import patch

import pytest

from hermes_cli.runtime_features import (
    FEATURE_IDS,
    MAX_REASON_LENGTH,
    list_runtime_features,
    resolve_runtime_feature,
    set_runtime_feature_override,
    status_runtime_features,
)
from hermes_state import SessionDB


def _db(tmp_path):
    return SessionDB(db_path=tmp_path / "state.db")


def test_feature_definitions_list_json_is_deterministic_and_side_effect_free(tmp_path):
    db = _db(tmp_path)
    try:
        payload = list_runtime_features()

        assert [item["feature_id"] for item in payload["features"]] == sorted(FEATURE_IDS)
        assert payload["schema_version"] == 1
        assert payload["scope"]["tenant_id"] is None
        assert payload["scope"]["repo_id"] is None
        assert all(item["default_enabled"] is False for item in payload["features"])
        assert all(item["safety"]["enforcement_allowed_default"] is False for item in payload["features"])
        assert db.get_meta("runtime_feature:any:any:any") is None
    finally:
        db.close()


def test_default_off_resolver_reports_effective_source_and_safety(tmp_path):
    db = _db(tmp_path)
    try:
        state = resolve_runtime_feature(
            db,
            "runtime.health_sidecar",
            tenant_id="tenant-a",
            repo_id="repo-a",
        )

        assert state["feature_id"] == "runtime.health_sidecar"
        assert state["enabled"] is False
        assert state["effective"] is False
        assert state["source"] == "default"
        assert state["override"] is None
        assert state["scope"] == {"tenant_id": "tenant-a", "repo_id": "repo-a"}
        assert state["enforcement_allowed"] is False
    finally:
        db.close()


def test_scoped_override_is_durable_and_does_not_bleed_across_repo(tmp_path):
    db = _db(tmp_path)
    try:
        updated = set_runtime_feature_override(
            db,
            "runtime.task_graph",
            enabled=True,
            reason="Enable for repo-a smoke test",
            tenant_id="tenant-a",
            repo_id="repo-a",
            now=1000.0,
        )
        same_scope = resolve_runtime_feature(
            db,
            "runtime.task_graph",
            tenant_id="tenant-a",
            repo_id="repo-a",
        )
        other_repo = resolve_runtime_feature(
            db,
            "runtime.task_graph",
            tenant_id="tenant-a",
            repo_id="repo-b",
        )

        assert updated["enabled"] is True
        assert updated["source"] == "override"
        assert updated["reason"] == "Enable for repo-a smoke test"
        assert same_scope["effective"] is True
        assert same_scope["updated_at"] == "1970-01-01T00:16:40Z"
        assert other_repo["effective"] is False
        assert other_repo["source"] == "default"
    finally:
        db.close()

    db2 = _db(tmp_path)
    try:
        persisted = resolve_runtime_feature(
            db2,
            "runtime.task_graph",
            tenant_id="tenant-a",
            repo_id="repo-a",
        )
        assert persisted["effective"] is True
        assert persisted["source"] == "override"
    finally:
        db2.close()


def test_reason_is_required_redacted_and_bounded(tmp_path):
    db = _db(tmp_path)
    try:
        with pytest.raises(ValueError, match="reason is required"):
            set_runtime_feature_override(db, "runtime.task_graph", enabled=True, reason=" ")

        state = set_runtime_feature_override(
            db,
            "runtime.task_graph",
            enabled=True,
            reason="token=sk-test1234567890 password=hunter2 " + ("x" * (MAX_REASON_LENGTH + 50)),
        )

        assert "sk-test" not in state["reason"]
        assert "hunter2" not in state["reason"]
        assert "[REDACTED]" in state["reason"]
        assert len(state["reason"]) <= MAX_REASON_LENGTH
    finally:
        db.close()


def test_unknown_feature_fails_helper_api(tmp_path):
    db = _db(tmp_path)
    try:
        with pytest.raises(ValueError, match="unknown runtime feature"):
            resolve_runtime_feature(db, "runtime.nope")
        with pytest.raises(ValueError, match="unknown runtime feature"):
            set_runtime_feature_override(db, "runtime.nope", enabled=True, reason="test")
    finally:
        db.close()


def test_status_includes_all_known_features_and_effective_states(tmp_path):
    db = _db(tmp_path)
    try:
        set_runtime_feature_override(
            db,
            "runtime.task_graph",
            enabled=True,
            reason="Task graph smoke",
            tenant_id="tenant-a",
            repo_id="repo-a",
        )

        payload = status_runtime_features(db, tenant_id="tenant-a", repo_id="repo-a")

        assert [item["feature_id"] for item in payload["features"]] == sorted(FEATURE_IDS)
        states = {item["feature_id"]: item for item in payload["features"]}
        assert states["runtime.task_graph"]["effective"] is True
        assert states["runtime.task_graph"]["source"] == "override"
        assert states["runtime.health_sidecar"]["effective"] is False
        assert states["runtime.health_sidecar"]["source"] == "default"
    finally:
        db.close()


def test_runtime_features_cli_json_commands(tmp_path, monkeypatch, capsys):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    import hermes_state

    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", home / "state.db")
    from hermes_cli import main as hermes_main

    with patch.object(sys, "argv", ["hermes", "runtime", "features", "list", "--json"]):
        hermes_main.main()
    listed = json.loads(capsys.readouterr().out)
    assert listed["features"][0]["feature_id"] == sorted(FEATURE_IDS)[0]

    with patch.object(
        sys,
        "argv",
        [
            "hermes",
            "runtime",
            "features",
            "set",
            "runtime.health_sidecar",
            "on",
            "--tenant-id",
            "tenant-a",
            "--repo-id",
            "repo-a",
            "--reason",
            "bounded health sidecar smoke",
            "--json",
        ],
    ):
        hermes_main.main()
    updated = json.loads(capsys.readouterr().out)
    assert updated["feature_id"] == "runtime.health_sidecar"
    assert updated["effective"] is True
    assert updated["enforcement_allowed"] is False

    with patch.object(
        sys,
        "argv",
        [
            "hermes",
            "runtime",
            "features",
            "status",
            "--tenant-id",
            "tenant-a",
            "--repo-id",
            "repo-a",
            "--json",
        ],
    ):
        hermes_main.main()
    status = json.loads(capsys.readouterr().out)
    states = {item["feature_id"]: item for item in status["features"]}
    assert states["runtime.health_sidecar"]["effective"] is True
    assert states["runtime.health_sidecar"]["reason"] == "bounded health sidecar smoke"


def test_runtime_features_cli_unknown_feature_fails(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    import hermes_state

    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", home / "state.db")
    from hermes_cli import main as hermes_main

    with patch.object(
        sys,
        "argv",
        [
            "hermes",
            "runtime",
            "features",
            "set",
            "runtime.nope",
            "on",
            "--reason",
            "test",
            "--json",
        ],
    ):
        with pytest.raises(SystemExit, match="unknown runtime feature"):
            hermes_main.main()
