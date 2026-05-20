# Lesser-Model Corpus Remittance Architecture

## Purpose

Hermes should not only remember mistakes. It should convert validated
failure/repair experience into approved training data for smaller, cheaper
coding models. The goal is to let an external MLOps platform fine-tune
configurable lesser models, such as a future Gemma-class coding worker, so
they gradually behave more like stronger teacher models on recurring
enterprise coding workflows.

Hermes owns corpus collection, curation, approval, packaging, and remittance
to configured storage. Hermes does not own training execution, model registry,
model serving, or rollout decisions. Those belong to external MLOps
infrastructure.

## Target Loop

```text
lesser worker attempts task
  -> sidecars detect failure, drift, hallucination, or tool misuse
  -> stronger model diagnoses and repairs
  -> supervisor validates corrected output
  -> approved failure/repair record
  -> Hermes corpus bundle
  -> Hermes remittance receipt
  -> external storage / Delta or Iceberg table
  -> external MLOps fine-tune job
  -> external held-out evaluation
  -> external model registry
  -> external staged deployment as optional worker tier
```

## Separation From Runtime Memory

Runtime memory helps the next task immediately. The training corpus feeds
external model improvement. Hermes must keep these concerns separate.

The training corpus must not contain:

- raw secrets
- full raw transcripts
- unbounded logs
- unapproved private tenant data
- speculative dreaming output
- failed patches without validated repair

It should contain compact, validated, approved learning examples.

## Storage And Remittance Layout

### Local/Dev

```text
~/.hermes/training-corpus/
  tenant=<tenant_id>/
    dataset_family=<family>/
      run=<run_id>/
        records.jsonl
        preference_pairs.jsonl
        manifest.json
        redaction_report.json
        approval_provenance.json
        external_training_hints.json
        remittance_receipt.json
        hashes.json
```

### Production

Use object storage plus a table format owned by the external MLOps/storage
environment:

- Azure Data Lake / S3 / GCS
- Delta Lake or Apache Iceberg
- optional feature/vector indexes downstream

Partition suggestion:

```text
training_corpus/
  tenant_id=<tenant_or_global>/
  scope=tenant|domain|global/
  dataset_family=failure_repair/
  model_family=gemma/
  date=YYYY-MM-DD/
    records.parquet
    preference_pairs.parquet
    manifest.json
    redaction_report.json
    external_training_hints.json
    remittance_receipt.json
```

Hermes may write to local disk, object storage, or a configured remittance
endpoint. It must not require Kafka, Spark, Ray, Kubernetes, vLLM, a model
registry, or GPU infrastructure to create corpus bundles.

## Dataset Families

Primary families for coding improvement:

- `failure_repair`
- `tool_misuse_repair`
- `hallucinated_completion_repair`
- `bad_code_patch_repair`
- `test_failure_repair`
- `routing_failure_repair`
- `missing_context_repair`
- `spec_noncompliance_repair`
- `before_after_diff`
- `validation_recipe`
- `policy_playbook`

Existing migration-oriented families remain valid:

- `repo_migration_plan`
- `migration_failure_repair`
- `architecture_pattern`

## Supervised Fine-Tuning Record

SFT records train the model to produce the corrected behavior directly.

```json
{
  "record_type": "sft",
  "dataset_family": "failure_repair",
  "messages": [
    {
      "role": "system",
      "content": "You are a coding agent. Follow Spec Kit, preserve git history, use tools carefully, run validation, and do not claim completion without evidence."
    },
    {
      "role": "user",
      "content": "Task packet, repo context summary, constraints, relevant memory/skill packet, and validation command."
    },
    {
      "role": "assistant",
      "content": "Corrected implementation plan, patch summary, validation evidence, and final response."
    }
  ],
  "metadata": {
    "tenant_id": "tenant_or_redacted",
    "repo_ref": "repo@commit",
    "task_type": "coding",
    "failed_model": "gemma-4-26b",
    "teacher_model": "codex",
    "failure_type": "hallucinated_completion",
    "validation_passed": true,
    "redaction_state": "safe",
    "approval_state": "approved"
  }
}
```

## Preference Record

Preference records train the model to prefer the validated repair over the
failed lesser-model response.

