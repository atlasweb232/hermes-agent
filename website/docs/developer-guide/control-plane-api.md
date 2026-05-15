---
sidebar_position: 6
title: "Control Plane API"
description: "A control-plane contract for reading, validating, applying, and observing Hermes config and orchestration state."
---

# Control Plane API

Hermes already exposes an OpenAI-compatible API server for chat and runs. This document defines the **control-plane** surface for apps, orchestrators, and manifest-driven automation that need to manage runtime config, sidecars, workers, and processes.

OpenAPI fragment: [`/api/control-plane.openapi.yaml`](/api/control-plane.openapi.yaml)

For the CLI mapping that mirrors this contract, see [Control Plane CLI](./control-plane-cli.md).

The control-plane API should be treated as a thin, structured layer over the same Hermes state used by:

- `~/.hermes/config.yaml`
- `~/.hermes/.env`
- `hermes config`
- `hermes status`
- `hermes curator`
- `hermes memory`
- `hermes dgm`

The goal is not a second configuration system. The goal is to make the same state accessible through HTTP, CLI, and manifests.

## Core Principles

1. **Single source of truth** - config lives in Hermes state files and runtime process state.
2. **Validation before apply** - every delivery path validates before mutating runtime.
3. **Selective reload** - restart only what changed when possible.
4. **Secret references only** - the API returns secret handles, not raw secret values.
5. **Streaming feedback** - long-running operations should emit progress events.

## Suggested Endpoints

The exact implementation may live behind Hermes' existing API server, but the contract should look like this:

### Read Current State

#### `GET /v1/control/config`

Returns the current structured config view, split into the same sections used by the app:

- runtime
- sidecars
- workers
- memory
- tools
- secrets references
- process state

Example response:

```json
{
  "object": "hermes.control.config",
  "profile": "default",
  "runtime": {
    "model": {
      "default": "gpt-oss-120b",
      "provider": "custom",
      "base_url": "https://api.cerebras.ai/v1",
      "api_key_ref": "aws-secrets://atlasweb/cerebras-api-key"
    },
    "terminal": {
      "backend": "ssh",
      "cwd": "/home/rakib/git/hermes-agent",
      "timeout": 300,
      "persistent_shell": true
    }
  },
  "sidecars": {
    "monitoring": {"enabled": true},
    "learning": {"enabled": true, "interval_seconds": 300},
    "curator": {"enabled": true, "interval_hours": 168},
    "dgm_h": {"enabled": false, "promotion_requires_approval": true}
  },
  "workers": {
    "tool_profile": "repo_eval",
    "browser": {"allow_private_urls": false}
  },
  "memory": {
    "enabled": true,
    "memory_char_limit": 2200,
    "user_char_limit": 1375
  },
  "processes": {
    "gateway": "running",
    "supervisor": "running",
    "curator": "idle",
    "learning_sidecar": "running"
  }
}
```

#### `GET /v1/control/status`

Returns a compact health and runtime summary. Intended for dashboards and probes.

#### `GET /v1/control/processes`

Lists the Hermes processes and sidecars that the control plane can manage.

#### `GET /v1/control/sidecars`

Lists sidecars with their current state, cadence, and last run information.

#### `GET /v1/control/workers`

Lists worker profiles and active tool/sandbox policies.

### Validate Desired State

#### `POST /v1/control/config/preview`

Accepts a proposed config patch or manifest, returns the computed diff without applying it.

Use this for:

- UI preview panes
- supervisor planning
- CI checks
- manifest review

#### `POST /v1/control/config/validate`

Validates a proposed config patch or manifest against Hermes policy:

- secret handling
- sidecar approval rules
- worker sandbox policy
- DGM-H runtime mutation rules
- restart requirements

Returns `valid: true/false` plus warnings and errors.

### Apply Desired State

#### `POST /v1/control/config/apply`

Applies a structured config patch.

Request can include:

- `apply_mode`: `orchestration-time | cli | manifest`
- `restart_policy`: `selective | full`
- `scope`: `profile | tenant | repo | job`
- `patch`: structured config delta

The server should:

1. validate the patch
2. compute the impacted runtime pieces
3. write config or secret references
4. apply reload/restart as needed
5. return the final status

#### `POST /v1/control/manifests/apply`

Accepts a manifest document and translates it to the same internal patch path as `config/apply`.

This is the preferred route for:

- provisioning
- multi-tenant rollouts
- repeatable deployment
- offline recovery

### Process Control

#### `POST /v1/control/processes/{name}/restart`

Restarts a named process or sidecar.

#### `POST /v1/control/processes/{name}/reload`

Reloads config without a full restart when the target supports it.

#### `POST /v1/control/processes/{name}/stop`

Stops a managed process.

#### `POST /v1/control/processes/{name}/start`

Starts a managed process.

These endpoints are intentionally narrow. They should not expose arbitrary process execution.

### Event Stream

#### `GET /v1/control/events`

Streams structured control-plane events over SSE or WebSocket.

Events should include:

- config load
- validation success/failure
- apply started/completed
- process restart/reload
- sidecar tick
- curator run
- memory consolidation
- DGM-H evaluation
- policy violation

## Suggested Event Shapes

Example control-plane event:

```json
{
  "type": "config.applied",
  "scope": "repo",
  "profile": "default",
  "timestamp": "2026-05-15T12:00:00Z",
  "details": {
    "changed": [
      "supervisor.learning.sidecar.enabled",
      "terminal.backend"
    ],
    "restart_policy": "selective"
  }
}
```

Example sidecar event:

```json
{
  "type": "sidecar.tick",
  "name": "learning",
  "state": "running",
  "timestamp": "2026-05-15T12:05:00Z"
}
```

## CLI Mapping

The API should map cleanly to the existing CLI operations:

- `hermes config show` → `GET /v1/control/config`
- `hermes config check` → `POST /v1/control/config/validate`
- `hermes config edit/set` → `POST /v1/control/config/apply`
- `hermes status` → `GET /v1/control/status`
- `hermes curator status` → `GET /v1/control/sidecars`
- `hermes memory status` → `GET /v1/control/sidecars` or a memory-specific view
- `hermes dgm variants` → `GET /v1/control/processes` plus DGM-specific endpoints

That mapping keeps the app, CLI, and manifests aligned on the same behavior.

## Manifest Support

If a request uses a manifest, the API should accept the same manifest shape documented in [Orchestration Manifests](./orchestration-manifests.md), then convert it to a validated patch before apply.

## Security Notes

- Do not return raw secret values in any control-plane response.
- Do not allow arbitrary command execution through control endpoints.
- Gate runtime-mutating operations behind policy and approval in production-like environments.
- Prefer narrow, typed inputs over generic free-form shell text.
