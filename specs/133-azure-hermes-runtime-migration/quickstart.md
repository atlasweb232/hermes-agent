# Quickstart: Azure Hermes Runtime Migration

## Read-Only Azure Check

```bash
az account show -o json
az account subscription show --subscription-id 2ba6c25e-6e03-4393-bb8b-866b0a3df7b3 -o json
az provider list --query "[?namespace=='Microsoft.Compute' || namespace=='Microsoft.App' || namespace=='Microsoft.ContainerRegistry' || namespace=='Microsoft.DBforPostgreSQL' || namespace=='Microsoft.KeyVault'].{Namespace:namespace,State:registrationState}" -o table
az vm list-usage --location eastus --query "[?contains(name.value,'cores')].{Name:name.localizedValue,Current:currentValue,Limit:limit}" -o table
```

Expected current baseline:

```text
Pay-As-You-Go subscription
Microsoft.Compute registered
East US total regional vCPUs: 10
Container Apps/PostgreSQL may require provider registration
```

## Provider Registration

Run only with operator approval:

```bash
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.DBforPostgreSQL
az provider register --namespace Microsoft.ContainerRegistry
az provider register --namespace Microsoft.KeyVault
```

## Local Hermes Smoke

```bash
PYTEST_ADDOPTS="" pytest -q -o addopts="" \
  tests/hermes_cli/test_goal_allocator.py \
  tests/hermes_cli/test_aws_secrets.py \
  tests/hermes_cli/test_runtime_smoke.py

python -m hermes_cli.main runtime smoke compare --no-upstream --json
```

## VM Recovery Smoke

On the Azure VM after bootstrap:

```bash
cd ~/hermes-agent
git checkout 132-learning-memory-runtime
git pull --ff-only fork 132-learning-memory-runtime
venv/bin/python -m hermes_cli.main runtime smoke compare --no-upstream --json
claude -p "Reply with exactly: claude-ok"
venv/bin/python -m hermes_cli.doctor | grep -A5 TinyFish
venv/bin/python -m hermes_cli.main runtime secrets check --json
```

## Safety

- Do not paste raw secrets into prompts.
- Do not commit `.env`, Claude local settings, Codex auth, or SSH keys.
- Use Key Vault for persistent secrets.
- Use temporary chmod-600 env file only during emergency VM recovery.