```json
{
  "record_type": "preference_pair",
  "dataset_family": "tool_misuse_repair",
  "prompt": "Task packet plus compact repo/memory/tool context.",
  "chosen": "Teacher-corrected answer with validation evidence.",
  "rejected": "Lesser-model answer that failed validation or violated policy.",
  "metadata": {
    "failure_type": "tool_misuse",
    "chosen_validation": "passed",
    "rejected_validation": "failed",
    "approval_state": "approved"
  }
}
```

## External Fine-Tuning Methods

These methods are recommendations for the external MLOps platform. Hermes
records them as non-executing hints.

### Stage 1: SFT

Use supervised fine-tuning first. This teaches the lesser model the correct
workflow, output style, and validation discipline.

### Stage 2: Preference Tuning

Use DPO, ORPO, or equivalent preference tuning after enough chosen/rejected
pairs exist. This is especially useful for:

- hallucinated completion
- tool misuse
- ignoring Spec Kit
- weak validation behavior
- unsafe shortcutting

### Stage 3: LoRA/QLoRA Adapters

Use LoRA or QLoRA for Gemma-class models first. It is cheaper and allows:

- tenant-specific adapters
- domain-specific adapters
- rollback to base model
- side-by-side evaluation

### Stage 4: Full Fine-Tune

Only consider full fine-tuning when the corpus, evaluation, and cost justify
it.

## Hermes Responsibilities

Hermes-owned stages:

1. corpus build
2. redaction and approval verification
3. deterministic JSONL bundle creation
4. stable hashes and manifest creation
5. external training hint creation
6. remittance to configured storage or endpoint
7. immutable remittance receipt creation
8. audit and observability metadata

Hermes must not create training jobs, register models, evaluate deployment
eligibility, or route traffic to a fine-tuned model based on corpus remittance.

## External MLOps Responsibilities

External MLOps-owned stages:

1. corpus ingestion from remitted storage
2. train/validation split
3. SFT job
4. optional preference tuning job
5. held-out Hermes benchmark
6. regression and safety evaluation
7. model package creation
8. model registry registration
9. canary deployment
10. telemetry comparison

These stages may run end-of-day, hourly, event-triggered, or near-real-time,
depending on budget and infrastructure. Hermes only emits corpus bundles and
receipts.

## External Model Registry

Registry layout, owned outside Hermes:

```text
model_registry/
  gemma-4-26b-hermes-code/
    version=2026-05-20-001/
      base_model.json
      adapter/
      tokenizer/
      training_manifest.json
      eval_report.json
      redaction_report.json
      approval_record.json
      deployment_status.json
```

Recommended registry metadata:

- base model
- adapter type
- corpus refs
- training job refs
- eval report refs
- benchmark score
- safety score
- approval status
- rollout status
- rollback target

## External Deployment Gate

A fine-tuned model cannot be promoted automatically. It must pass:

- held-out Hermes benchmark
- coding task success threshold
- false completion threshold
- tool misuse threshold
- cost/latency improvement threshold
- secret leakage tests
- tenant boundary tests
- regression suite vs base model

Only the external MLOps control plane can decide that it becomes an optional
worker model. Hermes may later consume an operator-approved model config like:

```yaml
worker_models:
  cheap_coding:
    provider: local_or_vllm
    model: gemma-4-26b-hermes-code:2026-05-20-001
    enabled: true
    rollout: canary
```

## Integration With Sidecars

Sidecars produce training candidates and corpus evidence but do not train
models.

- health sidecar detects failures
- progress summarizer distills evidence
- curator creates candidate lessons
- judge validates candidate quality
- supervisor validates repairs
- training corpus writer exports approved examples
- remittance writer stores the bundle and receipt
- external MLOps pipeline trains and evaluates

## First Implementation Slice

1. MLOps corpus remittance contract.
2. Failure/repair and preference-pair schemas.
3. Delta/Iceberg-compatible manifest fields.
4. External training hint schema.
5. Remittance receipt schema.
6. Boundary tests proving Hermes does not train, register, deploy, or promote
   models.
7. Local JSONL export only.

Production training execution, GPU scheduling, model registry, model serving,
and rollout automation belong to the external MLOps platform and should be
implemented outside Hermes after corpus quality is proven.
