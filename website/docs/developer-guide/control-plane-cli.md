---
sidebar_position: 7
title: "Control Plane CLI"
description: "CLI commands that mirror the Hermes control-plane API and manifest flows."
---

# Control Plane CLI

This page maps the Hermes CLI surface to the control-plane contract so an operator can use the terminal, the app, or a manifest without learning three different mental models.

The rule is simple:

- `hermes config show/check/edit/set` covers the config lifecycle
- `hermes status/doctor` covers health and validation
- `hermes curator`, `hermes memory`, and `hermes dgm` cover the background sidecars
- process control maps to targeted restart/reload operations

## CLI To API Map

| CLI Command | Control-Plane API | Purpose |
|---|---|---|
| `hermes config show` | `GET /v1/control/config` | Read the current runtime state |
| `hermes config check` | `POST /v1/control/config/validate` | Validate a proposed patch or manifest |
| `hermes config edit` | `POST /v1/control/config/apply` | Apply interactive config edits |
| `hermes config set` | `POST /v1/control/config/apply` | Apply a single key/value change |
| `hermes status` | `GET /v1/control/status` | Read the runtime health summary |
| `hermes curator status` | `GET /v1/control/sidecars` | Read curator sidecar state |
| `hermes curator run` | `POST /v1/control/processes/curator/reload` or `restart` | Trigger the curator loop depending on backend behavior |
| `hermes memory status` | `GET /v1/control/sidecars` | Read memory and learning sidecar state |
| `hermes memory monitor` | `GET /v1/control/events` or a memory-specific status view | Stream memory/consolidation events |
| `hermes dgm variants` | `GET /v1/control/processes` and DGM-specific endpoints | Inspect DGM-H variants and runtime state |
| `hermes doctor` | `GET /v1/control/status` plus validation checks | Diagnose configuration and runtime issues |
| `hermes gateway status` | `GET /v1/control/processes` | Inspect gateway process state |
| `hermes gateway restart` | `POST /v1/control/processes/gateway/restart` | Restart the gateway cleanly |
| `hermes gateway stop` | `POST /v1/control/processes/gateway/stop` | Stop the gateway cleanly |

## Suggested Operator Flow

### 1. Preview

Use the app or CLI to inspect the current state before making changes.

```bash
hermes config show
hermes status
```

### 2. Validate

Check the config or manifest before applying it.

```bash
hermes config check
```

### 3. Apply

Apply the config change by CLI, app, or manifest-driven control plane.

```bash
hermes config set terminal.backend docker
hermes config set supervisor.learning.sidecar.enabled true
```

### 4. Restart Or Reload

Only restart the pieces that need it.

```bash
hermes gateway restart
```

### 5. Confirm

Re-check status and sidecars after the change lands.

```bash
hermes status
hermes curator status
hermes memory status
```

## When To Use The CLI Instead Of The App

Use the CLI when you need:

- a local operator workflow
- scripted automation
- CI or deployment jobs
- recovery on a headless host
- direct triage during a failed orchestration run

The CLI should always be able to reach the same end state as the app or a manifest, even if the path is more manual.
