# Lesser-Model MLOps Architecture

## Purpose

Hermes should not only remember mistakes. It should convert validated
failure/repair experience into training data for smaller, cheaper coding
models. The goal is to make configurable lesser models, such as a future
Gemma-class coding worker, gradually behave more like the stronger teacher
models on recurring enterprise coding workflows.

This is an offline MLOps loop. It must remain separate from live runtime
memory, sidecar execution, and policy enforcement.

## Target Loop

```text
lesser worker attempts task
  -> sidecars detect failure, drift, hallucination, or tool misuse
  -> stronger model diagnoses and repairs
  -> supervisor validates corrected output
  -> approved failure/repair record
  -> training corpus table
  -> fine-tune job
  -> held-out evaluation
  -> model registry
  -> staged deployment as optional worker tier
```

## Separation From Runtime Memory

Runtime memory helps the next task immediately. The training corpus feeds
offline model improvement.

The training corpus must not contain:

- raw secrets
- full raw transcripts
- unbounded logs
- unapproved private tenant data
- speculative dreaming output
- failed patches without validated repair

It should contain compact, validated, approved learning examples.

## Storage Layout

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
        hashes.json
```

### Production

Use object storage plus a table format:

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
```

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

## Fine-Tuning Methods

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

## MLOps Pipeline

Pipeline stages:

1. corpus build
2. redaction and approval verification
3. train/validation split
4. SFT job
5. optional preference tuning job
6. held-out Hermes benchmark
7. regression and safety evaluation
8. model package creation
9. model registry registration
10. canary deployment
11. telemetry comparison

The runtime platform should trigger or observe these jobs, but training itself
belongs in the MLOps pipeline.

## Model Registry

Registry layout:

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

Registry metadata:

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

## Deployment Gate

A fine-tuned model cannot be promoted automatically. It must pass:

- held-out Hermes benchmark
- coding task success threshold
- false completion threshold
- tool misuse threshold
- cost/latency improvement threshold
- secret leakage tests
- tenant boundary tests
- regression suite vs base model

Only then can it become an optional worker model:

```yaml
worker_models:
  cheap_coding:
    provider: local_or_vllm
    model: gemma-4-26b-hermes-code:2026-05-20-001
    enabled: true
    rollout: canary
```

## Integration With Sidecars

Sidecars produce training candidates but do not train models.

- health sidecar detects failures
- progress summarizer distills evidence
- curator creates candidate lessons
- judge validates candidate quality
- supervisor validates repairs
- training corpus writer exports approved examples
- MLOps pipeline trains and evaluates

## First Implementation Slice

1. MLOps training corpus contract.
2. Failure/repair and preference-pair schemas.
3. Delta/Iceberg-compatible manifest fields.
4. Model registry metadata schema.
5. Fine-tune job metadata schema.
6. Evaluation gate report schema.
7. Local JSONL export only.

Production training execution, GPU scheduling, and model serving should follow
only after corpus quality and offline eval are proven.
