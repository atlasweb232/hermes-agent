# Global Memory Wiki Architecture

## Purpose

The global memory wiki is the cross-device, cross-domain knowledge layer for
Hermes. It accepts proposed knowledge from many Hermes instances, deduplicates
and reconciles it, gates canonical writes through judges/operators, and
publishes approved deltas back to local instances.

It is not a raw transcript store and not a free-form append log. Raw data is
evidence. Canonical wiki claims are approved, deduplicated, scoped knowledge.

## Storage Model

Use separate stores for raw evidence, canonical state, and indexes:

```text
source Hermes instances
  -> object storage raw blobs
  -> global inbox events
  -> Delta/Iceberg/Postgres state tables
  -> lexical/vector/graph indexes
  -> approved sync deltas
```

Recommended physical layout:

```text
global-memory-wiki/
  raw/                       # object storage prefixes, not retrieval truth
    sessions/
    evidence/
    citations/
  inbox/                     # proposed chunks from local instances
  canonical/                 # approved canonical claims/pages
  superseded/                # old claims replaced by newer canonical claims
  rejected/
  indexes/
    lexical/                 # BM25/FTS
    vector/                  # embedding vectors or provider ids
    graph/                   # claim/evidence/scope relationships
  audit/
    proposal_log/
    merge_decisions/
    approvals/
    sync_state/
```

For small deployments this can map to local disk and SQLite. For global
deployments:

- raw blobs: S3/GCS/Azure Blob/MinIO
- state: Delta Lake/Iceberg/Postgres
- lexical: OpenSearch/Postgres FTS
- vector: pgvector/Qdrant/Weaviate/Pinecone
- graph: Neo4j/Postgres graph tables/Neptune
- audit: append-only Delta/Iceberg/Postgres tables

## Configurable Storage

All storage locations must be config-driven:

```yaml
supervisor:
  global_memory_wiki:
    enabled: false
    instance_id: auto
    namespace: default
    local_cache_root: ~/.hermes/memory-wiki

    object_store:
      backend: local          # local | s3 | gcs | azure | minio
      uri: ~/.hermes/memory-wiki/global
      raw_prefix: raw/
      evidence_prefix: evidence/

    state_store:
      backend: sqlite         # sqlite | postgres | delta | iceberg
      uri: ~/.hermes/memory-wiki/global/state.sqlite

    lexical_index:
      backend: sqlite_fts     # sqlite_fts | postgres_fts | opensearch
      uri: ~/.hermes/memory-wiki/global/lexical.sqlite

    vector_index:
      backend: disabled       # disabled | pgvector | qdrant | weaviate | pinecone
      uri: ""
      embedding_provider: openai
      embedding_model: text-embedding-3-large

    graph_index:
      backend: sqlite         # disabled | sqlite | postgres | neo4j | neptune
      uri: ~/.hermes/memory-wiki/global/graph.sqlite

    limits:
      max_local_cache_gb: 50
      raw_retention_days: 30
      hot_cache_days: 30
      max_ingest_batch: 500
```

## Message Bus

A true Kafka-like bus makes sense for the global layer, but not as the required
local dependency.

Recommended split:

- Local single-machine Hermes: SQLite durable queue.
- Global multi-source deployment: Kafka-compatible bus.
- Lightweight self-hosted option: Redpanda.
- Cloud option: MSK/Confluent Cloud/PubSub/Event Hubs with adapter.

The bus must be interface-based:

```yaml
supervisor:
  global_memory_bus:
    backend: sqlite           # sqlite | kafka | redpanda | pubsub | eventhubs
    brokers: []
    topic_prefix: hermes.memory
    consumer_group: hermes-global-memory
    exactly_once: false
    idempotency_required: true
    dead_letter_topic: hermes.memory.dead_letter
```

Kafka/Redpanda is useful when:

- many Hermes instances write randomly and concurrently
- ingestion bursts need buffering
- sidecars should scale independently
- dead-letter queues and replay are required
- global dedupe/reconcile should be horizontally scalable

