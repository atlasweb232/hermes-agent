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

## Global Pre-Curation Dedupe Gate

Local runtimes should not spend curator or dreaming tokens rediscovering a
failure/repair pattern that already exists as approved global memory. Before a
local event enters expensive curation, the runtime should normalize the event
and check global approved memory.

Required local event signatures:

- `failure_signature`: normalized command, tool, provider, model, exception
  class, stderr hash, validation failure, or repeated-progress signature.
- `success_signature`: known working command, repair action, validation command,
  completion evidence hash, or policy repair action.
- `scope_signature`: tenant, repo, platform, language/framework, tool,
  task_type, worker_kind, and sensitivity.
- `evidence_signature`: hashes/refs for bounded logs, task ids, commits,
  validation outputs, or approved memory refs.

Pre-curation flow:

```text
local event emitted
  -> local normalizer computes signatures
  -> local hot/warm memory lookup
  -> global approved-memory lookup
  -> exact global hit:
       attach global canonical id
       skip local expensive curation
       record global_lesson_hit
  -> high-confidence near global hit:
       create lightweight local confirmation
       skip LLM curator unless configured otherwise
       record global_lesson_near_hit
  -> no hit:
       local curator may run
       record global_lesson_miss
```

This gate is not enforcement. It is a cost and dedupe control. The foreground
task can use approved global memory as compact advisory context, but local
execution still follows the supervisor, policy engine, judge, and operator
boundaries.

Implementation should expose this decision as a deterministic helper such as
`should_curate_locally(event)`, returning one of `skip_global_exact_hit`,
`confirm_global_near_hit`, or `curate_locally`.

The local runtime must record reuse metrics:

- `global_lesson_hit`: exact approved global lesson matched.
- `global_lesson_near_hit`: near match found, local confirmation recorded.
- `global_lesson_used`: lesson was injected or attached to a task packet.
- `global_lesson_helped`: later validation suggests it reduced failures or
  improved completion.
- `global_lesson_ignored`: retrieved but not used by the worker/supervisor.
- `global_lesson_hurt`: retrieved lesson correlated with worse outcome and
  should be decayed or reviewed.

These counters feed global confidence and retrieval ranking. They must never
promote private local evidence globally without the normal approval path.

## Local Dreaming Vs Global Dreaming

Local and global dreaming are separate sidecar roles.

Local dreaming:

- reads local approved memory/wiki evidence only
- defaults to tenant/repo/device scope
- proposes local playbooks, tests, cleanup, architecture work, or policy ideas
- cannot publish directly to global memory
- cannot change runtime prompts, config, routing, or enforcement

Global dreaming:

- reads only globally approved, redacted, shareable canonical memory/wiki
- looks for cross-tenant/cross-repo patterns, contradictions, drift, and
  reusable training/eval candidates
- proposes global wiki updates, eval fixtures, training candidates, or policy
  candidates
- requires stronger judge review and operator approval
- never reads private raw logs or private local proposal storage
- never pushes changes directly to local runtimes

Promotion hierarchy:

```text
local raw event
  -> local candidate
  -> local approved memory
  -> global promotion candidate
  -> global judge/operator approval
  -> global canonical memory/wiki
  -> local runtimes retrieve approved global lesson
```

Global dreaming may suggest that many local lessons should be consolidated, but
only the global reconcile/judge/operator chain can make a canonical global
write.

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
11. Add global pre-curation dedupe gate before expensive local curator/dreaming
    work.
12. Add global lesson reuse counters and confidence feedback.
13. Add separate local/global dreaming roles and sidecar leases.

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
