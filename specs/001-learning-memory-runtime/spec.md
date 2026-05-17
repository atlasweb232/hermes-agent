# Feature Specification: Runtime Learning Memory Framework

**Feature Branch**: `132-learning-memory-runtime`

**Created**: 2026-05-16

**Status**: Draft

**Input**: User description: "Merge Hermes with online upstream and use Spec Kit to implement the rest of the runtime learning work: learning judge, event bus, memory wiki, dreaming phase, injection/meta-based search, hot/warm/cold memory model, observability, and strict separation between raw events, curator candidates, wiki knowledge, dreaming proposals, and enforcement policies."

## User Scenarios & Testing

### User Story 1 - Judge Learning Candidates (Priority: P1)

As the Hermes operator, I want proposed learning candidates to be reviewed by a separate judge before they can become approved memory or enforcement policy, so that noisy or unsafe lessons do not alter future agent behavior.

**Why this priority**: This is the safety gate required before expanding self-learning beyond advisory retrieval.

**Independent Test**: Create proposed candidates with valid evidence, missing evidence, malformed judge output, and risky enforcement requests; run the judge command and verify approved, rejected, and needs-human states are deterministic.

**Acceptance Scenarios**:

1. **Given** a proposed candidate with valid evidence and low risk, **When** the learning judge approves it, **Then** the candidate records the judge decision and becomes eligible for approved memory.
2. **Given** a proposed candidate with missing evidence, **When** the learning judge evaluates it, **Then** the candidate is rejected or marked needs-human and is not enforced.
3. **Given** malformed judge output, **When** the judge runner parses the result, **Then** the system fails closed and records a parse failure without approving the candidate.

---

### User Story 2 - Durable Runtime Event Bus (Priority: P2)

As the Hermes supervisor, I want runtime events to be written to a durable local bus so sidecars can consume learning signals asynchronously without blocking chat, delegation, or tool execution.

**Why this priority**: Continuous work needs in-session learning signals, but foreground agents must not wait on curation or dreaming.

**Independent Test**: Publish tool-result, task-outcome, policy-audit, and candidate events; run a consumer once; verify lease, retry, consumed, and failed state transitions.

**Acceptance Scenarios**:

1. **Given** a terminal policy audit event, **When** the bus consumer runs, **Then** it creates or updates a candidate without blocking the original command.
2. **Given** a crashed consumer lease, **When** the lease expires, **Then** another consumer can reclaim the event.
3. **Given** repeated processing failures, **When** retry limits are reached, **Then** the event is marked failed with structured error metadata.

---

### User Story 3 - Retrieve And Inject Scoped Learning (Priority: P3)

As a worker or supervisor, I want only relevant approved learning context injected into a task prompt, so prior lessons help current work without overriding explicit instructions or current evidence.

**Why this priority**: Retrieval is already partially implemented; meta-based search, tiering, and source separation need to make it reliable.

**Independent Test**: Invoke tasks with different tenants, repos, tools, task types, and error signatures; verify the classifier creates a structured query, the scorer ranks only relevant approved memory, the packet builder injects a compact top-k advisory packet, and unrelated memory is excluded.

**Acceptance Scenarios**:

1. **Given** approved routing memory matching a task, **When** worker context is built, **Then** a compact advisory memory packet is included.
2. **Given** archived, proposed, rejected, or low-confidence candidates, **When** retrieval runs, **Then** they are not injected.
3. **Given** a task whose tokens only partially overlap a memory item, **When** retrieval runs, **Then** substring-only false positives are excluded.
4. **Given** a prior mistake from another repo and tenant with the same tool and error signature, **When** a new task has the same task type and tool, **Then** the memory may be retrieved with cross-scope penalty but is labeled advisory and never treated as repo-specific truth.
5. **Given** a deterministic approved memory item such as a known bad command pattern and known working replacement, **When** policy escalation runs, **Then** it creates an audit/advisory policy candidate and requires judge plus operator approval before enforcement.

---

### User Story 4 - Compile Memory Wiki And Dreaming Proposals (Priority: P4)

As the Hermes operator, I want stable lessons promoted into a memory wiki and offline dreaming proposals, so repeated work becomes easier without letting speculative ideas control live execution.

**Why this priority**: Wiki and dreaming are high-value but must stay downstream of judged, approved evidence.

**Independent Test**: Promote approved memory into wiki claims, run a dreaming cycle, and verify dreaming creates proposals only, not applied policies.

**Acceptance Scenarios**:

1. **Given** approved durable memory, **When** the wiki compiler runs, **Then** it creates or updates evidence-backed wiki claims.
2. **Given** wiki claims and recent failures, **When** dreaming runs, **Then** it emits proposal records with rationale and risk.
3. **Given** a dreaming proposal, **When** the next session starts, **Then** it is not injected unless separately approved through the judge/operator path.

---

### User Story 5 - Observe Runtime Learning (Priority: P5)

As the Hermes operator, I want historical and active learning jobs visible by date, repo, task, worker, status, completions, blockers, and system overrides, so I can audit effectiveness and diagnose failures.

**Why this priority**: Observability is required to trust the learning loop and evaluate whether it improves future sessions.

**Independent Test**: Run sidecar, judge, wiki, dreaming, and housekeeping jobs; verify JSON CLI and backend endpoints expose active jobs, historical jobs, metrics, and failures.

**Acceptance Scenarios**:

1. **Given** active background jobs, **When** status is queried, **Then** each job reports owner, lease, progress, and last heartbeat.
2. **Given** completed jobs, **When** history is queried by date and repo, **Then** results include counts, decisions, failures, and candidate changes.
3. **Given** a blocked task, **When** observability data is requested, **Then** the current blocker and next recovery action are visible.