Kafka is overkill when there is one VM or one laptop. Start with the same bus
interface and SQLite backend, then deploy Redpanda/Kafka for global operation.

## Tiered Sidecar Model Deployment

Global memory sidecars should not all use the same expensive reasoning model.
Model choice is a config concern exposed through `supervisor.sidecar_model_tiers`
and role-specific `supervisor.sidecar_models.*` assignments.

Default tier intent:

- `programmatic`: no LLM; deterministic index fanout, sync, leases, and
  housekeeping.
- `low_cost_reasoning`: bounded extraction/capture work using a cheaper hosted
  reasoning model, for example DeepSeek Reasoner or MiniMax.
- `balanced_reasoning`: synthesis work where quality matters but mistakes are
  still advisory, for example wiki compilation.
- `strong_reasoning`: judge, curator, dreaming, and approval-adjacent work
  where false positives are costly.

Resolution order:

1. Explicit role override, for example
   `supervisor.sidecar_models.claim_extractor.provider=minimax`.
2. Role tier, for example
   `supervisor.sidecar_models.claim_extractor.tier=low_cost_reasoning`.
3. Built-in safe defaults.

This keeps provider experiments transparent. Changing DeepSeek to MiniMax, or
later to a local GPU-hosted model, should not require sidecar code changes.
Operators can inspect and change the routing through `hermes config tiers
--json`, `hermes config tier set <tier> ...`, `GET /api/model/tiers`, and
`PUT /api/model/tiers/{tier}`.

## Event Topics

Global topics should be narrow and replayable:

```text
hermes.memory.proposed
hermes.memory.normalized
hermes.memory.dedupe.requested
hermes.memory.dedupe.completed
hermes.memory.reconcile.requested
hermes.memory.judge.requested
hermes.memory.judge.completed
hermes.memory.canonical.updated
hermes.memory.index.requested
hermes.memory.index.completed
hermes.memory.sync.delta
hermes.memory.dead_letter
```

Every event must carry an idempotency key:

```text
source_instance_id + source_session_id + normalized_hash + evidence_hash
```

Consumers must be idempotent. Replaying a topic must not create duplicate
canonical claims.

## Metadata Schema

Every proposed memory chunk needs enough metadata for hard filters, dedupe,
retrieval, and governance:

```json
{
  "id": "proposal_...",
  "source_instance_id": "device_or_vm_id",
  "source_session_id": "session_id",
  "source_event_id": "event_id",
  "tenant_id": "tenant_or_null",
  "user_id_hash": "hash",
  "domain": "architecture|construction|research|code|ops",
  "scope": "private|device|tenant|domain|global",
  "visibility": "private|shared|global_candidate",
  "sensitivity": "public|internal|confidential|secret",
  "claim_type": "principle|fact|decision|lesson|procedure|warning|citation_summary",
  "language": "en",
  "title": "short normalized title",
  "normalized_text": "canonicalized claim text",
  "text_hash": "sha256(normalized_text)",
  "simhash": "near_duplicate_hash",
  "embedding_id": "vector_ref",
  "graph_keys": ["domain:memory-architecture", "tool:codex"],
  "entities": ["Hermes", "Kafka", "Memory Wiki"],
  "evidence_refs": ["s3://bucket/evidence/..."],
  "citation_refs": ["doi:...", "url_hash:..."],
  "created_at": "timestamp",
  "confidence": 0.82,
  "approval_state": "proposed"
}
```

## Retrieval And Grouping

Use cascade retrieval. Do not rely on vector search alone.

1. Hard filters:

```text
scope, visibility, tenant, user, domain, sensitivity, language, approval_state
```

2. Hash retrieval:

```text
text_hash, normalized_hash, evidence_hash, citation_hash, entity_hash,
command/error/success signatures
```

3. Lexical retrieval:

```text
BM25/FTS over title, normalized_text, entities, citations, tags
```

4. Vector retrieval:

```text
embedding search over compact claim text + evidence summary
```

5. Graph expansion:

```text
claim -> evidence -> citation -> domain -> tenant -> related claims
claim -> supersedes -> older claim
claim -> contradicts -> conflicting claim
```

