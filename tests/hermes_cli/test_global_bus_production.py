import json
import time
from pathlib import Path

from hermes_cli.global_bus_production import (
    FakeKafkaAdapter,
    build_global_bus_envelope,
    broker_status_json,
    dead_letter_global_event,
    drain_sqlite_spool_to_broker,
    global_bus_lag_metrics,
    publish_global_bus_event,
    redrive_global_event,
    resolve_global_bus_config,
    validate_broker_security_config,
    verify_broker_topics,
)
from hermes_cli.global_memory import get_global_memory_bus
from hermes_cli.learning_bus import list_learning_events
from hermes_state import SessionDB


def _db(tmp_path: Path) -> SessionDB:
    return SessionDB(db_path=tmp_path / "state.db")


def _config(**bus_overrides):
    bus = {
        "enabled": True,
        "backend": "redpanda",
        "brokers": ["redpanda.local:9093"],
        "topic_prefix": "hermes.memory",
        "consumer_group": "hermes-global-memory",
        "fallback_to_sqlite": True,
        "tls": {"enabled": True, "ca_cert_ref": "kv://infra/redpanda/ca"},
        "sasl": {
            "enabled": True,
            "mechanism": "SCRAM-SHA-256",
            "username_ref": "kv://infra/redpanda/user",
            "password_ref": "kv://infra/redpanda/password",
        },
    }
    bus.update(bus_overrides)
    return {"supervisor": {"global_memory_bus": bus}}


def test_config_selection_keeps_sqlite_default_and_redpanda_opt_in(tmp_path):
    db = _db(tmp_path)
    try:
        default_cfg = resolve_global_bus_config({})
        assert default_cfg.backend == "sqlite"
        assert default_cfg.enabled is False

        selected = resolve_global_bus_config(_config())
        assert selected.backend == "redpanda"
        assert selected.enabled is True
        assert selected.brokers == ["redpanda.local:9093"]

        bus = get_global_memory_bus(db, _config())
        result = bus.publish("proposed", {"tenant_id": "t1", "repo_id": "r1"}, event_key="proposal:1")
        assert result["backend"] == "redpanda"
        assert result["fallback"]["used"] is True
        assert result["fallback"]["backend"] == "sqlite"
    finally:
        db.close()


def test_security_validation_redacts_tls_sasl_secret_refs():
    inline_sentinel_values = ["INLINE_CREDENTIAL_SENTINEL", "INLINE_IDENTITY_SENTINEL"]
    cfg = _config(
        sasl={
            "enabled": True,
            "mechanism": "PLAIN",
            "username": "INLINE_IDENTITY_SENTINEL",
            "password": "INLINE_CREDENTIAL_SENTINEL",
        }
    )

    result = validate_broker_security_config(resolve_global_bus_config(cfg))
    dumped = json.dumps(result.to_dict(), sort_keys=True)

    assert result.valid is False
    assert "sasl.username_ref is required" in result.errors
    assert "sasl.password_ref is required" in result.errors
    assert result.redacted["sasl"]["enabled"] is True
    assert result.redacted["sasl"]["username_ref_present"] is False
    assert result.redacted["sasl"]["password_ref_present"] is False
    assert result.redacted["tls"]["ca_cert_ref_present"] is True
    for value in inline_sentinel_values:
        assert value not in dumped


def test_broker_health_topic_lag_surfaces_are_json_safe():
    adapter = FakeKafkaAdapter(
        available=True,
        topics={"hermes.memory.proposed": 3, "hermes.memory.dead_letter": 1},
        group_offsets={"hermes-global-memory": {"hermes.memory.proposed": 1}},
    )
    cfg = resolve_global_bus_config(_config())

    health = broker_status_json(cfg, adapter=adapter)
    topics = verify_broker_topics(cfg, adapter=adapter, topics=["proposed", "dead_letter"])
    lag = global_bus_lag_metrics(cfg, adapter=adapter, topics=["proposed"])

    assert health["status"] == "ok"
    assert health["broker"]["backend"] == "redpanda"
    assert health["broker"]["broker_count"] == 1
    assert health["security"]["sasl"]["credential_ref_present"] is True
    assert topics["ok"] is True
    assert topics["topics"]["hermes.memory.proposed"]["exists"] is True
    assert lag["topics"]["hermes.memory.proposed"]["lag"] == 2
    assert "password" not in json.dumps(health).lower()


