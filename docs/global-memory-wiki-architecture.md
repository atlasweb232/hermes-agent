# Global Memory Wiki Architecture

## Purpose

The global memory wiki is the cross-device, cross-domain knowledge layer for
Hermes. It accepts proposed knowledge from many Hermes instances, deduplicates
and reconciles it, gates canonical writes through judges/operators, and
publishes approved deltas back to local instances.

It is not a raw transcript store and not a free-form append log. Raw data is
evidence. Canonical wiki claims are approved, deduplicated, scoped knowledge.

Tenant boundaries come from the tenant platform contract:
[`specs/001-learning-memory-runtime/contracts/tenant-onboarding.md`](../specs/001-learning-memory-runtime/contracts/tenant-onboarding.md).
Global memory may consume only redacted, approved, shareable tenant evidence;
tenant-private memory namespaces from runtime cell assignments remain private.

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

The runtime boundary lives behind adapter roles, not provider imports:

- Object store adapter: stores sanitized canonical JSON/blob artifacts. The
  default backend is local filesystem storage.
- State store adapter: stores canonical claim/page state and sync cursors. The
  default backend is SQLite.
- Lexical index adapter: stores dependency-free text search payloads. The
  default backend is SQLite-backed local search.
- Vector index adapter: disabled by default. Tests may opt into `local_fake`
  token-overlap search, but production vector providers must be added behind
  the adapter boundary.
- Graph index adapter: stores claim/evidence/scope relationships. The default
  backend is SQLite.

`hermes memory wiki backends --json` reports configured adapter health without
emitting provider secrets or raw backend URIs. Unknown production backends such
as S3, Postgres, Qdrant, or Neo4j are represented as configured-but-unavailable
health DTOs until a future plugin supplies the provider implementation. Hermes
must not import optional cloud/database/vector/graph packages from the core
runtime path.

Indexable payloads are limited to approved, canonical, or applied global
shareable memory/wiki evidence. Raw transcripts, raw proposals, provider logs,
secrets, unbounded logs, and tenant-private records are rejected or redacted
before any object, state, lexical, vector, or graph adapter receives them.

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

Before any Kafka/Redpanda work, the SQLite queue must prove:

- queued, leased, consumed, and dead-letter counts are observable
- one batch can be drained idempotently
- replay does not duplicate canonical lessons
- poison events move to dead-letter instead of blocking the worker
- sidecar queues do not block foreground chat/delegation

If the local SQLite bus cannot demonstrate these properties, adding Kafka will
hide the failure behind infrastructure rather than fix it.

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

## Cost Budget Policy

Token budget is a product requirement. The memory architecture exists to make
cheaper workers more reliable, not to replace every worker failure with another
expensive reasoning call.

Default budget order:

```text
1. Programmatic:
   signatures, hashes, simhash, hard filters, SQLite/FTS lookup, reuse metrics

2. Cheap model:
   bounded summarization, discussion capture, candidate extraction,
   lightweight confirmation for near matches

3. Strong model:
   curator, judge, contradiction resolution, policy proposal, promotion review

4. Operator:
   global promotion, enforcement, export, config mutation
```

Required runtime counters:

- memory lookup count
- exact global lesson hit count
- near global lesson hit count
- skipped curator count
- skipped dreaming count
- LLM sidecar calls by role/model
- estimated memory-packet tokens
- repeated error signatures before/after memory
- outcome feedback: helped, ignored, hurt

Hard rules:

- Exact approved persisted lesson hits must not call curator, judge, or dreaming
  by default.
- Near matches may use a cheap confirmation model only when programmatic
  evidence is insufficient.
- Strong judge/curator calls require low confidence, conflict, promotion,
  enforcement, or explicit operator request.
- Memory packet construction must enforce top-k and token caps before a worker
  prompt is assembled.
- Retrieval must fail closed on tenant/sensitivity/approval mismatches before
  any semantic similarity score is considered.

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

The detailed dreaming role, evidence packet, proposal DTO, and validator
contract lives in
[`dreaming-integration.md`](../specs/001-learning-memory-runtime/contracts/dreaming-integration.md).

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

## Least-Overhead Runtime Path

The cheapest useful path is to pull only the relevant approved global memory
down into local hot memory for the task run. Do not make every task call a
global sidecar, vector database, graph service, or LLM.

```text
task starts
  -> classify task metadata/signatures programmatically
  -> check local hot cache
  -> if miss, query persisted global lessons by exact signature/hash
  -> if exact miss, query bounded simhash/lexical near matches
  -> materialize top-k approved lessons into local hot cache
  -> merge local hot cache + local memory wiki + policy hints
  -> build compact advisory packet
  -> dispatch worker
  -> record helped/ignored/hurt feedback
```

Local hot cache entries should be compact and task-oriented:

- source global lesson id
- tenant/repo/tool/task/error signatures
- compact advisory text
- confidence
- sensitivity/scope labels
- evidence id refs, not raw evidence blobs
- ttl/expires_at
- last_used_at
- reuse stats

