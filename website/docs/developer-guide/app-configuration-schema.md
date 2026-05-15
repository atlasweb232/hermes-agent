---
sidebar_position: 4
title: "App Configuration Schema"
description: "A structured app-facing configuration model for Hermes control plane, sidecars, workers, and reload flows."
---

# App Configuration Schema

If you want to drive Hermes from an app, dashboard, or remote control plane, do not create a second configuration system. Treat the app as a structured editor and runtime controller over the same Hermes state:

- `~/.hermes/config.yaml` for non-secret settings
- `~/.hermes/.env` for secrets and API keys
- Hermes CLI commands for validation, status, and restart/reload

The app should expose the config in a few clear sections instead of one giant form.

## Recommended Sections

### 1. Core Runtime

This is the minimum set needed to run Hermes safely.

```yaml
model:
  default: gpt-oss-120b
  provider: custom
  base_url: https://api.cerebras.ai/v1
  api_key: ${HERMES_MODEL_API_KEY}

terminal:
  backend: ssh
  cwd: /home/rakib/git/project
  timeout: 300
  persistent_shell: true

code_execution:
  timeout: 300
  max_tool_calls: 50

delegation:
  orchestrator_enabled: true
  max_iterations: 50
  max_spawn_depth: 2
  subagent_auto_approve: false
  inherit_mcp_toolsets: true
```

### 2. Sidecars

These are the background orchestration and maintenance loops.

```yaml
supervisor:
  monitoring:
    enabled: true

  learning:
    sidecar:
      enabled: true
      interval_seconds: 300
      run_on_start: true

  dgm_h:
    enabled: false
    allow_runtime_code_changes: false
    promotion_requires_approval: true
    default_tool_profile: repo_eval
    max_parents: 3

curator:
  enabled: true
  interval_hours: 168
  min_idle_hours: 2
  stale_after_days: 30
  archive_after_days: 90
  backup:
    enabled: true
```

### 3. Worker Profiles

These are the execution policies for tasks, sandboxes, and agent tools.

```yaml
terminal:
  backend: docker
  docker_image: nikolaik/python-nodejs:python3.11-nodejs20
  docker_mount_cwd_to_workspace: true
  docker_run_as_host_user: true
  docker_forward_env:
    - GITHUB_TOKEN

tools:
  registry:
    web_search: true
    browser: true
    mcp: true
    file_tools: true
    terminal: true
    code_execution: true
    delegate_task: true
```

### 4. Memory And Learning

Keep the memory layer bounded and explicit.

```yaml
memory:
  memory_enabled: true
  user_profile_enabled: true
  memory_char_limit: 2200
  user_char_limit: 1375

skills:
  guard_agent_created: true
```

### 5. Secrets

Secrets should not be stored inline in the app UI or in plain YAML.

```bash
OPENROUTER_API_KEY=...
HERMES_MODEL_API_KEY=...
TERMINAL_SSH_HOST=...
TERMINAL_SSH_USER=...
```

If the app needs to reference a secret, it should store a secret name or secret URI and let Hermes resolve the actual value from `.env`, AWS Secrets Manager, or the platform secret store.

## App Workflow

The app should follow this sequence:

1. Read the current Hermes config state.
2. Display the settings grouped by runtime, sidecar, worker, memory, and secrets.
3. Allow structured edits per section.
4. Write changes back to `config.yaml` and `.env`.
5. Run `hermes config check`.
6. Run `hermes doctor` and any relevant status commands.
7. Restart or reload only the processes that need it.
8. Confirm the updated state with `hermes status`, `hermes curator status`, `hermes memory status`, and `hermes dgm variants`.

## Validation Rules

The app should reject or warn on:

- secrets entered directly into YAML
- sidecar promotion without approval gates
- worker profiles that expose unsafe tools by default
- config changes that require a restart but were not followed by a reload/restart step
- enabling DGM-H runtime mutation on production targets

## Practical UI Layout

The app should expose at least these tabs or panels:

- Runtime
- Sidecars
- Workers
- Memory
- Tools
- Secrets
- Validation
- Process Control

That keeps the control plane understandable and makes it possible to manage Hermes without inventing a parallel config model.
