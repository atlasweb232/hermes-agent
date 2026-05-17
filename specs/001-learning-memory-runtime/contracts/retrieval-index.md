# Retrieval Index Contract

## Retrieval Order

Hermes memory retrieval uses hybrid search in this order:

```text
TaskRetrievalQuery
  -> hard metadata filters
  -> lexical search for exact identifiers and signatures
  -> vector search over eligible compact memory documents
  -> graph expansion over eligible related nodes
  -> rerank/scoring
  -> compact MemoryPacket
```

Vector similarity never overrides hard filters for status, evidence, approval,
scope, tenant, repo, machine, or secret safety.

## Index Layers

### Structured Metadata

The first layer is relational metadata stored with approved memory and index
documents. It filters by:

- status
- evidence presence
- tenant
- repo
- machine
- workspace
- tool
- worker kind
- provider
- model
- task type
- intent
- error signature
- success signature
- scope
- confidence
- tier
- timestamps

### Lexical Index

Lexical search is for exact operational identifiers:

- commands
- CLI flags
- file paths
- branch names
- provider/model names
- error signatures
- tool names
- repo names

SQLite FTS5 is the default first implementation.

### Vector Index

Vector search is over compact, redacted, approved memory documents only.

Embed:

- claim
- summary
- failure pattern
- success pattern
- task type
- tool context
- evidence summary

Do not embed:

- raw transcripts
- raw logs
- secrets
- unapproved candidates
- dreaming proposals

Initial vector backends should be SQLite-friendly or local-first, such as
`sqlite-vec`, `sqlite-vss`, or LanceDB. External vector stores are optional
future backends.

### Graph Index

The first graph implementation can be SQLite node/edge tables.

Node types:

- tenant
- repo
- machine
- tool
- worker
- provider
- model
- task type
- error signature
- success signature
- memory
- wiki claim
- dreaming proposal
- policy

Edge types:

- `APPLIES_TO`
- `OBSERVED_ON`
- `USES_TOOL`
- `USES_MODEL`
- `AVOIDS_ERROR`
- `RECOMMENDS_ACTION`
- `DERIVED_FROM`
- `PROMOTED_TO`
- `RELATED_TO`

Graph expansion can add explainable candidates, but cannot bypass hard filters.

## Rerank Features

The scorer should combine:

- exact tenant/repo/machine/tool/task type matches
- lexical match score
- vector similarity
- graph path proximity
- error/signature match
- confidence
- recency
- tier
- evidence quality

Required penalties:

- cross-tenant penalty
- cross-repo penalty
- stale memory penalty
- low confidence penalty
- wrong-machine exclusion for `machine_safe` memory
- missing-evidence exclusion
- non-approved status exclusion

## Auditability

Every retrieval run must record:

- query features
- hard filters
- lexical candidates
- vector candidates
- graph candidates
- final rerank features
- packet output

This lets the operator inspect why a memory item was injected or excluded.
