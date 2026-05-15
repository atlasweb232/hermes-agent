---
sidebar_position: 5
title: "Orchestration Manifests"
description: "How Hermes app, CLI, and control-plane manifests map to the same configuration state."
---

# Orchestration Manifests

Hermes can be driven from an app, a CLI workflow, or a manifest-based control plane. The important rule is that all three paths must converge on the same validated runtime state.

This page describes the manifest path.

## What A Manifest Is

A manifest is a portable YAML declaration of the desired Hermes runtime shape for a tenant, repo, or environment.

It should describe:

- core model/provider/runtime settings
- sidecar settings
- worker profiles
- memory policy
- secret references
- apply mode
- restart policy

The manifest is not the source of truth by itself. It is input to the same validation and apply pipeline that the app and CLI use.

## Example

```yaml
apiVersion: hermes/v1
kind: RuntimeConfig
metadata:
  name: atlasweb-hermes
  tenant: atlasweb
  repo: hermes-agent
spec:
  runtime:
    model:
      default: gpt-oss-120b
      provider: custom
      base_url: https://api.cerebras.ai/v1
      api_key_ref: aws-secrets://atlasweb/cerebras-api-key
    terminal:
      backend: ssh
      cwd: /home/rakib/git/hermes-agent
      timeout: 300
      persistent_shell: true
  sidecars:
    learning:
      enabled: true
      interval_seconds: 300
    curator:
      enabled: true
      interval_hours: 168
    dreaming:
      enabled: true
      interval_hours: 12
      run_on_start: false
      phases: [light, rem, deep]
    dgm_h:
      enabled: false
      promotion_requires_approval: true
  workers:
    tool_profile: repo_eval
    browser:
      allow_private_urls: false
  memory:
    enabled: true
    memory_char_limit: 2200
    user_char_limit: 1375
  apply:
    mode: manifest
    restart_policy: selective
```

## Apply Flow

Whether the manifest is submitted by a UI, a supervisor, or a CI job, the flow should be the same:

1. Parse the manifest.
2. Convert it into the Hermes app config schema.
3. Validate secret references and policy rules.
4. Compare desired state against current state.
5. Compute whether a reload, restart, or full re-provision is required.
6. Apply only the affected runtime pieces when possible.
7. Confirm the final state with Hermes status commands.

## Supported Delivery Paths

### Orchestration Time

Use this when a task, tenant, or environment is being provisioned. The orchestrator can attach a manifest or config patch before the job starts.

Best for:

- tenant bootstrap
- repo onboarding
- controlled rollout of new sidecar settings
- tool profile changes for a new job class

### CLI Time

Use this for direct operator control.

The CLI flow should stay on the same validation path as the manifest flow:

- edit config
- validate
- restart/reload if needed
- confirm status

### Manifest Time

Use this when the desired runtime should be versioned, reviewed, or applied from automation.

Manifests are especially useful for:

- repeatable provisioning
- multi-tenant deployment
- offline recovery
- promotion gates
- reproducible runtime snapshots

## Secret Handling

Do not put raw secret values in the manifest.

Use references such as:

- `env:OPENROUTER_API_KEY`
- `aws-secrets://atlasweb/cerebras-api-key`
- `vault://path/to/secret`

Hermes should resolve the reference at apply time, then keep the resolved secret out of the manifest and UI.

## Recommended Guard Rails

The control plane should refuse or warn on:

- manifests that try to embed secret values directly
- runtime changes that enable unsafe tools by default
- dreaming changes that skip approval in production-like environments
- DGM-H changes that allow uncontrolled production mutation
- learning or curator changes that skip approval in production-like environments
- worker profiles that omit sandbox boundaries

## Relationship To The App

The app should be a viewer/editor for this manifest-shaped config, not a separate source of truth.

That gives you:

- orchestration-time changes for provisioning
- CLI changes for operators
- manifest changes for automation and multi-tenant rollout

All three paths end up producing the same Hermes runtime state.
