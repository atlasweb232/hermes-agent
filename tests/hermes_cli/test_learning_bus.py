import json
import sys
from pathlib import Path
from unittest.mock import patch

from hermes_cli.learning_bus import (
    consume_learning_events,
    ensure_learning_bus_schema,
    get_learning_event,
    learning_bus_metrics,
    list_learning_events,
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
        '{"ok": true}',
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