Hot-cache materialization must not copy private raw global evidence. It stores
only the approved claim/lesson summary and refs needed for audit. If a task
needs full evidence, it must use the evidence reference under the normal access
control path.

This path is Phase 11A because it directly reduces worker mistakes and token
spend. Global indexer and sync sidecars are Phase 11B because they are useful
for scale, not necessary to prove the value loop.

## Persisted Lesson Retrieval For Pre-Curation

The deterministic pre-curation gate is not complete until it reads approved
global lessons from durable storage. In-process dictionaries are acceptable for
unit tests, but production behavior must prove this sequence:

```text
approved global lesson
  -> persist_global_lesson(...)
  -> configured global state/index backend
  -> retrieve_global_lessons_for_event(...)
  -> should_curate_locally(...)
  -> skip / confirm / curate decision
  -> aggregate reuse metric
```

The persisted lesson schema must include enough metadata to make retrieval
targeted and safe:

- `lesson_id`
- `approval_state`
- `tenant_id`
- `repo_id`
- `scope`
- `sensitivity`
- `visibility`
- `claim_type`
- `tool`
- `task_type`
- `worker_kind`
- `failure_signature`
- `success_signature`
- `scope_signature`
- `evidence_signature`
- `normalized_text`
- `text_hash`
- `simhash`
- `confidence`
- `reuse_stats`
- `approval_provenance`
- `created_at`
- `updated_at`
- `retired_at`

Retrieval must be cascade based:

```text
1. hard gates:
   approval_state in approved/canonical/applied
   sensitivity != secret
   tenant/repo/scope visibility is allowed
   not retired/stale

2. exact lookup:
   failure_signature
   success_signature
   scope_signature
   evidence_signature
   text_hash

3. near lookup:
   simhash hamming distance threshold
   lexical overlap
   confidence floor

4. output:
   bounded top-k lessons
   rejected-candidate reasons
   retrieval audit id
```

The pre-curation runtime must never treat global memory as stronger than local
facts, tests, logs, git state, or explicit operator instruction. It may suppress
expensive local recuration only when the retrieved persisted lesson passes the
same gates that the in-process deterministic helper uses.

## Task-Start Hydration

Task-start hydration is the point where global memory helps workers before they
fault.

Inputs:

- tenant id
- repo id
- task type
- tool/provider/model hints
- worker kind
- failure/success signatures when available
- branch/file/framework entities
- local memory packet
- policy audit hints

Outputs:

- local hot-cache hits
- persisted global lesson hits
- compact merged advisory packet
- retrieval audit
- estimated packet tokens

Merge order:

```text
1. explicit operator/master instruction
2. current git/tests/logs/task facts
3. deterministic policy audit blocks/warnings
4. local hot memory exact hits
5. local repo memory wiki claims
6. approved global hot-cache lessons
7. approved persisted global lessons materialized during hydration
```

The packet must stay advisory unless policy engine or operator explicitly
escalates it. Workers should see concrete prior failures and working paths, not
large summaries.

## Failure-Lesson Learn Acceptance Test

The Claude router failure is the canonical first test because the system already
observed repeated bad commands followed by a direct working command.

Acceptance sequence:

```text
1. Persist approved global command-repair lesson:
   failed_path = worker-router claude
   working_path = claude --model sonnet -p
   failure_signature = cmd:worker-router:claude:parse-error

2. Restart Hermes so no in-memory test object exists.

3. Start a fresh task that asks Hermes to use Claude Code.

4. Supervisor creates structured event metadata before retrying tools.

5. Runtime retrieves the stored global lesson by signature/hash.

6. Pre-curation returns skip_global_exact_hit or confirm_global_near_hit.

7. Runtime records global_lesson_hit or global_lesson_near_hit.

8. Supervisor avoids repeating the old worker-router failure loop, or escalates
   through an explicit policy/audit path before trying it again.
```

This test is different from the first VM smoke. The first smoke proved the
decision helper. This acceptance test proves durable storage, retrieval,
runtime integration, and live task behavior.

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
14. Add persisted global lesson storage schema and local SQLite backend.
15. Add `retrieve_global_lessons_for_event(...)` and retrieval audits.
16. Wire persisted retrieval into pre-curation before local curator/dreaming.
17. Add live failure-lesson learn smoke after restart.
18. Add cost/value observability for memory hits, token estimates, skipped
    sidecars, repeated errors, and low-end worker outcomes.
19. Add compact task-memory retrieval profiles for low-cost worker task
    packets.

Do not implement production Kafka/Redpanda, production vector/graph backends,
large training export, realtime voice, or a full dashboard until steps 14-18
show measurable value on the VM.

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

Training-corpus construction is governed by
[`lesser-model-mlops-architecture.md`](lesser-model-mlops-architecture.md)
and the
[`MLOps corpus remittance contract`](../specs/001-learning-memory-runtime/contracts/mlops-corpus-remittance.md).
The wiki may supply only approved, redacted, shareable evidence for Hermes
corpus bundles. Hermes collects, curates, exports, validates, and remits those
bundles; external MLOps owns fine-tuning, model registry, evaluation gates,
serving, and rollout.

