import json
import sys
from pathlib import Path
from unittest.mock import patch

from hermes_cli.learning_bus import (
    audit_learning_bus,
    consume_learning_events,
    drain_learning_bus_batch,
    ensure_learning_bus_schema,
    get_learning_event,
    learning_bus_metrics,
    list_learning_events,
    mark_learning_event_dead,
    mark_learning_event_consumed,
    publish_learning_event,
)
from hermes_state import SessionDB


def _make_db(tmp_path: Path) -> SessionDB:
    return SessionDB(db_path=tmp_path / "state.db")


def test_learning_bus_publish_consume_ack_round_trip(tmp_path):
    db = _make_db(tmp_path)
    try:
        event = publish_learning_event(
            db,
            topic="learning.candidate.created",
            payload={"candidate_id": "metacand_1"},
            tenant_id="atlas",
            repo_id="hermes-agent",
            event_key="candidate:metacand_1",
        )

        assert event.id.startswith("evt_")
        assert event.status == "queued"
        assert list_learning_events(db, topic="learning.candidate.created")[0].id == event.id

        leased = consume_learning_events(
            db,
            consumer="sidecar",
            topics=["learning.candidate.created"],
            lease_seconds=30,
        )

        assert [item.id for item in leased.leased] == [event.id]
        assert leased.leased[0].status == "leased"
        assert leased.leased[0].attempts == 1
        from hermes_cli.learning_jobs import list_learning_jobs

        jobs = list_learning_jobs(db, job_type="learning_bus_consumer", owner="sidecar")
        assert len(jobs) == 1
        assert jobs[0].status == "completed"
        assert jobs[0].metrics_json["leased"] == 1

        consumed = mark_learning_event_consumed(db, event.id)
        assert consumed is not None
        assert consumed.status == "consumed"
        assert learning_bus_metrics(db)["consumed"] == 1
    finally:
        db.close()


def test_learning_bus_event_key_is_idempotent(tmp_path):
    db = _make_db(tmp_path)
    try:
        first = publish_learning_event(
            db,
            topic="learning.policy.audit",
            payload={"attempt": 1},
            event_key="policy:abc",
        )
        second = publish_learning_event(
            db,
            topic="learning.policy.audit",
            payload={"attempt": 2},
            event_key="policy:abc",
        )

        assert first.id == second.id
        assert second.payload_json["attempt"] == 2
        assert len(list_learning_events(db, topic="learning.policy.audit")) == 1
    finally:
        db.close()


def test_learning_bus_reclaims_expired_lease(tmp_path):
    db = _make_db(tmp_path)
    try:
        event = publish_learning_event(db, topic="learning.task.outcome", payload={"task": "x"})
        first = consume_learning_events(db, consumer="a", lease_seconds=5, now=100.0)
        assert first.leased[0].lease_owner == "a"

        second = consume_learning_events(db, consumer="b", lease_seconds=5, now=101.0)
        assert second.leased == []

        third = consume_learning_events(db, consumer="b", lease_seconds=5, now=106.0)
        assert [item.id for item in third.leased] == [event.id]
        assert third.leased[0].lease_owner == "b"
        assert third.leased[0].attempts == 2
    finally:
        db.close()


def test_learning_bus_dead_letters_after_retry_limit(tmp_path):
    db = _make_db(tmp_path)
    try:
        event = publish_learning_event(
            db,
            topic="learning.task.outcome",
            payload={"task": "x"},
            max_attempts=1,
        )
        first = consume_learning_events(db, consumer="a", lease_seconds=1, now=100.0)
        assert [item.id for item in first.leased] == [event.id]

        second = consume_learning_events(db, consumer="b", lease_seconds=1, now=102.0)
        assert second.leased == []
        assert second.dead_lettered == [event.id]
        row = get_learning_event(db, event.id)
        assert row is not None
        assert row.status == "dead"
        assert row.payload_json["dead_letter_reason"] == "max_attempts_exceeded"
    finally:
        db.close()


def test_learning_bus_schema_is_idempotent(tmp_path):
    db = _make_db(tmp_path)
    try:
        ensure_learning_bus_schema(db)
        ensure_learning_bus_schema(db)
        row = db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='hermes_learning_events'"
        ).fetchone()
        assert row is not None
    finally:
        db.close()