def test_idempotent_envelope_redrive_dead_letter_and_fake_adapter_publish_consume():
    adapter = FakeKafkaAdapter(available=True, topics={"hermes.memory.proposed": 0})
    envelope = build_global_bus_envelope(
        topic="proposed",
        payload={"tenant_id": "tenant-a", "repo_id": "repo-a", "claim": "redacted"},
        event_key="claim:1",
        adapter="redpanda",
        created_at=100.0,
    )

    first = adapter.publish("hermes.memory.proposed", envelope.idempotency_key, envelope.to_dict())
    second = adapter.publish("hermes.memory.proposed", envelope.idempotency_key, envelope.to_dict())
    consumed = adapter.consume("hermes.memory.proposed", "consumer-a", limit=10)
    replay = redrive_global_event(envelope, reason="lease_expired")
    dead = dead_letter_global_event(replay, reason="max_attempts_exceeded")

    assert first["published"] is True
    assert second["published"] is False
    assert second["duplicate"] is True
    assert [item["event_id"] for item in consumed] == [envelope.event_id]
    assert adapter.consume("hermes.memory.proposed", "consumer-a", limit=10) == []
    assert replay.replay_attempt == 1
    assert dead.dead_letter_reason == "max_attempts_exceeded"


def test_broker_unavailable_spools_to_sqlite_and_returns_quickly(tmp_path):
    db = _db(tmp_path)
    adapter = FakeKafkaAdapter(available=False, topics={"hermes.memory.proposed": 0})
    started = time.monotonic()
    try:
        result = publish_global_bus_event(
            db,
            _config(),
            topic="proposed",
            payload={"tenant_id": "tenant-a", "repo_id": "repo-a", "claim": "redacted"},
            event_key="claim:spooled",
            adapter=adapter,
        )
        elapsed = time.monotonic() - started
        rows = list_learning_events(db, topic="hermes.memory.proposed")

        assert elapsed < 0.25
        assert result["status"] == "spooled"
        assert result["fallback"]["used"] is True
        assert result["fallback"]["reason"] == "broker_unavailable"
        assert len(rows) == 1
        assert rows[0].event_key == "claim:spooled"
    finally:
        db.close()


def test_sqlite_spool_sidecar_drains_to_fake_broker_idempotently(tmp_path):
    db = _db(tmp_path)
    adapter = FakeKafkaAdapter(available=False, topics={"hermes.memory.proposed": 0})
    try:
        publish_global_bus_event(
            db,
            _config(),
            topic="proposed",
            payload={"tenant_id": "tenant-a", "repo_id": "repo-a", "claim": "redacted"},
            event_key="claim:sidecar",
            adapter=adapter,
        )
        adapter.available = True

        first = drain_sqlite_spool_to_broker(
            db,
            _config(),
            adapter=adapter,
            topics=["proposed"],
            drain_key="handoff-1",
            limit=10,
            now=200.0,
        )
        second = drain_sqlite_spool_to_broker(
            db,
            _config(),
            adapter=adapter,
            topics=["proposed"],
            drain_key="handoff-1",
            limit=10,
            now=201.0,
        )

        assert first["status"] == "ok"
        assert first["published_count"] == 1
        assert first["spool"]["drained_count"] == 1
        assert list_learning_events(db, topic="hermes.memory.proposed", status="consumed")
        assert second["idempotent_replay"] is True
        assert second["published_count"] == 0
        assert len(adapter.records["hermes.memory.proposed"]) == 1
    finally:
        db.close()
