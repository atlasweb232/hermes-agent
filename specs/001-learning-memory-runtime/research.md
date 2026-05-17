# Research: Runtime Learning Memory Framework

## Decision: SQLite Event Bus First

**Rationale**: Hermes already uses local state and CLI workflows. A SQLite-backed event bus gives durable async handoff, leases, retries, and auditability without adding Docker, Redis, or Kafka operational burden.

**Alternatives considered**:

- Kafka: too heavy for the current single-VM/local workflow.
- Redis Streams: reasonable second phase when multiple long-running workers need fanout.
- In-memory queues: lose evidence on process exit and cannot support replay.

## Decision: Learning Judge Fails Closed

**Rationale**: Goal judging can continue on judge failure, but learning approval cannot. A malformed or unavailable judge must leave candidates unapproved.

**Alternatives considered**:

- Fail-open: unsafe because it can promote noisy or risky candidates.
- Human-only approval: safe but too slow for routine low-risk memory curation.

## Decision: Enforcement Remains Audit-Only

**Rationale**: The current policy engine can detect matching policy candidates and record what it would do. Actual command rewrite requires a later deterministic enforcement design with judge plus operator approval.

**Alternatives considered**:

- Immediate rewrite: too risky for terminal commands and secrets.
- No policy engine: loses the ability to measure potential benefit.

## Decision: Memory Tiering Is Retrieval Policy, Not Storage Shortcut

**Rationale**: Hot, warm, and cold tiers control retrieval freshness, prompt budget, and curation level. They must not bypass evidence and approval requirements.

**Alternatives considered**:

- Store everything in hot memory: prompt bloat and stale lessons.
- Keep only cold wiki: misses useful in-session lessons.

## Decision: Hybrid Retrieval Over Pure RAG Or Pure Graph

**Rationale**: Vector search is useful for fuzzy matching but unsafe as the first gate because scope, approval, tenant, repo, machine, and evidence constraints are operationally more important than semantic similarity. Graph search is useful for explainable cross-scope relationships, but it cannot handle fuzzy phrasing alone. Hermes should use structured metadata filters first, lexical search for exact operational identifiers second, vector search only over eligible compact approved memory documents, graph expansion for explainable related candidates, and a final reranker.

**Alternatives considered**:

- Pure vector RAG: retrieves semantically similar but operationally wrong memories across tenant/repo/machine boundaries.
- Pure graph retrieval: misses semantically equivalent phrasing and requires too much perfect normalization up front.
- External vector database first: adds operational complexity before local SQLite-backed retrieval limits are proven.

## Decision: SQLite-First Retrieval Indexes

**Rationale**: Hermes is local-first and VM-friendly. SQLite metadata, FTS5 lexical search, and SQLite graph edge tables are deterministic and easy to test. Vector search should start with an optional local backend such as `sqlite-vec`, `sqlite-vss`, or LanceDB before introducing a service dependency.

**Alternatives considered**:

- Neo4j: too heavy for first implementation.
- Qdrant/Chroma service-first: useful later but unnecessary before local retrieval behavior is proven.
- Embedding raw logs/transcripts: unsafe and noisy; only compact approved memory summaries should be embedded.

## Decision: Dreaming Produces Proposals Only

**Rationale**: Dreaming can synthesize playbooks and improvement ideas, but it is speculative. Proposals must pass judge/operator gates before affecting runtime behavior.

**Alternatives considered**:

- Dreaming auto-applies policies: violates human-controlled enforcement.
- No dreaming: loses offline improvement opportunity.
