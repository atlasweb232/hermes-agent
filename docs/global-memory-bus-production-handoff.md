# Global Memory Bus Production Handoff

This handoff describes the opt-in Kafka-compatible production bus for Hermes
global memory. SQLite remains the default single-node backend. No live Azure
resource is required to use the local tests or staging template.

## Runtime Shape

- Default: `supervisor.global_memory_bus.backend: sqlite`.
- Production opt-in: set `enabled: true` and `backend: redpanda` or `kafka`.
- Supported broker shapes: Redpanda, Kafka, or Azure Event Hubs using the Kafka
  endpoint.
- Foreground publishes must not block on broker health. If the broker is
  unavailable and `fallback_to_sqlite: true`, events are spooled to the existing
  SQLite learning bus and can be drained later by the sidecar.

Example config shape:

```yaml
supervisor:
  global_memory_bus:
    enabled: true
    backend: redpanda
    brokers:
      - redpanda.internal.example:9093
    topic_prefix: hermes.memory
    consumer_group: hermes-global-memory
    fallback_to_sqlite: true
    idempotency_required: true
    tls:
      enabled: true
      ca_cert_ref: kv://hermes/prod/redpanda-ca
    sasl:
      enabled: true
      mechanism: SCRAM-SHA-256
      username_ref: kv://hermes/prod/redpanda-user
      password_ref: kv://hermes/prod/redpanda-password
```

Use secret references only. Do not store raw SASL usernames, passwords, tokens,
certificates, or keys in config files, logs, fixtures, screenshots, or command
output.

## Azure Options

Azure Event Hubs Kafka endpoint:

- Use Event Hubs namespace private networking where possible.
- Configure Kafka bootstrap servers from the namespace endpoint.
- Require TLS and SASL. Store connection material behind secret references.
- Keep Event Hubs resource creation outside Hermes tests and local validation.

Redpanda or Kafka on Azure Kubernetes Service:

- Expose brokers only on private networks or controlled ingress.
- Require TLS for broker and client traffic.
- Use SASL/SCRAM or cloud-managed identity integration where available.
- Keep topic creation and ACLs in deployment automation owned by the platform
  team.

## Topics

Create and verify the Hermes global-memory topics under the configured prefix:

- `hermes.memory.proposed`
- `hermes.memory.normalized`
- `hermes.memory.dedupe.requested`
- `hermes.memory.dedupe.completed`
- `hermes.memory.reconcile.requested`
- `hermes.memory.judge.requested`
- `hermes.memory.judge.completed`
- `hermes.memory.canonical.updated`
- `hermes.memory.index.requested`
- `hermes.memory.index.completed`
- `hermes.memory.sync.delta`
- `hermes.memory.dead_letter`

Run a read-only check:

```bash
hermes memory bus check --topic proposed --topic dead_letter --lag --json
```

The JSON output reports broker counts, TLS/SASL boolean presence, topic
verification, lag metrics, and fallback state. It must not include secret values.

## Staging

Local Redpanda staging template:

```bash
docker compose -f infra/redpanda/docker-compose.yml up -d
```

Point Hermes at `localhost:19092` with TLS/SASL disabled only for local staging.
Do not reuse that unauthenticated shape for production.

## SQLite Spool Drain

If broker publish fails while fallback is enabled, Hermes writes the event to
SQLite with the resolved global topic and idempotency key. Once the broker is
healthy, drain the spool:

```bash
hermes memory bus spool-drain --topic proposed --drain-key prod-drain-YYYYMMDDHH --json
```

Use a unique `--drain-key` for each operator run. Reusing the same key returns an
idempotent replay result and does not publish duplicates.

## Soak Checklist

1. Verify `hermes memory bus check --json` shows the intended backend and no
   fallback when the broker is healthy.
2. Verify required topics exist and lag is bounded.
3. Publish canary global-memory events with stable idempotency keys.
4. Confirm duplicate publishes are ignored by key.
5. Stop broker access and confirm foreground publishes return quickly and spool
   to SQLite.
6. Restore broker access and drain the SQLite spool.
7. Confirm dead-letter and redrive DTOs preserve canonical bus envelope fields.
8. Confirm logs, JSON output, and monitoring snapshots contain only secret-ref
   presence booleans, never raw secret material.

## Rollback

Set `supervisor.global_memory_bus.backend: sqlite` or `enabled: false`. Existing
SQLite-spooled events remain available for inspection through `hermes memory bus
audit --json` and can be drained later after the broker path is restored.
