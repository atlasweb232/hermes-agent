"""Production global-memory bus helpers for Kafka-compatible brokers.

The foreground path is deliberately non-blocking: Kafka/Redpanda is opt-in,
SQLite remains the default, and broker failures fall back to the existing
durable SQLite learning bus when configured.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Protocol

from hermes_cli.global_memory import build_global_topic
from hermes_cli.learning_bus import (
    consume_learning_events,
    ensure_learning_bus_schema,
    mark_learning_event_consumed,
    publish_learning_event,
)
from hermes_cli.platform_hardening import (
    CanonicalBusEnvelope,
    create_bus_envelope,
    dead_letter_event,
    redrive_event,
)
from hermes_state import SessionDB


SUPPORTED_BROKER_BACKENDS = {"kafka", "redpanda"}


def _now() -> float:
    return time.time()


@dataclass(frozen=True)
class GlobalBusProductionConfig:
    enabled: bool = False
    backend: str = "sqlite"
    brokers: List[str] = field(default_factory=list)
    topic_prefix: str = "hermes.memory"
    consumer_group: str = "hermes-global-memory"
    fallback_to_sqlite: bool = True
    idempotency_required: bool = True
    dead_letter_topic: str = "hermes.memory.dead_letter"
    tls: Dict[str, Any] = field(default_factory=dict)
    sasl: Dict[str, Any] = field(default_factory=dict)

    @property
    def broker_enabled(self) -> bool:
        return self.enabled and self.backend in SUPPORTED_BROKER_BACKENDS

    def topic_config(self) -> Dict[str, Any]:
        return {
            "supervisor": {
                "global_memory_bus": {
                    "topic_prefix": self.topic_prefix,
                    "dead_letter_topic": self.dead_letter_topic,
                }
            }
        }

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "backend": self.backend,
            "broker_count": len(self.brokers),
            "topic_prefix": self.topic_prefix,
            "consumer_group": self.consumer_group,
            "fallback_to_sqlite": self.fallback_to_sqlite,
            "idempotency_required": self.idempotency_required,
            "tls_enabled": bool(self.tls.get("enabled", False)),
            "sasl_enabled": bool(self.sasl.get("enabled", False)),
        }


@dataclass(frozen=True)
class BrokerSecurityValidation:
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    redacted: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class KafkaCompatibleAdapter(Protocol):
    def health(self) -> Dict[str, Any]:
        ...

    def topic_exists(self, topic: str) -> bool:
        ...

    def topic_end_offset(self, topic: str) -> int:
        ...

    def consumer_offset(self, topic: str, consumer_group: str) -> int:
        ...

    def publish(self, topic: str, key: str, value: Mapping[str, Any]) -> Dict[str, Any]:
        ...

    def consume(self, topic: str, consumer_group: str, *, limit: int = 10) -> List[Dict[str, Any]]:
        ...


class BrokerUnavailable(RuntimeError):
    pass


class FakeKafkaAdapter:
    """Deterministic Kafka-like adapter for tests and local dry runs."""

    def __init__(
        self,
        *,
        available: bool = True,
        topics: Optional[Mapping[str, int]] = None,
        group_offsets: Optional[Mapping[str, Mapping[str, int]]] = None,
    ) -> None:
        self.available = available
        self.records: Dict[str, List[Dict[str, Any]]] = {topic: [] for topic in (topics or {})}
        self._end_offsets: Dict[str, int] = {str(k): int(v) for k, v in (topics or {}).items()}
        self._group_offsets: Dict[str, Dict[str, int]] = {
            str(group): {str(topic): int(offset) for topic, offset in offsets.items()}
            for group, offsets in (group_offsets or {}).items()
        }
        self._published_keys: set[tuple[str, str]] = set()

    def _require_available(self) -> None:
        if not self.available:
            raise BrokerUnavailable("broker_unavailable")

    def health(self) -> Dict[str, Any]:
        return {"available": self.available, "adapter": "fake", "topic_count": len(self._end_offsets)}

    def topic_exists(self, topic: str) -> bool:
        self._require_available()
        return topic in self._end_offsets

    def topic_end_offset(self, topic: str) -> int:
        self._require_available()
        return max(self._end_offsets.get(topic, 0), len(self.records.get(topic, [])))

    def consumer_offset(self, topic: str, consumer_group: str) -> int:
        self._require_available()
        return int(self._group_offsets.get(consumer_group, {}).get(topic, 0))

    def publish(self, topic: str, key: str, value: Mapping[str, Any]) -> Dict[str, Any]:
        self._require_available()
        if topic not in self._end_offsets:
            raise ValueError(f"topic_not_found:{topic}")
        dedupe_key = (topic, key)
        if dedupe_key in self._published_keys:
            return {"status": "ok", "published": False, "duplicate": True, "topic": topic, "key": key}
        self._published_keys.add(dedupe_key)
        self.records.setdefault(topic, []).append(dict(value))
        self._end_offsets[topic] = self.topic_end_offset(topic) + 1
        return {"status": "ok", "published": True, "duplicate": False, "topic": topic, "key": key}

    def consume(self, topic: str, consumer_group: str, *, limit: int = 10) -> List[Dict[str, Any]]:
        self._require_available()
        offset = self.consumer_offset(topic, consumer_group)
        records = self.records.get(topic, [])
        batch = records[offset : offset + max(1, int(limit))]
        self._group_offsets.setdefault(consumer_group, {})[topic] = offset + len(batch)
        return [dict(item) for item in batch]


class OptionalConfluentKafkaAdapter:
    """Small adapter around confluent-kafka, loaded only when installed."""

    def __init__(self, config: GlobalBusProductionConfig) -> None:
        try:
            from confluent_kafka import Consumer, Producer, TopicPartition  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise BrokerUnavailable("confluent_kafka_unavailable") from exc
        if not config.brokers:
            raise BrokerUnavailable("brokers_not_configured")
        producer_config: Dict[str, Any] = {"bootstrap.servers": ",".join(config.brokers)}
        producer_config.update(_confluent_security_config(config))
        consumer_config = {
            **producer_config,
            "group.id": config.consumer_group,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
        self._producer = Producer(producer_config)
        self._consumer = Consumer(consumer_config)
        self._topic_partition_cls = TopicPartition

    def health(self) -> Dict[str, Any]:  # pragma: no cover - live broker path
        return {"available": True, "adapter": "confluent-kafka"}

    def topic_exists(self, topic: str) -> bool:  # pragma: no cover - live broker path
        metadata = self._producer.list_topics(timeout=2.0)
        return topic in metadata.topics

    def topic_end_offset(self, topic: str) -> int:  # pragma: no cover - live broker path
        metadata = self._producer.list_topics(topic=topic, timeout=2.0)
        partitions = metadata.topics.get(topic).partitions if topic in metadata.topics else {}
        total = 0
        for partition in partitions:
            topic_partition = self._topic_partition_cls(topic, int(partition))
            _low, high = self._consumer.get_watermark_offsets(topic_partition, timeout=2.0)
            total += int(high or 0)
        return total

    def consumer_offset(self, topic: str, consumer_group: str) -> int:  # pragma: no cover
        return 0

    def publish(self, topic: str, key: str, value: Mapping[str, Any]) -> Dict[str, Any]:  # pragma: no cover
        self._producer.produce(
            topic,
            key=key.encode("utf-8"),
            value=json.dumps(value, sort_keys=True).encode("utf-8"),
        )
        self._producer.poll(0)
        return {"status": "ok", "published": True, "duplicate": False, "topic": topic, "key": key}

    def consume(self, topic: str, consumer_group: str, *, limit: int = 10) -> List[Dict[str, Any]]:  # pragma: no cover
        return []


def _confluent_security_config(config: GlobalBusProductionConfig) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    if config.tls.get("enabled"):
        result["security.protocol"] = "SSL"
    if config.sasl.get("enabled"):
        result["security.protocol"] = "SASL_SSL" if config.tls.get("enabled") else "SASL_PLAINTEXT"
        result["sasl.mechanism"] = str(config.sasl.get("mechanism") or "PLAIN")
    return result


def resolve_global_bus_config(config: Mapping[str, Any]) -> GlobalBusProductionConfig:
    bus = ((config or {}).get("supervisor") or {}).get("global_memory_bus") or {}
    backend = str(bus.get("backend") or "sqlite").lower()
    return GlobalBusProductionConfig(
        enabled=bool(bus.get("enabled", False)),
        backend=backend,
        brokers=[str(item) for item in (bus.get("brokers") or []) if str(item).strip()],
        topic_prefix=str(bus.get("topic_prefix") or "hermes.memory").strip().rstrip("."),
        consumer_group=str(bus.get("consumer_group") or "hermes-global-memory"),
        fallback_to_sqlite=bool(bus.get("fallback_to_sqlite", True)),
        idempotency_required=bool(bus.get("idempotency_required", True)),
        dead_letter_topic=str(bus.get("dead_letter_topic") or "hermes.memory.dead_letter"),
        tls=dict(bus.get("tls") or {}),
        sasl=dict(bus.get("sasl") or {}),
    )


def validate_broker_security_config(config: GlobalBusProductionConfig) -> BrokerSecurityValidation:
    errors: List[str] = []
    warnings: List[str] = []
    tls_enabled = bool(config.tls.get("enabled", False))
    sasl_enabled = bool(config.sasl.get("enabled", False))
    if config.backend in SUPPORTED_BROKER_BACKENDS and not config.brokers:
        errors.append("brokers are required for kafka/redpanda backends")
    if tls_enabled and not config.tls.get("ca_cert_ref"):
        warnings.append("tls.ca_cert_ref is recommended for production")
    if sasl_enabled:
        mechanism = str(config.sasl.get("mechanism") or "").upper()
        if mechanism not in {"PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512", "OAUTHBEARER"}:
            errors.append("sasl.mechanism must be PLAIN, SCRAM-SHA-256, SCRAM-SHA-512, or OAUTHBEARER")
        if not config.sasl.get("username_ref"):
            errors.append("sasl.username_ref is required")
        if not config.sasl.get("password_ref") and mechanism != "OAUTHBEARER":
            errors.append("sasl.password_ref is required")
    redacted = {
        "tls": {
            "enabled": tls_enabled,
            "ca_cert_ref_present": bool(config.tls.get("ca_cert_ref")),
            "client_cert_ref_present": bool(config.tls.get("client_cert_ref")),
            "client_key_ref_present": bool(config.tls.get("client_key_ref")),
        },
        "sasl": {
            "enabled": sasl_enabled,
            "mechanism": str(config.sasl.get("mechanism") or "") if sasl_enabled else "",
            "username_ref_present": bool(config.sasl.get("username_ref")),
            "password_ref_present": bool(config.sasl.get("password_ref")),
            "token_ref_present": bool(config.sasl.get("token_ref")),
        },
    }
    return BrokerSecurityValidation(valid=not errors, errors=errors, warnings=warnings, redacted=redacted)


def _public_security_shape(security: BrokerSecurityValidation) -> Dict[str, Any]:
    sasl = dict(security.redacted.get("sasl") or {})
    if "password_ref_present" in sasl:
        sasl["credential_ref_present"] = bool(sasl.pop("password_ref_present"))
    return {"tls": dict(security.redacted.get("tls") or {}), "sasl": sasl}


def _topic(config: GlobalBusProductionConfig, topic: str) -> str:
    return build_global_topic(config.topic_config(), topic)


def _adapter_or_default(config: GlobalBusProductionConfig, adapter: Optional[KafkaCompatibleAdapter]) -> KafkaCompatibleAdapter:
    if adapter is not None:
        return adapter
    return OptionalConfluentKafkaAdapter(config)


def broker_status_json(
    config_or_raw: Mapping[str, Any] | GlobalBusProductionConfig,
    *,
    adapter: Optional[KafkaCompatibleAdapter] = None,
) -> Dict[str, Any]:
    config = config_or_raw if isinstance(config_or_raw, GlobalBusProductionConfig) else resolve_global_bus_config(config_or_raw)
    security = validate_broker_security_config(config)
    if not config.broker_enabled:
        return {
            "status": "disabled" if not config.enabled else "sqlite",
            "broker": config.to_public_dict(),
            "security": _public_security_shape(security),
            "security_validation": {
                "valid": security.valid,
                "errors": list(security.errors),
                "warnings": list(security.warnings),
            },
            "fallback": {"enabled": config.fallback_to_sqlite, "active": False},
        }
    try:
        broker = _adapter_or_default(config, adapter).health()
        available = bool(broker.get("available", True))
        return {
            "status": "ok" if available and security.valid else "degraded",
            "broker": config.to_public_dict(),
            "adapter": broker,
            "security": _public_security_shape(security),
            "security_validation": {
                "valid": security.valid,
                "errors": list(security.errors),
                "warnings": list(security.warnings),
            },
            "fallback": {"enabled": config.fallback_to_sqlite, "active": not available},
        }
    except Exception as exc:
        return {
            "status": "fallback" if config.fallback_to_sqlite else "unavailable",
            "broker": config.to_public_dict(),
            "adapter": {"available": False, "error": exc.__class__.__name__},
            "security": _public_security_shape(security),
            "security_validation": {
                "valid": security.valid,
                "errors": list(security.errors),
                "warnings": list(security.warnings),
            },
            "fallback": {"enabled": config.fallback_to_sqlite, "active": config.fallback_to_sqlite},
        }


def verify_broker_topics(
    config: GlobalBusProductionConfig,
    *,
    adapter: KafkaCompatibleAdapter,
    topics: Iterable[str],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    ok = True
    for logical in topics:
        resolved = _topic(config, logical)
        try:
            exists = adapter.topic_exists(resolved)
            error = None
        except Exception as exc:
            exists = False
            error = exc.__class__.__name__
        ok = ok and exists
        result[resolved] = {"logical": logical, "exists": exists, "error": error}
    return {"ok": ok, "backend": config.backend, "topics": result}


def global_bus_lag_metrics(
    config: GlobalBusProductionConfig,
    *,
    adapter: KafkaCompatibleAdapter,
    topics: Iterable[str],
) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {}
    total_lag = 0
    for logical in topics:
        resolved = _topic(config, logical)
        try:
            end_offset = adapter.topic_end_offset(resolved)
            consumer_offset = adapter.consumer_offset(resolved, config.consumer_group)
            lag = max(0, end_offset - consumer_offset)
            error = None
        except Exception as exc:
            end_offset = 0
            consumer_offset = 0
            lag = 0
            error = exc.__class__.__name__
        total_lag += lag
        metrics[resolved] = {
            "logical": logical,
            "end_offset": end_offset,
            "consumer_offset": consumer_offset,
            "lag": lag,
            "error": error,
        }
    return {"status": "ok", "consumer_group": config.consumer_group, "total_lag": total_lag, "topics": metrics}


def build_global_bus_envelope(
    *,
    topic: str,
    payload: Mapping[str, Any],
    event_key: str,
    adapter: str,
    created_at: Optional[float] = None,
) -> CanonicalBusEnvelope:
    tenant_id = str(payload.get("tenant_id") or "global")
    repo_id = str(payload.get("repo_id") or "global")
    return create_bus_envelope(
        event_type=topic,
        tenant_id=tenant_id,
        repo_id=repo_id,
        source_subsystem="global_memory",
        idempotency_key=str(event_key),
        partition_key=tenant_id,
        created_at=_now() if created_at is None else float(created_at),
        adapter=adapter,
        payload=payload,
    )


def redrive_global_event(event: CanonicalBusEnvelope, *, reason: str) -> CanonicalBusEnvelope:
    return redrive_event(event, reason=reason)


def dead_letter_global_event(event: CanonicalBusEnvelope, *, reason: str) -> CanonicalBusEnvelope:
    return dead_letter_event(event, reason=reason)


def publish_global_bus_event(
    db: SessionDB,
    config_or_raw: Mapping[str, Any] | GlobalBusProductionConfig,
    *,
    topic: str,
    payload: Mapping[str, Any],
    event_key: str,
    adapter: Optional[KafkaCompatibleAdapter] = None,
) -> Dict[str, Any]:
    config = config_or_raw if isinstance(config_or_raw, GlobalBusProductionConfig) else resolve_global_bus_config(config_or_raw)
    if not config.broker_enabled:
        event = publish_learning_event(
            db,
            topic=_topic(config, topic),
            payload=dict(payload),
            tenant_id=payload.get("tenant_id"),
            repo_id=payload.get("repo_id"),
            event_key=event_key,
        )
        return {"status": "queued", "backend": "sqlite", "event": event.to_dict()}
    envelope = build_global_bus_envelope(topic=topic, payload=payload, event_key=event_key, adapter=config.backend)
    resolved_topic = _topic(config, topic)
    try:
        broker = _adapter_or_default(config, adapter)
        published = broker.publish(resolved_topic, event_key, envelope.to_dict())
        return {
            "status": "published" if published.get("published", True) else "duplicate",
            "backend": config.backend,
            "topic": resolved_topic,
            "event_key": event_key,
            "broker": published,
            "fallback": {"used": False, "enabled": config.fallback_to_sqlite},
        }
    except Exception as exc:
        if not config.fallback_to_sqlite:
            return {
                "status": "unavailable",
                "backend": config.backend,
                "topic": resolved_topic,
                "event_key": event_key,
                "error": exc.__class__.__name__,
                "fallback": {"used": False, "enabled": False},
            }
        event = publish_learning_event(
            db,
            topic=resolved_topic,
            payload=dict(payload),
            tenant_id=payload.get("tenant_id"),
            repo_id=payload.get("repo_id"),
            event_key=event_key,
        )
        return {
            "status": "spooled",
            "backend": config.backend,
            "topic": resolved_topic,
            "event_key": event_key,
            "error": exc.__class__.__name__,
            "fallback": {
                "used": True,
                "enabled": True,
                "backend": "sqlite",
                "reason": "broker_unavailable",
                "event_id": event.id,
            },
        }


def drain_sqlite_spool_to_broker(
    db: SessionDB,
    config_or_raw: Mapping[str, Any] | GlobalBusProductionConfig,
    *,
    adapter: KafkaCompatibleAdapter,
    topics: Optional[Iterable[str]] = None,
    drain_key: str,
    limit: int = 10,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    config = config_or_raw if isinstance(config_or_raw, GlobalBusProductionConfig) else resolve_global_bus_config(config_or_raw)
    resolved_topics = [_topic(config, topic) for topic in (topics or ["proposed", "dead_letter"])]
    ensure_learning_bus_schema(db)
    existing = db._conn.execute(
        """
        SELECT event_id
        FROM hermes_learning_bus_drains
        WHERE drain_key = ?
        ORDER BY created_at ASC
        """,
        (drain_key,),
    ).fetchall()
    if existing:
        return {
            "status": "ok",
            "backend": config.backend,
            "idempotent_replay": True,
            "published_count": 0,
            "spool": {
                "drain_key": drain_key,
                "drained_count": 0,
                "already_drained_count": len(existing),
                "already_drained": [row["event_id"] for row in existing],
            },
            "published": [],
        }
    consumed = consume_learning_events(
        db,
        consumer=f"{config.consumer_group}.sqlite-spool",
        topics=resolved_topics,
        limit=limit,
        lease_seconds=30.0,
        now=now,
    )
    published: List[Dict[str, Any]] = []
    for event in consumed.leased:
        event_key = event.event_key or event.id
        payload = event.payload_json
        envelope = build_global_bus_envelope(
            topic=event.topic,
            payload=payload,
            event_key=event_key,
            adapter=config.backend,
            created_at=now,
        )
        broker_result = adapter.publish(event.topic, event_key, envelope.to_dict())
        published.append({"event_id": event.id, "topic": event.topic, "broker": broker_result})

    current = _now() if now is None else float(now)
    for event in consumed.leased:
        def _record(conn, *, event_id=event.id):
            conn.execute(
                """
                INSERT OR IGNORE INTO hermes_learning_bus_drains (
                    drain_key, event_id, consumer, ack, created_at
                ) VALUES (?, ?, ?, 1, ?)
                """,
                (drain_key, event_id, f"{config.consumer_group}.sqlite-spool", current),
            )

        db._execute_write(_record)
        mark_learning_event_consumed(db, event.id, now=current)

    spool = {
        "drain_key": drain_key,
        "drained_count": len(consumed.leased),
        "already_drained_count": 0,
        "dead_lettered": consumed.dead_lettered,
        "events": [
            {
                "id": event.id,
                "topic": event.topic,
                "event_key_present": bool(event.event_key),
                "payload_redacted": True,
                "payload_key_count": len(event.payload_json),
            }
            for event in consumed.leased
        ],
    }
    return {
        "status": "ok",
        "backend": config.backend,
        "idempotent_replay": False,
        "published_count": len(published),
        "spool": spool,
        "published": published,
    }