6. Rerank:

```text
scope match
+ semantic score
+ lexical score
+ confidence
+ recency
+ citation quality
+ approval state
+ graph proximity
- sensitivity mismatch
- weak evidence
```

Grouping keys:

- domain
- tenant
- project/repo when present
- claim type
- entity cluster
- citation cluster
- evidence lineage
- topic embedding cluster
- graph community

## Deduplication And Reconciliation

Deduplication runs before global approval.

Dedup classes:

- `exact_duplicate`: same normalized hash
- `near_duplicate`: high simhash or embedding similarity
- `same_evidence`: different wording, same evidence/citation lineage
- `same_topic`: graph/semantic cluster overlap
- `conflict`: same topic/scope but opposite conclusion
- `supersedes`: newer, stronger evidence replaces older claim

Canonical lifecycle:

```text
proposed
  -> normalized
  -> exact_duplicate | near_duplicate | merge_candidate | conflict | canonical_new
  -> judge_review
  -> approved | rejected | needs_operator
  -> canonical
  -> indexed
  -> synced
```

Conflicts must not be auto-merged. They become contradiction clusters requiring
judge/operator review.

## Global Sidecars

Global sidecars consume bus topics and write only through controlled state
transitions:

- `global_inbox_sidecar`: validates incoming metadata, stores raw refs, emits
  normalization requests.
- `global_normalizer_sidecar`: canonicalizes text, entities, scope, hashes, and
  sensitivity labels.
- `global_dedupe_sidecar`: performs hash, lexical, vector, and graph candidate
  matching.
- `global_reconcile_sidecar`: proposes merge/supersede/conflict decisions.
- `global_judge_sidecar`: approves/rejects canonical writes; must be separate
  from normalizer/dedupe/reconcile invocations.
- `global_indexer_sidecar`: updates lexical/vector/graph indexes after approval.
- `global_sync_sidecar`: publishes approved deltas and pulls them into local
  caches.

No sidecar should write raw LLM output directly into canonical memory. Canonical
writes require normalized metadata, evidence refs, dedupe status, judge result,
and audit record.

## Access Control

Global does not mean visible to everyone.

Access checks must apply before retrieval and before sync:

- tenant boundary
- user/team permission
- sensitivity label
- domain visibility
- global approval status
- export/sync eligibility

Private or secret memories must not be globally indexed. A redacted derived
claim may be globally proposed only when evidence and approval support it.

## Implementation Sequence

1. Define config schema for global storage and bus backends.
2. Implement local SQLite bus adapter behind the global bus interface.
3. Implement Redpanda/Kafka adapter behind the same interface.
4. Add proposal metadata schema and validators.
5. Add global inbox and normalizer sidecars.
6. Add deterministic hash/lexical dedupe.
7. Add vector and graph retrieval adapters.
8. Add reconcile and judge sidecars.
9. Add canonical write path and audit table.
10. Add index fanout and device sync deltas.

## Production Scale-Out And Evaluation

Global memory scale-out should be driven by measured need, not by default
infrastructure weight. The default remains local filesystem/SQLite for one
laptop or one VM. Production deployments add services only when the workload
requires them:

- Redpanda/Kafka when many Hermes instances publish randomly and replay/dead
  letter handling matters.
- Object storage when raw evidence and redacted artifacts exceed local cache
  limits.
- Vector index when lexical/hash/entity retrieval misses relevant approved
  memories.
- Graph index when tenant/domain/tool/error relationships become important for
  multi-hop retrieval.

The production validation loop should compare low-cost workers before and after
memory retrieval:

```text
baseline task run
  -> no memory packet
  -> capture failures and validation gaps
memory-assisted task run
  -> classifier + metadata filters + compact packet
  -> capture success, reduced repeats, and packet usefulness
judge/operator review
  -> promote only durable lessons
```

This keeps the global wiki useful for both runtime improvement and future
training-corpus construction while preventing noisy, speculative, or
tenant-inappropriate memories from spreading across devices.
