# MLOps Corpus Remittance Contract

## Boundary

Hermes owns only:

- approved training candidate selection
- redaction verification
- corpus bundle creation
- destination layout planning
- external training hints
- remittance receipts
- audit metadata

External MLOps owns:

- training schedules
- fine-tuning jobs
- validation splits
- model registry
- benchmark gates
- serving
- rollout and rollback

Hermes must not train, register, deploy, promote, or route to fine-tuned models
from this contract.

## Failure Repair Record

```json
{
  "schema_version": "mlops.corpus.failure_repair.v1",
  "record_id": "fr_...",
  "tenant_id": "tenant_or_redacted",
  "scope": "tenant|domain|global",
  "dataset_family": "failure_repair",
  "task": {
    "task_type": "coding",
    "repo_ref": "repo@commit",
    "spec_ref": "specs/001-learning-memory-runtime/tasks.md#T000",
    "summary": "Compact task packet summary."
  },
  "lesser_attempt": {
    "model_family": "gemma",
    "model": "gemma-4-26b",
    "summary": "Bounded failed attempt summary.",
    "failure_type": "hallucinated_completion|tool_misuse|timeout|validation_failure|spec_noncompliance",
    "evidence_refs": ["memory://...", "benchmark://..."]
  },
  "teacher_repair": {
    "model_family": "codex|deepseek|other_strong_reasoning",
    "model": "codex",
    "diagnosis": "Why the attempt failed.",
    "correction_summary": "What corrected behavior succeeded.",
    "repair_refs": ["git://commit", "spec://task", "test://run"]
  },
  "validation": {
    "status": "passed",
    "evidence_refs": ["test://run"],
    "false_completion_checked": true,
    "tool_misuse_checked": true
  },
  "lesson": {
    "distilled_behavior": "What the lesser model should do next time.",
    "forbidden_behavior": "What must not be repeated."
  },
  "safety": {
    "redaction_state": "safe",
    "contains_raw_transcript": false,
    "contains_secret": false,
    "tenant_shareability": "tenant_only|domain_shareable|global_shareable"
  },
  "approval": {
    "candidate_id": "metacand_...",
    "judge_decision_id": "judge_...",
    "operator_approval_id": "approval_..."
  }
}
```

## Preference Pair Record

```json
{
  "schema_version": "mlops.corpus.preference_pair.v1",
  "record_id": "pp_...",
  "dataset_family": "tool_misuse_repair",
  "prompt_summary": "Task packet plus compact repo/memory/tool context.",
  "chosen": "Teacher-corrected response summary with validation evidence.",
  "rejected": "Lesser-model response summary that failed validation or policy.",
  "metadata": {
    "failure_type": "tool_misuse",
    "chosen_validation": "passed",
    "rejected_validation": "failed",
    "approval_state": "approved"
  }
}
```

## Bundle Manifest

```json
{
  "schema_version": "mlops.corpus.bundle.v1",
  "bundle_id": "bundle_...",
  "created_at": "2026-05-20T00:00:00Z",
  "tenant_id": "tenant_or_redacted",
  "scope": "tenant|domain|global",
  "dataset_family": "failure_repair",
  "record_count": 100,
  "preference_pair_count": 40,
  "hash_algorithm": "sha256",
  "records_sha256": "...",
  "preference_pairs_sha256": "...",
  "redaction_report_ref": "redaction_report.json",
  "approval_provenance_ref": "approval_provenance.json",
  "external_training_hints_ref": "external_training_hints.json"
}
```

## External Training Hints

External training hints are advisory metadata only. They do not create jobs.

```json
{
  "schema_version": "mlops.training_hints.v1",
  "target_model_family": "gemma",
  "target_base_models": ["gemma-4-26b"],
  "recommended_methods": ["sft", "dpo", "lora", "qlora"],
  "corpus_refs": ["bundle://bundle_..."],
  "eval_refs": ["benchmark://heldout-hermes-runtime"],
  "approval_refs": ["approval://..."],
  "notes": "External MLOps may train end-of-day or streaming batches."
}
```

## Destination Layout

Hermes may plan and write to local fake paths in tests. Production destinations
are configured externally.

```text
training_corpus/
  tenant_id=<tenant_or_global>/
  scope=<tenant|domain|global>/
  dataset_family=<family>/
  model_family=<family>/
  date=<YYYY-MM-DD>/
    records.jsonl
    preference_pairs.jsonl
    manifest.json
    redaction_report.json
    approval_provenance.json
    external_training_hints.json
    remittance_receipt.json
```

## Remittance Receipt

```json
{
  "schema_version": "mlops.remittance_receipt.v1",
  "receipt_id": "receipt_...",
  "bundle_id": "bundle_...",
  "destination_uri": "s3://...|abfs://...|gs://...|file://...",
  "bundle_sha256": "...",
  "submitted_at": "2026-05-20T00:00:00Z",
  "external_pipeline_id": "optional_external_id",
  "status": "submitted|accepted|rejected|unknown",
  "audit_refs": ["audit://..."]
}
```

## Non-Goals

- No GPU scheduling.
- No fine-tune job execution.
- No model registry writes.
- No model deployment gates.
- No runtime routing changes.
- No automatic promotion of lesser models.