## Compact Worker Retrieval Profiles

`build_task_memory_retrieval_profile(...)` is the low-cost worker packet
builder for approved global lessons. The default `low_cost_worker` profile
uses the existing SQLite-backed canonical lesson store and remains
programmatic by default:

- Apply exact tenant, repo, tool, task type, and worker kind filters when the
  event supplies those fields.
- Normalize command/error signature inputs into failure/success signature
  matching so worker events can use `command_signature` and `error_signature`
  without changing the global lesson schema.
- Cap low-cost retrieval to at most three matches, even when callers request a
  larger `top_k`.
- Sort deterministically by match priority, feedback demotion, score
  descending, and lesson id.
- Estimate tokens deterministically and skip injection items that would exceed
  the caller's token budget while reporting `budget_exhausted`.
- Return only bounded advisory fields and evidence refs; never return raw
  transcripts, secrets, logs, or payload JSON.
- Demote, but do not mutate, lessons whose negative reuse feedback exceeds
  positive/helped feedback.

Exact approved profile hits are terminal for the cheap retrieval step:
`llm_calls` stays empty and no curator, judge, dreaming, vector, or graph
backend is requested. T135 adds an opt-in vector/graph extension point for this
profile after the low-end worker hot-cache/signature path has proven useful:

- The fallback is disabled by default at
  `supervisor.global_memory_wiki.task_memory_profile.vector_graph_fallback.enabled`.
- When enabled, it only accepts `vector_index.backend: local_fake` and
  `graph_index.backend: sqlite|memory`; production vector or graph services are
  not used by this path.
- Exact/signature matches remain the first path. The fallback is skipped when
  the best local exact/signature score meets `min_exact_score`; operators can
  raise that threshold to force fallback evaluation for experiments.
- Only approved/canonical/applied global lessons that are cross-tenant
  shareable, non-secret, and already compact/canonical are indexed. Private
  tenant-only lessons, raw proposals, raw transcripts, provider logs, and
  secret-like text are skipped and redacted from profile output.
- JSON profile output includes bounded counters for `exact_hit`,
  `signature_hit`, `vector_fallback_used`, `graph_fallback_used`,
  `skipped_private`, and `skipped_secret`.

On a scoped exact miss, the older optional semantic fallback is still a
deterministic `local_fake` advisory item that tells the worker no approved task
memory matched. It is a placeholder, not a production vector dependency.

Operators and dashboards can inspect the JSON packet through:

```bash
hermes memory global profile --event-json '<event-json>' --top-k 3 --token-budget 240 --json
```

## Explicit Local Sidecars

T132-T134 add two one-shot sidecars after the Phase 11A VM value gate. They are
disabled by default under `supervisor.global_memory_wiki.sidecars.*`, run only
when explicitly invoked, and use SQLite/local filesystem state only in this
slice. They do not install foreground hooks and they do not add production
vector DB, graph DB, Kafka, or Redpanda dependencies.

`global_indexer_sidecar` is exposed as:

```bash
hermes memory global index --once --json
```

It scans only `hermes_global_lessons` and writes local metadata rows to
`hermes_global_lesson_index`. Eligible lessons must be approved/canonical/applied,
global scope, not retired, not secret, and cross-tenant shareable. Proposed,
private, tenant-only, secret, retired, and secret-like lessons are skipped with
bounded id/reason refs. The index table stores hashes, simhashes, lexical terms,
graph-ready keys, and a disabled vector stub. It does not store raw proposals,
raw transcripts, provider logs, or secret values.

`local_sync_sidecar` is exposed as:

```bash
hermes memory sync --once --json --tenant-id <tenant> --repo-id <repo> --tool <tool>
```

It reads approved active index rows, applies tenant/repo/tool/task filters, and
materializes relevant lessons into the existing `hermes_global_hot_cache`.
Sync deltas are recorded in local SQLite for idempotent replay accounting.
Expired cache rows are demoted by TTL cleanup, while retired/deleted or no
longer shareable lessons are removed from local cache/index state.

Both JSON surfaces report `status`, `feature_enabled`, `scanned`, `indexed` or
`synced`, `updated`, `skipped`, `demoted`, `removed`, `errors`, and bounded
`refs`. Result refs intentionally contain ids and reasons only, never raw lesson
text or secret-bearing payloads.

## Skill Pipeline Boundary

The global memory wiki can provide evidence for skill candidates, but it does
not publish procedural skills directly. Skill creation, repair, validation, and
optional SkillClaw sync are governed by
[`skill-memory-pipeline-architecture.md`](./skill-memory-pipeline-architecture.md)
and the contract in
[`../specs/001-learning-memory-runtime/contracts/skill-memory-pipeline.md`](../specs/001-learning-memory-runtime/contracts/skill-memory-pipeline.md).