def test_learning_bus_audit_redacts_payloads_and_reports_replay_safety(tmp_path):
    db = _make_db(tmp_path)
    raw_secret_values = [
        "fake-token-value",
        "sk-fake-test-secret",
        "fake-password-value",
        "fake-log-value",
    ]
    try:
        leased = publish_learning_event(
            db,
            topic="learning.audit",
            payload={"token": "fake-token-value"},
        )
        consume_learning_events(
            db,
            consumer="worker-a",
            topics=["learning.audit"],
            limit=1,
            now=100.0,
        )
        assert get_learning_event(db, leased.id).status == "leased"
        queued = publish_learning_event(
            db,
            topic="learning.audit",
            payload={
                "api_key": "sk-fake-test-secret",
                "transcript": "fake-log-value",
                "ok": True,
            },
            tenant_id="tenant-a",
            repo_id="repo-a",
            event_key="audit:queued",
        )
        consumed = publish_learning_event(
            db,
            topic="learning.audit",
            payload={"password": "fake-password-value"},
        )
        mark_learning_event_consumed(db, consumed.id, now=101.0)
        dead = publish_learning_event(db, topic="learning.audit", payload={"logs": "fake-log-value"})
        mark_learning_event_dead(db, dead.id, now=102.0)

        audit = audit_learning_bus(db, topic="learning.audit", limit=10, now=500.0)

        assert audit["status_counts"] == {"queued": 1, "leased": 1, "consumed": 1, "dead": 1}
        assert audit["replay_safety"]["replayable_expired_leases"] == 1
        assert audit["replay_safety"]["non_replayable_consumed"] == 1
        assert audit["replay_safety"]["non_replayable_dead"] == 1
        assert audit["replay_safety"]["idempotency_keys_present"] == 1
        assert audit["dedicated_consumer_sidecar_required"] is True
        assert "queued backlog" in audit["dedicated_consumer_sidecar_reason"]

        sample = audit["samples"]["queued"][0]
        assert sample["id"] == queued.id
        assert sample["event_key_present"] is True
        assert sample["payload_redacted"] is True
        assert "payload_json" not in sample
        audit_json = json.dumps(audit)
        for raw_value in raw_secret_values:
            assert raw_value not in audit_json
    finally:
        db.close()


def test_learning_bus_drain_batch_is_idempotent_by_drain_key(tmp_path):
    db = _make_db(tmp_path)
    raw_secret_value = "fake-token-value"
    try:
        event = publish_learning_event(
            db,
            topic="learning.drain",
            payload={"token": raw_secret_value},
            event_key="drain:event-1",
        )

        first = drain_learning_bus_batch(
            db,
            consumer="audit",
            topics=["learning.drain"],
            limit=1,
            drain_key="smoke-1",
            ack=True,
            now=100.0,
        )
        second = drain_learning_bus_batch(
            db,
            consumer="audit",
            topics=["learning.drain"],
            limit=1,
            drain_key="smoke-1",
            ack=True,
            now=101.0,
        )

        assert first["drained_count"] == 1
        assert first["already_drained_count"] == 0
        assert first["events"][0]["id"] == event.id
        assert first["events"][0]["payload_redacted"] is True
        assert "payload_json" not in first["events"][0]
        assert raw_secret_value not in json.dumps(first)

        assert second["drained_count"] == 0
        assert second["already_drained_count"] == 1
        assert second["events"] == []
        assert second["already_drained"][0]["id"] == event.id
        assert get_learning_event(db, event.id).status == "consumed"
    finally:
        db.close()


def test_learning_bus_cli_json_smoke(tmp_path, monkeypatch, capsys):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    import hermes_state

    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", home / "state.db")

    from hermes_cli import main as hermes_main

    publish_argv = [
        "hermes",
        "memory",
        "bus",
        "publish",
        "--topic",
        "learning.cli.test",
        "--payload-json",
        '{"password": "fake-password-value"}',
        "--json",
    ]
    with patch.object(sys, "argv", publish_argv):
        hermes_main.main()
    published = json.loads(capsys.readouterr().out)
    assert published["status"] == "queued"

    list_argv = ["hermes", "memory", "bus", "list", "--topic", "learning.cli.test", "--json"]
    with patch.object(sys, "argv", list_argv):
        hermes_main.main()
    listed = json.loads(capsys.readouterr().out)
    assert listed[0]["id"] == published["id"]

    consume_argv = [
        "hermes",
        "memory",
        "bus",
        "consume",
        "--topic",
        "learning.cli.test",
        "--consumer",
        "cli-test",
        "--ack",
        "--json",
    ]
    with patch.object(sys, "argv", consume_argv):
        hermes_main.main()
    consumed = json.loads(capsys.readouterr().out)
    assert consumed["leased"][0]["id"] == published["id"]

    audit_argv = ["hermes", "memory", "bus", "audit", "--topic", "learning.cli.test", "--json"]
    with patch.object(sys, "argv", audit_argv):
        hermes_main.main()
    audit = json.loads(capsys.readouterr().out)
    assert audit["status_counts"]["consumed"] == 1
    assert audit["samples"]["consumed"][0]["payload_redacted"] is True
    assert "payload_json" not in audit["samples"]["consumed"][0]
    assert "fake-password-value" not in json.dumps(audit)

    publish_argv = [
        "hermes",
        "memory",
        "bus",
        "publish",
        "--topic",
        "learning.cli.drain",
        "--payload-json",
        '{"token": "fake-token-value"}',
        "--event-key",
        "cli-drain-1",
        "--json",
    ]
    with patch.object(sys, "argv", publish_argv):
        hermes_main.main()
    drain_published = json.loads(capsys.readouterr().out)

    drain_argv = [
        "hermes",
        "memory",
        "bus",
        "drain",
        "--topic",
        "learning.cli.drain",
        "--consumer",
        "audit",
        "--drain-key",
        "smoke-1",
        "--limit",
        "1",
        "--json",
    ]
    with patch.object(sys, "argv", drain_argv):
        hermes_main.main()
    drained = json.loads(capsys.readouterr().out)
    assert drained["drained_count"] == 1
    assert drained["events"][0]["id"] == drain_published["id"]
    assert "fake-token-value" not in json.dumps(drained)