### Edge Cases

- Judge provider is unavailable, times out, or returns non-JSON.
- Event bus contains duplicate events or events from older schema versions.
- Candidate evidence references missing memory packets or missing kanban records.
- Background job is killed while holding a lease.
- Retrieved memory conflicts with explicit operator instructions or current git/test evidence.
- Dreaming proposes a risky or destructive change.
- Hot memory grows beyond prompt budget.

## Requirements

### Functional Requirements

- **FR-001**: System MUST provide a learning judge runner with strict structured output validation.
- **FR-002**: System MUST fail closed when judge output is missing, malformed, risky, or unsupported.
- **FR-003**: System MUST record judge decisions separately from curator candidates and approved memory.
- **FR-004**: System MUST keep enforcement disabled unless both judge approval and operator approval are present.
- **FR-005**: System MUST provide a durable local event bus for runtime learning events.
- **FR-006**: System MUST process event bus work asynchronously with leases, retries, and failure states.
- **FR-007**: System MUST keep raw events, curator candidates, judge decisions, approved memory, wiki claims, dreaming proposals, and enforcement policies in separate records or tables.
- **FR-008**: System MUST support hot, warm, and cold memory tiers with explicit promotion and demotion rules.
- **FR-009**: System MUST classify each task invocation into a structured retrieval query that includes tenant, repo, task type, tools, intent, entities, error signatures, success signatures, and scope.
- **FR-010**: System MUST store approved memory with metadata fields sufficient for targeted retrieval, including tenant, repo, tool, task type, error signature, success signature, confidence, tier, scope, source, and verification timestamps.
- **FR-011**: System MUST score memory relevance using exact scope matches, task type, tool, error/success signatures, semantic similarity, confidence, recency, and cross-tenant/repo penalties.
- **FR-012**: System MUST build compact top-k memory packets from scored approved memory and include evidence, scope, confidence, and advisory priority labels.
- **FR-013**: System MUST provide policy escalation for deterministic approved memory, producing audit/advisory/enforcement candidates without enabling enforcement automatically.
- **FR-014**: System MUST record outcome feedback that marks injected memory as helpful, irrelevant, harmful, or unknown and adjusts confidence or tier according to policy.
- **FR-015**: System MUST retrieve learning context using quality gates, evidence requirements, scope filters, and exact or semantic matching rules that avoid substring-only false positives.
- **FR-016**: System MUST label injected learning context as advisory and lower priority than current evidence and explicit instructions.
- **FR-017**: System MUST compile approved durable memory into evidence-backed memory wiki claims.
- **FR-018**: System MUST run dreaming as proposal-only background synthesis.
- **FR-019**: System MUST expose CLI and backend-compatible JSON status for active jobs, historical jobs, candidates, decisions, and policy audits.
- **FR-020**: System MUST expose housekeeping for stale, noisy, low-quality, duplicate, or invalid candidates without deleting audit history.
- **FR-021**: System MUST document operator approval points, automated promotion points, and forbidden automatic actions.

### Key Entities

- **Runtime Event**: Durable record of a foreground or sidecar signal such as tool result, task outcome, policy audit, or candidate proposal.
- **Learning Candidate**: Curator-generated proposed lesson with evidence, score, kind, scope, and status.
- **Judge Decision**: Structured approval, rejection, or needs-human decision for a candidate or policy proposal.
- **Approved Memory**: Candidate promoted for retrieval after passing quality, judge, and operator gates.
- **Memory Wiki Claim**: Curated durable knowledge derived from approved memory with evidence and confidence.
- **Dreaming Proposal**: Offline suggestion for playbooks, routing, tests, or policies that cannot affect runtime until approved.
- **Policy Audit**: Non-enforcing evaluation that records what a policy would have done.
- **Memory Tier**: Hot, warm, or cold storage classification that controls retrieval latency, prompt budget, and summarization.
- **Learning Job**: Background execution record for sidecar, judge, wiki, dreaming, housekeeping, or reconcile work.
- **Task Retrieval Query**: Structured representation of a task invocation used to find relevant approved memory.
- **Memory Packet**: Compact prompt-ready advisory context built from top-ranked approved memory.
- **Outcome Feedback**: Post-task record describing whether injected memory helped, was irrelevant, was harmful, or had unknown impact.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Judge runner approves or rejects a controlled candidate set with 100% deterministic status transitions in tests.
- **SC-002**: Foreground terminal/chat/delegation paths do not wait for event bus consumers, curator, judge, wiki, dreaming, or housekeeping work.
- **SC-003**: Retrieval injects only approved/applied, evidence-backed, scope-matching memory in focused tests.
- **SC-004**: Sidecar and job status commands return machine-readable JSON for active and historical work.
- **SC-005**: No enforcement policy can actively rewrite a command unless a test fixture includes both judge approval and operator approval.
- **SC-006**: No raw secrets or raw transcripts are stored in approved memory, wiki claims, or dreaming proposals in safety tests.
- **SC-007**: Housekeeping can reduce noisy active candidate lists without deleting archived audit history.

## Assumptions

- SQLite `state.db` remains the first durable event bus implementation.
- Redis Streams or Kafka are future options only after local SQLite bus limits are proven.
- Codex can be the initial learning judge provider; Qwen or Cerebras-backed models can be configured later.
- Existing Hermes CLI and dashboard/backend patterns should be reused instead of introducing a separate service.
- Existing learning sidecar, curator policy runner, housekeeping, retrieval, and policy audit code remain the base implementation.
- Operator approval means explicit user or admin action through CLI/API/config, not implicit model confidence.
