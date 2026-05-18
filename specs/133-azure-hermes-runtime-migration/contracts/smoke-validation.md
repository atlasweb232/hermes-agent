# Smoke Validation Contract

## Purpose

Define the minimum evidence required before trusting the Azure environment.

## Smoke Phases

### Read-Only Azure Check

```bash
az account show -o json
az account subscription show --subscription-id <id> -o json
az provider list --query "[?namespace=='Microsoft.Compute' || namespace=='Microsoft.App' || namespace=='Microsoft.ContainerRegistry' || namespace=='Microsoft.DBforPostgreSQL' || namespace=='Microsoft.KeyVault']" -o table
az vm list-usage --location eastus -o table
```

### Hermes Runtime Check

```bash
git rev-parse --short HEAD
venv/bin/python -m hermes_cli.main runtime smoke compare --no-upstream --json
PYTEST_ADDOPTS="" venv/bin/python -m pytest -q -o addopts="" tests/hermes_cli/test_goal_allocator.py tests/hermes_cli/test_aws_secrets.py tests/hermes_cli/test_runtime_smoke.py
```

### Worker Check

```bash
claude -p "Reply with exactly: claude-ok"
codex --version
```

### TinyFish Check

```bash
venv/bin/python -m hermes_cli.doctor | grep -A5 TinyFish
```

### Secret Reference Check

```bash
venv/bin/python -m hermes_cli.main runtime secrets check --json
```

## Required Report Fields

- environment name
- region
- branch and commit
- provider registration status
- compute quota
- Hermes runtime smoke result
- worker smoke result
- TinyFish readiness
- secret reference status
- blockers
- next action

## Failure Rules

- Missing worker auth blocks live worker smoke but not infrastructure smoke.
- Missing secrets block TinyFish/IMAP/deployment smoke.
- Runtime allocator smoke failure blocks production migration.
- Provider registration incomplete blocks Container Apps production path.
