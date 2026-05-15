---
sidebar_position: 8
title: "Dreaming Control Plane"
description: "A first-class control-plane contract for Hermes dreaming, consolidation, and promotion workflows."
---

# Dreaming Control Plane

Dreaming is Hermes' background consolidation loop. It should be treated as a first-class orchestration factor, not just an implementation detail hidden inside memory maintenance.

The role of dreaming is to:

- consolidate recent work
- compress repeated signals
- produce durable memory candidates
- generate wiki candidates where appropriate
- trigger reviewed promotions into long-term memory

## Dreaming Config

The app/config/manifests should expose a dedicated `dreaming` block.

```yaml
dreaming:
  enabled: true
  interval_hours: 12
  run_on_start: false
  phases:
    - light
    - rem
    - deep
  promote_to_memory: true
  write_wiki_candidates: true
```

Recommended fields:

- `enabled` - turn scheduled dreaming on or off
- `interval_hours` - cadence between dreaming passes
- `run_on_start` - whether to run immediately when Hermes boots
- `phases` - which dreaming phases are active
- `promote_to_memory` - whether deep dreams may propose durable memory candidates
- `write_wiki_candidates` - whether dreams may emit wiki proposals

## Dreaming Workflow

1. Hermes runs a scheduled dreaming tick or a manual `run`.
2. The loop ingests recent signals from task history, memory, and curator outputs.
3. It compresses them through the active phases.
4. It emits memory candidates, wiki candidates, and reviewable outcomes.
5. A reviewer or policy gate decides whether to promote them.

Dreaming should not directly mutate durable memory in production-like contexts without approval.

## Suggested API Surface

- `GET /v1/control/dreaming`
- `POST /v1/control/dreaming/run`
- `POST /v1/control/dreaming/pause`
- `POST /v1/control/dreaming/resume`
- `POST /v1/control/dreaming/review`

## Suggested CLI Surface

- `hermes dream status`
- `hermes dream run`
- `hermes dream pause`
- `hermes dream resume`
- `hermes dream review`

## Manifest Support

Dreaming settings should appear inside the same runtime manifest used for sidecars and workers.

```yaml
spec:
  sidecars:
    dreaming:
      enabled: true
      interval_hours: 12
      run_on_start: false
      phases: [light, rem, deep]
```

## Validation Rules

The control plane should reject or warn on:

- dreaming enabled without a review path
- dreaming promotion in production-like environments without approval
- phases that are inconsistent with the runtime policy
- dreams that try to bypass the same secret-handling and sandbox rules as other control-plane operations

## Relationship To Other Loops

- `curator` maintains skills and skill hygiene.
- `learning sidecar` handles memory rollup and monitoring.
- `dreaming` consolidates and proposes durable knowledge.
- `DGM-H` evolves variants and agent behavior.

They are related but distinct. Dreaming is the consolidation bridge between raw activity and durable memory.
